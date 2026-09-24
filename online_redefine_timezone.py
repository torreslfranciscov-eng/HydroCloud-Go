#!/usr/bin/env python3
"""Online timezone correction for a large Oracle table using DBMS_REDEFINITION."""

import os
import oracledb

from migrate_timescale_to_oracle import required, qi


TABLE = os.getenv("REDEF_TABLE", "DCP_DATOS").upper()
INTERIM = (TABLE + "_TZ_INT")[:128]
REGION = os.getenv("PG_TIMEZONE_REGION", "America/Mexico_City")
TECH_KEY = "MIG_REDEF_KEY"
TECH_PK = "MIG_REDEF_PK"
USE_ROWID = os.getenv("REDEF_USE_ROWID", "0") == "1"


def main():
    conn = oracledb.connect(
        user=required("ORACLE_USER"), password=required("ORACLE_PASSWORD"),
        dsn=required("ORACLE_DSN"),
    )
    cur = conn.cursor()
    cur.execute("alter session set ddl_lock_timeout=600")
    if USE_ROWID:
        cur.execute("select count(*) from user_constraints where constraint_name=:1", (TECH_PK,))
        if cur.fetchone()[0]:
            cur.execute(f"alter table {qi(TABLE)} drop constraint {qi(TECH_PK)}")
            print("TECHNICAL PRIMARY KEY REMOVED", flush=True)
        cur.execute(
            "select count(*) from user_tab_columns where table_name=:1 and column_name=:2",
            (TABLE, TECH_KEY),
        )
        if cur.fetchone()[0]:
            cur.execute(f"alter table {qi(TABLE)} drop column {qi(TECH_KEY)}")
            print("TECHNICAL KEY COLUMN REMOVED", flush=True)
    else:
        setup_technical_key(cur)

    redefine(conn, cur)


def setup_technical_key(cur):
    cur.execute(
        "select count(*) from user_tab_columns where table_name=:1 and column_name=:2",
        (TABLE, TECH_KEY),
    )
    tech_key_exists = bool(cur.fetchone()[0])
    cur.execute("select count(*) from user_constraints where constraint_name=:1", (TECH_PK,))
    tech_pk_exists = bool(cur.fetchone()[0])
    # An earlier attempt used SYS_EXTRACT_UTC in this key.  That is not stable
    # while a table is only partially corrected: a corrected row can then share
    # an instant with an as-yet uncorrected row six wall-clock hours later.
    # The source PK is unique by local wall-clock value, DCP and sensor, and the
    # wall-clock representation itself is unchanged by the correction.
    if tech_key_exists and not tech_pk_exists:
        cur.execute(f"alter table {qi(TABLE)} drop column {qi(TECH_KEY)}")
        tech_key_exists = False
        print("STALE TECHNICAL KEY REMOVED", flush=True)
    if not tech_key_exists:
        cur.execute(
            f"alter table {qi(TABLE)} add {qi(TECH_KEY)} raw(32) generated always as ("
            f"standard_hash(to_char({qi('TS')},'YYYYMMDDHH24MISSFF6')"
            f"||'|'||{qi('DCP_ID')}||'|'||{qi('SENSOR_ID')},'SHA256')) virtual"
        )
        print("TECHNICAL KEY COLUMN CREATED", flush=True)
    if not tech_pk_exists:
        cur.execute(
            f"alter table {qi(TABLE)} add constraint {qi(TECH_PK)} "
            f"primary key ({qi(TECH_KEY)})"
        )
        print("TECHNICAL PRIMARY KEY CREATED", flush=True)


def redefine(conn, cur):
    cur.execute(
        "select column_name,data_type,nullable,virtual_column,data_default from user_tab_cols "
        "where table_name=:1 and hidden_column='NO' order by column_id", (TABLE,)
    )
    columns = cur.fetchall()
    if not columns:
        raise SystemExit(f"Table not found: {TABLE}")
    cur.execute("select count(*) from user_tables where table_name=:1", (INTERIM,))
    if cur.fetchone()[0]:
        try:
            cur.execute(
                "begin dbms_redefinition.abort_redef_table(user,:1,:2); end;",
                (TABLE, INTERIM),
            )
        except oracledb.DatabaseError:
            pass
        cur.execute(f"drop table {qi(INTERIM)} cascade constraints purge")
    cur.execute(
        f"create table {qi(INTERIM)} compress for query low as "
        f"select * from {qi(TABLE)} where 1=0"
    )
    # CTAS materializes a source virtual column as an ordinary column.  Restore
    # it as virtual in the interim table so it computes from the mapped values;
    # DBMS_REDEFINITION explicitly forbids virtual columns in COL_MAPPING.
    for column, _, _, virtual, default_expr in columns:
        if virtual == "YES":
            cur.execute(f"alter table {qi(INTERIM)} drop column {qi(column)}")
            cur.execute(
                f"alter table {qi(INTERIM)} add {qi(column)} raw(32) "
                f"generated always as ({default_expr}) virtual"
            )
    for column, _, nullable, virtual, _ in columns:
        if virtual == "YES":
            continue
        if nullable == "N":
            try:
                cur.execute(f"alter table {qi(INTERIM)} modify {qi(column)} not null")
            except oracledb.DatabaseError as exc:
                if "ORA-01442" not in str(exc):
                    raise

    mappings = []
    for column, data_type, _, virtual, _ in columns:
        if virtual == "YES":
            continue
        if data_type == "TIMESTAMP WITH TIME ZONE":
            expression = (
                f"CASE WHEN {qi(column)} IS NOT NULL AND "
                f"EXTRACT(TIMEZONE_HOUR FROM {qi(column)})=0 THEN "
                f"TO_TIMESTAMP_TZ(TO_CHAR({qi(column)},'YYYY-MM-DD HH24:MI:SS.FF6')"
                f"||' {REGION}','YYYY-MM-DD HH24:MI:SS.FF6 TZR') "
                f"ELSE {qi(column)} END {qi(column)}"
            )
        else:
            expression = f"{qi(column)} {qi(column)}"
        mappings.append(expression)
    mapping = ",".join(mappings)
    try:
        print(f"START ONLINE REDEFINITION {TABLE}", flush=True)
        cur.execute(
            """begin dbms_redefinition.start_redef_table(
                 uname=>user,orig_table=>:orig,int_table=>:interim,
                 col_mapping=>:mapping,
                 options_flag=>:method); end;""",
            {"orig": TABLE, "interim": INTERIM, "mapping": mapping,
             "method": 2 if USE_ROWID else 1},
        )
        print("INITIAL COPY COMPLETE", flush=True)
        if USE_ROWID:
            cur.execute(
                "select column_name from user_tab_cols where table_name=:1 "
                "and upper(column_name)='M_ROW$$'", (INTERIM,)
            )
            rowid_column = cur.fetchone()
            if rowid_column:
                cur.execute(
                    f"create index {qi(('MIG_' + TABLE + '_ROWID')[:128])} "
                    f"on {qi(INTERIM)} ({qi(rowid_column[0])})"
                )
                print("ROWID SYNC INDEX CREATED", flush=True)
        cur.execute(
            "begin dbms_redefinition.sync_interim_table(user,:1,:2); end;",
            (TABLE, INTERIM),
        )
        print("SYNC COMPLETE", flush=True)
        cur.execute(
            """begin dbms_redefinition.finish_redef_table(
                 uname=>user,orig_table=>:orig,int_table=>:interim,
                 dml_lock_timeout=>600); end;""",
            {"orig": TABLE, "interim": INTERIM},
        )
        print("ATOMIC SWAP COMPLETE", flush=True)
        cur.execute(f"drop table {qi(INTERIM)} cascade constraints purge")
        print("OLD SEGMENT DROPPED", flush=True)
        if not USE_ROWID:
            cur.execute(f"alter table {qi(TABLE)} drop column {qi(TECH_KEY)}")
            print("TECHNICAL KEY REMOVED", flush=True)
    except Exception:
        try:
            cur.execute(
                "begin dbms_redefinition.abort_redef_table(user,:1,:2); end;",
                (TABLE, INTERIM),
            )
        except Exception:
            pass
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
