import os
import sys
import configparser
import psycopg2

def _get_aiven_uri():
    if os.environ.get("AIVEN_URI"):
        return os.environ["AIVEN_URI"]
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(os.path.dirname(__file__), "..", "config.ini"))
    sec = cfg["timescaledb"]
    return f"postgres://{sec['user']}:{sec['password']}@{sec['host']}:{sec['port']}/{sec['database']}?sslmode={sec.get('sslmode', 'require')}"

AIVEN_URI = _get_aiven_uri()

DDL_VISTA_DIAGNOSTICO = """
CREATE OR REPLACE VIEW public.v_almacenamiento_circular AS
SELECT
    ROUND((pg_database_size(current_database()) / (1024.0 * 1024.0))::numeric, 2) AS tamano_actual_mb,
    4000.00 AS cuota_objetivo_mb,
    5120.00 AS limite_aiven_gratis_mb,
    ROUND(((pg_database_size(current_database()) / (1024.0 * 1024.0 * 4000.0)) * 100)::numeric, 1) AS pct_cuota_usada,
    (SELECT COUNT(*) FROM public.dcp_datos) AS total_filas_datos,
    (SELECT MIN(ts) FROM public.dcp_datos) AS fecha_mas_antigua,
    (SELECT MAX(ts) FROM public.dcp_datos) AS fecha_mas_reciente,
    ROUND((EXTRACT(EPOCH FROM ((SELECT MAX(ts) FROM public.dcp_datos) - (SELECT MIN(ts) FROM public.dcp_datos))) / 86400.0)::numeric, 1) AS dias_en_ventana;
"""

DDL_PROCEDIMIENTO_4GB = """
CREATE OR REPLACE FUNCTION public.gestionar_cupo_circular(
    p_limite_mb NUMERIC DEFAULT 4000.0,
    p_dias_maximos INT DEFAULT 40
)
RETURNS TABLE(
    tamano_inicial_mb NUMERIC,
    filas_eliminadas_tiempo BIGINT,
    filas_eliminadas_tamano BIGINT,
    tamano_final_mb NUMERIC
) AS $func$
DECLARE
    v_tam_ini NUMERIC;
    v_tam_act NUMERIC;
    v_del_tiempo BIGINT := 0;
    v_del_tamano BIGINT := 0;
    v_del_lote BIGINT;
    v_min_ts TIMESTAMPTZ;
    v_limite_corte TIMESTAMPTZ;
BEGIN
    v_tam_ini := ROUND((pg_database_size(current_database()) / (1024.0 * 1024.0))::numeric, 2);

    -- Paso A: Purgar datos más antiguos que el límite de días (~40 días para 4 GB)
    v_limite_corte := NOW() - (p_dias_maximos || ' days')::INTERVAL;
    DELETE FROM public.dcp_datos WHERE ts < v_limite_corte;
    GET DIAGNOSTICS v_del_tiempo = ROW_COUNT;

    DELETE FROM public.dcp_headers WHERE timestamp_msg < v_limite_corte;
    DELETE FROM public.bitacora_goes WHERE timestamp_utc < v_limite_corte;
    DELETE FROM public.resumen_horario WHERE ts < v_limite_corte;

    -- Paso B: Si el tamaño de la base de datos supera el límite de 4 GB,
    -- purgar progresivamente los días más antiguos hasta estar por debajo del límite
    LOOP
        v_tam_act := ROUND((pg_database_size(current_database()) / (1024.0 * 1024.0))::numeric, 2);
        EXIT WHEN v_tam_act <= p_limite_mb;

        SELECT MIN(ts) INTO v_min_ts FROM public.dcp_datos;
        EXIT WHEN v_min_ts IS NULL;

        -- Borrar el bloque de 1 día más antiguo
        DELETE FROM public.dcp_datos WHERE ts < (v_min_ts + INTERVAL '1 day');
        GET DIAGNOSTICS v_del_lote = ROW_COUNT;
        EXIT WHEN v_del_lote = 0;

        v_del_tamano := v_del_tamano + v_del_lote;
        DELETE FROM public.dcp_headers WHERE timestamp_msg < (v_min_ts + INTERVAL '1 day');
        DELETE FROM public.bitacora_goes WHERE timestamp_utc < (v_min_ts + INTERVAL '1 day');
        DELETE FROM public.resumen_horario WHERE ts < (v_min_ts + INTERVAL '1 day');
    END LOOP;

    v_tam_act := ROUND((pg_database_size(current_database()) / (1024.0 * 1024.0))::numeric, 2);

    RETURN QUERY SELECT v_tam_ini, v_del_tiempo, v_del_tamano, v_tam_act;
END;
$func$ LANGUAGE plpgsql;
"""

def asegurar_procedimientos(conn):
    cur = conn.cursor()
    cur.execute(DDL_VISTA_DIAGNOSTICO)
    cur.execute(DDL_PROCEDIMIENTO_4GB)
    conn.commit()

def mostrar_diagnostico(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM public.v_almacenamiento_circular;")
    r = cur.fetchone()
    print("\n=======================================================")
    print("      📊 DIAGNÓSTICO DE CAPACIDAD CIRCULAR (4 GB)      ")
    print("=======================================================")
    print(f" • Tamaño actual BD:     {r[0]} MB")
    print(f" • Cuota configurada:    {r[1]} MB (4.0 GB)")
    print(f" • Límite máximo Aiven:  {r[2]} MB (5.0 GB)")
    print(f" • Porcentaje de cuota:  {r[3]}% usado")
    print(f" • Registros de datos:   {r[4]:,}")
    print(f" • Ventana en BD:        {r[5]} hasta {r[6]}")
    print(f" • Días cubiertos:       {r[7]} días")
    print("=======================================================\n")

def ejecutar_control_cupo(limite_mb=4000.0, dias_max=40):
    conn = psycopg2.connect(AIVEN_URI)
    asegurar_procedimientos(conn)
    cur = conn.cursor()
    cur.execute("SELECT * FROM public.gestionar_cupo_circular(%s, %s);", (limite_mb, dias_max))
    tam_ini, del_tiempo, del_tamano, tam_fin = cur.fetchone()
    conn.commit()

    print(f"[CIRCULAR 4GB] Control ejecutado:")
    print(f" - Tamaño antes: {tam_ini} MB -> Tamaño después: {tam_fin} MB")
    if del_tiempo > 0:
        print(f" - Purgados por antigüedad (> {dias_max} días): {del_tiempo:,} registros")
    if del_tamano > 0:
        print(f" - Purgados por rebase de cuota (> {limite_mb} MB): {del_tamano:,} registros")
    if del_tiempo == 0 and del_tamano == 0:
        print(f" - ✅ Base de datos saludable dentro de la cuota de 4 GB.")

    mostrar_diagnostico(conn)
    conn.close()

if __name__ == "__main__":
    limite = float(sys.argv[1]) if len(sys.argv) > 1 else 4000.0
    dias = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    ejecutar_control_cupo(limite, dias)
