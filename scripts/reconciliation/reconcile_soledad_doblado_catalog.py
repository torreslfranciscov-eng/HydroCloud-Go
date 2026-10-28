"""Reconcile SOLEDAD DE DOBLADO (HC1) with its verified 100-word layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'SOLEVER007'
DCP = '1A5066A6'
LAYOUT = (
    ('0001', 0, 12), ('0003', 12, 12), ('0004', 24, 12),
    ('0005', 36, 12), ('0006', 48, 12), ('0007', 60, 12),
    ('0022', 72, 12), ('0023', 84, 12), ('0019', 96, 2),
    ('0021', 98, 2),
)
CURRENT_SENSORS = {
    '0001', '0003', '0004', '0005', '0006', '0007', '0014', '0015',
    '0016', '0017', '0019',
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
        if len(words) != 100:
            raise ValueError(f'SOLEDAD HC1: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('SOLEDAD HC1: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 100, 'segments': {}}
    for sensor, start, count in LAYOUT:
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        proof['segments'][sensor] = {
            'start': start, 'count': count,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }
    bounds = {
        '0001': (6000, 6500), '0003': (0, 100), '0004': (5000, 6500),
        '0022': (0, 500), '0023': (0, 10), '0019': (1200, 1500),
        '0021': (1500, 5000),
    }
    for sensor, (low, high) in bounds.items():
        segment = proof['segments'][sensor]
        if segment['minimum_raw'] < low or segment['maximum_raw'] > high:
            raise ValueError(f'SOLEDAD HC1: firma fuera de rango en {sensor}')
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
            raise ValueError('SOLEDAD HC1: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('SOLEDAD HC1: DATOSGOES cambió')

        cursor.execute(
            '''SELECT S.ID,TRIM(S.NUMEROSENSOR),S.IDTIPOSENSOR,
                      S.IDUNIDADMEDIDA,S.PUNTODECIMAL,S.PERIODOMUESTRA,
                      S.VALORMINIMO,S.VALORMAXIMO,S.ORDEN,S.ACTIVO,S.VISIBLE
               FROM SENSOR S WHERE S.IDESTACION=:station
               ORDER BY S.ORDEN''' + lock, station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 11 or any(row[9] != 1 for row in sensors):
            raise ValueError('SOLEDAD HC1: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != CURRENT_SENSORS:
            raise ValueError('SOLEDAD HC1: sensores inesperados')
        for number in ('0014', '0015'):
            if float(by_number[number][5]) != 60:
                raise ValueError(f'SOLEDAD HC1: periodo previo cambió en {number}')

        cursor.execute(
            '''SELECT T.ID,U.ID FROM TIPOSENSOR T
               JOIN UNIDADMEDIDA U ON TRIM(U.ABREVIATURA)='°C'
               WHERE UPPER(TRIM(T.NOMBRE))='TEMPERATURA INTERNA' ''')
        internal_type = cursor.fetchall()
        if len(internal_type) != 1:
            raise ValueError('SOLEDAD HC1: tipo Temperatura Interna ambiguo')

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
                raise ValueError('SOLEDAD HC1: no se actualizó el rango')
            for number, new_number in (('0014', '0022'), ('0015', '0023')):
                cursor.execute(
                    '''UPDATE SENSOR SET NUMEROSENSOR=:new_number,
                              PERIODOMUESTRA=10
                       WHERE ID=:id AND PERIODOMUESTRA=60''',
                    new_number=new_number, id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'SOLEDAD HC1: no se actualizó {number}')
            cursor.execute(
                '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                   WHERE ID=:id AND ACTIVO=1''', id=by_number['0016'][0])
            if cursor.rowcount != 1:
                raise ValueError('SOLEDAD HC1: no se desactivó 0016')
            cursor.execute(
                '''UPDATE SENSOR SET NUMEROSENSOR='0021',
                      IDTIPOSENSOR=:type_id,IDUNIDADMEDIDA=:unit_id,
                      PUNTODECIMAL=1,PERIODOMUESTRA=60,
                      VALORMINIMO=-10,VALORMAXIMO=80,ORDEN=10
                   WHERE ID=:id AND TRIM(NUMEROSENSOR)='0017' ''',
                type_id=internal_type[0][0], unit_id=internal_type[0][1],
                id=by_number['0017'][0])
            if cursor.rowcount != 1:
                raise ValueError('SOLEDAD HC1: no se convirtió 0017 en 0021')
            cursor.execute(
                '''UPDATE SENSOR SET ORDEN=9
                   WHERE ID=:id''', id=by_number['0019'][0])
            if cursor.rowcount != 1:
                raise ValueError('SOLEDAD HC1: no se reordenó 0019')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof},
                     ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
