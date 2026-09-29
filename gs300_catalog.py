"""Authoritative decoder configuration; no ingestion or database writes on import."""
import datetime
import math
import os


def duration_minutes(value):
    parts = str(value).strip().split(':')
    if len(parts) != 3:
        raise ValueError('Horario debe tener formato HH:MM:SS')
    h, m, s = map(int, parts)
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError('Horario inválido')
    return h * 60 + m + s / 60


def connect_catalog(config):
    import oracledb
    def setting(key):
        return os.environ.get('ORACLE_CATALOG_' + key.upper()) or config.get('oracle_catalog', key, fallback='')
    user, password = setting('user'), setting('password')
    dsn = setting('dsn') or os.environ.get('ORACLE_DSN') or config.get('oracle_cloud', 'dsn', fallback='')
    if not all((user, password, dsn)):
        raise RuntimeError('Configura ORACLE_CATALOG_USER/PASSWORD/DSN o [oracle_catalog]. No se infiere configuración del histórico.')
    return oracledb.connect(user=user, password=password, dsn=dsn)


def load_stations(connection):
    with connection.cursor() as cur:
        cur.execute('''SELECT G.IDSATELITAL,E.IDASIGNADO,E.NOMBRE,G.PRIMERATRANSMISION,
            G.INTERVALOTRANSMISION,G.RANGOTRANSMISION,G.DECODIFICADOR,E.LATITUD,E.LONGITUD
            FROM HYDROCLOUD.DATOSGOES G JOIN HYDROCLOUD.ESTACION E ON E.ID=G.IDESTACION
            WHERE E.ACTIVO=1 AND E.GOES=1''')
        result = {}
        for dcp, code, name, first, interval, span, decoder, lat, lon in cur:
            try:
                if not dcp or not code or not decoder:
                    raise ValueError('Configuración GOES incompleta: identificador, clave o decoder')
                phase, cadence, coverage = map(duration_minutes, (first, interval, span))
                if not 0 <= phase < 1440 or cadence <= 0 or coverage <= 0:
                    raise ValueError('Horario GOES inválido para ' + str(code))
                dcp = str(dcp).strip().upper()
                if dcp in result:
                    raise ValueError('DCP duplicado en catálogo: ' + dcp)
                result[dcp] = dict(nombre=str(name).strip(), id_asignado=str(code).strip(),
                    primera_transmision=str(first).strip(), intervalo_transmision=cadence,
                    rango_transmision=coverage, minuto=int(phase) % 60,
                    decoder=str(decoder).strip(), latitud=lat, longitud=lon)
            except (ValueError, TypeError) as exc:
                print(f"[CONFIG RECHAZADA] {code} / {dcp}: {exc}")
        if not result:
            raise ValueError("No hay estaciones GOES con configuración válida")
        return result


def load_sensors(connection):
    with connection.cursor() as cur:
        cur.execute('''SELECT E.IDASIGNADO,S.NUMEROSENSOR,T.NOMBRE,S.PUNTODECIMAL,
            S.PERIODOMUESTRA,S.VALORMINIMO,S.VALORMAXIMO,S.ORDEN,U.ABREVIATURA,
            T.ESCALCULADA,
            (SELECT CASE WHEN COUNT(DISTINCT TRIM(G.DECODIFICADOR))=1
              THEN MAX(TRIM(G.DECODIFICADOR)) END FROM HYDROCLOUD.DATOSGOES G
              WHERE G.IDESTACION=E.ID)
            FROM HYDROCLOUD.SENSOR S JOIN HYDROCLOUD.ESTACION E ON E.ID=S.IDESTACION
            JOIN HYDROCLOUD.TIPOSENSOR T ON T.ID=S.IDTIPOSENSOR
            LEFT JOIN HYDROCLOUD.UNIDADMEDIDA U ON U.ID=S.IDUNIDADMEDIDA
            WHERE E.ACTIVO=1 AND S.ACTIVO=1 ORDER BY E.IDASIGNADO,S.NUMEROSENSOR''')
        result = {}
        for code, number, name, decimals, period, low, high, order, unit, calculated, decoder in cur:
            if number is None or decimals is None or period is None or float(period) <= 0:
                raise ValueError('Sensor sin periodo/decimales válidos: ' + str(code))
            sensor = dict(numero_sensor=str(number).strip().zfill(4), nombre=str(name),
                decimales=int(decimals), periodo=float(period), posiciones=[],
                orden=order, unidad=str(unit).strip() if unit is not None else None,
                calculada=calculated, decoder=decoder)
            if low is not None:
                sensor['valor_minimo'] = float(low)
            if high is not None:
                sensor['valor_maximo'] = float(high)
            result.setdefault(str(code).strip(), []).append(sensor)
        return result


def assign_positions(sensors, coverage):
    if not math.isfinite(coverage) or coverage <= 0:
        raise ValueError('Rango de datos inválido')
    position, seen = 0, set()
    ordered = sorted(sensors, key=lambda s: s['numero_sensor'])
    for sensor in ordered:
        number, period = sensor['numero_sensor'], sensor['periodo']
        if number in seen or not math.isfinite(period) or period <= 0:
            raise ValueError('Sensor duplicado o periodo inválido: ' + number)
        seen.add(number)
        count = coverage / period
        if count < 1:
            count = 1  # Existing single-value representation for slower sensors.
        if not math.isclose(count, round(count), abs_tol=1e-9):
            raise ValueError('Rango no divisible por periodo: ' + number)
        count = int(round(count))
        sensor['posiciones'] = list(range(position, position + count))
        position += count
    return ordered


def validate_words(values, sensors):
    expected = sum(len(s['posiciones']) for s in sensors)
    if expected == 0 or len(values) != expected:
        raise ValueError(f'GS300: {len(values)} valores recibidos; catálogo exige {expected}. Mensaje no insertado.')


def next_fetch(data, now):
    """UTC cadence anchored to first transmission; range is never scheduling input."""
    phase = duration_minutes(data['primera_transmision']) * 60
    cadence = float(data['intervalo_transmision']) * 60
    if cadence <= 0:
        raise ValueError('Intervalo de transmisión inválido')
    anchor = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=phase + 120)
    elapsed = (now - anchor).total_seconds()
    return anchor + datetime.timedelta(seconds=(math.floor(elapsed / cadence) + 1) * cadence)
