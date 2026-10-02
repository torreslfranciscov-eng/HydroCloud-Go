"""Reconcile HUIMANGUILLO (INIFAP) with its verified 110-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'HUIMA27XXX'
DCP = '15F355C8'
LAYOUT = (
    ('0001', 0, 12, 10), ('0002', 12, 12, 10),
    ('0003', 24, 12, 10), ('0006', 36, 12, 10),
    ('0007', 48, 12, 10), ('0008', 60, 12, 10),
    ('0009', 72, 12, 10), ('0012', 84, 12, 10),
    ('0013', 96, 12, 10), ('0016', 108, 2, 60),
)
ABSENT_SENSORS = ('0014', '0015')


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
            raise ValueError(f'HUIMANGUILLO: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('HUIMANGUILLO: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 110, 'segments': {}}
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
            raise ValueError(f'HUIMANGUILLO: solapamiento inválido en {sensor}')
        proof['segments'][sensor] = {
            'start': start, 'count': count, 'period': period,
            'overlap_checks': checks, 'overlap_failures': failures,
            'minimum_raw': min(values), 'maximum_raw': max(values),
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
            raise ValueError('HUIMANGUILLO: estación o DCP ambiguo')
        station_id, _, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '02:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('HUIMANGUILLO: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,PUNTODECIMAL
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 13 or any(row[4] != 1 for row in sensors):
            raise ValueError('HUIMANGUILLO: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != {
                '0001', '0002', '0003', '0006', '0007', '0008', '0009',
                '0011', '0012', '0013', '0014', '0015', '0016'}:
            raise ValueError('HUIMANGUILLO: sensores inesperados')
        if int(by_number['0013'][6]) != 0:
            raise ValueError('HUIMANGUILLO: decimales previos de 0013 cambiaron')

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
                '''UPDATE SENSOR SET PUNTODECIMAL=1
                   WHERE ID=:id AND PUNTODECIMAL=0''',
                id=by_number['0013'][0])
            if cursor.rowcount != 1:
                raise ValueError('HUIMANGUILLO: no se ajustó 0013')
            for number in ABSENT_SENSORS:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'HUIMANGUILLO: no se desactivó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
