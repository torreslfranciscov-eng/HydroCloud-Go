"""Read-only audit of recent raw messages, decoder/catalog and saved data."""
import ast
import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
from gs300_catalog import load_stations,load_sensors,assign_positions,validate_words
from telemetry_decoders import (validate_decoder_payload,payload_family,gs300_payload_words,
    ott_blocks,ott_sensors,text_records,record_sensors,named_records,named_sensor_channels)


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-frames', action='store_true', help='Check every received message in the last 24 hours')
    args = parser.parse_args()
    dsn=os.environ['ORACLE_DSN']
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],password=os.environ['ORACLE_CATALOG_PASSWORD'],dsn=dsn) as c:
        stations=load_stations(c);sensors=load_sensors(c)
    tree=ast.parse(Path('mycloud_all_timescale.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ConvertFrom6BitsTo8Bits')
    scope={};exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated','exec'),scope)
    result={}
    with oracledb.connect(user=os.environ['ORACLE_USER'],password=os.environ['ORACLE_PASSWORD'],dsn=dsn) as c:
        c.call_timeout=60000;q=c.cursor()
        q.execute('''SELECT DCP_ID,SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE FROM (
          SELECT DCP_ID,TIMESTAMP_MSG,RAW_MESSAGE,ROW_NUMBER() OVER(PARTITION BY DCP_ID ORDER BY TIMESTAMP_MSG DESC) RN
          FROM DCP_HEADERS WHERE TIMESTAMP_MSG>SYSTIMESTAMP-INTERVAL '1' DAY AND TIMESTAMP_MSG<=SYSTIMESTAMP
          AND RAW_MESSAGE IS NOT NULL AND INSTR(RAW_MESSAGE,'Missing message from')=0 AND INSTR(RAW_MESSAGE,'SATLINK DATA BUFFER EMPTY')=0)''' + ('' if args.all_frames else ' WHERE RN<=12'))
        for d,t,raw in q:
            station=stations.get(d);code=station['id_asignado'] if station else None
            e=result.setdefault(d,dict(station=station,sensors=sensors.get(code,[]),frames=[],saved=None))
            f=dict(received=t.isoformat(),raw=raw,family=payload_family(raw[37:].encode('latin1')))
            try:
                if not station:raise ValueError('No existe configuración GOES activa válida')
                if raw[:8]!=d:raise ValueError('DCP de encabezado discordante')
                p=raw[37:].encode('latin1');decoder=station['decoder'];ss=e['sensors']
                validate_decoder_payload(decoder,p,station=code)
                if decoder=='GS300':
                    mapped=assign_positions([dict(s) for s in ss],station['rango_transmision'])
                    validate_words(gs300_payload_words(p, station=code), mapped,
                                   station=code)
                elif decoder=='OTTBinario':
                    blocks=ott_blocks(p,scope[node.name],t);ott_sensors(code,blocks,ss,station['rango_transmision'])
                elif decoder in ('SMN','SMN_ver2','VAISALA_Protocol_Text'):
                    for stamp,v in text_records(p,t,decoder):record_sensors(code,v,ss)
                elif decoder in ('GS','CILA_Text'):
                    decoded=named_records(p,t,decoder=='CILA_Text')
                    mapped,rejected=named_sensor_channels(code,decoded,ss)
                    if rejected:f['rejected_channels']=rejected
                f['status']='compatible_partial' if f.get('rejected_channels') else 'compatible'
            except (ValueError,KeyError,UnicodeError) as exc:f['status']=str(exc)
            e['frames'].append(f)
        q.execute("SELECT DCP_ID,COUNT(*),MAX(SYS_EXTRACT_UTC(TS)),SUM(CASE WHEN VALIDO=0 THEN 1 ELSE 0 END) FROM DCP_DATOS WHERE TS>SYSTIMESTAMP-INTERVAL '1' DAY AND TS<=SYSTIMESTAMP GROUP BY DCP_ID")
        for d,n,t,bad in q:
            if d in result:result[d]['saved']=dict(rows=n,last=str(t),invalid=bad)
    with open('live-ingestion-audit.json','w') as f:
        os.chmod('live-ingestion-audit.json',0o600);json.dump(result,f,ensure_ascii=False,default=str,indent=2)
    counts=collections.Counter()
    report_rows=[]
    for d,e in result.items():
        statuses=collections.Counter(f['status'] for f in e['frames'])
        counts['transmitting']+=1
        counts['with_compatible_sample']+='compatible' in statuses
        counts['with_partial_sample']+='compatible_partial' in statuses
        counts['with_saved_data']+=e['saved'] is not None
        station=e['station'] or {}
        errors=[s for s in statuses if s not in ('compatible','compatible_partial')]
        rejected=sorted({ch+': '+reason for f in e['frames'] for ch,reason in f.get('rejected_channels',{}).items()})
        report_rows.append((station.get('id_asignado',d),station.get('nombre',''),station.get('decoder',''),len(e['frames']),statuses['compatible'],statuses['compatible_partial'],(e['saved'] or {}).get('rows',0),'; '.join(errors+rejected)))
        if 'compatible' not in statuses:
            station=e['station'] or {};print(station.get('id_asignado',d),station.get('decoder'),dict(statuses),'saved',e['saved'])
    print('SUMMARY',dict(counts))
    lines=['# Auditoría de ingesta — últimas 24 horas','',
           'Compatibilidad del parser local y del catálogo; no certifica calibración física ni igualdad de todas las mediciones con Oracle.',
           'Las filas guardadas se cuentan por fecha de medición; no prueban cuándo se insertaron. Un mensaje parcial conserva solo canales con identificador explícito en Sensor.',
           f"Modo: {'todas las tramas' if args.all_frames else 'hasta 12 por estación'}. Estaciones: {len(result)}. Tramas: {sum(len(e['frames']) for e in result.values())}.",
           '', '| Clave | Estación | Decoder | Tramas | Compatibles | Parciales | Filas en Oracle | Pendiente |',
           '|---|---|---|---:|---:|---:|---:|---|']
    for row in sorted(report_rows):
        lines.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in row)+' |')
    Path('INGESTA_AUDITORIA_20260930.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
