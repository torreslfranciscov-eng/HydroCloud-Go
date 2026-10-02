"""Reconcile GONZALEZ TAM with its verified 86-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words

STATION = 'GONZTAM001'
DCP = '15F3A54C'
LAYOUT = (
    ('0001', 0, 2, 60), ('0002', 2, 2, 60),
    ('0003', 4, 2, 60), ('0004', 6, 2, 60),
    ('0005', 8, 2, 60), ('0006', 10, 12, 10),
    ('0007', 22, 12, 10), ('0008', 34, 12, 10),
    ('0009', 46, 12, 10), ('0010', 58, 12, 10),
    ('0011', 70, 12, 10), ('0014', 82, 2, 60),
)


def prove(connection):
    cursor = connection.cursor()
    cursor.execute(
        '''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE FROM DCP_HEADERS
           WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(7,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
           ORDER BY TIMESTAMP_MSG''', dcp=DCP)
    frames = []
    for stamp, raw in cursor:
        words = gs300_payload_words(raw[37:].encode('latin1'), station=STATION)
        if len(words) != 86:
            raise ValueError(f'GONZALEZ TAM: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('GONZALEZ TAM: evidencia insuficiente')
    result = {'frames': len(frames), 'words': 86, 'segments': {}}
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
            raise ValueError(f'GONZALEZ TAM: solapamiento inválido en {sensor}')
        result['segments'][sensor] = {
            'start': start, 'count': count, 'period': period,
            'overlap_checks': checks, 'minimum_raw': min(values),
            'maximum_raw': max(values),
        }
    auxiliary = [value for _, words in frames for value in words[84:86]]
    if not all(1500 <= value <= 6000 for value in auxiliary):
        raise ValueError('GONZALEZ TAM: temperatura auxiliar fuera de rango')
    result['auxiliary_words'] = 2
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read('config.ini')
    source = config['oracle_cloud']
    dsn = source['dsn']
    with oracledb.connect(user=source['user'], password=source['password'],
                          dsn=dsn) as history:
        proof = prove(history)
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
        rows = cursor.fetchall()
        if len(rows) != 1 or str(rows[0][2]) != '01:00:00' or rows[0][4] != 'GS300':
            raise ValueError('GONZALEZ TAM: DATOSGOES cambió')
        station_id, goes_id = rows[0][0], rows[0][1]
        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 14 or any(row[4] != 1 for row in sensors):
            raise ValueError('GONZALEZ TAM: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': rows[0], 'sensors': sensors, 'proof': proof}
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
                raise ValueError('GONZALEZ TAM: no se actualizó el rango')
            for number in ('0006', '0007', '0008', '0009'):
                cursor.execute(
                    '''UPDATE SENSOR SET PERIODOMUESTRA=10
                       WHERE ID=:id AND PERIODOMUESTRA=60''',
                    id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'GONZALEZ TAM: no se actualizó {number}')
            for number in ('0012', '0013'):
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'GONZALEZ TAM: no se desactivó {number}')
            catalog.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
