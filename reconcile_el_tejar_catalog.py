"""Reconcile EL TEJAR (HC1) with its verified 78-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'TEJAVER009'
DCP = '1A508554'
LAYOUT = (
    ('0001', 0, 12, 10), ('0003', 12, 12, 10),
    ('0006', 24, 12, 10), ('0005', 36, 12, 10),
    ('0007', 48, 12, 10), ('0020', 60, 12, 10),
    ('0018', 72, 2, 60),
)
CURRENT_SENSORS = {
    '0001', '0003', '0004', '0005', '0006', '0007',
    '0015', '0016', '0017', '0018', '0019',
}
ABSENT_SENSORS = ('0015', '0017', '0019')
ORDER = {
    '0001': 1, '0003': 2, '0009': 3, '0006': 4,
    '0005': 5, '0007': 6, '0020': 7, '0018': 8,
}


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
        if len(words) != 78:
            raise ValueError(f'EL TEJAR: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('EL TEJAR: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 78, 'segments': {}}
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
        if failures or not checks:
            raise ValueError(f'EL TEJAR: solapamiento inválido en {sensor}')
        proof['segments'][sensor] = {
            'start': start, 'count': count, 'period': period,
            'overlap_checks': checks, 'overlap_failures': failures,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }

    suffix_ranges = (
        (1000, 1600), (1000, 1600),
        (1500, 6000), (1500, 6000),
    )
    suffix = [value for _, words in frames for value in words[74:78]]
    for _, words in frames:
        if any(not low <= value <= high
               for value, (low, high) in zip(words[74:78], suffix_ranges)):
            raise ValueError('EL TEJAR: sufijo auxiliar fuera de rango')
    proof['auxiliary_suffix'] = {
        'start': 74, 'count': 4,
        'minimum_raw': min(suffix), 'maximum_raw': max(suffix),
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
            raise ValueError('EL TEJAR: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('EL TEJAR: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,PUNTODECIMAL
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 11 or any(row[4] != 1 for row in sensors):
            raise ValueError('EL TEJAR: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != CURRENT_SENSORS:
            raise ValueError('EL TEJAR: sensores inesperados')

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
                raise ValueError('EL TEJAR: no se actualizó el rango')
            cursor.execute(
                '''UPDATE SENSOR SET NUMEROSENSOR='0009'
                   WHERE ID=:id AND TRIM(NUMEROSENSOR)='0004' ''',
                id=by_number['0004'][0])
            if cursor.rowcount != 1:
                raise ValueError('EL TEJAR: no se convirtió 0004 en 0009')
            cursor.execute(
                '''UPDATE SENSOR SET NUMEROSENSOR='0020',PERIODOMUESTRA=10
                   WHERE ID=:id AND TRIM(NUMEROSENSOR)='0016'
                         AND PERIODOMUESTRA=60''', id=by_number['0016'][0])
            if cursor.rowcount != 1:
                raise ValueError('EL TEJAR: no se convirtió 0016 en 0020')
            cursor.execute(
                '''UPDATE SENSOR SET PUNTODECIMAL=2
                   WHERE ID=:id AND PUNTODECIMAL=0''', id=by_number['0006'][0])
            if cursor.rowcount != 1:
                raise ValueError('EL TEJAR: no se corrigió humedad 0006')
            desired_ids = {
                **{number: by_number[number][0]
                   for number in ('0001', '0003', '0005', '0006', '0007', '0018')},
                '0009': by_number['0004'][0], '0020': by_number['0016'][0],
            }
            for number, order in ORDER.items():
                cursor.execute(
                    '''UPDATE SENSOR SET ORDEN=:sensor_order
                       WHERE ID=:id AND ACTIVO=1''',
                    sensor_order=order, id=desired_ids[number])
                if cursor.rowcount != 1:
                    raise ValueError(f'EL TEJAR: no se reordenó {number}')
            for number in ABSENT_SENSORS:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'EL TEJAR: no se desactivó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
