"""Reconcile explicit OTT wire metadata against catalog; dry-run by default.

Never guesses names, units, scales or channel order. Requires at least three
consistent complete recent OTA messages, exact physical channel count, unique
Sensor.Orden, valid internal dates. B1 and ambiguous layouts are not changed.
"""
import argparse
import ast
import datetime as dt
import json
import os
from pathlib import Path
from telemetry_decoders import ott_blocks


def plans(report, convert):
    result=[]
    for d,e in report.items():
        sensors=sorted([s for s in e['sensors'] if not s.get('calculada')],key=lambda s:float(s['orden'] or 0))
        orders=[s['orden'] for s in sensors]
        ids=[s['numero_sensor'] for s in sensors]
        if not sensors or None in orders or len(set(orders))!=len(orders) or len(set(ids))!=len(ids):continue
        layouts=[]
        for f in e['frames']:
            if f['family']=='notice':continue
            if f['family']!='ota':layouts=[];break
            try:
                blocks=ott_blocks(f['raw'][37:].encode('latin1'),convert,dt.datetime.fromisoformat(f['received']))
            except ValueError:layouts=[];break
            if len(blocks)!=len(sensors):layouts=[];break
            layouts.append(tuple((i,len(v)) for i,v in blocks))
        if len(layouts)<3 or len(set(layouts))!=1:continue
        layout=layouts[0]
        if any(i<=0 or n<=0 for i,n in layout):continue
        # A common, explicit duration in every block supports a range correction.
        coverages={i*n for i,n in layout}
        if len(coverages)!=1:continue
        coverage=coverages.pop()
        period_changes=[dict(sensor=s['numero_sensor'],old=s['periodo'],new=i) for s,(i,n) in zip(sensors,layout) if s['periodo']!=i]
        old=e['station']['rango_transmision']
        if old!=coverage or period_changes:
            result.append(dict(dcp=d,code=e['station']['id_asignado'],old_range=old,new_range=coverage,period_changes=period_changes,evidence=len(layouts)))
    return result


def main():
    import oracledb
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true');p.add_argument('--backup',required=True)
    args=p.parse_args()
    report=json.loads(Path('ott-audit-20260930.json').read_text())
    tree=ast.parse(Path('mycloud_all_timescale.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ConvertFrom6BitsTo8Bits')
    scope={};exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated','exec'),scope)
    plan=plans(report,scope[node.name]);original=[]
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],password=os.environ['ORACLE_CATALOG_PASSWORD'],dsn=os.environ['ORACLE_DSN']) as c:
        c.call_timeout=60000;q=c.cursor()
        for x in plan:
            q.execute('SELECT G.ID,G.IDESTACION,G.RANGOTRANSMISION,G.DECODIFICADOR FROM DATOSGOES G JOIN ESTACION E ON E.ID=G.IDESTACION WHERE TRIM(G.IDSATELITAL)=:d AND E.IDASIGNADO=:code'+(' FOR UPDATE' if args.apply else ''),d=x['dcp'],code=x['code'])
            rows=q.fetchall()
            if len(rows)!=1 or rows[0][3]!='OTTBinario':raise ValueError('GOES cambió o duplicado')
            gid,eid,rango,decoder=rows[0]
            from gs300_catalog import duration_minutes
            if duration_minutes(rango)!=x['old_range']:raise ValueError('Rango cambió')
            originals=[]
            for change in x['period_changes']:
                q.execute('SELECT ID,PERIODOMUESTRA FROM SENSOR WHERE IDESTACION=:e AND NUMEROSENSOR=:s AND ACTIVO=1'+(' FOR UPDATE' if args.apply else ''),e=eid,s=change['sensor'])
                rows=q.fetchall()
                if len(rows)!=1 or float(rows[0][1])!=change['old']:raise ValueError('Sensor cambió o duplicado')
                originals.append(dict(id=rows[0][0],old=rows[0][1],new=change['new']))
            original.append(dict(goes_id=gid,range=rango,sensors=originals,plan=x))
        with open(args.backup,'x') as f:
            os.chmod(args.backup,0o600)
            json.dump(dict(original=original,evidence=report),f,default=str,ensure_ascii=False)
            f.flush();os.fsync(f.fileno())
        if args.apply:
            for row in original:
                x=row['plan'];n=x['new_range'];r=f'{n//60:02d}:{n%60:02d}:00'
                if x['old_range']!=n:
                    q.execute('UPDATE DATOSGOES SET RANGOTRANSMISION=:r WHERE ID=:i AND RANGOTRANSMISION=:old',r=r,i=row['goes_id'],old=row['range'])
                    if q.rowcount!=1:raise ValueError('No se actualizó rango')
                for s in row['sensors']:
                    q.execute('UPDATE SENSOR SET PERIODOMUESTRA=:v WHERE ID=:i AND PERIODOMUESTRA=:old',v=s['new'],i=s['id'],old=s['old'])
                    if q.rowcount!=1:raise ValueError('No se actualizó sensor')
            c.commit()
    print(json.dumps(dict(applied=args.apply,plans=plan),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
