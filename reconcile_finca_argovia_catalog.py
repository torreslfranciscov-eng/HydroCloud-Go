"""Reconcile FINCA ARGOVIA with its verified 110-word GS300 layout.

Dry-run by default.  An exclusive JSON backup is written before any optional
Oracle changes are committed.
"""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'FARGO07012'
DCP = '15F1B3CE'
ABSENT = ('0004', '0005', '0011', '0014', '0015')
LAYOUT = (
    ('0001', 0, 1, -15, 55),
    ('0002', 12, 0, 0, 101),
    ('0003', 24, 1, -20, 50),
    ('0006', 36, 1, 0, 252),
    ('0007', 48, 0, 0, 360),
    ('0008', 60, 1, 0, 252),
    ('0009', 72, 0, 0, 360),
    ('0012', 84, 1, 0, 30),
    ('0013', 96, 0, -1, 1100),
)


def load_frames(connection):
    cursor = connection.cursor()
    cursor.execute(
        '''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
           FROM DCP_HEADERS
           WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(7,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
           ORDER BY TIMESTAMP_MSG''', dcp=DCP)
    frames = []
    for stamp, raw in cursor:
        words = gs300_payload_words(raw[37:].encode('latin1'), station=STATION)
        if len(words) != 110:
            raise ValueError(f'FINCA ARGOVIA: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('FINCA ARGOVIA: evidencia insuficiente')
    return frames


def prove_layout(frames):
    proof = {'frames': len(frames), 'words': 110, 'segments': {}}
    for sensor, start, decimals, low, high in LAYOUT:
        checks = failures = range_failures = 0
        values = []
        for _, words in frames:
            block = words[start:start + 12]
            values.extend(block)
            range_failures += sum(
                not low <= value / (10 ** decimals) <= high
                for value in block)
        for (old_stamp, old), (new_stamp, new) in zip(frames, frames[1:]):
            shift = round((new_stamp - old_stamp).total_seconds() / 600)
            if 0 < shift < 12:
                left = old[start:start + 12 - shift]
                right = new[start + shift:start + 12]
                checks += len(left)
                failures += sum(a != b for a, b in zip(left, right))
        if failures or not checks:
            raise ValueError(f'FINCA ARGOVIA: solapamiento inválido en {sensor}')
        if sensor != '0013' and range_failures:
            raise ValueError(f'FINCA ARGOVIA: rango físico incompatible en {sensor}')
        if sensor == '0013' and not all(35000 <= value <= 37000 for value in values):
            raise ValueError('FINCA ARGOVIA: firma anómala de radiación cambió')
        proof['segments'][sensor] = {
            'start': start, 'count': 12, 'period': 10,
            'overlap_checks': checks, 'range_failures': range_failures,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }
    battery = [value for _, words in frames for value in words[108:110]]
    if not all(700 <= value <= 1800 for value in battery):
        raise ValueError('FINCA ARGOVIA: voltaje fuera de rango físico')
    proof['segments']['0016'] = {
        'start': 108, 'count': 2, 'period': 60,
        'minimum_raw': min(battery), 'maximum_raw': max(battery),
    }
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
        proof = prove_layout(load_frames(history))

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
            raise ValueError('FINCA ARGOVIA: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('FINCA ARGOVIA: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        expected = [f'{number:04d}' for number in
                    (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16)]
        if [row[1] for row in sensors] != expected or any(row[4] != 1 for row in sensors):
            raise ValueError('FINCA ARGOVIA: catálogo de sensores cambió')
        by_number = {row[1]: row for row in sensors}

        backup = {
            'applied': args.apply, 'station': STATION, 'dcp': DCP,
            'datos_goes': station_rows[0], 'sensors': sensors, 'proof': proof,
        }
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
                raise ValueError('FINCA ARGOVIA: no se actualizó el rango')
            for number in ABSENT:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND TRIM(NUMEROSENSOR)=:sensor_number
                         AND ACTIVO=1''',
                    id=by_number[number][0], sensor_number=number)
                if cursor.rowcount != 1:
                    raise ValueError(f'FINCA ARGOVIA: no se desactivó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
