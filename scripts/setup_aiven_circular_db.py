import os
import psycopg2
from psycopg2.extras import execute_values
import configparser
import sys

def _get_aiven_uri():
    if os.environ.get("AIVEN_URI"):
        return os.environ["AIVEN_URI"]
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(os.path.dirname(__file__), "..", "config.ini"))
    sec = cfg["timescaledb"]
    return f"postgres://{sec['user']}:{sec['password']}@{sec['host']}:{sec['port']}/{sec['database']}?sslmode={sec.get('sslmode', 'require')}"

AIVEN_URI = _get_aiven_uri()

def setup_schema():
    print("[1/4] Conectando a Aiven PostgreSQL...")
    conn = psycopg2.connect(AIVEN_URI)
    cur = conn.cursor()

    print("[2/4] Creando tablas e índices para almacenamiento circular...")

    # 1. dcp_datos
    cur.execute("""
    CREATE TABLE IF NOT EXISTS public.dcp_datos (
        ts TIMESTAMPTZ NOT NULL,
        dcp_id VARCHAR(20) NOT NULL,
        id_asignado VARCHAR(50),
        sensor_id VARCHAR(20) NOT NULL,
        variable VARCHAR(50),
        valor REAL,
        tipo VARCHAR(50),
        valido BOOLEAN DEFAULT TRUE,
        descripcion VARCHAR(200),
        anio SMALLINT,
        mes SMALLINT,
        dia SMALLINT,
        hora SMALLINT,
        minuto SMALLINT,
        CONSTRAINT dcp_datos_pkey PRIMARY KEY (ts, dcp_id, sensor_id)
    );
    CREATE INDEX IF NOT EXISTS idx_dcp_datos_lookup ON public.dcp_datos (dcp_id, sensor_id, ts DESC);
    CREATE INDEX IF NOT EXISTS idx_dcp_datos_ts ON public.dcp_datos (ts DESC);
    """)

    # 2. estatus_estaciones
    cur.execute("""
    CREATE TABLE IF NOT EXISTS public.estatus_estaciones (
        dcp_id VARCHAR(20) NOT NULL PRIMARY KEY,
        fecha_calculo TIMESTAMPTZ,
        intervalo_minutos INT DEFAULT 60,
        mensajes_esperados_48h INT,
        mensajes_recibidos_48h INT DEFAULT 0,
        color_estatus VARCHAR(20) DEFAULT 'NEGRO',
        fecha_ultima_tx TIMESTAMPTZ,
        servidor VARCHAR(50),
        transmitiendo BOOLEAN DEFAULT FALSE,
        rango_transmision INT DEFAULT 60
    );
    CREATE INDEX IF NOT EXISTS idx_estatus_ultima_tx ON public.estatus_estaciones (fecha_ultima_tx DESC);
    """)

    # 3. dcp_headers
    cur.execute("""
    CREATE TABLE IF NOT EXISTS public.dcp_headers (
        dcp_id VARCHAR(20) NOT NULL,
        timestamp_msg TIMESTAMPTZ NOT NULL,
        ts TIMESTAMPTZ,
        signal_strength SMALLINT,
        frequency_offset VARCHAR(20),
        mod_index VARCHAR(20),
        data_quality VARCHAR(20),
        channel SMALLINT,
        spacecraft VARCHAR(20),
        data_source VARCHAR(50),
        failure_code VARCHAR(10),
        raw_message TEXT,
        CONSTRAINT dcp_headers_pkey PRIMARY KEY (dcp_id, timestamp_msg)
    );
    CREATE INDEX IF NOT EXISTS idx_dcp_headers_dcp_time ON public.dcp_headers (dcp_id, timestamp_msg DESC);
    """)

    # 4. resumen_horario y resumen_diario
    cur.execute("""
    CREATE TABLE IF NOT EXISTS public.resumen_horario (
        ts TIMESTAMPTZ NOT NULL,
        dcp_id VARCHAR(20) NOT NULL,
        sensor_id VARCHAR(20) NOT NULL,
        id_asignado VARCHAR(50),
        variable VARCHAR(50),
        tipo VARCHAR(50),
        suma REAL,
        conteo INT,
        promedio REAL,
        minimo REAL,
        maximo REAL,
        acumulado REAL,
        CONSTRAINT resumen_horario_pkey PRIMARY KEY (ts, dcp_id, sensor_id)
    );
    CREATE INDEX IF NOT EXISTS idx_resumen_horario_lookup ON public.resumen_horario (dcp_id, sensor_id, ts DESC);

    CREATE TABLE IF NOT EXISTS public.resumen_diario (
        fecha DATE NOT NULL,
        dcp_id VARCHAR(20) NOT NULL,
        sensor_id VARCHAR(20) NOT NULL,
        id_asignado VARCHAR(50),
        variable VARCHAR(50),
        tipo VARCHAR(50),
        suma REAL,
        conteo INT,
        promedio REAL,
        minimo REAL,
        maximo REAL,
        acumulado REAL,
        CONSTRAINT resumen_diario_pkey PRIMARY KEY (fecha, dcp_id, sensor_id)
    );
    """)

    # 5. Función de limpieza circular (Hot window)
    cur.execute("""
    CREATE OR REPLACE FUNCTION public.limpiar_datos_circulares(dias_retencion INT DEFAULT 15)
    RETURNS TABLE(filas_eliminadas_datos BIGINT, filas_eliminadas_headers BIGINT) AS $$
    DECLARE
        del_datos BIGINT;
        del_headers BIGINT;
    BEGIN
        DELETE FROM public.dcp_datos WHERE ts < NOW() - (dias_retencion || ' days')::INTERVAL;
        GET DIAGNOSTICS del_datos = ROW_COUNT;

        DELETE FROM public.dcp_headers WHERE timestamp_msg < NOW() - (dias_retencion || ' days')::INTERVAL;
        GET DIAGNOSTICS del_headers = ROW_COUNT;

        RETURN QUERY SELECT del_datos, del_headers;
    END;
    $$ LANGUAGE plpgsql;
    """)

    conn.commit()
    print("[3/4] ✅ Esquema circular y función de retención creados exitosamente.")
    conn.close()

def sync_initial_seed():
    print("[4/4] Sincronizando catálogo actual y semáforos desde atlas16...")
    try:
        source = psycopg2.connect(host='atlas16.ddns.net', port=5432, dbname='mycloud_timescale', user='postgres', password='Cfe123pass', connect_timeout=8)
        target = psycopg2.connect(AIVEN_URI)
        
        cur_src = source.cursor()
        cur_tgt = target.cursor()

        # 1. Copiar estatus_estaciones
        cur_src.execute("""
            SELECT dcp_id, fecha_calculo, intervalo_minutos, mensajes_esperados_48h, mensajes_recibidos_48h,
                   color_estatus, fecha_ultima_tx, servidor, transmitiendo, rango_transmision
            FROM public.estatus_estaciones
        """)
        estatus_rows = cur_src.fetchall()
        if estatus_rows:
            execute_values(cur_tgt, """
                INSERT INTO public.estatus_estaciones (
                    dcp_id, fecha_calculo, intervalo_minutos, mensajes_esperados_48h, mensajes_recibidos_48h,
                    color_estatus, fecha_ultima_tx, servidor, transmitiendo, rango_transmision
                ) VALUES %s
                ON CONFLICT (dcp_id) DO UPDATE SET
                    fecha_calculo = EXCLUDED.fecha_calculo,
                    intervalo_minutos = EXCLUDED.intervalo_minutos,
                    mensajes_esperados_48h = EXCLUDED.mensajes_esperados_48h,
                    mensajes_recibidos_48h = EXCLUDED.mensajes_recibidos_48h,
                    color_estatus = EXCLUDED.color_estatus,
                    fecha_ultima_tx = EXCLUDED.fecha_ultima_tx,
                    servidor = EXCLUDED.servidor,
                    transmitiendo = EXCLUDED.transmitiendo,
                    rango_transmision = EXCLUDED.rango_transmision
            """, estatus_rows)
            target.commit()
            print(f"      ✅ {len(estatus_rows)} estaciones semaforizadas sincronizadas en Aiven.")

        # 2. Copiar últimas 48 horas de dcp_datos para tener datos iniciales inmediatos
        cur_src.execute("""
            SELECT ts, dcp_id, id_asignado, sensor_id, variable, valor, tipo, valido, descripcion,
                   anio, mes, dia, hora, minuto
            FROM public.dcp_datos
            WHERE ts >= NOW() - INTERVAL '48 hours'
        """)
        recent_datos = cur_src.fetchall()
        if recent_datos:
            execute_values(cur_tgt, """
                INSERT INTO public.dcp_datos (
                    ts, dcp_id, id_asignado, sensor_id, variable, valor, tipo, valido, descripcion,
                    anio, mes, dia, hora, minuto
                ) VALUES %s
                ON CONFLICT (ts, dcp_id, sensor_id) DO NOTHING
            """, recent_datos, page_size=2000)
            target.commit()
            print(f"      ✅ {len(recent_datos)} lecturas recientes (últimas 48h) cargadas en Aiven.")

        # 3. Sincronizar ultimas_mediciones desde dcp_datos en Aiven
        cur_tgt.execute("""
            INSERT INTO public.ultimas_mediciones (dcp_id, variable, ts, valor, tipo)
            SELECT DISTINCT ON (dcp_id, variable) dcp_id, variable, ts, valor, tipo
            FROM public.dcp_datos
            WHERE variable IS NOT NULL AND valor IS NOT NULL
            ORDER BY dcp_id, variable, ts DESC
            ON CONFLICT (dcp_id, variable) DO UPDATE SET
                ts = EXCLUDED.ts,
                valor = EXCLUDED.valor,
                tipo = EXCLUDED.tipo
        """)
        target.commit()
        print("      ✅ ultimas_mediciones sincronizada en Aiven.")

        # 4. Copiar resumen_horario y resumen_diario (últimos 7 días)
        cur_src.execute("""
            SELECT ts, dcp_id, sensor_id, id_asignado, variable, tipo, suma, conteo, promedio, minimo, maximo, acumulado
            FROM public.resumen_horario
            WHERE ts >= NOW() - INTERVAL '7 days'
        """)
        rows_rh = cur_src.fetchall()
        if rows_rh:
            execute_values(cur_tgt, """
                INSERT INTO public.resumen_horario (
                    ts, dcp_id, sensor_id, id_asignado, variable, tipo, suma, conteo, promedio, minimo, maximo, acumulado
                ) VALUES %s
                ON CONFLICT (ts, dcp_id, sensor_id) DO NOTHING
            """, rows_rh, page_size=2000)
            target.commit()
            print(f"      ✅ {len(rows_rh)} filas de resumen_horario (7d) cargadas en Aiven.")

        cur_src.execute("""
            SELECT fecha, dcp_id, sensor_id, id_asignado, variable, tipo, suma, conteo, promedio, minimo, maximo, acumulado
            FROM public.resumen_diario
            WHERE fecha >= CURRENT_DATE - INTERVAL '7 days'
        """)
        rows_rd = cur_src.fetchall()
        if rows_rd:
            execute_values(cur_tgt, """
                INSERT INTO public.resumen_diario (
                    fecha, dcp_id, sensor_id, id_asignado, variable, tipo, suma, conteo, promedio, minimo, maximo, acumulado
                ) VALUES %s
                ON CONFLICT (fecha, dcp_id, sensor_id) DO NOTHING
            """, rows_rd, page_size=2000)
            target.commit()
            print(f"      ✅ {len(rows_rd)} filas de resumen_diario (7d) cargadas en Aiven.")

        # 5. Copiar lluvia_acumulada
        cur_src.execute("""
            SELECT id_asignado, dcp_id, sensor_id, variable, periodo_inicio, periodo_fin,
                   tipo_periodo, acumulado, horas_con_dato, ultima_actualizacion
            FROM public.lluvia_acumulada
        """)
        rows_la = cur_src.fetchall()
        if rows_la:
            execute_values(cur_tgt, """
                INSERT INTO public.lluvia_acumulada (
                    id_asignado, dcp_id, sensor_id, variable, periodo_inicio, periodo_fin,
                    tipo_periodo, acumulado, horas_con_dato, ultima_actualizacion
                ) VALUES %s
                ON CONFLICT (id_asignado, sensor_id, tipo_periodo) DO UPDATE SET
                    periodo_inicio = EXCLUDED.periodo_inicio,
                    periodo_fin = EXCLUDED.periodo_fin,
                    acumulado = EXCLUDED.acumulado,
                    horas_con_dato = EXCLUDED.horas_con_dato,
                    ultima_actualizacion = EXCLUDED.ultima_actualizacion
            """, rows_la, page_size=2000)
            target.commit()
            print(f"      ✅ {len(rows_la)} filas de lluvia_acumulada cargadas en Aiven.")

        source.close()
        target.close()
    except Exception as e:
        print(f"      ⚠️ No se pudo sembrar datos iniciales (opcional): {e}")

if __name__ == "__main__":
    setup_schema()
    sync_initial_seed()
    print("\n🎉 Base de datos Aiven lista para operar con almacenamiento circular.")
