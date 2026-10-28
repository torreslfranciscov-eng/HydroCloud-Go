"""Reconcile ZAPALUTA with its verified 86-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'ZAPAL07099'
DCP = '15F262A8'
TEN_MINUTE = ('0001', '0002', '0003', '0006', '0007', '0008')
HOURLY = ('0009', '0011', '0012', '0013', '0014', '0015', '0016')


def prove_layout(connection):
    cursor = connection.cursor()
    cursor.execute(
        '''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
           FROM DCP_HEADERS WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(7,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
             AND INSTR(RAW_MESSAGE,'Wrong channel -- expect')=0
           ORDER BY TIMESTAMP_MSG''', dcp=DCP)
    frames = []
    for stamp, raw in cursor:
        words = gs300_payload_words(raw[37:].encode('latin1'), station=STATION)
        if len(words) != 86:
            raise ValueError(f'ZAPALUTA: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('ZAPALUTA: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 86, 'segments': {}}
    layout = []
    position = 0
    for sensor in TEN_MINUTE:
        layout.append((sensor, position, 12, 10))
        position += 12
    for sensor in HOURLY:
        layout.append((sensor, position, 2, 60))
        position += 2
    if position != 86:
        raise AssertionError('ZAPALUTA: layout interno inválido')

    for sensor, start, count, period in layout:
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
            raise ValueError(f'ZAPALUTA: solapamiento inválido en {sensor}')
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
    source = config['oracle_cloud']
    dsn = source['dsn']

    with oracledb.connect(user=source['user'], password=source['password'],
                          dsn=dsn) as history:
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
            raise ValueError('ZAPALUTA: estación o DCP ambiguo')
        station_id, _, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '02:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('ZAPALUTA: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 13 or any(row[4] != 1 for row in sensors):
            raise ValueError('ZAPALUTA: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != set(TEN_MINUTE) | set(HOURLY):
            raise ValueError('ZAPALUTA: sensores inesperados')
        for number in TEN_MINUTE + ('0009', '0011', '0012', '0013'):
            if float(by_number[number][2]) != 10:
                raise ValueError(f'ZAPALUTA: periodo previo cambió en {number}')
        for number in ('0014', '0015', '0016'):
            if float(by_number[number][2]) != 60:
                raise ValueError(f'ZAPALUTA: periodo previo cambió en {number}')

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            for number in ('0009', '0011', '0012', '0013'):
                cursor.execute(
                    '''UPDATE SENSOR SET PERIODOMUESTRA=60
                       WHERE ID=:id AND PERIODOMUESTRA=10 AND ACTIVO=1''',
                    id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'ZAPALUTA: no se actualizó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
