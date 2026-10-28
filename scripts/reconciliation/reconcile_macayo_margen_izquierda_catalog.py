"""Reconcile MACAYO MARGEN IZQUIERDA with its verified 97-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'MMIZTAB018'
DCP = '1A526352'
LAYOUT = (
    ('0001', 0, 6), ('0011', 6, 6), ('0012', 12, 6),
    ('0013', 18, 6), ('0031', 24, 6), ('0036', 30, 6),
    ('0041', 36, 6), ('0046', 42, 6), ('0047', 48, 6),
    ('0048', 54, 6), ('0049', 60, 6), ('0902', 66, 1),
    ('0903', 67, 6), ('0904', 73, 6), ('0905', 79, 6),
    ('0906', 85, 6), ('0907', 91, 6),
)
ABSENT_SENSORS = ('0909', '0910')


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
        if len(words) != 97:
            raise ValueError(f'MACAYO MI: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('MACAYO MI: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 97, 'segments': {}}
    for sensor, start, count in LAYOUT:
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        proof['segments'][sensor] = {
            'start': start, 'count': count,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }
    battery = proof['segments']['0902']
    if not (1200 <= battery['minimum_raw'] <= battery['maximum_raw'] <= 1500):
        raise ValueError('MACAYO MI: firma de batería cambió')
    state = proof['segments']['0903']
    if state['minimum_raw'] < 0 or state['maximum_raw'] > 10:
        raise ValueError('MACAYO MI: firma de estado RLS cambió')
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
            raise ValueError('MACAYO MI: estación o DCP ambiguo')
        station_id, _, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('MACAYO MI: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,PUNTODECIMAL
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 19 or any(row[4] != 1 for row in sensors):
            raise ValueError('MACAYO MI: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != {sensor for sensor, _, _ in LAYOUT} | set(ABSENT_SENSORS):
            raise ValueError('MACAYO MI: sensores inesperados')

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            for number in ABSENT_SENSORS:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'MACAYO MI: no se desactivó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
