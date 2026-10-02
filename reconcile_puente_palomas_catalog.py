"""Reconcile PUENTE PALOMAS (H1) with its verified 64-word GS300 layout."""
import argparse
import configparser
import json
import os
import uuid

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'LOMAPUE004'
DCP = '1A5036DA'
TEMPERATURE_SENSOR = '0020'
FINAL_ORDER = {
    '0001': 1, '0003': 2, '0004': 3, '0014': 4,
    '0016': 5, '0019': 6,
}
ABSENT_SENSORS = ('0015', '0017')
COLUMNS = (
    'IDTIPOSENSOR,VISIBLE,ACTIVO,VALORMINIMO,VALORMAXIMO,ESPECIFICACION,'
    'PERIODOMUESTRA,TIPOGRAFICA,IDUNIDADMEDIDA,VALORMAXERROR,VALORMINERROR,'
    'MODOALMACENAMIENTO,ORDEN,PUNTODECIMAL,FECHAREGISTRO,USUARIOREGISTRO,'
    'FECHAMODIFICACION,USUARIOMODIFICACION,APLICACOTA,FUNCIONA,VALIDO'
).split(',')


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
        if len(words) != 64:
            raise ValueError(f'PUENTE PALOMAS: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('PUENTE PALOMAS: evidencia insuficiente')

    segments = (
        ('0001', 0, 12), ('0003', 12, 12), ('0004', 24, 12),
        ('0014', 36, 12), ('0016', 48, 12), ('0019', 60, 2),
        (TEMPERATURE_SENSOR, 62, 2),
    )
    proof = {'frames': len(frames), 'words': 64, 'segments': {}}
    for sensor, start, count in segments:
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        proof['segments'][sensor] = {
            'start': start, 'count': count,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }
    bounds = {
        '0001': (15000, 17000), '0003': (0, 100),
        '0004': (2000, 3000), '0014': (100, 250),
        '0016': (0, 0), '0019': (1200, 1500),
        TEMPERATURE_SENSOR: (1500, 5000),
    }
    for sensor, (low, high) in bounds.items():
        segment = proof['segments'][sensor]
        if segment['minimum_raw'] < low or segment['maximum_raw'] > high:
            raise ValueError(f'PUENTE PALOMAS: firma fuera de rango en {sensor}')
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
    new_id = str(uuid.uuid4()).upper()

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
            raise ValueError('PUENTE PALOMAS: estación o DCP ambiguo')
        station_id, _, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '02:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('PUENTE PALOMAS: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,PUNTODECIMAL
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 8 or any(row[4] != 1 for row in sensors):
            raise ValueError('PUENTE PALOMAS: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != set(FINAL_ORDER) | set(ABSENT_SENSORS):
            raise ValueError('PUENTE PALOMAS: sensores inesperados')
        cursor.execute(
            '''SELECT COUNT(*) FROM SENSOR
               WHERE IDESTACION=:station AND TRIM(NUMEROSENSOR)=:sensor_number''',
            station=station_id, sensor_number=TEMPERATURE_SENSOR)
        if cursor.fetchone()[0] != 0:
            raise ValueError('PUENTE PALOMAS: ya existe 0020')

        cursor.execute(
            'SELECT ' + ','.join('S.' + column for column in COLUMNS) +
            ''' FROM SENSOR S JOIN ESTACION E ON E.ID=S.IDESTACION
                JOIN TIPOSENSOR T ON T.ID=S.IDTIPOSENSOR
                WHERE E.IDASIGNADO='LACAN07337'
                  AND TRIM(S.NUMEROSENSOR)='0021'
                  AND TRIM(T.NOMBRE)='Temperatura Interna' ''')
        source_rows = cursor.fetchall()
        if len(source_rows) != 1:
            raise ValueError('PUENTE PALOMAS: plantilla de temperatura ambigua')
        source = dict(zip(COLUMNS, source_rows[0]))
        source['ORDEN'] = 7

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'new_id': new_id, 'datos_goes': station_rows[0],
                  'sensors': sensors, 'temperature_template': source,
                  'proof': proof}
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
                    raise ValueError(f'PUENTE PALOMAS: no se reordenó {number}')
            cursor.execute(
                '''UPDATE SENSOR SET PERIODOMUESTRA=10
                   WHERE ID=:id AND ACTIVO=1 AND PERIODOMUESTRA=60''',
                id=by_number['0014'][0])
            if cursor.rowcount != 1:
                raise ValueError('PUENTE PALOMAS: no se ajustó 0014')
            for number in ABSENT_SENSORS:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'PUENTE PALOMAS: no se desactivó {number}')

            values = [source[column] for column in COLUMNS]
            names = ['ID', 'NUMEROSENSOR', 'IDESTACION'] + COLUMNS
            binds = ['sensor_pk', 'sensor_number', 'station_pk'] + [
                f'v{i}' for i in range(len(COLUMNS))]
            cursor.execute(
                'INSERT INTO SENSOR (' + ','.join(names) + ') VALUES (' +
                ','.join(':' + bind for bind in binds) + ')',
                dict(zip(binds, [new_id, TEMPERATURE_SENSOR, station_id] + values)))
            if cursor.rowcount != 1:
                raise ValueError('PUENTE PALOMAS: no se insertó 0020')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION, 'dcp': DCP,
                      'new_sensor': TEMPERATURE_SENSOR, 'new_id': new_id,
                      'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
