"""Correct two proven B1 decoder labels only; backup and dry-run by default."""
import argparse
import json
import os
from pathlib import Path
from gs300_catalog import load_sensors,assign_positions,validate_words
from telemetry_decoders import gs300_words,payload_family


def main():
    import oracledb
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true');p.add_argument('--backup',required=True)
    args=p.parse_args();audit=json.loads(Path('ott-audit-20260930.json').read_text())
    cases={'15F36052':'JONUT27028','15B00FB4':'CHICVER067'}
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],password=os.environ['ORACLE_CATALOG_PASSWORD'],dsn=os.environ['ORACLE_DSN']) as c:
        c.call_timeout=60000;sensors=load_sensors(c);q=c.cursor();original=[]
        for d,code in cases.items():
            e=audit[d];frames=[f for f in e['frames'] if f['family']!='notice']
            if len(frames)<3 or any(s.get('calculada') for s in sensors[code]):raise ValueError('Evidencia insuficiente o canales virtuales')
            ordered=assign_positions([dict(s,decoder='GS300') for s in sensors[code]],e['station']['rango_transmision'])
            for f in frames:
                raw=f['raw'];payload=raw[37:].encode('latin1').strip(b' \r\n')
                if raw[:8]!=d or payload_family(payload)!='pseudobinary_b':raise ValueError('Trama no B1')
                validate_words(gs300_words(payload[4:]),ordered)
            q.execute('SELECT G.ID,G.DECODIFICADOR FROM DATOSGOES G JOIN ESTACION E ON E.ID=G.IDESTACION WHERE TRIM(G.IDSATELITAL)=:d AND E.IDASIGNADO=:c'+(' FOR UPDATE' if args.apply else ''),d=d,c=code)
            rows=q.fetchall()
            if len(rows)!=1 or rows[0][1]!='OTTBinario':raise ValueError('Decoder cambió')
            original.append(dict(id=rows[0][0],old=rows[0][1],new='GS300',code=code,evidence=e))
        with open(args.backup,'x') as f:
            os.chmod(args.backup,0o600);json.dump(original,f,default=str,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        if args.apply:
            for r in original:
                q.execute('UPDATE DATOSGOES SET DECODIFICADOR=:v WHERE ID=:i AND DECODIFICADOR=:old',v=r['new'],i=r['id'],old=r['old'])
                if q.rowcount!=1:raise ValueError('Configuración cambió')
            c.commit()
        print(dict(applied=args.apply,stations=list(cases.values())))


if __name__=='__main__':main()
