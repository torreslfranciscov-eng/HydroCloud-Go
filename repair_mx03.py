"""Read-only by default; repair MX03 last seven days from raw SMN messages.

Explicit --apply and a new backup file required. Does not import ingestion.
"""
import argparse
import datetime as dt
import json
import math
import os
from gs300_catalog import load_sensors
from telemetry_decoders import text_records, record_sensors, payload_family, MISSING
from repair_so06_voltages import normalize


def samples_from_raw(messages, sensors, start, end):
    samples = {}
    for received, raw in messages:
        if raw[:8] != '15AFD602':
            raise ValueError('DCP incorrecto')
        payload = raw[37:].encode('latin1')
        if payload_family(payload) == 'notice':
            continue
        if payload_family(payload) != 'table_text':
            raise ValueError('Formato no confirmado')
        for stamp, values in text_records(payload, received, 'SMN'):
            stamp = stamp.replace(tzinfo=None)
            if not dt.timedelta(0) <= received-stamp <= dt.timedelta(hours=3):
                raise ValueError('Fecha fuera de ventana')
            mapped = record_sensors('MX03', values, sensors)
            if not start <= stamp <= end:
                continue
            for sensor, raw_value in zip(mapped, values):
                if sensor is None:
                    raise ValueError('Perfil incompleto')
                period = sensor['periodo']
                if stamp.second or (stamp.hour*60+stamp.minute) % period:
                    raise ValueError('Periodo distinto del catálogo')
                value = None if raw_value in (MISSING,-32768) else raw_value
                if value is not None and not math.isfinite(value):
                    raise ValueError('Valor no finito')
                valid = int(value is not None and
                    sensor.get('valor_minimo',-math.inf) <= value <= sensor.get('valor_maximo',math.inf))
                key = stamp,sensor['numero_sensor']
                entry = value,valid,sensor['nombre'].lower().replace(' ','_')
                if key in samples and samples[key]!=entry:
                    raise ValueError('Tramas contradictorias')
                samples[key]=entry
    if not samples:
        raise ValueError('Sin muestras originales')
    return samples


def main():
    import oracledb
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--backup',required=True)
    args=p.parse_args()
    end=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    start=end-dt.timedelta(days=7)
    dsn=os.environ['ORACLE_DSN']
    cat=oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],password=os.environ['ORACLE_CATALOG_PASSWORD'],dsn=os.environ.get('ORACLE_CATALOG_DSN',dsn))
    try:
        sensors=load_sensors(cat)['MX03']
    finally:
        cat.close()
    with open(args.backup,'x',encoding='utf-8') as backup:
        c=oracledb.connect(user=os.environ['ORACLE_USER'],password=os.environ['ORACLE_PASSWORD'],dsn=dsn)
        c.call_timeout=60000
        try:
            with c.cursor() as q:
                q.execute("ALTER SESSION SET TIME_ZONE='UTC'")
                q.execute("SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE FROM DCP_HEADERS WHERE DCP_ID='15AFD602' AND TIMESTAMP_MSG>=:s AND TIMESTAMP_MSG<=:e AND RAW_MESSAGE IS NOT NULL ORDER BY TIMESTAMP_MSG",s=start,e=end)
                messages=q.fetchall()
                samples=samples_from_raw(messages,sensors,start,end)
                q.execute("SELECT ROWIDTOCHAR(ROWID) RID,SYS_EXTRACT_UTC(TS) TS,DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,TIPO,VALIDO,DESCRIPCION,ANIO,MES,DIA,HORA,MINUTO,QC_FLAG,QC_DETAIL FROM DCP_DATOS WHERE DCP_ID='15AFD602' AND TS>=:s AND TS<=:e"+(' FOR UPDATE' if args.apply else ''),s=start,e=end)
                cols=[d[0] for d in q.description];rows=[dict(zip(cols,r)) for r in q]
                existing={(r['TS'],r['SENSOR_ID']):r for r in rows}
                if len(existing)!=len(rows):raise ValueError('Filas duplicadas')
                unmatched=[r for key,r in existing.items() if key not in samples]
                if any(r['VALOR'] is None or r['VALOR']>=-200 for r in unmatched):
                    raise ValueError('Lectura no recuperable requiere revisión individual')
                q.execute("SELECT DCP_ID,VARIABLE,SYS_EXTRACT_UTC(TS) TS,VALOR,TIPO FROM ULTIMAS_MEDICIONES WHERE DCP_ID='15AFD602'"+(' FOR UPDATE' if args.apply else ''))
                cols=[d[0] for d in q.description];summaries=[dict(zip(cols,r)) for r in q]
                report=dict(station='MX03',start=start,end=end,original_rows=rows,original_summaries=summaries,raw_messages=messages,unmatched=unmatched,
                    reconstructed=[(t,s,*v) for (t,s),v in sorted(samples.items())])
                json.dump(report,backup,default=lambda x:x.isoformat(),ensure_ascii=False,indent=2)
                backup.flush();os.fsync(backup.fileno())
                if args.apply:
                    updates=[];inserts=[];latest={}
                    for (t,s),(v,ok,var) in sorted(samples.items()):
                        note='Reprocesado MX03 desde trama SMN; '+('OK' if ok else 'Faltante o fuera de rango')
                        if (t,s) in existing:
                            updates.append((v,ok,var,note,existing[(t,s)]['RID']))
                        else:
                            inserts.append((t,s,var,v,ok,note,t.year,t.month,t.day,t.hour,t.minute,var))
                        latest[var]=(t,v)
                    q.executemany('''UPDATE DCP_DATOS SET VALOR=:1,VALIDO=:2,VARIABLE=:3,DESCRIPCION=:4,QC_FLAG=NULL,QC_DETAIL=NULL WHERE ROWID=CHARTOROWID(:5) AND DCP_ID='15AFD602' ''',updates)
                    q.executemany('''INSERT INTO DCP_DATOS (TS,DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,VALIDO,DESCRIPCION,ANIO,MES,DIA,HORA,MINUTO,TIPO) VALUES (:1,'15AFD602','MX03',:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12)''',inserts)
                    for r in unmatched:
                        note=f"Decodificación incorrecta ({r['VALOR']}); sin muestra original a esta hora. MX03 2026-09-29"
                        q.execute("UPDATE DCP_DATOS SET VALOR=NULL,VALIDO=0,DESCRIPCION=:n,QC_DETAIL=:n WHERE ROWID=CHARTOROWID(:r) AND DCP_ID='15AFD602'",n=note,r=r['RID'])
                    for var,(t,v) in latest.items():
                        aliases={var}|{r['VARIABLE'] for r in summaries if normalize(r['VARIABLE'])==normalize(var)}
                        for alias in aliases:
                            q.execute('''MERGE INTO ULTIMAS_MEDICIONES u USING (SELECT :var VARIABLE FROM DUAL) x
                            ON (u.DCP_ID='15AFD602' AND u.VARIABLE=x.VARIABLE)
                            WHEN MATCHED THEN UPDATE SET TS=:t,VALOR=:v WHERE u.TS<=:t
                            WHEN NOT MATCHED THEN INSERT(DCP_ID,VARIABLE,TS,VALOR,TIPO) VALUES('15AFD602',:var,:t,:v,:var)''',var=alias,t=t,v=v)
                    c.commit()
                print(json.dumps(dict(applied=args.apply,messages=len(messages),samples=len(samples),updated=sum(k in existing for k in samples),inserted=sum(k not in existing for k in samples),unmatched=len(unmatched))))
        except Exception:
            c.rollback();raise
        finally:
            c.close()


if __name__=='__main__':main()
