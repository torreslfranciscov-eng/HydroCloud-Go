"""Reconcile SUCHIATE with the five sensors proven by its 50-word wire."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'SUCHIXXXXX'
DCP = '15F390D6'
ACTIVE = {'0001', '0002', '0003', '0019', '0028'}
ABSENT = {
    '0006', '0007', '0011', '0012', '0018', '0020', '0021', '0022',
    '0023', '0024', '0025', '0026', '0027', '0029',
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
        if len(words) != 50:
            raise ValueError(f'SUCHIATE: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('SUCHIATE: evidencia insuficiente')
    segments = {
        '0001': (0, 12, -4000, 8000),
        '0002': (12, 12, 0, 110),
        '0003': (24, 12, -4000, 8000),
        '0019': (36, 12, 0, 10000),
        '0028': (48, 2, 700, 1800),
    }
    proof = {'frames': len(frames), 'words': 50, 'segments': {}}
    for number, (start, count, low, high) in segments.items():
        values = [value for _, words in frames for value in words[start:start + count]
                  if value is not None and value not in (-99999, -131072)]
        if not values or min(values) < low or max(values) > high:
            raise ValueError(f'SUCHIATE: firma fuera de rango en {number}')
        proof['segments'][number] = {
            'start': start, 'count': count,
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
            raise ValueError('SUCHIATE: estación o DCP ambiguo')
        station_id, goes_id, coverage, cadence, decoder = station_rows[0]
        if (str(coverage), str(cadence), decoder) != ('01:00:00', '01:00:00', 'GS300'):
            raise ValueError('SUCHIATE: DATOSGOES cambió')
        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        by_number = {row[1]: row for row in sensors}
        if set(by_number) != ACTIVE | ABSENT or any(row[4] != 1 for row in sensors):
            raise ValueError('SUCHIATE: catálogo cambió')
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
                raise ValueError('SUCHIATE: no se actualizó el rango')
            for number in ABSENT:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'SUCHIATE: no se desactivó {number}')
            for order, number in enumerate(('0001', '0002', '0003', '0019', '0028'), 1):
                period = 60 if number == '0028' else 10
                cursor.execute(
                    '''UPDATE SENSOR SET ORDEN=:ord,PERIODOMUESTRA=:period
                       WHERE ID=:id AND ACTIVO=1''',
                    ord=order, period=period, id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'SUCHIATE: no se ordenó {number}')
            catalog.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
