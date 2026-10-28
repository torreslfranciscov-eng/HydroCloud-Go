"""Reconcile JAMAPA (HC) with its verified 80-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'JAMAVER008'
DCP = '1A5075D0'
PHYSICAL_ORDER = {
    '0001': 1, '0003': 2, '0008': 3, '0005': 4, '0006': 5,
    '0007': 6, '0010': 7, '0011': 8, '0012': 9, '0013': 10,
    '0004': 11,
}
TEN_MINUTE_DIAGNOSTICS = ('0014', '0015')
ABSENT_SENSORS = ('0016', '0017')


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
        if len(words) != 80:
            raise ValueError(f'JAMAPA: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('JAMAPA: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 80, 'blocks': {}}
    for block in range(13):
        values = [value for _, words in frames
                  for value in words[block * 6:(block + 1) * 6]]
        proof['blocks'][str(block + 1)] = {
            'start': block * 6, 'count': 6,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }

    pressure = proof['blocks']['3']
    if not (9000 <= pressure['minimum_raw'] <= pressure['maximum_raw'] <= 11000):
        raise ValueError('JAMAPA: firma de presión cambió')
    expected_missing = {
        '7': -131072, '8': -131072, '9': -99999,
        '10': -131072, '11': -99999,
    }
    for block, expected in expected_missing.items():
        observed = proof['blocks'][block]
        if observed['minimum_raw'] != expected or observed['maximum_raw'] != expected:
            raise ValueError(f'JAMAPA: firma de ausencia cambió en bloque {block}')

    battery = [words[78] for _, words in frames]
    logger_temperature = [words[79] for _, words in frames]
    if not all(1200 <= value <= 1500 for value in battery):
        raise ValueError('JAMAPA: firma de batería cambió')
    if not all(1500 <= value <= 6000 for value in logger_temperature):
        raise ValueError('JAMAPA: temperatura auxiliar fuera de rango')
    proof['battery'] = {'start': 78, 'minimum_raw': min(battery),
                        'maximum_raw': max(battery)}
    proof['logger_temperature'] = {
        'start': 79, 'minimum_raw': min(logger_temperature),
        'maximum_raw': max(logger_temperature),
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
            raise ValueError('JAMAPA: estación o DCP ambiguo')
        station_id, _, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('JAMAPA: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,IDTIPOSENSOR
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 16 or any(row[4] != 1 for row in sensors):
            raise ValueError('JAMAPA: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        expected_numbers = set(PHYSICAL_ORDER) | set(TEN_MINUTE_DIAGNOSTICS) | \
            set(ABSENT_SENSORS) | {'0019'}
        if set(by_number) != expected_numbers:
            raise ValueError('JAMAPA: sensores inesperados')

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            for number, order in PHYSICAL_ORDER.items():
                cursor.execute(
                    '''UPDATE SENSOR SET ORDEN=:sensor_order
                       WHERE ID=:id AND ACTIVO=1''',
                    sensor_order=order, id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'JAMAPA: no se reordenó {number}')
            for order, number in enumerate(TEN_MINUTE_DIAGNOSTICS, start=12):
                cursor.execute(
                    '''UPDATE SENSOR SET PERIODOMUESTRA=10,
                              ORDEN=:sensor_order,VISIBLE=1
                       WHERE ID=:id AND ACTIVO=1 AND PERIODOMUESTRA=60''',
                    sensor_order=order, id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'JAMAPA: no se normalizó {number}')
            for number in ABSENT_SENSORS:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'JAMAPA: no se desactivó {number}')
            cursor.execute(
                '''UPDATE SENSOR SET ORDEN=14
                   WHERE ID=:id AND ACTIVO=1''', id=by_number['0019'][0])
            if cursor.rowcount != 1:
                raise ValueError('JAMAPA: no se reordenó 0019')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
