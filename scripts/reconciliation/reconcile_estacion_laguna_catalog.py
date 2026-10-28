"""Reconcile ESTACION LAGUNA with its verified 106-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'GFLAGUNA04'
DCP = '15F492E2'
PERIOD_CHANGES = {'0015': 10, '0016': 10, '0017': 10,
                  '0020': 120, '0021': 120}
LAYOUT = (
    ('0001', 0, 12, 10), ('0002', 12, 12, 10),
    ('0004', 24, 12, 10), ('0005', 36, 12, 10),
    ('0006', 48, 2, 60), ('0007', 50, 2, 60),
    ('0008', 52, 2, 60), ('0009', 54, 2, 60),
    ('0010', 56, 2, 60), ('0011', 58, 2, 60),
    ('0012', 60, 2, 60), ('0013', 62, 2, 60),
    ('0014', 64, 2, 60), ('0015', 66, 12, 10),
    ('0016', 78, 12, 10), ('0017', 90, 12, 10),
    ('0020', 102, 1, 120), ('0021', 103, 1, 120),
    ('0022', 104, 2, 60),
)


def prove_layout(connection):
    cursor = connection.cursor()
    cursor.execute(
        '''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
           FROM DCP_HEADERS WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(7,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
           ORDER BY TIMESTAMP_MSG''', dcp=DCP)
    frames = []
    for stamp, raw in cursor:
        words = gs300_payload_words(raw[37:].encode('latin1'), station=STATION)
        if len(words) != 106:
            raise ValueError(f'ESTACION LAGUNA: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('ESTACION LAGUNA: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 106, 'segments': {}}
    for sensor, start, count, period in LAYOUT:
        checks = failures = 0
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        for (old_stamp, old), (new_stamp, new) in zip(frames, frames[1:]):
            shift = round((new_stamp - old_stamp).total_seconds() / 60 / period)
            if 0 < shift < count:
                left = old[start:start + count - shift]
                right = new[start + shift:start + count]
                checks += len(left)
                failures += sum(a != b for a, b in zip(left, right))
        # Intensity is recalculated in a few overlapping buckets by the DCP.
        allowed = 40 if sensor == '0005' else 0
        if failures > allowed or (count > 1 and not checks):
            raise ValueError(f'ESTACION LAGUNA: solapamiento inválido en {sensor}')
        proof['segments'][sensor] = {
            'start': start, 'count': count, 'period': period,
            'overlap_checks': checks, 'overlap_failures': failures,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }
    state_values = [words[102] for _, words in frames]
    if not all(2000 <= value <= 2400 for value in state_values):
        raise ValueError('ESTACION LAGUNA: firma anómala de 0020 cambió')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read('config.ini')
    history_config = config['oracle_cloud']
    dsn = history_config['dsn']
    with oracledb.connect(user=history_config['user'],
                          password=history_config['password'], dsn=dsn) as history:
        proof = prove_layout(history)

    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                          password=os.environ['ORACLE_CATALOG_PASSWORD'],
                          dsn=dsn) as catalog:
        cursor = catalog.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            '''SELECT E.ID,G.ID,G.RANGOTRANSMISION,G.INTERVALOTRANSMISION,
                      TRIM(G.DECODIFICADOR)
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO=:station AND TRIM(G.IDSATELITAL)=:dcp''' + lock,
            station=STATION, dcp=DCP)
        station_rows = cursor.fetchall()
        if len(station_rows) != 1:
            raise ValueError('ESTACION LAGUNA: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('ESTACION LAGUNA: DATOSGOES cambió')
        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 19 or any(row[4] != 1 for row in sensors):
            raise ValueError('ESTACION LAGUNA: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        for number, period in PERIOD_CHANGES.items():
            if number not in by_number or float(by_number[number][2]) != 60:
                raise ValueError(f'ESTACION LAGUNA: periodo previo cambió en {number}')

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors, 'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            cursor.execute(
                '''UPDATE DATOSGOES SET RANGOTRANSMISION='02:00:00'
                   WHERE ID=:id AND RANGOTRANSMISION='01:00:00' ''', id=goes_id)
            if cursor.rowcount != 1:
                raise ValueError('ESTACION LAGUNA: no se actualizó el rango')
            for number, period in PERIOD_CHANGES.items():
                cursor.execute(
                    '''UPDATE SENSOR SET PERIODOMUESTRA=:period
                       WHERE ID=:id AND TRIM(NUMEROSENSOR)=:sensor_number
                         AND PERIODOMUESTRA=60''',
                    period=period, id=by_number[number][0], sensor_number=number)
                if cursor.rowcount != 1:
                    raise ValueError(f'ESTACION LAGUNA: no se actualizó {number}')
            catalog.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
