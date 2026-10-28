"""Reconcile TALISMAN with its verified 98-word GS300 layout."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words


STATION = 'TALIS07000'
DCP = '15F383A0'
LAYOUT = (
    ('0001', 0, 12), ('0002', 12, 12), ('0003', 24, 12),
    ('0006', 36, 12), ('0007', 48, 12), ('0011', 60, 12),
    ('0012', 72, 12), ('0019', 84, 12), ('0025', 96, 2),
)
PERIOD_CHANGES = ('0006', '0007', '0011', '0012')
ABSENT_SENSORS = ('0018', '0020', '0021', '0022', '0023', '0026', '0027', '0030')
CALCULATED_SENSOR = '0024'


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
        if len(words) != 98:
            raise ValueError(f'TALISMAN: trama con {len(words)} palabras')
        frames.append((stamp, words))
    if len(frames) < 24:
        raise ValueError('TALISMAN: evidencia insuficiente')

    proof = {'frames': len(frames), 'words': 98, 'segments': {}}
    for sensor, start, count in LAYOUT:
        values = [value for _, words in frames
                  for value in words[start:start + count]]
        proof['segments'][sensor] = {
            'start': start, 'count': count,
            'minimum_raw': min(values), 'maximum_raw': max(values),
        }
    bounds = {
        '0001': (1500, 4500), '0006': (0, 500), '0007': (0, 360),
        '0011': (0, 40000), '0012': (0, 1000), '0019': (0, 500),
        '0025': (1200, 1500),
    }
    for sensor, (low, high) in bounds.items():
        segment = proof['segments'][sensor]
        if segment['minimum_raw'] < low or segment['maximum_raw'] > high:
            raise ValueError(f'TALISMAN: firma fuera de rango en {sensor}')
    if proof['segments']['0002']['minimum_raw'] != -99999:
        raise ValueError('TALISMAN: firma de falla de humedad cambió')
    if proof['segments']['0003']['minimum_raw'] != -131072:
        raise ValueError('TALISMAN: firma de falla de rocío cambió')
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
            raise ValueError('TALISMAN: estación o DCP ambiguo')
        station_id, _, coverage, cadence, decoder = station_rows[0]
        if str(coverage) != '02:00:00' or str(cadence) != '01:00:00' or decoder != 'GS300':
            raise ValueError('TALISMAN: DATOSGOES cambió')

        cursor.execute(
            '''SELECT S.ID,TRIM(S.NUMEROSENSOR),S.PERIODOMUESTRA,S.ORDEN,
                      S.ACTIVO,S.VISIBLE,S.PUNTODECIMAL,T.ESCALCULADA
               FROM SENSOR S JOIN TIPOSENSOR T ON T.ID=S.IDTIPOSENSOR
               WHERE S.IDESTACION=:station ORDER BY S.ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 18 or any(row[4] != 1 for row in sensors):
            raise ValueError('TALISMAN: catálogo cambió')
        by_number = {row[1]: row for row in sensors}
        expected = ({sensor for sensor, _, _ in LAYOUT} | set(ABSENT_SENSORS) |
                    {CALCULATED_SENSOR})
        if set(by_number) != expected:
            raise ValueError('TALISMAN: sensores inesperados')
        if not bool(by_number[CALCULATED_SENSOR][7]):
            raise ValueError('TALISMAN: gasto dejó de ser calculado')
        for number in PERIOD_CHANGES:
            if float(by_number[number][2]) != 60:
                raise ValueError(f'TALISMAN: periodo previo cambió en {number}')

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            for number in PERIOD_CHANGES:
                cursor.execute(
                    '''UPDATE SENSOR SET PERIODOMUESTRA=10
                       WHERE ID=:id AND PERIODOMUESTRA=60''',
                    id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'TALISMAN: no se actualizó {number}')
            for number in ABSENT_SENSORS:
                cursor.execute(
                    '''UPDATE SENSOR SET ACTIVO=0,VISIBLE=0
                       WHERE ID=:id AND ACTIVO=1''', id=by_number[number][0])
                if cursor.rowcount != 1:
                    raise ValueError(f'TALISMAN: no se desactivó {number}')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof},
                     ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
