"""Correct Carrizal's UI-confirmed radar state channel; dry-run by default."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

from gs300_catalog import assign_positions, validate_words
from telemetry_decoders import gs300_words


STATION = 'CAZLVER018'
DCP = '1A5112CC'


def raw_evidence():
    entry = json.loads(Path('live-ingestion-audit.json').read_text())[DCP]
    frames = []
    for frame in entry['frames']:
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        if len(payload) < 4 or payload[1:3] != b'B1':
            raise ValueError('CARRIZAL: trama no B1')
        words = gs300_words(payload[4:])
        if len(words) != 30:
            raise ValueError('CARRIZAL: longitud inestable')
        if not all(1500 <= value <= 6000 for value in words[28:]):
            raise ValueError('CARRIZAL: temperatura auxiliar fuera de rango')
        frames.append((dt.datetime.fromisoformat(frame['received']).replace(second=0), words))
    frames.sort()
    if len(frames) < 3:
        raise ValueError('CARRIZAL: evidencia insuficiente')
    checks = failures = 0
    layout = ((0, 12, 10), (12, 12, 10), (24, 2, 60),
              (26, 2, 60), (28, 2, 60))
    for (old_stamp, old), (new_stamp, new) in zip(frames, frames[1:]):
        elapsed = round((new_stamp - old_stamp).total_seconds() / 60)
        for base, count, period in layout:
            shift = round(elapsed / period)
            if 0 < shift < count:
                for left, right in zip(old[base:base + count - shift],
                                       new[base + shift:base + count]):
                    checks += 1
                    failures += left != right
    if failures:
        raise ValueError('CARRIZAL: solapamientos discordantes')
    mapped = assign_positions([
        dict(numero_sensor='0001', periodo=10, orden=1, decoder='GS300'),
        dict(numero_sensor='0020', periodo=10, orden=2, decoder='GS300'),
        dict(numero_sensor='0018', periodo=60, orden=3, decoder='GS300'),
        dict(numero_sensor='0019', periodo=60, orden=4, decoder='GS300'),
    ], 120)
    for _, words in frames:
        validate_words(words, mapped, station=STATION)
    return {'frames': len(frames), 'sensor_words': 28,
            'auxiliary_words': 2, 'overlap_checks': checks}


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
            '''SELECT E.ID,G.ID,G.RANGOTRANSMISION,TRIM(G.DECODIFICADOR)
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO=:station AND TRIM(G.IDSATELITAL)=:dcp''' + lock,
            station=STATION, dcp=DCP)
        rows = cursor.fetchall()
        if (len(rows) != 1 or str(rows[0][2]) != '02:00:00' or
                rows[0][3] != 'GS300'):
            raise ValueError('CARRIZAL: DATOSGOES cambió')
        station_id = rows[0][0]
        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,VISIBLE
               FROM SENSOR WHERE IDESTACION=:station
                 AND TRIM(NUMEROSENSOR) IN ('0015','0020')''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 1 or sensors[0][1:] != ('0015', 60.0, 2, 1, 1):
            raise ValueError('CARRIZAL: canal Estado del radar cambió')
        original = sensors[0]
        backup = {'applied': args.apply, 'station': STATION,
                  'original_sensor': original, 'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if args.apply:
            cursor.execute(
                '''UPDATE SENSOR SET NUMEROSENSOR='0020',PERIODOMUESTRA=10
                   WHERE ID=:id AND TRIM(NUMEROSENSOR)='0015'
                     AND PERIODOMUESTRA=60 AND ORDEN=2 AND ACTIVO=1''',
                id=original[0])
            if cursor.rowcount != 1:
                raise ValueError('CARRIZAL: sensor no actualizado')
            connection.commit()
    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
