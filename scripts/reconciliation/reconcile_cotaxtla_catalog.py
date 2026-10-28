"""Reconcile COTAXTLA (H1) with its verified 54-word GS300 layout.

The command is a dry run unless --apply is supplied.  It always writes an
exclusive backup before changing Oracle.
"""
import argparse
import configparser
import datetime as dt
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'COTAVER010'
DCP = '1A509622'
LAYOUT = (
    ('0001', 0, 12, 10),
    ('0003', 12, 12, 10),
    ('0009', 24, 12, 10),
    ('0020', 36, 12, 10),
    ('0018', 48, 2, 60),
    ('0019', 50, 2, 60),
)


def load_frames(connection):
    cursor = connection.cursor()
    cursor.execute(
        '''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
           FROM DCP_HEADERS
           WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(3,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
           ORDER BY TIMESTAMP_MSG''', dcp=DCP)
    frames = []
    for stamp, raw in cursor:
        words = gs300_payload_words(raw[37:].encode('latin1'), station=STATION)
        if len(words) != 54:
            raise ValueError(f'COTAXTLA: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('COTAXTLA: evidencia insuficiente')
    return frames


def prove_layout(frames):
    proof = {'frames': len(frames), 'words': 54, 'segments': {}}
    for sensor, start, count, period in LAYOUT:
        checks = failures = 0
        values = []
        for _, words in frames:
            values.extend(words[start:start + count])
        for (old_stamp, old), (new_stamp, new) in zip(frames, frames[1:]):
            shift = round((new_stamp - old_stamp).total_seconds() / 60 / period)
            if 0 < shift < count:
                left = old[start:start + count - shift]
                right = new[start + shift:start + count]
                checks += len(left)
                failures += sum(a != b for a, b in zip(left, right))
        if failures or not checks:
            raise ValueError(f'COTAXTLA: solapamiento inválido en {sensor}')
        proof['segments'][sensor] = {
            'start': start, 'count': count, 'period': period,
            'overlap_checks': checks, 'minimum_raw': min(values),
            'maximum_raw': max(values),
        }
    for _, words in frames:
        if not all(700 <= value <= 1800 for value in words[48:52]):
            raise ValueError('COTAXTLA: voltaje fuera de rango físico')
        if not all(1500 <= value <= 6000 for value in words[52:54]):
            raise ValueError('COTAXTLA: sufijo térmico fuera de rango')
    proof['auxiliary_words'] = 2
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
            raise ValueError('COTAXTLA: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('COTAXTLA: DATOSGOES cambió')

        cursor.execute(
            '''SELECT S.ID,TRIM(S.NUMEROSENSOR),S.IDTIPOSENSOR,S.IDUNIDADMEDIDA,
                      S.PUNTODECIMAL,S.PERIODOMUESTRA,S.VALORMINIMO,
                      S.VALORMAXIMO,S.ORDEN,S.ACTIVO,S.VISIBLE
               FROM SENSOR S WHERE S.IDESTACION=:station
               ORDER BY S.ORDEN''' + lock, station=station_id)
        sensors = cursor.fetchall()
        numbers = [row[1] for row in sensors]
        if numbers != ['0001', '0003', '0004', '0015', '0016', '0017', '0018', '0019']:
            raise ValueError('COTAXTLA: catálogo de sensores cambió')

        cursor.execute(
            '''SELECT ID FROM TIPOSENSOR
               WHERE UPPER(TRIM(NOMBRE))=UPPER(:name)''',
            name='Precipitación acumulada')
        type_rows = cursor.fetchall()
        if len(type_rows) != 1:
            raise ValueError('COTAXTLA: tipo Precipitación acumulada ambiguo')
        accumulated_type = type_rows[0][0]
        cursor.execute(
            '''SELECT ID FROM UNIDADMEDIDA
               WHERE LOWER(TRIM(ABREVIATURA))=:unit''', unit='mm')
        unit_rows = cursor.fetchall()
        if len(unit_rows) != 1:
            raise ValueError('COTAXTLA: unidad mm ambigua')
        millimeters = unit_rows[0][0]

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
                raise ValueError('COTAXTLA: no se actualizó el rango')

            by_number = {row[1]: row for row in sensors}
            cursor.execute(
                '''UPDATE SENSOR SET NUMEROSENSOR='0009',IDTIPOSENSOR=:type_id,
                      IDUNIDADMEDIDA=:unit_id,PUNTODECIMAL=1,PERIODOMUESTRA=10,
                      VALORMINIMO=0,VALORMAXIMO=10000,ORDEN=3
                   WHERE ID=:id AND TRIM(NUMEROSENSOR)='0004' ''',
                type_id=accumulated_type, unit_id=millimeters,
                id=by_number['0004'][0])
            if cursor.rowcount != 1:
                raise ValueError('COTAXTLA: no se convirtió 0004 en 0009')
            cursor.execute(
                '''UPDATE SENSOR SET NUMEROSENSOR='0020',PERIODOMUESTRA=10,ORDEN=4
                   WHERE ID=:id AND TRIM(NUMEROSENSOR)='0015' ''',
                id=by_number['0015'][0])
            if cursor.rowcount != 1:
                raise ValueError('COTAXTLA: no se convirtió 0015 en 0020')
            # Keep these as single-row statements.  Oracle may parallelize an
            # IN-list update on SENSOR and its audit trigger can then contend
            # with a sibling worker for the same station row.
            for number in ('0016', '0017'):
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND TRIM(NUMEROSENSOR)=:sensor_number
                         AND ACTIVO=1''',
                    id=by_number[number][0], sensor_number=number)
                if cursor.rowcount != 1:
                    raise ValueError(f'COTAXTLA: no se desactivó {number}')
            for number, order in (('0018', 5), ('0019', 6)):
                cursor.execute(
                    '''UPDATE SENSOR SET ORDEN=:new_order
                       WHERE ID=:id AND TRIM(NUMEROSENSOR)=:sensor_number''',
                    new_order=order, id=by_number[number][0],
                    sensor_number=number)
                if cursor.rowcount != 1:
                    raise ValueError(f'COTAXTLA: no se reordenó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
