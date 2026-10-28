"""Reconcile PLATANAR GS300 catalog with its proven 50-word wire layout."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

from telemetry_decoders import gs300_words


DCP = '15B27202'
STATION = '0000000G03'
SIGNAL_RLS_TYPE = '2EBE1DDE-D65B-4B39-94E0-C5074387808E'

CHANGES = {
    '0012': {'new_number': '0900', 'new_order': 3},
    '0906': {'new_number': '0901', 'new_order': 4},
    '0905': {'new_number': '0902', 'new_order': 5, 'new_period': 10,
             'new_decimals': 1, 'new_type': SIGNAL_RLS_TYPE},
    '0017': {'new_active': 0, 'new_visible': 0},
    '0018': {'new_active': 0, 'new_visible': 0},
}


def raw_evidence():
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    entry = audit[DCP]
    frames = []
    for frame in entry['frames']:
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        if len(payload) < 4 or payload[1:3] != b'B1':
            continue
        words = gs300_words(payload[4:])
        if len(words) != 50:
            raise ValueError('PLATANAR: longitud inestable')
        blocks = (words[:12], words[12:24], words[24:26],
                  words[26:38], words[38:50])
        if any(value is not None and not -100000 <= value / 100 <= 1000
               for value in blocks[0]):
            raise ValueError('PLATANAR: bloque de nivel inválido')
        if any(value is not None and not 0 <= value / 10 <= 30
               for value in blocks[1]):
            raise ValueError('PLATANAR: bloque de precipitación inválido')
        if any(value is not None and not 7 <= value / 100 <= 18
               for value in blocks[2]):
            raise ValueError('PLATANAR: bloque de batería inválido')
        if any(value is not None and not 0 <= value <= 1000
               for value in blocks[3]):
            raise ValueError('PLATANAR: bloque de estado inválido')
        if any(value is not None and not 0 <= value / 10 <= 1000
               for value in blocks[4]):
            raise ValueError('PLATANAR: bloque de señal inválido')
        frames.append((dt.datetime.fromisoformat(frame['received']), words))
    if len(frames) < 3:
        raise ValueError('PLATANAR: evidencia insuficiente')
    frames.sort()
    overlap_values = overlap_failures = 0
    counts = (12, 12, 2, 12, 12)
    periods = (10, 10, 60, 10, 10)
    for (old_stamp, old), (new_stamp, new) in zip(frames, frames[1:]):
        elapsed = round((new_stamp - old_stamp).total_seconds() / 60)
        position = 0
        for count, period in zip(counts, periods):
            shift = round(elapsed / period)
            if 0 < shift < count:
                for left, right in zip(
                        old[position:position + count - shift],
                        new[position + shift:position + count]):
                    if left is None or right is None:
                        continue
                    overlap_values += 1
                    overlap_failures += left != right
            position += count
    if overlap_failures:
        raise ValueError('PLATANAR: el solapamiento temporal no coincide')
    return {'frames': len(frames), 'words': 50,
            'overlap_values': overlap_values,
            'overlap_failures': overlap_failures,
            'layout': [
                {'sensor': '0001', 'count': 12, 'period': 10},
                {'sensor': '0002', 'count': 12, 'period': 10},
                {'sensor': '0900', 'count': 2, 'period': 60},
                {'sensor': '0901', 'count': 12, 'period': 10},
                {'sensor': '0902', 'count': 12, 'period': 10},
            ]}


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    proof = raw_evidence()
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                           password=os.environ['ORACLE_CATALOG_PASSWORD'],
                           dsn=os.environ['ORACLE_DSN']) as connection:
        cursor = connection.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            '''SELECT G.ID,G.IDESTACION,G.RANGOTRANSMISION,G.DECODIFICADOR
               FROM DATOSGOES G JOIN ESTACION E ON E.ID=G.IDESTACION
               WHERE E.IDASIGNADO=:station AND TRIM(G.IDSATELITAL)=:dcp''' + lock,
            station=STATION, dcp=DCP)
        rows = cursor.fetchall()
        if len(rows) != 1 or str(rows[0][2]) != '01:00:00' or str(rows[0][3]).strip() != 'GS300':
            raise ValueError('PLATANAR: DATOSGOES cambió')
        goes_id, station_id = rows[0][0], rows[0][1]
        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR) AS NUMEROSENSOR,IDTIPOSENSOR,VISIBLE,ACTIVO,
                      PERIODOMUESTRA,ORDEN,PUNTODECIMAL,IDUNIDADMEDIDA,
                      VALORMINIMO,VALORMAXIMO
               FROM SENSOR WHERE IDESTACION=:station ORDER BY NUMEROSENSOR''' + lock,
            station=station_id)
        columns = [item[0].lower() for item in cursor.description]
        originals = [dict(zip(columns, row)) for row in cursor.fetchall()]
        by_number = {row['numerosensor']: row for row in originals}
        if len(by_number) != 7 or any(number not in by_number for number in CHANGES):
            raise ValueError('PLATANAR: conjunto de sensores cambió')
        if any(number in by_number for number in ('0900', '0901', '0902')):
            raise ValueError('PLATANAR: ya existen los números destino')
        backup = {'applied': args.apply, 'goes_id': goes_id,
                  'old_range': rows[0][2], 'new_range': '02:00:00',
                  'original_sensors': originals, 'changes': CHANGES,
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
                raise ValueError('PLATANAR: no se actualizó el rango')
            for old_number, change in CHANGES.items():
                original = by_number[old_number]
                values = {
                    'new_number': change.get('new_number', old_number),
                    'new_type': change.get('new_type', original['idtiposensor']),
                    'new_visible': change.get('new_visible', original['visible']),
                    'new_active': change.get('new_active', original['activo']),
                    'new_period': change.get('new_period', original['periodomuestra']),
                    'new_order': change.get('new_order', original['orden']),
                    'new_decimals': change.get('new_decimals', original['puntodecimal']),
                    'id': original['id'], 'old_number': old_number,
                    'old_type': original['idtiposensor'],
                    'old_visible': original['visible'], 'old_active': original['activo'],
                    'old_period': original['periodomuestra'],
                    'old_order': original['orden'],
                    'old_decimals': original['puntodecimal'],
                }
                cursor.execute(
                    '''UPDATE SENSOR SET NUMEROSENSOR=:new_number,
                           IDTIPOSENSOR=:new_type,VISIBLE=:new_visible,
                           ACTIVO=:new_active,PERIODOMUESTRA=:new_period,
                           ORDEN=:new_order,PUNTODECIMAL=:new_decimals
                       WHERE ID=:id AND TRIM(NUMEROSENSOR)=:old_number
                         AND IDTIPOSENSOR=:old_type AND VISIBLE=:old_visible
                         AND ACTIVO=:old_active AND PERIODOMUESTRA=:old_period
                         AND ORDEN=:old_order AND PUNTODECIMAL=:old_decimals''',
                    values)
                if cursor.rowcount != 1:
                    raise ValueError(f'PLATANAR/{old_number}: no se actualizó')
            connection.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
