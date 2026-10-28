"""Quarantine negative SMN panel samples only when catalog and raw agree.

Seven days, explicit station allowlist, exclusive private backup before writes.
Does not manufacture a replacement reading or change sensor configuration.
"""
import argparse
import datetime as dt
import json
import math
import os

from gs300_catalog import load_sensors
from telemetry_decoders import text_records, record_sensors

STATIONS = ('CH26', 'CH29', 'PU03', 'SO07', 'SO09')


def main():
    import oracledb
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--backup', required=True)
    args = p.parse_args()
    dsn = os.environ['ORACLE_DSN']
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'], password=os.environ['ORACLE_CATALOG_PASSWORD'], dsn=dsn) as cat:
        sensors = load_sensors(cat)
    with oracledb.connect(user=os.environ['ORACLE_USER'], password=os.environ['ORACLE_PASSWORD'], dsn=dsn) as c:
        c.call_timeout = 60000
        q = c.cursor()
        q.execute("ALTER SESSION SET TIME_ZONE='UTC'")
        q.execute('SELECT SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM DUAL')
        end = q.fetchone()[0]
        start = end - dt.timedelta(days=7)
        changes, skipped, messages = [], [], []
        for code in STATIONS:
            ss = sensors[code]
            panel = [s for s in ss if 'panel' in s['nombre'].lower() and 'voltaje' in s['nombre'].lower() and s['unidad'] == 'V']
            if len(panel) != 1:
                raise ValueError(f'{code}: panel no unívoco')
            sensor = panel[0]['numero_sensor']
            q.execute("SELECT ROWIDTOCHAR(ROWID),DCP_ID,SENSOR_ID,SYS_EXTRACT_UTC(TS),VARIABLE,VALOR,VALIDO,DESCRIPCION,QC_FLAG,QC_DETAIL FROM DCP_DATOS WHERE ID_ASIGNADO=:code AND SENSOR_ID=:sensor AND TS BETWEEN :s AND :e AND VALOR<0" + (' FOR UPDATE' if args.apply else ''), code=code, sensor=sensor, s=start, e=end)
            rows = q.fetchall()
            for dcp in {r[1] for r in rows}:
                q.execute('SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE FROM DCP_HEADERS WHERE DCP_ID=:d AND TIMESTAMP_MSG BETWEEN :s AND :e AND RAW_MESSAGE IS NOT NULL', d=dcp, s=start, e=end)
                evidence = {}
                for received, raw in q.fetchall():
                    if raw[:8] != dcp:
                        continue
                    try:
                        records = text_records(raw[37:].encode('latin1'), received, 'SMN')
                        decoded = []
                        for stamp, values in records:
                            if values.table != '4':
                                continue
                            mapped = record_sensors(code, values, ss)
                            decoded += [(stamp.replace(tzinfo=None), v) for s,v in zip(mapped, values) if s and s['numero_sensor'] == sensor]
                    except (ValueError, UnicodeError):
                        continue
                    messages.append((code, received, raw))
                    for stamp, value in decoded:
                        evidence.setdefault(stamp, set()).add(value)
                for row in (r for r in rows if r[1] == dcp):
                    values = evidence.get(row[3], set())
                    if len(values) == 1 and math.isclose(next(iter(values)), row[5], rel_tol=1e-6, abs_tol=1e-6):
                        changes.append(dict(code=code, before=row, raw_value=next(iter(values))))
                    else:
                        skipped.append(dict(code=code, row=row, reason='Sin coincidencia unívoca con trama'))
        summaries = []
        for dcp, variable in sorted({(e['before'][1], e['before'][4]) for e in changes}):
            q.execute('SELECT ROWIDTOCHAR(ROWID),SYS_EXTRACT_UTC(TS),VALOR,TIPO FROM ULTIMAS_MEDICIONES WHERE DCP_ID=:d AND VARIABLE=:v AND VALOR<0' + (' FOR UPDATE' if args.apply else ''), d=dcp, v=variable)
            summaries += [(dcp, variable, *r) for r in q.fetchall()]
        fd = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(dict(start=start,end=end,changes=changes,skipped=skipped,messages=messages,summaries=summaries), f, default=str, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        if args.apply:
            for e in changes:
                row = e['before']
                note = f"Voltaje de panel negativo en trama SMN: {e['raw_value']} V; no se infiere valor corregido"
                q.execute('UPDATE DCP_DATOS SET VALOR=NULL,VALIDO=0,DESCRIPCION=:note WHERE ROWID=CHARTOROWID(:rid) AND VALOR=:old', note=note, rid=row[0], old=row[5])
                if q.rowcount != 1:
                    raise ValueError('Registro modificado durante reparación')
            for dcp, variable, rid, stamp, value, tipo in summaries:
                q.execute('SELECT SYS_EXTRACT_UTC(TS),VALOR FROM DCP_DATOS WHERE DCP_ID=:d AND VARIABLE=:v AND VALIDO=1 AND VALOR>=0 AND TS<=SYSTIMESTAMP ORDER BY TS DESC FETCH FIRST 1 ROW ONLY', d=dcp, v=variable)
                latest = q.fetchone()
                if latest:
                    q.execute('UPDATE ULTIMAS_MEDICIONES SET TS=:t,VALOR=:v WHERE ROWID=CHARTOROWID(:rid)', t=latest[0],v=latest[1],rid=rid)
                else:
                    q.execute('DELETE FROM ULTIMAS_MEDICIONES WHERE ROWID=CHARTOROWID(:rid)',rid=rid)
            for e in changes:
                q.execute('SELECT VALOR,VALIDO FROM DCP_DATOS WHERE ROWID=CHARTOROWID(:rid)',rid=e['before'][0])
                if q.fetchone() != (None,0):
                    raise ValueError('Verificación fallida')
            c.commit()
        from collections import Counter
        print(dict(applied=args.apply, matched=len(changes), skipped=len(skipped), summaries=len(summaries), stations=dict(Counter(e['code'] for e in changes))))


if __name__ == '__main__':
    main()
