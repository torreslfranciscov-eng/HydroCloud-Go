#!/usr/bin/env python3
"""Migrate the DB_ATLAS SQL Server schema into an empty Oracle schema.

Credentials are read only from environment variables.  The program is
restart-safe when MIGRATION_RESET=1 is supplied; that option drops only
objects owned by the connected Oracle user.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import oracledb
import pyodbc


REPORT_PATH = Path(__file__).with_name("migration-report.json")
BATCH_SIZE = int(os.getenv("MIGRATION_BATCH_SIZE", "1000"))


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def q(name: str) -> str:
    """Quote an identifier while normalizing it for unquoted Oracle clients."""
    return '"' + name.upper().replace('"', '""') + '"'


def source_connect():
    cs = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={required('SOURCE_HOST')},{os.getenv('SOURCE_PORT', '1433')};"
        f"DATABASE={required('SOURCE_DATABASE')};"
        f"UID={required('SOURCE_USER')};PWD={required('SOURCE_PASSWORD')};"
        "Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=15"
    )
    return pyodbc.connect(cs, timeout=30)


def target_connect():
    return oracledb.connect(
        user=required("TARGET_USER"),
        password=required("TARGET_PASSWORD"),
        dsn=required("TARGET_DSN"),
    )


def rows(cur, sql: str, *params):
    cur.execute(sql, *params)
    return cur.fetchall()


def reset_target(conn):
    cur = conn.cursor()
    objects = rows(
        cur,
        """select object_name, object_type
             from user_objects
            where object_type in ('VIEW','TABLE')
            order by case object_type when 'VIEW' then 1 else 2 end""",
    )
    for name, object_type in objects:
        suffix = " cascade constraints purge" if object_type == "TABLE" else ""
        cur.execute(f"drop {object_type.lower()} {q(name)}{suffix}")
    print(f"Reset target: dropped {len(objects)} objects", flush=True)


def get_tables(src):
    return [
        (schema, table)
        for schema, table in rows(
            src,
            """select s.name, t.name
                 from sys.tables t join sys.schemas s on s.schema_id=t.schema_id
                where t.is_ms_shipped=0
                order by s.name,t.name""",
        )
    ]


def get_columns(src, schema, table):
    return rows(
        src,
        """select c.column_id,c.name,ty.name,c.max_length,c.precision,c.scale,
                  c.is_nullable,c.is_identity,dc.definition
             from sys.tables t
             join sys.schemas s on s.schema_id=t.schema_id
             join sys.columns c on c.object_id=t.object_id
             join sys.types ty on ty.user_type_id=c.user_type_id
             left join sys.default_constraints dc
               on dc.parent_object_id=c.object_id and dc.parent_column_id=c.column_id
            where s.name=? and t.name=? order by c.column_id""",
        schema,
        table,
    )


def oracle_type(type_name, max_length, precision, scale):
    t = type_name.lower()
    if t in ("int",):
        return "NUMBER(10)"
    if t == "bigint":
        return "NUMBER(19)"
    if t == "smallint":
        return "NUMBER(5)"
    if t == "tinyint":
        return "NUMBER(3)"
    if t == "bit":
        return "NUMBER(1)"
    if t in ("decimal", "numeric"):
        return f"NUMBER({precision},{scale})"
    if t in ("float", "real"):
        return "BINARY_DOUBLE"
    if t in ("datetime", "datetime2", "smalldatetime"):
        return "TIMESTAMP(3)"
    if t == "date":
        return "DATE"
    if t in ("uniqueidentifier",):
        return "CHAR(36)"
    if t in ("nvarchar", "nchar", "sysname"):
        length = 128 if t == "sysname" else (-1 if max_length == -1 else max_length // 2)
        if length < 0 or length > 2000:
            return "NCLOB"
        return f"NVARCHAR2({max(1, length)})"
    if t in ("varchar", "char"):
        if max_length < 0 or max_length > 4000:
            return "CLOB"
        return f"VARCHAR2({max(1, max_length)})"
    if t in ("varbinary", "binary", "image", "timestamp", "rowversion"):
        if max_length < 0 or max_length > 2000:
            return "BLOB"
        return f"RAW({max(1, max_length)})"
    if t in ("text",):
        return "CLOB"
    if t in ("ntext",):
        return "NCLOB"
    if t in ("money", "smallmoney"):
        return "NUMBER(19,4)"
    if t == "sql_variant":
        return "VARCHAR2(4000)"
    raise ValueError(f"Unsupported SQL Server type: {type_name}")


def oracle_default(value):
    if value is None:
        return None
    v = value.strip()
    while v.startswith("(") and v.endswith(")"):
        v = v[1:-1].strip()
    low = v.lower()
    if low in ("getdate()", "sysdatetime()"):
        return "SYSTIMESTAMP"
    if low in ("newid()",):
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        return v
    if v.startswith("N'"):
        return v[1:]
    if v.startswith("'"):
        return v
    return None


def create_tables(src, dst, tables):
    dcur = dst.cursor()
    metadata = {}
    for pos, (schema, table) in enumerate(tables, 1):
        columns = get_columns(src, schema, table)
        metadata[(schema, table)] = columns
        defs = []
        for _, name, typ, length, precision, scale, nullable, identity, default in columns:
            item = f"{q(name)} {oracle_type(typ, length, precision, scale)}"
            converted_default = oracle_default(default)
            if converted_default is not None:
                item += f" DEFAULT {converted_default}"
            if identity:
                item += " GENERATED BY DEFAULT ON NULL AS IDENTITY"
            if not nullable:
                item += " NOT NULL"
            defs.append(item)
        dcur.execute(f"create table {q(table)} (\n  " + ",\n  ".join(defs) + "\n)")
        print(f"DDL tables {pos}/{len(tables)} {schema}.{table}", flush=True)
    return metadata


def normalize_value(value, type_name, nullable, substitutions):
    if value is None:
        return None
    t = type_name.lower()
    if value == "" and not nullable and t in (
        "varchar", "nvarchar", "char", "nchar", "sysname", "text", "ntext"
    ):
        # Oracle treats an empty string as NULL. Preserve NOT NULL semantics
        # with a single-space sentinel and record the conversion.
        substitutions["required_empty_strings_to_space"] += 1
        return " "
    if isinstance(value, uuid.UUID):
        return str(value).upper()
    if t == "uniqueidentifier":
        return str(value).upper()
    if t == "sql_variant":
        return str(value)
    if t == "bit":
        return int(value)
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, (dt.datetime, dt.date, decimal.Decimal, bytes, str, int, float)):
        return value
    return str(value)


def load_data(src_conn, dst_conn, tables, metadata):
    result = {}
    substitutions = {"required_empty_strings_to_space": 0}
    for pos, (schema, table) in enumerate(tables, 1):
        columns = metadata[(schema, table)]
        names = [c[1] for c in columns]
        types = [c[2] for c in columns]
        nullable = [c[6] for c in columns]
        select_sql = f"select {','.join('[' + n.replace(']', ']]') + ']' for n in names)} from [{schema}].[{table}]"
        insert_sql = (
            f"insert into {q(table)} ({','.join(q(n) for n in names)}) "
            f"values ({','.join(':' + str(i + 1) for i in range(len(names)))})"
        )
        scur = src_conn.cursor()
        dcur = dst_conn.cursor()
        scur.execute(select_sql)
        loaded = 0
        while True:
            batch = scur.fetchmany(BATCH_SIZE)
            if not batch:
                break
            converted = [
                tuple(
                    normalize_value(value, types[i], nullable[i], substitutions)
                    for i, value in enumerate(record)
                )
                for record in batch
            ]
            dcur.executemany(insert_sql, converted)
            dst_conn.commit()
            loaded += len(converted)
        result[table] = loaded
        print(f"DATA {pos}/{len(tables)} {schema}.{table}: {loaded}", flush=True)
    return result, substitutions


def add_primary_keys(src, dst):
    sql = """select s.name,t.name,k.name,c.name,ic.key_ordinal
               from sys.key_constraints k
               join sys.tables t on t.object_id=k.parent_object_id
               join sys.schemas s on s.schema_id=t.schema_id
               join sys.index_columns ic on ic.object_id=t.object_id and ic.index_id=k.unique_index_id
               join sys.columns c on c.object_id=t.object_id and c.column_id=ic.column_id
              where k.type='PK' order by s.name,t.name,k.name,ic.key_ordinal"""
    grouped = {}
    for schema, table, constraint, column, _ in rows(src, sql):
        grouped.setdefault((schema, table, constraint), []).append(column)
    cur = dst.cursor()
    for (_, table, constraint), columns in grouped.items():
        cur.execute(
            f"alter table {q(table)} add constraint {q(constraint)} primary key "
            f"({','.join(q(c) for c in columns)})"
        )
    print(f"DDL primary keys: {len(grouped)}", flush=True)


def add_foreign_keys(src, dst):
    sql = """select ps.name,pt.name,fk.name,pc.name,rt.name,rc.name,
                    fkc.constraint_column_id,fk.delete_referential_action_desc
               from sys.foreign_keys fk
               join sys.foreign_key_columns fkc on fkc.constraint_object_id=fk.object_id
               join sys.tables pt on pt.object_id=fk.parent_object_id
               join sys.schemas ps on ps.schema_id=pt.schema_id
               join sys.columns pc on pc.object_id=pt.object_id and pc.column_id=fkc.parent_column_id
               join sys.tables rt on rt.object_id=fk.referenced_object_id
               join sys.columns rc on rc.object_id=rt.object_id and rc.column_id=fkc.referenced_column_id
              order by ps.name,pt.name,fk.name,fkc.constraint_column_id"""
    grouped = {}
    for schema, table, constraint, column, ref_table, ref_column, _, delete_action in rows(src, sql):
        item = grouped.setdefault((schema, table, constraint, ref_table, delete_action), [[], []])
        item[0].append(column)
        item[1].append(ref_column)
    cur = dst.cursor()
    for (_, table, constraint, ref_table, delete_action), (columns, ref_columns) in grouped.items():
        ddl = (
            f"alter table {q(table)} add constraint {q(constraint)} foreign key "
            f"({','.join(q(c) for c in columns)}) references {q(ref_table)} "
            f"({','.join(q(c) for c in ref_columns)})"
        )
        if delete_action == "CASCADE":
            ddl += " on delete cascade"
        elif delete_action == "SET_NULL":
            ddl += " on delete set null"
        cur.execute(ddl)
    print(f"DDL foreign keys: {len(grouped)}", flush=True)


def advance_identities(dst, metadata):
    cur = dst.cursor()
    count = 0
    for (_, table), columns in metadata.items():
        for _, name, _, _, _, _, _, identity, _ in columns:
            if identity:
                cur.execute(
                    f"alter table {q(table)} modify {q(name)} generated by default on null "
                    "as identity (start with limit value)"
                )
                count += 1
    print(f"DDL identities advanced: {count}", flush=True)


def convert_view(name, definition):
    match = re.search(r"\bAS\b", definition, flags=re.IGNORECASE)
    if not match:
        raise ValueError("missing AS")
    body = definition[match.end():].strip().rstrip(";")
    body = re.sub(r"\[([^]]+)\]", r"\1", body)
    body = re.sub(r"\bdbo\.", "", body, flags=re.IGNORECASE)
    body = re.sub(r"\bISNULL\s*\(", "NVL(", body, flags=re.IGNORECASE)
    body = re.sub(r"\bSUBSTRING\s*\(", "SUBSTR(", body, flags=re.IGNORECASE)
    body = re.sub(r"\bCAST\s*\((.*?)\s+AS\s+varchar\s*\((\d+)\)\s*\)", r"CAST(\1 AS VARCHAR2(\2))", body, flags=re.IGNORECASE)
    body = re.sub(r"\bN'", "'", body, flags=re.IGNORECASE)
    # Oracle allows AS for select-list aliases, but not table aliases.
    body = re.sub(
        r"(\bFROM|\bJOIN|,)\s+([A-Za-z_][A-Za-z0-9_$#]*)\s+AS\s+([A-Za-z_][A-Za-z0-9_$#]*)",
        r"\1 \2 \3",
        body,
        flags=re.IGNORECASE,
    )
    # The legacy views use + only for text concatenation.
    body = body.replace("+", "||")
    if name.lower() == "nv_estacionesadmin":
        body = re.sub(
            r"TRY_CAST\s*\(PARSENAME\s*\(REPLACE\s*\(Est\.Coordenadas,\s*',',\s*'\.'\),\s*2\)\s*AS\s*DECIMAL\s*\(10,6\)\s*\)",
            "TO_NUMBER(TRIM(SUBSTR(Est.Coordenadas,1,INSTR(Est.Coordenadas,',')-1)) DEFAULT NULL ON CONVERSION ERROR)",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            r"TRY_CAST\s*\(PARSENAME\s*\(REPLACE\s*\(Est\.Coordenadas,\s*',',\s*'\.'\),\s*1\)\s*AS\s*DECIMAL\s*\(10,6\)\s*\)",
            "TO_NUMBER(TRIM(SUBSTR(Est.Coordenadas,INSTR(Est.Coordenadas,',')+1)) DEFAULT NULL ON CONVERSION ERROR)",
            body,
            flags=re.IGNORECASE,
        )
    if name.lower() == "nv_ultimabitacoraestacion":
        # Oracle cannot apply DISTINCT directly to LOB values. SQL Server's
        # three nvarchar(max) display fields are projected to SQL-size text.
        for column in ("Descripcion", "Usuario", "UsuarioNombreCompleto"):
            body = re.sub(
                rf"vbe\.{column}",
                f"DBMS_LOB.SUBSTR(vbe.{column},2000,1) AS {column}",
                body,
                count=1,
                flags=re.IGNORECASE,
            )
    return f"create or replace view {q(name)} as\n{body}"


def create_views(src, dst):
    definitions = rows(
        src,
        """select v.name,m.definition from sys.views v
             join sys.sql_modules m on m.object_id=v.object_id
            where v.is_ms_shipped=0 order by v.name""",
    )
    pending = {name: definition for name, definition in definitions}
    errors = {}
    for _ in range(len(pending) + 1):
        progressed = False
        for name in list(pending):
            try:
                dst.cursor().execute(convert_view(name, pending[name]))
                del pending[name]
                errors.pop(name, None)
                progressed = True
                print(f"DDL view {name}", flush=True)
            except Exception as exc:
                errors[name] = str(exc)
        if not pending or not progressed:
            break
    return {"created": len(definitions) - len(pending), "failed": errors}


def validate(src, dst, tables, expected):
    actual = {}
    mismatches = {}
    cur = dst.cursor()
    for schema, table in tables:
        cur.execute(f"select count(*) from {q(table)}")
        actual[table] = cur.fetchone()[0]
        if actual[table] != expected[table]:
            mismatches[table] = {"source": expected[table], "target": actual[table]}
    cur.execute("select count(*) from user_constraints where constraint_type='P'")
    pk_count = cur.fetchone()[0]
    cur.execute("select count(*) from user_constraints where constraint_type='R'")
    fk_count = cur.fetchone()[0]
    cur.execute("select count(*) from user_views")
    view_count = cur.fetchone()[0]
    return {
        "source_rows": sum(expected.values()),
        "target_rows": sum(actual.values()),
        "table_count": len(tables),
        "primary_keys": pk_count,
        "foreign_keys": fk_count,
        "views": view_count,
        "row_count_mismatches": mismatches,
    }


def live_validation(src, dst):
    tables = get_tables(src)
    source_counts = {}
    target_counts = {}
    table_mismatches = {}
    dcur = dst.cursor()
    for schema, table in tables:
        scur = src.connection.cursor()
        scur.execute(f"select count(*) from [{schema}].[{table}]")
        source_counts[table] = scur.fetchone()[0]
        dcur.execute(f"select count(*) from {q(table)}")
        target_counts[table] = dcur.fetchone()[0]
        if source_counts[table] != target_counts[table]:
            table_mismatches[table] = {
                "source": source_counts[table], "target": target_counts[table]
            }

    view_mismatches = {}
    view_errors = {}
    view_names = [r[0] for r in rows(src, "select name from sys.views where is_ms_shipped=0 order by name")]
    for name in view_names:
        try:
            scur = src.connection.cursor()
            scur.execute(f"select count(*) from [dbo].[{name}]")
            source_count = scur.fetchone()[0]
            dcur.execute(f"select count(*) from {q(name)}")
            target_count = dcur.fetchone()[0]
            if source_count != target_count:
                view_mismatches[name] = {"source": source_count, "target": target_count}
        except Exception as exc:
            view_errors[name] = str(exc)

    dcur.execute("select object_name,object_type from user_objects where status <> 'VALID'")
    invalid_objects = [list(r) for r in dcur.fetchall()]
    dcur.execute(
        "select constraint_name,status,validated from user_constraints "
        "where constraint_type in ('P','R') and (status <> 'ENABLED' or validated <> 'VALIDATED')"
    )
    bad_constraints = [list(r) for r in dcur.fetchall()]
    return {
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_rows": sum(source_counts.values()),
        "target_rows": sum(target_counts.values()),
        "tables_checked": len(tables),
        "table_count_mismatches": table_mismatches,
        "views_checked": len(view_names),
        "view_count_mismatches": view_mismatches,
        "view_query_errors": view_errors,
        "invalid_objects": invalid_objects,
        "nonvalidated_constraints": bad_constraints,
    }


def main():
    started = time.time()
    src_conn = source_connect()
    dst_conn = target_connect()
    try:
        if os.getenv("MIGRATION_VALIDATE_ONLY") == "1":
            result = live_validation(src_conn.cursor(), dst_conn)
            report = (
                json.loads(REPORT_PATH.read_text(encoding="utf-8"))
                if REPORT_PATH.exists() else {}
            )
            report["live_validation"] = result
            REPORT_PATH.write_text(
                json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
            )
            print(json.dumps({"live_validation": result}, indent=2), flush=True)
            if any((
                result["table_count_mismatches"], result["view_count_mismatches"],
                result["view_query_errors"], result["invalid_objects"],
                result["nonvalidated_constraints"],
            )):
                raise SystemExit(2)
            return
        if os.getenv("MIGRATION_VIEWS_ONLY") == "1":
            view_result = create_views(src_conn.cursor(), dst_conn)
            if REPORT_PATH.exists():
                report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
                report["view_result"] = view_result
                cur = dst_conn.cursor()
                cur.execute("select count(*) from user_views")
                report.setdefault("validation", {})["views"] = cur.fetchone()[0]
                report["last_view_deploy_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                REPORT_PATH.write_text(
                    json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
                )
            print(json.dumps({"view_result": view_result}, indent=2), flush=True)
            if view_result["failed"]:
                raise SystemExit(2)
            return
        if os.getenv("MIGRATION_RESET") == "1":
            reset_target(dst_conn)
        cur = dst_conn.cursor()
        cur.execute("select count(*) from user_tables")
        if cur.fetchone()[0]:
            raise SystemExit("Target schema is not empty; set MIGRATION_RESET=1 to replace its objects")
        tables = get_tables(src_conn.cursor())
        print(f"Starting migration of {len(tables)} tables", flush=True)
        metadata = create_tables(src_conn.cursor(), dst_conn, tables)
        loaded, substitutions = load_data(src_conn, dst_conn, tables, metadata)
        add_primary_keys(src_conn.cursor(), dst_conn)
        add_foreign_keys(src_conn.cursor(), dst_conn)
        advance_identities(dst_conn, metadata)
        view_result = create_views(src_conn.cursor(), dst_conn)
        validation = validate(src_conn.cursor(), dst_conn, tables, loaded)
        report = {
            "completed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "elapsed_seconds": round(time.time() - started, 2),
            "validation": validation,
            "view_result": view_result,
            "substitutions": substitutions,
            "compatibility_notes": [
                "Oracle treats an empty string as NULL; required empty strings are stored as one space.",
                "NV_UltimaBitacoraEstacion projects three NCLOB fields to 2000 characters so DISTINCT is supported.",
            ],
        }
        REPORT_PATH.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, default=str), flush=True)
        if validation["row_count_mismatches"] or view_result["failed"]:
            raise SystemExit(2)
    finally:
        src_conn.close()
        dst_conn.close()


if __name__ == "__main__":
    main()
