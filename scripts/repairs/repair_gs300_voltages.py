"""Backed-up, explicit repair of verified voltage channels only (7 days)."""
import argparse
import datetime as dt
import json
import os
from gs300_catalog import load_sensors, assign_positions, validate_words
from telemetry_decoders import gs300_words, scaled_gs300_value, payload_family, align
from repair_so06_voltages import normalize

CASES={'RADIOCO019':('AC5081AE',60,{'2001'}),'RIOFTAM005':('15AD6078',180,{'0012','0013'})}


def main():
    import oracledb
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--station',choices=CASES,required=True)
    p.add_argument('--backup',required=True)
    p.add_argument('--apply',action='store_true')
    args=p.parse_args();dcp,coverage,selected=CASES[args.station]
    end=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None);start=end-dt.timedelta(days=7)
    dsn=os.environ['ORACLE_DSN']
    a=oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],password=os.environ['ORACLE_CATALOG_PASSWORD'],dsn=dsn)
    try:sensors=assign_positions(load_sensors(a)[args.station],coverage)
    finally:a.close()
    with open(args.backup,'x',encoding='utf-8') as f:
        c=oracledb.connect(user=os.environ['ORACLE_USER'],password=os.environ['ORACLE_PASSWORD'],dsn=dsn)
        c.call_timeout=60000
        try:
            with c.cursor() as q:
                q.execute("ALTER SESSION SET TIME_ZONE='UTC'")
                q.execute('SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE FROM DCP_HEADERS WHERE DCP_ID=:d AND TIMESTAMP_MSG>=:s AND TIMESTAMP_MSG<=:e AND RAW_MESSAGE IS NOT NULL ORDER BY TIMESTAMP_MSG',d=dcp,s=start,e=end)
                messages=q.fetchall();samples={};rejected=[]
                for received,raw in messages:
                    payload=raw[37:].encode('latin1').strip(b' \r\n')
                    if payload_family(payload)=='notice':continue
                    try:
                        if raw[:8]!=dcp or payload_family(payload)!='pseudobinary_b':raise ValueError('Trama incompatible')
                        words=gs300_words(payload[4:]);validate_words(words,sensors)
                    except ValueError as exc:
                        rejected.append((str(received),str(exc)));continue
                    for sensor in sensors:
                        if sensor['numero_sensor'] not in selected:continue
                        for i,pos in enumerate(sensor['posiciones']):
                            stamp=align(received-dt.timedelta(minutes=i*sensor['periodo']),sensor['periodo'])
                            if not start<=stamp<=end:continue
                            value,valid,note=scaled_gs300_value(words[pos],sensor)
                            entry=(value,int(valid),note,sensor['nombre'].lower().replace(' ','_'))
                            key=stamp,sensor['numero_sensor']
                            if key in samples and samples[key]!=entry:raise ValueError('Tramas contradictorias: '+str(key))
                            samples[key]=entry
                if not samples:raise ValueError('Sin muestras verificables')
                ids=','.join("'"+s+"'" for s in sorted(selected))
                q.execute(f'''SELECT ROWIDTOCHAR(ROWID) RID,SYS_EXTRACT_UTC(TS) TS,SENSOR_ID,VARIABLE,VALOR,VALIDO,DESCRIPCION,QC_FLAG,QC_DETAIL FROM DCP_DATOS WHERE DCP_ID=:d AND SENSOR_ID IN ({ids}) AND TS>=:s AND TS<=:e'''+(' FOR UPDATE' if args.apply else ''),d=dcp,s=start,e=end)
                columns=[x[0] for x in q.description];rows=[dict(zip(columns,r)) for r in q]
                existing={(r['TS'],r['SENSOR_ID']):r for r in rows}
                if len(existing)!=len(rows):raise ValueError('Duplicados')
                q.execute('SELECT VARIABLE,SYS_EXTRACT_UTC(TS) TS,VALOR,TIPO FROM ULTIMAS_MEDICIONES WHERE DCP_ID=:d'+(' FOR UPDATE' if args.apply else ''),d=dcp)
                columns=[x[0] for x in q.description];summary=[dict(zip(columns,r)) for r in q]
                json.dump(dict(station=args.station,dcp=dcp,start=start,end=end,original_rows=rows,original_summary=summary,messages=messages,rejected=rejected,reconstructed=[(t,s,*v) for (t,s),v in sorted(samples.items())]),f,ensure_ascii=False,default=lambda x:x.isoformat(),indent=2)
                f.flush();os.fsync(f.fileno())
                if args.apply:
                    latest={}
                    for (t,s),(v,ok,note,var) in sorted(samples.items()):
                        note='Reprocesado GS300 Sensor.Orden: '+note
                        if (t,s) in existing:
                            q.execute('UPDATE DCP_DATOS SET VALOR=:v,VALIDO=:ok,DESCRIPCION=:n,QC_FLAG=NULL,QC_DETAIL=NULL WHERE ROWID=CHARTOROWID(:rid) AND DCP_ID=:d',v=v,ok=ok,n=note,rid=existing[(t,s)]['RID'],d=dcp)
                            if q.rowcount!=1:raise ValueError('Fila cambió')
                        else:
                            q.execute('''INSERT INTO DCP_DATOS(TS,DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,VALIDO,DESCRIPCION,TIPO,ANIO,MES,DIA,HORA,MINUTO) VALUES(:t,:d,:code,:s,:var,:v,:ok,:n,:var,:y,:m,:day,:h,:minute)''',t=t,d=dcp,code=args.station,s=s,var=var,v=v,ok=ok,n=note,y=t.year,m=t.month,day=t.day,h=t.hour,minute=t.minute)
                        if ok and v is not None:latest[var]=(t,v)
                    for var,(t,v) in latest.items():
                        aliases={var}|{r['VARIABLE'] for r in summary if normalize(r['VARIABLE'])==normalize(var)}
                        for alias in aliases:
                            q.execute('''MERGE INTO ULTIMAS_MEDICIONES u USING(SELECT :d DCP_ID,:var VARIABLE FROM DUAL) x ON(u.DCP_ID=x.DCP_ID AND u.VARIABLE=x.VARIABLE)
                            WHEN MATCHED THEN UPDATE SET TS=:t,VALOR=:v WHERE u.TS<=:t
                            WHEN NOT MATCHED THEN INSERT(DCP_ID,VARIABLE,TS,VALOR,TIPO) VALUES(:d,:var,:t,:v,:var)''',d=dcp,var=alias,t=t,v=v)
                    c.commit()
                print(json.dumps(dict(station=args.station,applied=args.apply,samples=len(samples),updates=sum(k in existing for k in samples),inserts=sum(k not in existing for k in samples),invalid=sum(not v[1] for v in samples.values()),rejected_messages=len(rejected))))
        except Exception:
            c.rollback();raise
        finally:c.close()


if __name__=='__main__':main()
