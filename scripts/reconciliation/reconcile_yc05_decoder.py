"""Correct YC05 decoder from GS300 to SMN with raw evidence and backup."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

from telemetry_decoders import payload_family, text_records


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    entry = audit['15CC1620']
    frames = []
    widths = set()
    for frame in entry['frames']:
        payload = frame['raw'][37:].encode('latin1')
        if payload_family(payload) != 'text':
            raise ValueError('YC05: trama no textual mezclada')
        received = dt.datetime.fromisoformat(frame['received'])
        records = text_records(payload, received, 'SMN')
        widths.update(len(values) for _, values in records)
        frames.append({'received': frame['received'],
                       'records': len(records),
                       'widths': sorted({len(values) for _, values in records})})
    if len(frames) < 3 or not widths.issubset({10, 12}) or 12 not in widths:
        raise ValueError('YC05: evidencia SMN insuficiente o inesperada')
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                           password=os.environ['ORACLE_CATALOG_PASSWORD'],
                           dsn=os.environ['ORACLE_DSN']) as connection:
        cursor = connection.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            '''SELECT G.ID,G.DECODIFICADOR,G.IDSATELITAL,E.IDASIGNADO,E.NOMBRE
               FROM DATOSGOES G JOIN ESTACION E ON E.ID=G.IDESTACION
               WHERE E.IDASIGNADO='YC05' AND TRIM(G.IDSATELITAL)='15CC1620' ''' + lock)
        rows = cursor.fetchall()
        if len(rows) != 1 or str(rows[0][1]).strip() != 'GS300':
            raise ValueError('YC05: configuración cambió o está duplicada')
        original = {
            'goes_id': rows[0][0], 'old_decoder': rows[0][1],
            'new_decoder': 'SMN', 'dcp': rows[0][2],
            'station': rows[0][3], 'name': rows[0][4],
            'evidence_frames': len(frames), 'record_widths': sorted(widths),
            'evidence': frames,
        }
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump({'applied': args.apply, 'original': original}, stream,
                      ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if args.apply:
            cursor.execute(
                '''UPDATE DATOSGOES SET DECODIFICADOR='SMN'
                   WHERE ID=:id AND DECODIFICADOR='GS300' ''',
                id=rows[0][0])
            if cursor.rowcount != 1:
                raise ValueError('YC05: no se actualizó el decoder')
            connection.commit()
    print(json.dumps({'applied': args.apply, 'station': 'YC05',
                      'old_decoder': 'GS300', 'new_decoder': 'SMN',
                      'frames': len(frames), 'record_widths': sorted(widths)}))


if __name__ == '__main__':
    main()
