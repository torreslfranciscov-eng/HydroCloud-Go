#!/usr/bin/env python3
"""Online timezone correction for a large Oracle table using DBMS_REDEFINITION."""

import os
import oracledb

from migrate_timescale_to_oracle import required, qi


TABLE = os.getenv("REDEF_TABLE", "DCP_DATOS").upper()
INTERIM = (TABLE + "_TZ_INT")[:128]
REGION = os.getenv("PG_TIMEZONE_REGION", "America/Mexico_City")


def main():
    conn = oracledb.connect(
        user=required("ORACLE_USER"), password=required("ORACLE_PASSWORD"),
        dsn=required("ORACLE_DSN"),
    )
    cur = conn.cursor()
    cur.execute("alter session set ddl_lock_timeout=600")
    cur.execute(
        "select column_name,data_type,nullable from user_tab_columns "
        "where table_name=:1 order by column_id", (TABLE,)
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
    for column, _, nullable in columns:
        if nullable == "N":
            try:
                cur.execute(f"alter table {qi(INTERIM)} modify {qi(column)} not null")
            except oracledb.DatabaseError as exc:
                if "ORA-01442" not in str(exc):
                    raise

    mappings = []
    for column, data_type, _ in columns:
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
                 options_flag=>dbms_redefinition.cons_use_rowid); end;""",
            {"orig": TABLE, "interim": INTERIM, "mapping": mapping},
        )
        print("INITIAL COPY COMPLETE", flush=True)
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
