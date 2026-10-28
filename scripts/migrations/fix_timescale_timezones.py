#!/usr/bin/env python3
"""Correct timezone offsets lost by Oracle direct path load.

python-oracledb direct path load preserved PostgreSQL wall-clock fields but
stored aware datetimes at +00:00.  Source timestamps are interpreted in the
source session region (America/Mexico_City).  Existing live rows already using
non-zero offsets are never changed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import oracledb
import psycopg2

from migrate_timescale_to_oracle import SCHEMAS, required, target_name, qi


STATE = Path(__file__).with_name("timescale-timezone-state.json")
SOURCE_TZ = os.getenv("PG_TIMEZONE_REGION", "America/Mexico_City")


def connections():
    pg = psycopg2.connect(
        host=required("PG_HOST"), port=int(os.getenv("PG_PORT", "5432")),
        dbname=required("PG_DATABASE"), user=required("PG_USER"),
        password=required("PG_PASSWORD"), connect_timeout=15,
        sslmode=os.getenv("PG_SSLMODE", "prefer"),
    )
    ora = oracledb.connect(
        user=required("ORACLE_USER"), password=required("ORACLE_PASSWORD"),
        dsn=required("ORACLE_DSN"),
    )
    ora.cursor().execute("alter session enable parallel dml")
    ora.cursor().execute("alter session set ddl_lock_timeout=300")
    return pg, ora


def timestamp_columns(pg):
    cur = pg.cursor()
    cur.execute(
        """select table_schema,table_name,column_name,is_nullable,ordinal_position
             from information_schema.columns
            where table_schema=any(%s) and udt_name='timestamptz'
            order by table_schema,table_name,ordinal_position""",
        (list(SCHEMAS),),
    )
    result = {}
    for schema, table, column, nullable, _ in cur.fetchall():
        result.setdefault((schema, table), []).append((column, nullable))
    return result


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"completed_tables": {}, "source_timezone_region": SOURCE_TZ}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def offset_zero(column):
    return f"EXTRACT(TIMEZONE_HOUR FROM {qi(column)})=0"


def corrected(column):
    return (
        f"CASE WHEN {qi(column)} IS NOT NULL AND {offset_zero(column)} THEN "
        f"TO_TIMESTAMP_TZ(TO_CHAR({qi(column)},'YYYY-MM-DD HH24:MI:SS.FF6')"
        f"||' {SOURCE_TZ}','YYYY-MM-DD HH24:MI:SS.FF6 TZR') ELSE {qi(column)} END"
    )


def drop_nonunique_time_indexes(ora, mappings):
    cur = ora.cursor()
    targets = {
        target_name(s, t): {c.upper() for c, _ in cols}
        for (s, t), cols in mappings.items()
    }
    cur.execute(
        """select distinct i.table_name,i.index_name,c.column_name
             from user_indexes i join user_ind_columns c on c.index_name=i.index_name
            where i.uniqueness='NONUNIQUE' and i.generated='N'"""
    )
    to_drop = set()
    for table, index, column in cur.fetchall():
        if table in targets and column in targets[table]:
            to_drop.add(index)
    for index in sorted(to_drop):
        cur.execute(f"drop index {qi(index)}")
        print(f"DROP TEMPORAL INDEX {index}", flush=True)
    return sorted(to_drop)


def drop_utc_function_indexes(ora):
    cur = ora.cursor()
    cur.execute("select index_name,column_expression from user_ind_expressions")
    indexes = sorted({
        name for name, expression in cur.fetchall()
        if expression and "SYS_EXTRACT_UTC" in expression.upper()
    })
    for index in indexes:
        cur.execute(f"drop index {qi(index)}")
        print(f"DROP UTC UNIQUE INDEX {index}", flush=True)
    return indexes


def fix_table(ora, schema, table, columns):
    name = target_name(schema, table)
    cur = ora.cursor()
    conditions = " OR ".join(
        f"({qi(c)} IS NOT NULL AND {offset_zero(c)})" for c, _ in columns
    )
    required_cols = [c for c, nullable in columns if nullable == "NO"]
    anchor = required_cols[0] if required_cols else columns[0][0]
    cur.execute(
        f"select to_char(min({qi(anchor)}),'YYYY-MM-DD HH24:MI:SS'),"
        f"to_char(max({qi(anchor)}),'YYYY-MM-DD HH24:MI:SS') "
        f"from {qi(name)} where {offset_zero(anchor)}"
    )
    low_text, high_text = cur.fetchone()
    if low_text is None:
        print(f"TIMEZONE {schema}.{table}: no +00 rows", flush=True)
        return 0
    low = dt.datetime.strptime(low_text, "%Y-%m-%d %H:%M:%S").replace(hour=0, minute=0, second=0)
    high = dt.datetime.strptime(high_text, "%Y-%m-%d %H:%M:%S") + dt.timedelta(seconds=1)
    assignments = ",".join(f"{qi(c)}={corrected(c)}" for c, _ in columns)
    total = 0
    cursor = low
    batch_days = 1 if name == "DCP_DATOS" else 7
    while cursor < high:
        end = min(cursor + dt.timedelta(days=batch_days), high)
        lower = cursor.strftime("%Y-%m-%d %H:%M:%S")
        upper = end.strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            f"update /*+ ENABLE_PARALLEL_DML PARALLEL({qi(name)},8) */ {qi(name)} set {assignments} "
            f"where {qi(anchor)} >= to_timestamp_tz(:1||' +00:00','YYYY-MM-DD HH24:MI:SS TZH:TZM') "
            f"and {qi(anchor)} < to_timestamp_tz(:2||' +00:00','YYYY-MM-DD HH24:MI:SS TZH:TZM') "
            f"and ({conditions})",
            (lower, upper),
        )
        changed = cur.rowcount
        ora.commit()
        total += changed
        if changed:
            print(f"TIMEZONE {schema}.{table} through {upper}: {total}", flush=True)
        cursor = end
    # Nullable anchors can miss rows where another timestamp is populated.
    if not required_cols:
        cur.execute(
            f"update {qi(name)} set {assignments} where {qi(anchor)} is null and ({conditions})"
        )
        total += cur.rowcount
        ora.commit()
    return total


def main():
    pg, ora = connections()
    try:
        mappings = timestamp_columns(pg)
        state = load_state()
        if not state.get("utc_unique_indexes_dropped"):
            state["dropped_utc_unique_indexes"] = drop_utc_function_indexes(ora)
            state["utc_unique_indexes_dropped"] = True
            save_state(state)
        if not state.get("indexes_dropped"):
            state["dropped_indexes"] = drop_nonunique_time_indexes(ora, mappings)
            state["indexes_dropped"] = True
            save_state(state)
        cur = ora.cursor()
        cur.execute("select count(*) from user_indexes where index_name='MIG_DCP_TS_IDX'")
        if not cur.fetchone()[0] and "public.dcp_datos" not in state["completed_tables"]:
            cur.execute("create index MIG_DCP_TS_IDX on DCP_DATOS(TS)")
            print("CREATE TEMPORARY INDEX MIG_DCP_TS_IDX", flush=True)
        for (schema, table), columns in mappings.items():
            key = f"{schema}.{table}"
            if key in state["completed_tables"]:
                continue
            changed = fix_table(ora, schema, table, columns)
            state["completed_tables"][key] = changed
            state["updated_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            save_state(state)
        cur.execute("select count(*) from user_indexes where index_name='MIG_DCP_TS_IDX'")
        if cur.fetchone()[0]:
            cur.execute("drop index MIG_DCP_TS_IDX")
            print("DROP TEMPORARY INDEX MIG_DCP_TS_IDX", flush=True)
        print(json.dumps(state, indent=2), flush=True)
    finally:
        pg.close()
        ora.close()


if __name__ == "__main__":
    main()
