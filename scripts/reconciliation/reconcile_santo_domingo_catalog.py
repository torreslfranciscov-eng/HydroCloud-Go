"""Reconcile SANTO DOMINGO with its verified 36-word GS300 layout."""
import argparse
import configparser
import json
import os
import uuid

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'STODCHIA22'
DCP = '15D3F4DE'
FINAL_ORDER = {'0001': 1, '0900': 2, '0901': 3}
LAYOUT = (('0001', 0, 12), ('0900', 12, 12), ('0901', 24, 12))
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
        if len(words) != 36:
            raise ValueError(f'SANTO DOMINGO: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('SANTO DOMINGO: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 36, 'segments': {}}
    for sensor, start, count in LAYOUT:
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        proof['segments'][sensor] = {
            'start': start, 'count': count,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }
    level = proof['segments']['0001']
    state = proof['segments']['0901']
    battery = proof['segments']['0900']
    if level['minimum_raw'] != -131072 or level['maximum_raw'] != -131072:
        raise ValueError('SANTO DOMINGO: firma de falla de nivel cambió')
    if state['minimum_raw'] != -99999 or state['maximum_raw'] != -99999:
        raise ValueError('SANTO DOMINGO: firma de falla CBS cambió')
    if not (1200 <= battery['minimum_raw'] <= battery['maximum_raw'] <= 1500):
        raise ValueError('SANTO DOMINGO: firma de batería cambió')
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
            raise ValueError('SANTO DOMINGO: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '01:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('SANTO DOMINGO: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,PUNTODECIMAL
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 2 or any(row[4] != 1 for row in sensors):
            raise ValueError('SANTO DOMINGO: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != {'0001', '0900'}:
            raise ValueError('SANTO DOMINGO: sensores inesperados')
        if any(float(row[2]) != 10 for row in sensors):
            raise ValueError('SANTO DOMINGO: periodo inesperado')
        if int(by_number['0900'][6]) != 2:
            # The existing catalog uses one decimal; preserve its deployed
            # scale rather than silently changing historical semantics.
            if int(by_number['0900'][6]) != 1:
                raise ValueError('SANTO DOMINGO: escala de batería cambió')

        cursor.execute(
            'SELECT ' + ','.join('S.' + column for column in COLUMNS) +
            ''' FROM SENSOR S JOIN ESTACION E ON E.ID=S.IDESTACION
                JOIN TIPOSENSOR T ON T.ID=S.IDTIPOSENSOR
                WHERE E.IDASIGNADO='000CUAUTLA'
                  AND UPPER(TRIM(T.NOMBRE))='ESTADO DEL CBS' ''')
        source_rows = cursor.fetchall()
        if len(source_rows) != 1:
            raise ValueError('SANTO DOMINGO: sensor Estado del CBS homólogo ambiguo')
        source = dict(zip(COLUMNS, source_rows[0]))
        source['ORDEN'] = 3
        source['PERIODOMUESTRA'] = 10
        source['VISIBLE'] = 1
        source['ACTIVO'] = 1
        new_id = str(uuid.uuid4()).upper()

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'new_sensor_id': new_id, 'new_sensor_source': source,
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
                raise ValueError('SANTO DOMINGO: no se actualizó el rango')
            for number, order in {'0001': 1, '0900': 2}.items():
                cursor.execute(
                    '''UPDATE SENSOR SET ORDEN=:sensor_order
                       WHERE ID=:id AND ACTIVO=1''',
                    sensor_order=order, id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'SANTO DOMINGO: no se reordenó {number}')
            names = ['ID', 'NUMEROSENSOR', 'IDESTACION'] + COLUMNS
            binds = ['sensor_pk', 'sensor_number', 'station_pk'] + [
                f'v{i}' for i in range(len(COLUMNS))]
            cursor.execute(
                f"INSERT INTO SENSOR ({','.join(names)}) VALUES "
                f"({','.join(':'+bind for bind in binds)})",
                dict(zip(binds, [new_id, '0901', station_id] +
                         [source[column] for column in COLUMNS])))
            if cursor.rowcount != 1:
                raise ValueError('SANTO DOMINGO: no se insertó 0901')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof},
                     ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
