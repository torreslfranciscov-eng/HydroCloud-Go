"""Reconcile EMILIANO ZAPATA CHABLE with its proven 62-word GS300 wire."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

from telemetry_decoders import gs300_words


DCP = '15B2C18C'
STATION = '0000000G07'
LAYOUT = (
    ('0001', 12, 10),
    ('0003', 2, 60),
    ('0004', 2, 60),
    ('0005', 2, 60),
    ('0009', 2, 60),
    ('0010', 2, 60),
    ('0011', 2, 60),
    ('0012', 2, 60),
    ('0002', 12, 10),
    ('0020', 12, 10),
    ('0021', 12, 10),
)


def raw_evidence():
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    frames = []
    for frame in audit[DCP]['frames']:
        stamp = dt.datetime.fromisoformat(frame['received']).replace(second=0)
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        if len(payload) < 4 or payload[1:3] != b'B1':
            raise ValueError('EMILIANO: trama no B1')
        words = gs300_words(payload[4:])
        if len(words) != 62:
            raise ValueError('EMILIANO: longitud inestable')
        if not any(existing[0] == stamp for existing in frames):
            frames.append((stamp, words))
    frames.sort()
    if len(frames) < 3:
        raise ValueError('EMILIANO: evidencia insuficiente')

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
        raise ValueError('EMILIANO: el solapamiento temporal no coincide')

    # Check the unambiguous physical ranges in every frame. -131072 is the
    # station's missing-value code for the level block.
    for _, words in frames:
        checks = (
            (words[0:12], lambda value: value == -131072 or 0 <= value / 100 <= 12),
            (words[12:14], lambda value: -15 <= value / 100 <= 55),
            (words[14:16], lambda value: 0 <= value / 10 <= 252),
            (words[16:18], lambda value: 0 <= value <= 360),
            (words[18:20], lambda value: 0 <= value / 10 <= 252),
            (words[20:22], lambda value: 0 <= value <= 360),
            (words[22:24], lambda value: 0 <= value <= 101),
            (words[24:26], lambda value: 0 <= value / 100 <= 17),
            (words[26:38], lambda value: 0 <= value / 10 <= 30),
            (words[38:50], lambda value: 0 <= value / 10 <= 80000),
            (words[50:62], lambda value: 0 <= value <= 1000),
        )
        if any(not all(check(value) for value in values)
               for values, check in checks):
            raise ValueError('EMILIANO: valores incompatibles con Sensor')
    return {
        'frames': len(frames),
        'words': 62,
        'overlap_values': overlap_values,
        'overlap_failures': overlap_failures,
        'layout': [
            {'sensor': sensor, 'count': count, 'period': period}
            for sensor, count, period in LAYOUT
        ],
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
        goes_rows = cursor.fetchall()
        if (len(goes_rows) != 1 or str(goes_rows[0][2]) != '01:00:00'
                or str(goes_rows[0][3]).strip() != 'GS300'):
            raise ValueError('EMILIANO: DATOSGOES cambió')
        goes_id, station_id = goes_rows[0][0], goes_rows[0][1]
        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR) AS NUMEROSENSOR,
                      PERIODOMUESTRA,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        columns = [item[0].lower() for item in cursor.description]
        originals = [dict(zip(columns, row)) for row in cursor.fetchall()]
        active = {row['numerosensor']: row for row in originals if row['activo'] == 1}
        expected = {sensor for sensor, _, _ in LAYOUT}
        if set(active) != expected:
            raise ValueError('EMILIANO: conjunto de sensores activos cambió')
        if active['0020']['periodomuestra'] != 60 or active['0021']['periodomuestra'] != 60:
            raise ValueError('EMILIANO: períodos destino ya cambiaron')

        backup = {
            'applied': args.apply,
            'goes_id': goes_id,
            'old_range': goes_rows[0][2],
            'new_range': '02:00:00',
            'original_sensors': originals,
            'changes': {'0020': {'period': 10}, '0021': {'period': 10}},
            'proof': proof,
        }
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            cursor.execute(
                '''UPDATE DATOSGOES SET RANGOTRANSMISION='02:00:00'
                   WHERE ID=:id AND RANGOTRANSMISION='01:00:00' ''',
                id=goes_id)
            if cursor.rowcount != 1:
                raise ValueError('EMILIANO: no se actualizó el rango')
            for number in ('0020', '0021'):
                cursor.execute(
                    '''UPDATE SENSOR SET PERIODOMUESTRA=10
                       WHERE ID=:id AND PERIODOMUESTRA=60 AND ACTIVO=1''',
                    id=active[number]['id'])
                if cursor.rowcount != 1:
                    raise ValueError(f'EMILIANO/{number}: no se actualizó')
            connection.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
