"""Reconcile BOCA DEL CERRO using its UI-confirmed 90-word GS300 layout."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

from telemetry_decoders import gs300_words


DCP = '15B2D2FA'
STATION = '0000000G08'
LAYOUT = (
    ('0001', 12, 10), ('0002', 12, 10), ('0003', 2, 60),
    ('0004', 12, 10), ('0005', 12, 10), ('0009', 12, 10),
    ('0010', 12, 10), ('0011', 2, 60), ('0012', 2, 60),
    ('0905', 12, 10),
)
CHANGES = {
    '0001': {'active': 1, 'visible': 1},
    '0004': {'period': 10},
    '0005': {'period': 10},
    '0009': {'period': 10},
    '0010': {'period': 10},
    '0016': {'active': 0, 'visible': 0},
    '0906': {'active': 0, 'visible': 0},
    '0907': {'active': 0, 'visible': 0},
}


def raw_evidence():
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    frames = []
    for frame in audit[DCP]['frames']:
        stamp = dt.datetime.fromisoformat(frame['received']).replace(second=0)
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        if len(payload) < 4 or payload[1:3] != b'B1':
            raise ValueError('BOCA DEL CERRO: trama no B1')
        words = gs300_words(payload[4:])
        if len(words) != 90:
            raise ValueError('BOCA DEL CERRO: longitud inestable')
        if not any(existing[0] == stamp for existing in frames):
            frames.append((stamp, words))
    frames.sort()
    if len(frames) < 3:
        raise ValueError('BOCA DEL CERRO: evidencia insuficiente')
    overlap_values = overlap_failures = 0
    for (old_stamp, old), (new_stamp, new) in zip(frames, frames[1:]):
        elapsed = round((new_stamp - old_stamp).total_seconds() / 60)
        position = 0
        for _, count, period in LAYOUT:
            shift = round(elapsed / period)
            if 0 < shift < count:
                for left, right in zip(
                        old[position:position + count - shift],
                        new[position + shift:position + count]):
                    overlap_values += 1
                    overlap_failures += left != right
            position += count
    if overlap_failures:
        raise ValueError('BOCA DEL CERRO: el solapamiento no coincide')
    return {
        'frames': len(frames), 'words': 90,
        'overlap_values': overlap_values,
        'overlap_failures': overlap_failures,
        'layout': [
            {'sensor': sensor, 'count': count, 'period': period}
            for sensor, count, period in LAYOUT
        ],
        'physical_confirmation': 'Captura del usuario: 0001,0002,0003,0004,0005,0009,0010,0011,0012,0905',
    }


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    proof = raw_evidence()
    with oracledb.connect(
            user=os.environ['ORACLE_CATALOG_USER'],
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
        if (len(rows) != 1 or str(rows[0][2]) != '02:00:00'
                or str(rows[0][3]).strip() != 'GS300'):
            raise ValueError('BOCA DEL CERRO: DATOSGOES cambió')
        station_id = rows[0][1]
        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR) AS NUMEROSENSOR,
                      PERIODOMUESTRA,ACTIVO,VISIBLE,ORDEN
               FROM SENSOR WHERE IDESTACION=:station''' + lock,
            station=station_id)
        columns = [item[0].lower() for item in cursor.description]
        originals = [dict(zip(columns, row)) for row in cursor.fetchall()]
        by_number = {row['numerosensor']: row for row in originals}
        expected_numbers = {sensor for sensor, _, _ in LAYOUT} | set(CHANGES)
        if not expected_numbers <= set(by_number):
            raise ValueError('BOCA DEL CERRO: conjunto SENSOR cambió')
        if by_number['0001']['activo'] != 0:
            raise ValueError('BOCA DEL CERRO: 0001 ya cambió')
        for number in ('0004', '0005', '0009', '0010'):
            if by_number[number]['periodomuestra'] != 60:
                raise ValueError(f'BOCA DEL CERRO/{number}: período ya cambió')
        for number in ('0016', '0906', '0907'):
            if by_number[number]['activo'] != 1:
                raise ValueError(f'BOCA DEL CERRO/{number}: estado ya cambió')

        backup = {
            'applied': args.apply, 'goes_id': rows[0][0],
            'original_sensors': originals, 'changes': CHANGES, 'proof': proof,
        }
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if args.apply:
            for number, change in CHANGES.items():
                original = by_number[number]
                values = {
                    'period': change.get('period', original['periodomuestra']),
                    'active': change.get('active', original['activo']),
                    'visible': change.get('visible', original['visible']),
                    'id': original['id'],
                    'old_period': original['periodomuestra'],
                    'old_active': original['activo'],
                    'old_visible': original['visible'],
                }
                cursor.execute(
                    '''UPDATE SENSOR SET PERIODOMUESTRA=:period,
                           ACTIVO=:active,VISIBLE=:visible
                       WHERE ID=:id AND PERIODOMUESTRA=:old_period
                         AND ACTIVO=:old_active AND VISIBLE=:old_visible''',
                    values)
                if cursor.rowcount != 1:
                    raise ValueError(f'BOCA DEL CERRO/{number}: no se actualizó')
            connection.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
