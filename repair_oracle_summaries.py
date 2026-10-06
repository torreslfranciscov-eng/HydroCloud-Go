"""Audita o repara resúmenes Oracle afectados por la regresión del 2026-09-29.

Sin ``--apply`` sólo reporta el alcance. La reparación:

* invalida direcciones de viento físicamente imposibles;
* retira los agregados de dirección contaminados;
* reconstruye, mediante MERGE, los resúmenes horario y diario desde ``--start``.
"""

from __future__ import annotations

import argparse
import configparser
import datetime as dt
import os
import time


HOURLY_MERGE = """
MERGE /*+ NO_PARALLEL(t) */ INTO resumen_horario t
USING (
    SELECT /*+ NO_PARALLEL(dcp_datos) */
        TRUNC(ts - (1/1440), 'HH') AS ts,
        dcp_id,
        sensor_id,
        MAX(id_asignado) AS id_asignado,
        MAX(variable) AS variable,
        MAX(tipo) AS tipo,
        SUM(valor) AS suma,
        COUNT(*) AS conteo,
        AVG(valor) AS promedio,
        MIN(valor) AS minimo,
        MAX(valor) AS maximo,
        SUM(valor) AS acumulado
    FROM dcp_datos
    WHERE ts >= :start_ts AND ts < :end_ts AND valido = 1
    GROUP BY TRUNC(ts - (1/1440), 'HH'), dcp_id, sensor_id
) src
ON (t.ts = src.ts AND t.dcp_id = src.dcp_id AND t.sensor_id = src.sensor_id)
WHEN MATCHED THEN UPDATE SET
    t.id_asignado = src.id_asignado,
    t.variable = src.variable,
    t.tipo = src.tipo,
    t.suma = src.suma,
    t.conteo = src.conteo,
    t.promedio = src.promedio,
    t.minimo = src.minimo,
    t.maximo = src.maximo,
    t.acumulado = src.acumulado
WHEN NOT MATCHED THEN INSERT
    (ts, dcp_id, sensor_id, id_asignado, variable, tipo,
     suma, conteo, promedio, minimo, maximo, acumulado)
VALUES
    (src.ts, src.dcp_id, src.sensor_id, src.id_asignado, src.variable, src.tipo,
     src.suma, src.conteo, src.promedio, src.minimo, src.maximo, src.acumulado)
"""


DAILY_MERGE = """
MERGE /*+ NO_PARALLEL(t) */ INTO resumen_diario t
USING (
    SELECT /*+ NO_PARALLEL(dcp_datos) */
        TRUNC(SYS_EXTRACT_UTC(ts)) AS fecha,
        dcp_id,
        sensor_id,
        MAX(id_asignado) AS id_asignado,
        MAX(variable) AS variable,
        MAX(tipo) AS tipo,
        SUM(valor) AS suma,
        COUNT(*) AS conteo,
        AVG(valor) AS promedio,
        MIN(valor) AS minimo,
        MAX(valor) AS maximo,
        SUM(valor) AS acumulado
    FROM dcp_datos
    WHERE ts >= :start_ts AND ts < :end_ts AND valido = 1
    GROUP BY TRUNC(SYS_EXTRACT_UTC(ts)), dcp_id, sensor_id
) src
ON (t.fecha = src.fecha AND t.dcp_id = src.dcp_id AND t.sensor_id = src.sensor_id)
WHEN MATCHED THEN UPDATE SET
    t.id_asignado = src.id_asignado,
    t.variable = src.variable,
    t.tipo = src.tipo,
    t.suma = src.suma,
    t.conteo = src.conteo,
    t.promedio = src.promedio,
    t.minimo = src.minimo,
    t.maximo = src.maximo,
    t.acumulado = src.acumulado
WHEN NOT MATCHED THEN INSERT
    (fecha, dcp_id, sensor_id, id_asignado, variable, tipo,
     suma, conteo, promedio, minimo, maximo, acumulado)
VALUES
    (src.fecha, src.dcp_id, src.sensor_id, src.id_asignado, src.variable, src.tipo,
     src.suma, src.conteo, src.promedio, src.minimo, src.maximo, src.acumulado)
"""


def utc_midnight(value: str) -> dt.datetime:
    return dt.datetime.combine(
        dt.date.fromisoformat(value), dt.time.min, tzinfo=dt.timezone.utc
    )


def repair_window_start(start: dt.datetime, corrupt_start: dt.datetime) -> dt.datetime:
    """Include every row that may be invalidated in the rebuilt summaries."""
    return min(start, corrupt_start)


def scalar(cursor, sql: str, binds=None) -> int:
    cursor.execute(sql, binds or {})
    return int(cursor.fetchone()[0] or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-09-29")
    parser.add_argument("--corrupt-since", default="2026-09-24")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # python-oracledb binds aware datetimes using the process timezone.
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()

    import oracledb

    cfg = configparser.ConfigParser()
    cfg.read("config.ini")
    requested_start = utc_midnight(args.start)
    corrupt_start = utc_midnight(args.corrupt_since)
    start_ts = repair_window_start(requested_start, corrupt_start)
    end_ts = dt.datetime.now(dt.timezone.utc)
    binds = {"start_ts": start_ts, "end_ts": end_ts}

    with oracledb.connect(
        user=cfg["oracle_cloud"]["user"],
        password=cfg["oracle_cloud"]["password"],
        dsn=cfg["oracle_cloud"]["dsn"],
    ) as conn:
        conn.call_timeout = 20 * 60 * 1000
        cur = conn.cursor()
        # Autonomous Database may enable parallel DML from the service profile.
        # A large MERGE then can deadlock against its own workers (ORA-12860).
        cur.execute("ALTER SESSION DISABLE PARALLEL DML")
        cur.execute("ALTER SESSION DISABLE PARALLEL QUERY")
        corrupt_binds = {"corrupt_start": corrupt_start, "end_ts": end_ts}
        bad_raw = scalar(cur, """
            SELECT COUNT(*) FROM dcp_datos
            WHERE ts >= :corrupt_start AND ts < :end_ts AND valido = 1
              AND UPPER(variable) LIKE '%DIRECCI%'
              AND (valor < 0 OR valor > 360)
        """, corrupt_binds)
        bad_hourly = scalar(cur, """
            SELECT COUNT(*) FROM resumen_horario
            WHERE ts >= :start_ts AND ts < :end_ts
              AND UPPER(variable) LIKE '%DIRECCI%'
              AND (minimo < 0 OR maximo > 360)
        """, binds)
        bad_daily = scalar(cur, """
            SELECT COUNT(*) FROM resumen_diario
            WHERE fecha >= TRUNC(CAST(:start_ts AS DATE))
              AND fecha < TRUNC(CAST(:end_ts AS DATE)) + 1
              AND UPPER(variable) LIKE '%DIRECCI%'
              AND (minimo < 0 OR maximo > 360)
        """, binds)
        expected_hourly = scalar(cur, """
            SELECT COUNT(*) FROM (
                SELECT TRUNC(ts - (1/1440), 'HH'), dcp_id, sensor_id
                FROM dcp_datos
                WHERE ts >= :start_ts AND ts < :end_ts AND valido = 1
                GROUP BY TRUNC(ts - (1/1440), 'HH'), dcp_id, sensor_id
            )
        """, binds)
        expected_daily = scalar(cur, """
            SELECT COUNT(*) FROM (
                SELECT TRUNC(SYS_EXTRACT_UTC(ts)), dcp_id, sensor_id
                FROM dcp_datos
                WHERE ts >= :start_ts AND ts < :end_ts AND valido = 1
                GROUP BY TRUNC(SYS_EXTRACT_UTC(ts)), dcp_id, sensor_id
            )
        """, binds)
        print({
            "mode": "apply" if args.apply else "dry-run",
            "start": start_ts.isoformat(),
            "end": end_ts.isoformat(),
            "corrupt_direction_raw": bad_raw,
            "corrupt_direction_hourly": bad_hourly,
            "corrupt_direction_daily": bad_daily,
            "expected_hourly_groups": expected_hourly,
            "expected_daily_groups": expected_daily,
        })
        if not args.apply:
            return

        cur.execute("""
            UPDATE dcp_datos
            SET valido = 0,
                descripcion = 'Dirección fuera del intervalo físico [0, 360]'
            WHERE ts >= :corrupt_start AND ts < :end_ts AND valido = 1
              AND UPPER(variable) LIKE '%DIRECCI%'
              AND (valor < 0 OR valor > 360)
        """, corrupt_binds)
        print("raw_invalidated", cur.rowcount)
        cur.execute("""
            DELETE FROM resumen_horario
            WHERE ts >= :start_ts AND ts < :end_ts
              AND UPPER(variable) LIKE '%DIRECCI%'
              AND (minimo < 0 OR maximo > 360)
        """, binds)
        print("bad_hourly_deleted", cur.rowcount)
        cur.execute("""
            DELETE FROM resumen_diario
            WHERE fecha >= TRUNC(CAST(:start_ts AS DATE))
              AND fecha < TRUNC(CAST(:end_ts AS DATE)) + 1
              AND UPPER(variable) LIKE '%DIRECCI%'
              AND (minimo < 0 OR maximo > 360)
        """, binds)
        print("bad_daily_deleted", cur.rowcount)

        cur.execute(HOURLY_MERGE, binds)
        print("hourly_merged", cur.rowcount)
        cur.execute(DAILY_MERGE, binds)
        print("daily_merged", cur.rowcount)
        conn.commit()


if __name__ == "__main__":
    main()
