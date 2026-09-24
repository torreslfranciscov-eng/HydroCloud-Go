#!/usr/bin/env python3
"""Migrate logical TimescaleDB schemas to the Oracle MYCLOUD_TS schema.

Timescale internal catalogs and physical chunks are intentionally excluded.
Credentials are accepted only through environment variables.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import re
import time
import uuid
from pathlib import Path

import oracledb
import psycopg2


SCHEMAS = ("hydro_model", "public", "rain_forecast")
BATCH_SIZE = int(os.getenv("TS_BATCH_SIZE", "20000"))
REPORT_PATH = Path(__file__).with_name("timescale-migration-report.json")
STATE_PATH = Path(__file__).with_name("timescale-migration-state.json")


def required(name):
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def qi(name):
    return '"' + name.upper().replace('"', '""') + '"'


def pqi(name):
    return '"' + name.replace('"', '""') + '"'


def target_name(schema, name):
    prefix = {"public": "", "hydro_model": "HM_", "rain_forecast": "RF_"}[schema]
    return (prefix + name).upper()


def pg_connect():
    conn = psycopg2.connect(
        host=required("PG_HOST"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=required("PG_DATABASE"),
        user=required("PG_USER"),
        password=required("PG_PASSWORD"),
        connect_timeout=15,
        sslmode=os.getenv("PG_SSLMODE", "prefer"),
        application_name="oracle_migration",
    )
    conn.set_session(isolation_level="REPEATABLE READ", readonly=True, autocommit=False)
    return conn


def oracle_connect():
    conn = oracledb.connect(
        user=required("ORACLE_USER"),
        password=required("ORACLE_PASSWORD"),
        dsn=required("ORACLE_DSN"),
    )
    conn.cursor().execute("alter session set ddl_lock_timeout=300")
    return conn


def fetchall(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchall()


def table_list(cur):
    return fetchall(
        cur,
        """select table_schema,table_name
             from information_schema.tables
            where table_type='BASE TABLE' and table_schema=any(%s)
            order by table_schema,table_name""",
        (list(SCHEMAS),),
    )


def column_list(cur, schema, table):
    return fetchall(
        cur,
        """select column_name,ordinal_position,data_type,udt_name,
                  character_maximum_length,numeric_precision,numeric_scale,
                  is_nullable,column_default
             from information_schema.columns
            where table_schema=%s and table_name=%s order by ordinal_position""",
        (schema, table),
    )


def hypertable_names(cur):
    return {
        (s, t)
        for s, t in fetchall(
            cur,
            "select hypertable_schema,hypertable_name from timescaledb_information.hypertables",
        )
    }


def pg_type_to_oracle(col):
    _, _, data_type, udt, length, precision, scale, _, _ = col
    if udt == "int2":
        return "NUMBER(5)"
    if udt == "int4":
        return "NUMBER(10)"
    if udt == "int8":
        return "NUMBER(19)"
    if udt == "float4":
        return "BINARY_FLOAT"
    if udt == "float8":
        return "BINARY_DOUBLE"
    if udt == "numeric":
        return f"NUMBER({precision},{scale})" if precision is not None else "NUMBER"
    if udt == "bool":
        return "NUMBER(1)"
    if udt in ("varchar", "bpchar"):
        if length is None or length > 4000:
            return "VARCHAR2(4000)"
        return f"VARCHAR2({max(1, length)})"
    if udt == "text":
        return "VARCHAR2(4000)"
    if udt == "bytea":
        return "BLOB"
    if udt == "uuid":
        return "CHAR(36)"
    if udt == "date":
        return "DATE"
    if udt in ("timestamp",):
        return "TIMESTAMP(6)"
    if udt == "timestamptz":
        return "TIMESTAMP(6) WITH TIME ZONE"
    if udt in ("time", "timetz"):
        return "VARCHAR2(40)"
    if data_type == "ARRAY":
        return "CLOB"
    raise ValueError(f"Unsupported PostgreSQL type {data_type}/{udt}")


def oracle_default(col):
    default = col[8]
    udt = col[3]
    if not default or default.startswith("nextval("):
        return None
    value = default.strip()
    value = re.sub(r"::[A-Za-z ]+(?:\[\])?$", "", value)
    if value.lower() in ("true", "false"):
        return "1" if value.lower() == "true" else "0"
    if value.lower() in ("now()", "current_timestamp"):
        return "SYSTIMESTAMP"
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return value
    if value.startswith("'") and value.endswith("'") and udt != "_int4":
        return value
    return None


def load_state():
    if not STATE_PATH.exists():
        return {"completed_tables": {}, "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def reset_target(conn):
    cur = conn.cursor()
    cur.execute(
        """select object_name,object_type from user_objects
            where object_type in ('VIEW','TABLE')
            order by case object_type when 'VIEW' then 1 else 2 end"""
    )
    objects = cur.fetchall()
    for name, typ in objects:
        suffix = " cascade constraints purge" if typ == "TABLE" else ""
        cur.execute(f"drop {typ.lower()} {qi(name)}{suffix}")
    if STATE_PATH.exists():
        STATE_PATH.unlink()
    print(f"Reset target: dropped {len(objects)} objects", flush=True)


def sequence_columns(cur):
    result = set()
    for schema, table, column in fetchall(
        cur,
        """select table_schema,table_name,column_name
             from information_schema.columns
            where table_schema=any(%s) and column_default like 'nextval(%%'""",
        (list(SCHEMAS),),
    ):
        result.add((schema, table, column))
    return result


def create_tables(pg, ora, tables, metadata, hypertables, sequence_cols):
    cur = ora.cursor()
    cur.execute("select table_name from user_tables")
    existing = {r[0] for r in cur.fetchall()}
    for pos, (schema, table) in enumerate(tables, 1):
        name = target_name(schema, table)
        if name in existing:
            continue
        definitions = []
        for col in metadata[(schema, table)]:
            column, _, _, _, _, _, _, nullable, _ = col
            item = f"{qi(column)} {pg_type_to_oracle(col)}"
            default = oracle_default(col)
            if default is not None:
                item += f" DEFAULT {default}"
            if (schema, table, column) in sequence_cols:
                item += " GENERATED BY DEFAULT ON NULL AS IDENTITY"
            if nullable == "NO":
                item += " NOT NULL"
            definitions.append(item)
        compression = (
            "COMPRESS FOR QUERY LOW"
            if (schema, table) in hypertables or table in {"bitacora_goes", "dcp_headers", "precipitacion_cuenca"}
            else "ROW STORE COMPRESS ADVANCED"
        )
        ddl = f"create table {qi(name)} (\n  " + ",\n  ".join(definitions) + f"\n) {compression}"
        cur.execute(ddl)
        print(f"DDL {pos}/{len(tables)} {schema}.{table} -> {name} [{compression}]", flush=True)


def normalize(value, col, substitutions):
    if value is None:
        return None
    udt = col[3]
    nullable = col[7]
    if value == "" and nullable == "NO" and udt in ("varchar", "bpchar", "text"):
        substitutions["required_empty_strings_to_space"] += 1
        return " "
    if udt == "bool":
        return int(value)
    if udt == "uuid" or isinstance(value, uuid.UUID):
        return str(value)
    if col[2] == "ARRAY":
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), default=str)
    if isinstance(value, (dt.datetime, dt.date, decimal.Decimal, bytes, str, int, float)):
        return value
    return str(value)


def load_tables(pg, ora, tables, metadata, state):
    completed = state.setdefault("completed_tables", {})
    substitutions = state.setdefault("substitutions", {"required_empty_strings_to_space": 0})
    only = os.getenv("TS_ONLY_TABLE")
    for pos, (schema, table) in enumerate(tables, 1):
        key = f"{schema}.{table}"
        if only and key != only:
            continue
        if key in completed:
            print(f"SKIP {pos}/{len(tables)} {key}: {completed[key]} already loaded", flush=True)
            continue
        target = target_name(schema, table)
        dcur = ora.cursor()
        dcur.execute(f"select count(*) from {qi(target)}")
        partial = dcur.fetchone()[0]
        if partial:
            print(f"TRUNCATE partial {key}: {partial}", flush=True)
            dcur.execute(f"truncate table {qi(target)}")
        cols = metadata[(schema, table)]
        col_names = [c[0] for c in cols]
        cursor_name = "mig_" + re.sub(r"\W", "_", key)
        scur = pg.cursor(name=cursor_name, withhold=False)
        scur.itersize = BATCH_SIZE
        scur.execute(
            f"select {','.join(pqi(n) for n in col_names)} from {pqi(schema)}.{pqi(table)}"
        )
        loaded = 0
        started = time.time()
        while True:
            batch = scur.fetchmany(BATCH_SIZE)
            if not batch:
                break
            converted = [
                tuple(normalize(value, cols[i], substitutions) for i, value in enumerate(row))
                for row in batch
            ]
            ora.direct_path_load(
                schema_name=required("ORACLE_USER").upper(),
                table_name=target,
                column_names=[n.upper() for n in col_names],
                data=converted,
                batch_size=BATCH_SIZE,
            )
            ora.commit()
            loaded += len(converted)
            if loaded % 1000000 < len(converted):
                rate = loaded / max(time.time() - started, 0.001)
                print(f"DATA {pos}/{len(tables)} {key}: {loaded} ({rate:,.0f} rows/s)", flush=True)
        scur.close()
        completed[key] = loaded
        state["updated_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        save_state(state)
        print(f"DATA {pos}/{len(tables)} {key}: COMPLETE {loaded}", flush=True)
    return substitutions


def constraints(cur):
    sql = """select n.nspname,c.relname,con.conname,con.contype,
                    array_agg(a.attname order by k.ord)
               from pg_constraint con
               join pg_class c on c.oid=con.conrelid
               join pg_namespace n on n.oid=c.relnamespace
               join lateral unnest(con.conkey) with ordinality k(attnum,ord) on true
               join pg_attribute a on a.attrelid=c.oid and a.attnum=k.attnum
              where n.nspname=any(%s) and con.contype in ('p','u')
              group by n.nspname,c.relname,con.conname,con.contype
              order by n.nspname,c.relname,con.contype,con.conname"""
    return fetchall(cur, sql, (list(SCHEMAS),))


def create_constraints(pg, ora):
    cur = ora.cursor()
    cur.execute("select constraint_name from user_constraints where constraint_type in ('P','U')")
    existing = {r[0] for r in cur.fetchall()}
    cur.execute("select index_name from user_indexes")
    existing_indexes = {r[0] for r in cur.fetchall()}
    timestamptz = {
        (s, t, c)
        for s, t, c in fetchall(
            pg,
            """select table_schema,table_name,column_name
                 from information_schema.columns
                where table_schema=any(%s) and udt_name='timestamptz'""",
            (list(SCHEMAS),),
        )
    }
    made = 0
    for schema, table, name, typ, columns in constraints(pg):
        cname = target_name(schema, name)
        if cname in existing or cname in existing_indexes:
            continue
        if any((schema, table, column) in timestamptz for column in columns):
            expressions = [
                f"SYS_EXTRACT_UTC({qi(column)})"
                if (schema, table, column) in timestamptz else qi(column)
                for column in columns
            ]
            compression = f" compress {len(columns)-1}" if len(columns) > 1 else ""
            cur.execute(
                f"create unique index {qi(cname)} on {qi(target_name(schema, table))} "
                f"({','.join(expressions)}){compression}"
            )
            made += 1
            print(f"UNIQUE INDEX (UTC timestamp) {schema}.{table} {name}", flush=True)
            continue
        keyword = "primary key" if typ == "p" else "unique"
        compression = f" compress {len(columns)-1}" if len(columns) > 1 else ""
        ddl = (
            f"alter table {qi(target_name(schema, table))} add constraint {qi(cname)} "
            f"{keyword} ({','.join(qi(c) for c in columns)}) using index{compression}"
        )
        cur.execute(ddl)
        made += 1
        print(f"CONSTRAINT {schema}.{table} {name}", flush=True)
    return made


def secondary_indexes(cur):
    return fetchall(
        cur,
        """select n.nspname,t.relname,ix.relname,i.indisunique,
                  array_agg(pg_get_indexdef(i.indexrelid,k.ord::int,true) order by k.ord)
             from pg_index i
             join pg_class t on t.oid=i.indrelid
             join pg_namespace n on n.oid=t.relnamespace
             join pg_class ix on ix.oid=i.indexrelid
             join lateral generate_series(1,i.indnkeyatts) k(ord) on true
             left join pg_constraint con on con.conindid=i.indexrelid
            where n.nspname=any(%s) and con.oid is null and i.indisvalid
            group by n.nspname,t.relname,ix.relname,i.indisunique
            order by n.nspname,t.relname,ix.relname""",
        (list(SCHEMAS),),
    )


def create_indexes(pg, ora):
    cur = ora.cursor()
    cur.execute("select index_name from user_indexes")
    existing = {r[0] for r in cur.fetchall()}
    made = 0
    for schema, table, name, unique, expressions in secondary_indexes(pg):
        iname = target_name(schema, name)
        if iname in existing:
            continue
        converted = []
        supported = True
        for expr in expressions:
            expr = re.sub(r"\s+NULLS\s+(FIRST|LAST)", "", expr, flags=re.I)
            match = re.fullmatch(r'"?([A-Za-z_][A-Za-z0-9_$]*)"?(\s+DESC)?', expr, flags=re.I)
            if not match:
                supported = False
                break
            converted.append(qi(match.group(1)) + (match.group(2) or ""))
        if not supported:
            print(f"INDEX SKIP unsupported expression {schema}.{name}: {expressions}", flush=True)
            continue
        prefix = "unique " if unique else ""
        compression = f" compress {len(converted)-1}" if len(converted) > 1 else ""
        try:
            cur.execute(
                f"create {prefix}index {qi(iname)} on {qi(target_name(schema, table))} "
                f"({','.join(converted)}){compression}"
            )
        except oracledb.DatabaseError as exc:
            if "ORA-01408" in str(exc):
                print(f"INDEX SKIP redundant {schema}.{name}", flush=True)
                continue
            raise
        made += 1
        print(f"INDEX {schema}.{name}", flush=True)
    return made


def advance_identities(ora, sequence_cols):
    cur = ora.cursor()
    for schema, table, column in sorted(sequence_cols):
        cur.execute(
            f"alter table {qi(target_name(schema, table))} modify {qi(column)} "
            "generated by default on null as identity (start with limit value)"
        )


def create_views(ora):
    cur = ora.cursor()
    minutes = (
        "(CAST(SYS_EXTRACT_UTC(SYSTIMESTAMP) AS DATE) - "
        "CAST(SYS_EXTRACT_UTC(FECHA_ULTIMA_TX) AS DATE))*1440"
    )
    cur.execute(
        f"""create or replace view V_ESTADO_TRANSMISION as
        select DCP_ID,FECHA_ULTIMA_TX,RANGO_TRANSMISION,SERVIDOR,FECHA_CALCULO,
               MENSAJES_RECIBIDOS_48H,MENSAJES_ESPERADOS_48H,
               round(MENSAJES_RECIBIDOS_48H/nullif(MENSAJES_ESPERADOS_48H,0)*100,1) EFECTIVIDAD_48H_PCT,
               COLOR_ESTATUS,
               case when FECHA_ULTIMA_TX is null then null else round({minutes}) end MINUTOS_SIN_TX,
               case when FECHA_ULTIMA_TX is null then null else round(({minutes})/60,1) end HORAS_SIN_TX,
               case when FECHA_ULTIMA_TX is null then 0
                    when ({minutes}) <= RANGO_TRANSMISION*2.5 then 1 else 0 end TRANSMITIENDO,
               case when FECHA_ULTIMA_TX is null then 'SIN_DATOS'
                    when ({minutes}) <= RANGO_TRANSMISION*1.5 then 'OK'
                    when ({minutes}) <= RANGO_TRANSMISION*3 then 'RETRASADA'
                    else 'OFFLINE' end ESTADO_TX
          from ESTATUS_ESTACIONES"""
    )
    cur.execute(
        """create or replace view RF_RESUMEN_HORARIO_PRONOSTICO as
        select TS,FORECAST_DATE,CUENCA_CODE,SUBCUENCA_NAME,
               avg(RAIN_MM) LLUVIA_MEDIA_MM,max(RAIN_MM) LLUVIA_MAX_MM,count(*) NUM_PUNTOS
          from RF_RAIN_RECORD
         group by TS,FORECAST_DATE,CUENCA_CODE,SUBCUENCA_NAME"""
    )


def validate(pg, ora, tables, state):
    cur = ora.cursor()
    mismatches = {}
    total_target = 0
    for schema, table in tables:
        key = f"{schema}.{table}"
        expected = state["completed_tables"].get(key)
        cur.execute(f"select count(*) from {qi(target_name(schema, table))}")
        actual = cur.fetchone()[0]
        total_target += actual
        if expected != actual:
            mismatches[key] = {"snapshot": expected, "target": actual}
    cur.execute("select object_name,object_type from user_objects where status<>'VALID'")
    invalid = [list(r) for r in cur.fetchall()]
    cur.execute("select count(*) from user_constraints where constraint_type='P'")
    pks = cur.fetchone()[0]
    cur.execute("select count(*) from user_constraints where constraint_type='U'")
    uniques = cur.fetchone()[0]
    cur.execute("select count(*) from user_indexes")
    indexes = cur.fetchone()[0]
    cur.execute("select count(*) from user_views")
    views = cur.fetchone()[0]
    return {
        "tables": len(tables),
        "snapshot_rows": sum(state["completed_tables"].values()),
        "target_rows": total_target,
        "row_count_mismatches": mismatches,
        "primary_keys": pks,
        "unique_constraints": uniques,
        "indexes": indexes,
        "views": views,
        "invalid_objects": invalid,
    }


def main():
    started = time.time()
    pg = pg_connect()
    ora = oracle_connect()
    try:
        pgcur = pg.cursor()
        if os.getenv("TS_RESET") == "1":
            reset_target(ora)
        tables = table_list(pgcur)
        metadata = {(s, t): column_list(pgcur, s, t) for s, t in tables}
        hypertables = hypertable_names(pgcur)
        sequence_cols = sequence_columns(pgcur)
        create_tables(pgcur, ora, tables, metadata, hypertables, sequence_cols)
        state = load_state()
        substitutions = load_tables(pg, ora, tables, metadata, state)
        if os.getenv("TS_ONLY_TABLE"):
            return
        made_constraints = create_constraints(pgcur, ora)
        made_indexes = create_indexes(pgcur, ora)
        advance_identities(ora, sequence_cols)
        create_views(ora)
        result = validate(pgcur, ora, tables, state)
        report = {
            "completed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "elapsed_seconds": round(time.time() - started, 2),
            "source": "mycloud_timescale",
            "target_schema": required("ORACLE_USER").upper(),
            "schema_mapping": {"public": "(no prefix)", "hydro_model": "HM_", "rain_forecast": "RF_"},
            "timescale_hypertables_mapped_to_oracle_tables": len(hypertables),
            "constraints_created_this_run": made_constraints,
            "indexes_created_this_run": made_indexes,
            "substitutions": substitutions,
            "validation": result,
            "compatibility_notes": [
                "TimescaleDB internal schemas, chunks, compression metadata and jobs are not copied.",
                "PostgreSQL arrays are stored as JSON text in Oracle CLOB columns.",
                "PostgreSQL empty strings in required text columns are represented by one space in Oracle.",
                "Boolean values are represented by NUMBER(1).",
                "Keys containing TIMESTAMP WITH TIME ZONE are enforced by unique indexes on SYS_EXTRACT_UTC because Oracle does not permit that type in PRIMARY KEY or UNIQUE constraints.",
            ],
        }
        REPORT_PATH.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, default=str), flush=True)
        if result["row_count_mismatches"] or result["invalid_objects"]:
            raise SystemExit(2)
    finally:
        pg.close()
        ora.close()


if __name__ == "__main__":
    main()
