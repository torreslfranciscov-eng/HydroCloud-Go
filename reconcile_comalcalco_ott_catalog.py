"""Correct COMALCALCO OTT coverage using its repeated complete 120-minute frames."""
import argparse
import ast
import configparser
import json
import os
from pathlib import Path

import oracledb

from telemetry_decoders import ott_blocks


STATION = 'COMAL27125'
DCP = '1A54F6FE'
EXPECTED = ((10, 12), (10, 12), (10, 12),
            (60, 2), (60, 2), (60, 2), (60, 2), (60, 2))


def converter():
    tree = ast.parse(Path('mycloud_all_timescale.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'ConvertFrom6BitsTo8Bits')
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'isolated', 'exec'), scope)
    return scope[node.name]


def prove(connection):
    cur = connection.cursor()
    cur.execute(
        '''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
           FROM DCP_HEADERS WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(7,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
           ORDER BY TIMESTAMP_MSG''', dcp=DCP)
    convert = converter()
    complete = rejected = 0
    for received, raw in cur:
        try:
            blocks = ott_blocks(raw[37:].encode('latin1'), convert, received)
            layout = tuple((interval, len(values)) for interval, values in blocks)
        except ValueError:
            rejected += 1
            continue
        if layout == EXPECTED:
            complete += 1
        else:
            rejected += 1
    if complete < 24:
        raise ValueError('COMALCALCO: evidencia completa insuficiente')
    return {'complete_frames': complete, 'rejected_or_partial_frames': rejected,
            'layout': EXPECTED, 'coverage_minutes': 120}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read('config.ini')
    source = config['oracle_cloud']
    with oracledb.connect(user=source['user'], password=source['password'],
                          dsn=source['dsn']) as history:
        proof = prove(history)
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                          password=os.environ['ORACLE_CATALOG_PASSWORD'],
                          dsn=source['dsn']) as catalog:
        cur = catalog.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cur.execute(
            '''SELECT E.ID,G.ID,G.RANGOTRANSMISION,TRIM(G.DECODIFICADOR)
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO=:station AND TRIM(G.IDSATELITAL)=:dcp''' + lock,
            station=STATION, dcp=DCP)
        rows = cur.fetchall()
        if len(rows) != 1 or str(rows[0][2]) != '01:00:00' or rows[0][3] != 'OTTBinario':
            raise ValueError('COMALCALCO: configuración cambió')
        station_id, goes_id = rows[0][0], rows[0][1]
        cur.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cur.fetchall()
        if len(sensors) != 8 or any(row[4] != 1 for row in sensors):
            raise ValueError('COMALCALCO: sensores cambiaron')
        backup = {'applied': args.apply, 'station': rows[0],
                  'sensors': sensors, 'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        if args.apply:
            cur.execute(
                '''UPDATE DATOSGOES SET RANGOTRANSMISION='02:00:00'
                   WHERE ID=:id AND RANGOTRANSMISION='01:00:00' ''', id=goes_id)
            if cur.rowcount != 1:
                raise ValueError('COMALCALCO: no se actualizó el rango')
            catalog.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
