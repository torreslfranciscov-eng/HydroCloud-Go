"""Bounded OTT battery replay: verified Acueducto station, seven days, backup first.

Read-only by default; requires --apply for writes. Never imports the ingestion app.
Only reconstructible sample keys are modified; unmatched old rows are reported.
"""
import argparse
import ast
import datetime as dt
import json
import math
import os
from pathlib import Path
from gs300_catalog import load_sensors, load_stations
from telemetry_decoders import ott_blocks, ott_sensors, ott_value, payload_family


def main():
    import oracledb
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backup', required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    code, dcp, sensor_id = '000000LG44', '15B94430', '0011'
    tree = ast.parse(Path(__file__).with_name('mycloud_all_timescale.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'ConvertFrom6BitsTo8Bits')
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'isolated', 'exec'), scope)
    dsn = os.environ['ORACLE_DSN']
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'], password=os.environ['ORACLE_CATALOG_PASSWORD'], dsn=dsn) as cat:
        sensors = load_sensors(cat)[code]
        station = load_stations(cat)[dcp]
    if station['decoder'] != 'OTTBinario' or station['id_asignado'] != code:
        raise ValueError('Catálogo cambió')
    sensor = next(s for s in sensors if s['numero_sensor'] == sensor_id)
    if 'bater' not in sensor['nombre'].lower() or sensor['unidad'].upper() != 'V':
        raise ValueError('Canal no confirmado como batería en V')
    end = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    start = end-dt.timedelta(days=7)
    with oracledb.connect(user=os.environ['ORACLE_USER'], password=os.environ['ORACLE_PASSWORD'], dsn=dsn) as conn:
        conn.call_timeout = 60000
        q = conn.cursor()
        q.execute("ALTER SESSION SET TIME_ZONE='UTC'")
        q.execute('SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE FROM DCP_HEADERS WHERE DCP_ID=:d AND TIMESTAMP_MSG BETWEEN :s AND :e ORDER BY TIMESTAMP_MSG', d=dcp, s=start, e=end)
        messages = q.fetchall()
        samples, rejected = {}, []
        for received, raw in messages:
            if not raw: continue
            payload = raw[37:].encode('latin1')
            if payload_family(payload) == 'notice': continue
            try:
                if raw[:8] != dcp: raise ValueError('DCP discordante')
                blocks = ott_blocks(payload, scope['ConvertFrom6BitsTo8Bits'], received)
                mapped = ott_sensors(code, blocks, sensors, station['rango_transmision'])
            except ValueError as exc:
                rejected.append((received, str(exc)))
                continue
            for (_, values), current in zip(blocks, mapped):
                if current['numero_sensor'] != sensor_id: continue
                for stamp, value in zip(values.times, values):
                    stamp = stamp.replace(tzinfo=None)
                    if not start <= stamp <= end: continue
                    result = ott_value(value, current)
                    if stamp in samples and samples[stamp] != result:
                        raise ValueError('Tramas contradictorias: '+str(stamp))
                    samples[stamp] = result
        if not samples: raise ValueError('Sin muestras verificables')
        q.execute('SELECT ROWIDTOCHAR(ROWID),SYS_EXTRACT_UTC(TS),VARIABLE,VALOR,VALIDO,DESCRIPCION,QC_FLAG,QC_DETAIL FROM DCP_DATOS WHERE DCP_ID=:d AND SENSOR_ID=:sensor AND TS BETWEEN :s AND :e'+(' FOR UPDATE' if args.apply else ''), d=dcp, sensor=sensor_id, s=start, e=end)
        original = q.fetchall()
        existing = {r[1]:r for r in original}
        if len(existing) != len(original): raise ValueError('Duplicados: no se modifican')
        variable = sensor['nombre'].lower().replace(' ', '_')
        q.execute('SELECT VARIABLE,SYS_EXTRACT_UTC(TS),VALOR,TIPO FROM ULTIMAS_MEDICIONES WHERE DCP_ID=:d'+(' FOR UPDATE' if args.apply else ''), d=dcp)
        summary = q.fetchall()
        with open(args.backup, 'x', encoding='utf-8') as backup:
            os.chmod(args.backup, 0o600)
            json.dump(dict(station=code,dcp=dcp,sensor=sensor_id,start=start,end=end,original=original,summary=summary,messages=messages,sensors=sensors,station_config=station,rejected=rejected,reconstructed=list(samples.items())), backup, default=str, ensure_ascii=False, indent=2)
            backup.flush(); os.fsync(backup.fileno())
        changed = inserted = 0
        if args.apply:
            for stamp,(value,valid,note) in sorted(samples.items()):
                note = 'Reprocesado OTT IGS: '+note
                if stamp in existing:
                    q.execute('UPDATE DCP_DATOS SET VALOR=:v,VALIDO=:ok,DESCRIPCION=:n,QC_FLAG=NULL,QC_DETAIL=NULL WHERE ROWID=CHARTOROWID(:rid) AND DCP_ID=:d AND SENSOR_ID=:sensor',v=value,ok=int(valid),n=note,rid=existing[stamp][0],d=dcp,sensor=sensor_id)
                    if q.rowcount != 1: raise ValueError('Fila cambió')
                    changed += 1
                else:
                    q.execute('INSERT INTO DCP_DATOS(TS,DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,VALIDO,DESCRIPCION,TIPO,ANIO,MES,DIA,HORA,MINUTO) VALUES(:t,:d,:c,:s,:var,:v,:ok,:n,:var,:y,:m,:day,:h,:minute)',t=stamp,d=dcp,c=code,s=sensor_id,var=variable,v=value,ok=int(valid),n=note,y=stamp.year,m=stamp.month,day=stamp.day,h=stamp.hour,minute=stamp.minute)
                    inserted += 1
            good = [(t,v) for t,(v,ok,_) in samples.items() if ok and v is not None]
            if good:
                t,v = max(good)
                q.execute('MERGE INTO ULTIMAS_MEDICIONES u USING(SELECT :d DCP_ID,:var VARIABLE FROM DUAL) x ON(u.DCP_ID=x.DCP_ID AND u.VARIABLE=x.VARIABLE) WHEN MATCHED THEN UPDATE SET TS=:t,VALOR=:v WHERE u.TS<=:t WHEN NOT MATCHED THEN INSERT(DCP_ID,VARIABLE,TS,VALOR,TIPO) VALUES(:d,:var,:t,:v,:var)',d=dcp,var=variable,t=t,v=v)
            # Verify all reconstructed keys before commit, including float storage.
            q.execute('SELECT SYS_EXTRACT_UTC(TS),VALOR,VALIDO FROM DCP_DATOS WHERE DCP_ID=:d AND SENSOR_ID=:s AND TS BETWEEN :a AND :b',d=dcp,s=sensor_id,a=start,b=end)
            rows = q.fetchall()
            observed = {t:(v,ok) for t,v,ok in rows}
            if len(observed) != len(rows): raise ValueError('Duplicados durante reparación')
            for t,(v,ok,_) in samples.items():
                actual,flag = observed[t]
                if flag != int(ok) or (actual is None) != (v is None) or (v is not None and not math.isclose(actual,v,rel_tol=1e-6,abs_tol=1e-6)):
                    raise ValueError('Verificación falló: '+str(t))
            conn.commit()
        print(json.dumps(dict(applied=args.apply,samples=len(samples),matched=sum(t in existing for t in samples),updates=changed,inserts=inserted,rejected_messages=len(rejected),unmatched_old_rows=sum(t not in samples for t in existing),invalid=sum(not x[1] for x in samples.values()))))


if __name__ == '__main__':
    main()
