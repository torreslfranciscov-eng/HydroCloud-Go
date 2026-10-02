"""Reconcile LACANTUN (SGT) with its verified 148-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'LACAN07337'
DCP = '15F2D126'
FINAL_ORDER = {
    '0001': 1, '0002': 2, '0003': 3, '0006': 4, '0007': 5,
    '0010': 6, '0011': 7, '0012': 8, '0013': 9, '0019': 10,
    '0016': 11, '0020': 12, '0014': 13, '0021': 14,
}
UNDEFINED_SENSOR = '0014'
ABSENT_SENSOR = '0015'


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
        if len(words) != 148:
            raise ValueError(f'LACANTUN: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('LACANTUN: evidencia insuficiente')

    segments = (
        ('0001', 0, 12), ('0002', 12, 12), ('0003', 24, 12),
        ('0006', 36, 12), ('0007', 48, 12), ('0010', 60, 12),
        ('0011', 72, 12), ('0012', 84, 12), ('0013', 96, 12),
        ('0019', 108, 12), ('0016', 120, 2), ('0020', 122, 12),
        ('undefined', 134, 12), ('0021', 146, 2),
    )
    proof = {'frames': len(frames), 'words': 148, 'segments': {}}
    for sensor, start, count in segments:
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        proof['segments'][sensor] = {
            'start': start, 'count': count,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }

    level = proof['segments']['0019']
    if not (14000 <= level['minimum_raw'] <= level['maximum_raw'] <= 16000):
        raise ValueError('LACANTUN: firma de nivel cambió')
    battery = proof['segments']['0016']
    if not (1200 <= battery['minimum_raw'] <= battery['maximum_raw'] <= 1500):
        raise ValueError('LACANTUN: firma de batería cambió')
    cbs = proof['segments']['0020']
    if cbs['minimum_raw'] != -131072 or cbs['maximum_raw'] != -131072:
        raise ValueError('LACANTUN: firma de CBS cambió')
    undefined = proof['segments']['undefined']
    if undefined['minimum_raw'] != -99999 or undefined['maximum_raw'] != -99999:
        raise ValueError('LACANTUN: bloque indefinido cambió')
    internal = proof['segments']['0021']
    if not (1500 <= internal['minimum_raw'] <= internal['maximum_raw'] <= 6000):
        raise ValueError('LACANTUN: temperatura interna fuera de rango')
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
            raise ValueError('LACANTUN: estación o DCP ambiguo')
        station_id, _, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '02:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('LACANTUN: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,IDTIPOSENSOR
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 15 or any(row[4] != 1 for row in sensors):
            raise ValueError('LACANTUN: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != set(FINAL_ORDER) | {ABSENT_SENSOR}:
            raise ValueError('LACANTUN: sensores inesperados')
        cursor.execute(
            '''SELECT ID FROM TIPOSENSOR
               WHERE UPPER(TRIM(NOMBRE))='INDEFINIDO' ''')
        undefined_types = cursor.fetchall()
        if len(undefined_types) != 1:
            raise ValueError('LACANTUN: tipo Indefinido ambiguo')
        undefined_type = undefined_types[0][0]

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'undefined_type': undefined_type, 'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            for number, order in FINAL_ORDER.items():
                cursor.execute(
                    '''UPDATE SENSOR SET ORDEN=:sensor_order
                       WHERE ID=:id AND ACTIVO=1''',
                    sensor_order=order, id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'LACANTUN: no se reordenó {number}')
            cursor.execute(
                '''UPDATE SENSOR SET IDTIPOSENSOR=:sensor_type,
                          PERIODOMUESTRA=10,VISIBLE=0
                   WHERE ID=:id AND ACTIVO=1 AND PERIODOMUESTRA=60''',
                sensor_type=undefined_type, id=by_number[UNDEFINED_SENSOR][0])
            if cursor.rowcount != 1:
                raise ValueError('LACANTUN: no se normalizó el bloque indefinido')
            cursor.execute(
                '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                   WHERE ID=:id AND ACTIVO=1''', id=by_number[ABSENT_SENSOR][0])
            if cursor.rowcount != 1:
                raise ValueError('LACANTUN: no se desactivó 0015')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
