"""Repair ZONTECOMATLAN OTT order and decimal scales from stable wire blocks."""
import argparse
import ast
import configparser
import json
import os
from pathlib import Path

import oracledb

from telemetry_decoders import ott_blocks


STATION = 'ZONTVER066'
DCP = '1A5653F2'
SENSORS = ('0003', '0005', '0006', '0007', '0008',
           '0010', '0011', '0012', '0013', '0019')
DECIMALS = dict(zip(SENSORS, (1, 1, 1, 1, 1, 1, 1, 1, 1, 2)))
RANGES = ((0, 2000), (-400, 800), (0, 1100), (-400, 800),
          (8000, 12000), (0, 3000), (0, 3600), (0, 5000),
          (0, 3600), (700, 1800))


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
    frames = []
    rejected = 0
    for received, raw in cur:
        blocks = ott_blocks(raw[37:].encode('latin1'), convert, received)
        layout = tuple((interval, len(values)) for interval, values in blocks)
        if layout != ((10, 12),) + ((60, 2),) * 9:
            rejected += 1
            continue
        frames.append(blocks)
    if len(frames) < 24:
        raise ValueError('ZONTECOMATLAN: evidencia insuficiente')
    proof = {'frames': len(frames), 'rejected_or_partial_frames': rejected,
             'layout': [(10, 12)] + [(60, 2)] * 9,
             'segments': {}}
    for index, (number, (low, high)) in enumerate(zip(SENSORS, RANGES)):
        values = [value for blocks in frames for value in blocks[index][1]
                  if value >= -32700]
        if not values:
            raise ValueError(f'ZONTECOMATLAN: sin datos físicos en {number}')
        physical = [value for value in values if low <= value <= high]
        if len(physical) < 24 or len(physical) / len(values) < .95:
            raise ValueError(
                f'ZONTECOMATLAN: demasiados valores fuera de rango en {number}')
        proof['segments'][number] = {
            'minimum_raw': min(physical), 'maximum_raw': max(physical),
            'outliers': len(values) - len(physical),
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
        station_rows = cur.fetchall()
        if len(station_rows) != 1 or str(station_rows[0][2]) != '02:00:00' or station_rows[0][3] != 'OTTBinario':
            raise ValueError('ZONTECOMATLAN: configuración GOES cambió')
        station_id = station_rows[0][0]
        cur.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PUNTODECIMAL,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station ORDER BY NUMEROSENSOR''' + lock,
            station=station_id)
        rows = cur.fetchall()
        by_number = {row[1]: row for row in rows}
        if set(by_number) != set(SENSORS) or any(row[4] != 1 for row in rows):
            raise ValueError('ZONTECOMATLAN: sensores cambiaron')
        backup = {'applied': args.apply, 'station': station_rows[0],
                  'sensors': rows, 'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        if args.apply:
            for order, number in enumerate(SENSORS, 1):
                cur.execute(
                    '''UPDATE SENSOR SET ORDEN=:ord,PUNTODECIMAL=:decimals
                       WHERE ID=:id AND ACTIVO=1''',
                    ord=order, decimals=DECIMALS[number], id=by_number[number][0])
                if cur.rowcount != 1:
                    raise ValueError(f'ZONTECOMATLAN: no se actualizó {number}')
            catalog.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
