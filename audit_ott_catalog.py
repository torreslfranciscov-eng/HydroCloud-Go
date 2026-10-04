"""Read-only OTT catalog/wire audit; never imports the ingestion application."""
import ast
import argparse
import collections
import json
import os
import struct
from pathlib import Path
from gs300_catalog import load_sensors, load_stations
from telemetry_decoders import ott_blocks, ott_sensors, payload_family


def main():
    import oracledb
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measurements-only',action='store_true')
    parser.add_argument('--output',default='ott-audit-20260930.json')
    args=parser.parse_args()
    dsn = os.environ['ORACLE_DSN']
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'], password=os.environ['ORACLE_CATALOG_PASSWORD'], dsn=dsn) as c:
        stations = {d:s for d,s in load_stations(c).items() if s['decoder']=='OTTBinario'}
        sensors = load_sensors(c)
    tree = ast.parse(Path('mycloud_all_timescale.py').read_text())
    node = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ConvertFrom6BitsTo8Bits')
    scope = {}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated','exec'),scope)
    convert = scope[node.name]
    result = {d:dict(station=s,sensors=sensors.get(s['id_asignado'],[]),frames=[]) for d,s in stations.items()}
    with oracledb.connect(user=os.environ['ORACLE_USER'], password=os.environ['ORACLE_PASSWORD'], dsn=dsn) as c:
        c.call_timeout=60000
        q=c.cursor()
        binds={f'd{i}':d for i,d in enumerate(stations)}
        ids=','.join(':'+k for k in binds)
        measurement_filter = " AND INSTR(raw_message,'Missing message from')=0 AND INSTR(raw_message,'SATLINK DATA BUFFER EMPTY')=0" if args.measurements_only else ''
        q.execute(f'''select dcp_id,sys_extract_utc(timestamp_msg),raw_message from
        (select dcp_id,timestamp_msg,raw_message,row_number() over(partition by dcp_id order by timestamp_msg desc) rn
        from dcp_headers where timestamp_msg>systimestamp-interval '7' day and dcp_id in ({ids}) {measurement_filter}) where rn<=12''',binds)
        for d,t,raw in q:
            entry=result[d];s=entry['station'];payload=(raw or '')[37:].encode('latin1')
            frame=dict(received=str(t),raw=raw,family=payload_family(payload))
            try:
                blocks=ott_blocks(payload,convert,t)
                frame['blocks']=[dict(interval=i,count=len(v)) for i,v in blocks]
                ott_sensors(s['id_asignado'],blocks,entry['sensors'],s['rango_transmision'])
                frame['status']='accepted'
            except (ValueError,KeyError) as e:frame['status']=str(e)
            if frame['family']=='ota':
                data=convert(payload.rstrip(b' \r\n')[5:]);pos=4;layout=[]
                while pos+4<=len(data):
                    interval,count=struct.unpack_from('<hh',data,pos)
                    width=6 if interval==0 else 2
                    if not 0<=interval<=1000 or not 0<count<=1000 or pos+4+width*count>len(data):break
                    pos+=4+width*count;layout.append((interval,count))
                frame['observed_layout']=layout;frame['tail']=data[pos:].hex()
            entry['frames'].append(frame)
    path=Path(args.output)
    with path.open('w') as f:
        os.chmod(path,0o600);json.dump(result,f,ensure_ascii=False,indent=2,default=str)
    counts=collections.Counter()
    for d,e in result.items():
        states=collections.Counter(f['status'] for f in e['frames'])
        counts['stations']+=1
        counts['no_headers']+=not bool(states)
        counts['any_accepted']+='accepted' in states
        if states:print(e['station']['id_asignado'],e['station']['nombre'],dict(states), 'layouts', sorted({str(f.get('observed_layout')) for f in e['frames']}), 'tails',sorted({f.get('tail','') for f in e['frames']}))
    print('TOTAL',dict(counts))


if __name__=='__main__':main()
