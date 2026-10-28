"""Reconcile MOTOZINTLA with its verified 110-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'MOTOZ07119'
DCP = '15F2815A'
LAYOUT = (
    ('0001', 0, 12), ('0002', 12, 12), ('0003', 24, 12),
    ('0006', 36, 12), ('0007', 48, 12), ('0008', 60, 12),
    ('0009', 72, 12), ('0012', 84, 12), ('0013', 96, 12),
    ('0016', 108, 2),
)
ABSENT_SENSORS = ('0004', '0005', '0011', '0014', '0015')


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
        if len(words) != 110:
            raise ValueError(f'MOTOZINTLA: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('MOTOZINTLA: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 110, 'segments': {}}
    for sensor, start, count in LAYOUT:
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        proof['segments'][sensor] = {
            'start': start, 'count': count,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }

    bounds = {
        '0001': (100, 500), '0002': (0, 110), '0003': (100, 450),
        '0006': (0, 500), '0007': (0, 360), '0008': (0, 1000),
        '0009': (0, 360), '0012': (0, 300), '0013': (0, 1500),
        '0016': (1200, 1500),
    }
    for sensor, (low, high) in bounds.items():
        segment = proof['segments'][sensor]
        if segment['minimum_raw'] < low or segment['maximum_raw'] > high:
            raise ValueError(f'MOTOZINTLA: firma fuera de rango en {sensor}')
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
            raise ValueError('MOTOZINTLA: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('MOTOZINTLA: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,PUNTODECIMAL
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 15 or any(row[4] != 1 for row in sensors):
            raise ValueError('MOTOZINTLA: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != {
                '0001', '0002', '0003', '0004', '0005', '0006', '0007',
                '0008', '0009', '0011', '0012', '0013', '0014', '0015',
                '0016'}:
            raise ValueError('MOTOZINTLA: sensores inesperados')
        if int(by_number['0013'][6]) != 0:
            raise ValueError('MOTOZINTLA: radiación no conserva escala entera')

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'proof': proof}
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
                raise ValueError('MOTOZINTLA: no se actualizó el rango')
            for number in ABSENT_SENSORS:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'MOTOZINTLA: no se desactivó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
