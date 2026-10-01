"""Audit/correct DatosGOES format labels and primary channel from LRGS evidence.

Does not rewrite measurements or guess sensor mappings. Requires three distinct
messages and a consistent format/channel in the last twelve measurements.
Never modifies alarm channel, speed, satellite, sampling or sensor definitions.
"""
import argparse
import collections
import datetime as dt
import json
import os
from telemetry_decoders import payload_family, gs300_words, text_records


def wire_decoder(payload, received):
    family=payload_family(payload)
    if family=='pseudobinary_b':
        gs300_words(payload.strip(b' \r\n')[4:])
        return 'GS300'
    if family=='ota':return 'OTTBinario'
    if family=='table_text':
        records=text_records(payload,received,'audit')
        if all(values.table in ('2','4') for _,values in records):return 'SMN'
    if family=='named':return 'GS'
    if family=='cila':return 'CILA_Text'
    # Plain textual columns cannot uniquely distinguish SMN/Vaisala variants.
    return None


def proposal(row, frames, duplicate=False):
    entry=dict(original=row,frames=frames,changes={},notes=[])
    if duplicate:
        entry['notes'].append('DCP duplicado en catálogo');return entry
    unique={f['utc']:f for f in frames}
    for stamp in unique:
        variants={(f['decoder'],f['channel']) for f in frames if f['utc']==stamp}
        if len(variants)>1:
            entry['notes'].append('Recepciones contradictorias para la misma fecha');return entry
    if len(unique)<3:
        entry['notes'].append('Menos de tres recepciones distintas');return entry
    frames=list(unique.values())
    formats={f['decoder'] for f in frames}
    if len(formats)==1 and None not in formats:
        proposed=next(iter(formats))
        compatible_text = proposed=='SMN' and row['decoder'] in ('SMN','SMN_ver2','VAISALA_Protocol_Text')
        if proposed!=row['decoder'] and not compatible_text:entry['changes']['decoder']=proposed
    else:entry['notes'].append('Formato ambiguo o discordante; no se cambia decoder')
    channels={f['channel'] for f in frames}
    dates=[dt.datetime.fromisoformat(f['utc']) for f in frames]
    if len(channels)==1 and None not in channels and max(dates)-min(dates)>=dt.timedelta(hours=2):
        channel=next(iter(channels))
        if channel==row['alarm'] and channel!=row['primary']:
            entry['notes'].append('Canal observado coincide con alarma; no se cambia primario')
        elif channel!=row['primary']:entry['changes']['primary']=channel
    else:entry['notes'].append('Canal discordante/insuficiente; no se cambia primario')
    return entry


def main():
    import oracledb
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true');p.add_argument('--backup',required=True)
    args=p.parse_args();dsn=os.environ['ORACLE_DSN']
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],password=os.environ['ORACLE_CATALOG_PASSWORD'],dsn=dsn) as cat, oracledb.connect(user=os.environ['ORACLE_USER'],password=os.environ['ORACLE_PASSWORD'],dsn=dsn) as hist:
        cat.call_timeout=hist.call_timeout=60000;q=cat.cursor()
        q.execute('SELECT G.ID,E.IDASIGNADO,E.NOMBRE,TRIM(G.IDSATELITAL),G.DECODIFICADOR,G.CANALPRIMARIO,G.CANALALARMA FROM DATOSGOES G JOIN ESTACION E ON E.ID=G.IDESTACION WHERE E.ACTIVO=1 AND E.GOES=1')
        rows=[dict(zip(('id','code','name','dcp','decoder','primary','alarm'),r)) for r in q]
        dup=collections.Counter(r['dcp'] for r in rows)
        h=hist.cursor();h.execute('''SELECT DCP_ID,SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE FROM (
        SELECT DCP_ID,TIMESTAMP_MSG,RAW_MESSAGE,ROW_NUMBER() OVER(PARTITION BY DCP_ID ORDER BY TIMESTAMP_MSG DESC) RN
        FROM DCP_HEADERS WHERE TIMESTAMP_MSG>SYSTIMESTAMP-INTERVAL '7' DAY AND TIMESTAMP_MSG<=SYSTIMESTAMP
        AND RAW_MESSAGE IS NOT NULL AND INSTR(RAW_MESSAGE,'Missing message from')=0 AND INSTR(RAW_MESSAGE,'SATLINK DATA BUFFER EMPTY')=0) WHERE RN<=12''')
        messages=collections.defaultdict(list)
        for d,t,raw in h:
            if len(raw)<37 or raw[:8].strip()!=d:continue
            payload=raw[37:].encode('latin1')
            try:decoder=wire_decoder(payload,t)
            except (ValueError,UnicodeError):decoder=None
            ch=raw[26:29];channel=int(ch) if ch.isdigit() and int(ch)>0 else None
            messages[d].append(dict(utc=t.isoformat(),decoder=decoder,channel=channel,raw=raw))
        entries=[proposal(r,messages[r['dcp']],dup[r['dcp']]>1) for r in rows]
        changes=[e for e in entries if e['changes']]
        if args.apply:
            for e in changes:
                r=e['original'];q.execute('SELECT DECODIFICADOR,CANALPRIMARIO,CANALALARMA FROM DATOSGOES WHERE ID=:i FOR UPDATE',i=r['id'])
                if q.fetchone()!=(r['decoder'],r['primary'],r['alarm']):raise ValueError('DatosGOES cambió durante auditoría')
        with open(args.backup,'x') as f:
            os.chmod(args.backup,0o600)
            json.dump(dict(applied_requested=args.apply,entries=entries),f,ensure_ascii=False,indent=2,default=str);f.flush();os.fsync(f.fileno())
        if args.apply:
            for e in changes:
                r=e['original'];new=e['changes']
                q.execute('UPDATE DATOSGOES SET DECODIFICADOR=:decoder,CANALPRIMARIO=:primary WHERE ID=:i',decoder=new.get('decoder',r['decoder']),primary=new.get('primary',r['primary']),i=r['id'])
                if q.rowcount!=1:raise ValueError('Fila no actualizada')
                q.execute('SELECT DECODIFICADOR,CANALPRIMARIO FROM DATOSGOES WHERE ID=:i',i=r['id'])
                if q.fetchone()!=(new.get('decoder',r['decoder']),new.get('primary',r['primary'])):raise ValueError('Verificación fallida')
            cat.commit()
        for e in changes:
            r=e['original'];print(r['code'],r['name'],'ANTES',r['decoder'],r['primary'],'CAMBIOS',e['changes'])
        print(dict(applied=args.apply,stations=len(rows),changed=len(changes),decoders=sum('decoder' in e['changes'] for e in changes),channels=sum('primary' in e['changes'] for e in changes)))


if __name__=='__main__':main()
