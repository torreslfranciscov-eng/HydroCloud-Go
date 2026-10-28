"""Read-only SMN audit. Writes only local JSON/Markdown evidence reports."""
import collections
import datetime as dt
import json
import os
from pathlib import Path
import oracledb
from gs300_catalog import load_sensors
from telemetry_decoders import text_records, payload_family, profile


def main():
    dsn=os.environ['ORACLE_DSN']
    a=oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],password=os.environ['ORACLE_CATALOG_PASSWORD'],dsn=dsn)
    q=a.cursor()
    q.execute("select e.IDASIGNADO,e.NOMBRE,g.IDSATELITAL from HYDROCLOUD.ESTACION e join HYDROCLOUD.DATOSGOES g on g.IDESTACION=e.ID where trim(g.DECODIFICADOR)='SMN' and e.ACTIVO=1 and e.GOES=1 order by e.IDASIGNADO")
    stations=q.fetchall();ss=load_sensors(a);a.close()
    b=oracledb.connect(user=os.environ['ORACLE_USER'],password=os.environ['ORACLE_PASSWORD'],dsn=dsn)
    b.call_timeout=60000;q=b.cursor();q.execute("ALTER SESSION SET TIME_ZONE='UTC'")
    results=[]
    for code,name,dcp in stations:
        sensors=ss.get(code,[])
        voltages={s['numero_sensor'] for s in sensors if 'voltaje' in s['nombre'].lower()}
        entry=dict(code=code,name=name,dcp=dcp,profile=bool(profile(code)),frames=[],data=[],negative_voltages=[],same_time_evidence=[])
        q.execute("select sys_extract_utc(timestamp_msg),raw_message from dcp_headers where dcp_id=:d and timestamp_msg>systimestamp-interval '7' day and raw_message is not null order by timestamp_msg desc fetch first 3 rows only",d=dcp)
        for received,raw in q:
            p=raw[37:].encode('latin1');f=dict(received=str(received),family=payload_family(p))
            try:
                records=text_records(p,received,'SMN')
                f['layouts']=sorted(set((v.table,len(v)) for _,v in records))
            except (ValueError,UnicodeError) as e:f['error']=str(e)
            entry['frames'].append(f)
        q.execute("select sensor_id,count(*),sum(case when valor<0 then 1 else 0 end),min(valor),max(valor),max(sys_extract_utc(ts)) from dcp_datos where dcp_id=:d and ts>systimestamp-interval '7' day group by sensor_id",d=dcp)
        for s,n,neg,low,high,t in q:
            row=dict(sensor=s,count=n,negative=neg,minimum=low,maximum=high,latest=str(t))
            entry['data'].append(row)
            if s in voltages and neg:entry['negative_voltages'].append(row)
        if entry['negative_voltages']:
            q.execute("select sys_extract_utc(ts),sensor_id,valor from dcp_datos where dcp_id=:d and ts>systimestamp-interval '7' day and valor<0 order by ts desc",d=dcp)
            negative=[(t,s,v) for t,s,v in q if s in voltages]
            if negative:
                target=negative[0][0]
                q.execute('select sys_extract_utc(timestamp_msg),raw_message from dcp_headers where dcp_id=:d and timestamp_msg>=:t and timestamp_msg<:finish and raw_message is not null order by timestamp_msg',d=dcp,t=target,finish=target+dt.timedelta(hours=3))
                for received,raw in q:
                    try:records=text_records(raw[37:].encode('latin1'),received,'SMN')
                    except (ValueError,UnicodeError):continue
                    for stamp,values in records:
                        if stamp.replace(tzinfo=None)==target and values.table=='4':
                            entry['same_time_evidence'].append(dict(time=str(target),table='4',raw_values=list(values),stored_negative=[(s,v) for t,s,v in negative if t==target]))
        results.append(entry)
        if len(results)%40==0:print('Audited',len(results),flush=True)
    b.close()
    report=dict(checked_utc=dt.datetime.now(dt.timezone.utc).isoformat(),window_days=7,stations=results)
    with open('smn-audit-20260929.json','x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    affected=[r for r in results if r['negative_voltages']]
    evidenced=[r for r in affected if any(e['raw_values'] and all(v>=0 for v in e['raw_values']) for e in r['same_time_evidence'])]
    noframes=[r for r in results if not r['frames']]
    summary=dict(total=len(results),with_frames=len(results)-len(noframes),negative_voltage_stations=len(affected),same_time_positive_table4=len(evidenced),negative_rows=sum(x['negative'] for r in affected for x in r['negative_voltages']),with_profiles=[r['code'] for r in results if r['profile']],no_frames=[r['code'] for r in noframes],negative_without_table4_evidence=[r['code'] for r in affected if r not in evidenced])
    print(json.dumps(summary,ensure_ascii=False))
    print('LAYOUTS',dict(collections.Counter(str(sorted({tuple(l) for f in r['frames'] for l in f.get('layouts',[])})) for r in results if r['frames'])))
    lines=['# Auditoría SMN — 29/09/2026','',f"Ventana: últimos 7 días. Estaciones activas GOES con decoder SMN: {len(results)}.",'',
           'Solo lectura. Se revisaron hasta 3 tramas recientes por estación y se buscó evidencia de tabla 4 a la misma hora del último voltaje negativo. Una firma compatible no certifica por sí sola la asignación de canales.','',
           '| Clave | Estación | DCP | Filas de voltaje negativas | Tramas recientes | Tabla 4 positiva a misma hora | Perfil incorporado |',
           '|---|---|---|---:|---:|---|---|']
    for r in results:
        lines.append(f"| {r['code']} | {r['name']} | {r['dcp']} | {sum(x['negative'] for x in r['negative_voltages'])} | {len(r['frames'])} | {'Sí' if r in evidenced else 'No comprobada'} | {'Sí' if r['profile'] else 'No'} |")
    with open('SMN_AUDITORIA_20260929.md','x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')


if __name__=='__main__':main()
