"""Recover only SO06 voltage sensors from raw text, with an exclusive backup.

Default is dry-run. --apply updates negative values at exactly matching sample
timestamps and inserts absent raw samples. Unrecoverable negative voltages
become NULL/invalid with the original value in DESCRIPCION and the backup.
Never deletes rows, changes dates, applies abs(), or interpolates gaps.
"""
import argparse
import datetime as dt
import json
import math
import os
import unicodedata

from telemetry_decoders import payload_family, text_records

DCP = '15B6A150'
SENSORS = {'0011': (10, 'voltaje_de_batería', 17),
           '0012': (11, 'voltaje_del_panel_solar', 1000)}
STATIONS = {
    'SO06': ('15B6A150', SENSORS, 'default', 12),
    'HI03': ('15B651D4', SENSORS, 'default', 12),
    'NY02': ('15B26174', SENSORS, 'default', 12),
    'NY03': ('15B6D7C0', SENSORS, 'default', 12),
    'MC38': ('15B0B2E8', {'0012': (0, 'voltaje_de_batería', 17),
                        '0013': (1, 'voltaje_del_panel_solar', 1000)}, '4', 2),
    'QR15': ('15F5E688', {'0010': (10, 'voltaje_de_batería', 17)}, 'default', 12),
}


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower().replace('_', ' '))
                   if not unicodedata.combining(c))


def decode_voltages(messages, cutoff, end, dcp=DCP, sensors=None, table='default', count=12):
    sensors = SENSORS if sensors is None else sensors
    samples, skipped = {}, []
    for received, raw in messages:
        if raw[:8] != dcp or len(raw) < 37:
            raise ValueError('Cabecera inválida')
        payload = raw[37:].encode('latin1')
        if payload_family(payload) == 'notice':
            skipped.append(received.isoformat())
            continue
        if payload_family(payload) not in ('text', 'table_text'):
            raise ValueError('Cambió el formato: no reprocesar automáticamente')
        records = text_records(payload, received, 'SMN_ver2')
        for stamp, values in records:
            if values.table != table:
                continue
            stamp = stamp.replace(tzinfo=None)  # All times explicitly UTC below.
            if len(values) != count or stamp.minute % 10 or stamp.second:
                raise ValueError('Columnas o periodo diferentes del perfil')
            if not dt.timedelta(0) <= received - stamp <= dt.timedelta(hours=3):
                raise ValueError('Muestra fuera de ventana temporal confirmada')
            if not cutoff <= stamp <= end:
                continue
            for sensor, (column, _, maximum) in sensors.items():
                value = values[column]
                if not math.isfinite(value) or not 0 <= value <= maximum:
                    raise ValueError(f'Voltaje crudo no verificable: {stamp}/{sensor}/{value}')
                key = (stamp, sensor)
                if key in samples and samples[key] != value:
                    raise ValueError('Mensajes originales contradictorios para '+str(key))
                samples[key] = value
    if not samples:
        raise ValueError('No hay voltajes recuperables')
    return samples, skipped


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--station', choices=sorted(STATIONS), default='SO06')
    parser.add_argument('--backup', required=True, help='New JSON file, never overwritten')
    args = parser.parse_args()
    DCP, SENSORS, table, count = STATIONS[args.station]
    sensor_ids = ','.join("'"+sensor+"'" for sensor in SENSORS)  # Fixed allowlist above.
    end = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cutoff = end - dt.timedelta(days=7)
    with open(args.backup, 'x', encoding='utf-8') as backup:
        c = oracledb.connect(user=os.environ['ORACLE_USER'],
            password=os.environ['ORACLE_PASSWORD'], dsn=os.environ['ORACLE_DSN'])
        c.call_timeout = 60000
        try:
            with c.cursor() as q:
                q.execute("ALTER SESSION SET TIME_ZONE='UTC'")
                q.execute('''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
                    FROM DCP_HEADERS WHERE DCP_ID=:d AND TIMESTAMP_MSG>=:start_time
                    AND TIMESTAMP_MSG<=:end_time AND RAW_MESSAGE IS NOT NULL
                    ORDER BY TIMESTAMP_MSG''', d=DCP,
                    start_time=cutoff-dt.timedelta(hours=3), end_time=end)
                messages = q.fetchall()
                samples, skipped = decode_voltages(messages, cutoff, end, DCP, SENSORS, table, count)
                q.execute(f'''SELECT ROWIDTOCHAR(ROWID) RID,SYS_EXTRACT_UTC(TS) TS,
                    DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,TIPO,VALIDO,DESCRIPCION,
                    ANIO,MES,DIA,HORA,MINUTO,QC_FLAG,QC_DETAIL
                    FROM DCP_DATOS WHERE DCP_ID=:d AND SENSOR_ID IN ({sensor_ids})
                    AND TS>=:start_time AND TS<=:end_time''' + (' FOR UPDATE' if args.apply else ''),
                    d=DCP,start_time=cutoff,end_time=end)
                columns = [x[0] for x in q.description]
                rows = [dict(zip(columns, row)) for row in q]
                existing = {}
                for row in rows:
                    key = row['TS'], row['SENSOR_ID']
                    if key in existing:
                        raise ValueError('Duplicados en DCP_DATOS: '+str(key))
                    existing[key] = row
                q.execute('''SELECT DCP_ID,VARIABLE,SYS_EXTRACT_UTC(TS) TS,VALOR,TIPO
                    FROM ULTIMAS_MEDICIONES WHERE DCP_ID=:d''' + (' FOR UPDATE' if args.apply else ''),d=DCP)
                cols = [x[0] for x in q.description]
                summaries = [dict(zip(cols, row)) for row in q]
                updates, inserts, conflicts = [], [], []
                for (stamp, sensor), value in sorted(samples.items()):
                    row = existing.get((stamp, sensor))
                    if row is None:
                        inserts.append((stamp,sensor,value))
                    elif row['VALOR'] is None or row['VALOR'] < 0:
                        updates.append((row['RID'],stamp,sensor,value))
                    elif row['VALOR'] is None or not math.isclose(row['VALOR'],value,abs_tol=1e-4):
                        conflicts.append((stamp,sensor,row['VALOR'],value))
                unmatched = [r for k,r in existing.items() if r['VALOR'] is not None and r['VALOR']<0 and k not in samples]
                if conflicts:
                    raise ValueError('Existen valores no negativos diferentes del crudo; revisar antes de escribir')
                report = dict(dcp=DCP,station=args.station,cutoff_utc=cutoff,end_utc=end,
                    original_data=rows,original_summaries=summaries,raw_messages=messages,
                    updates=updates,inserts=inserts,unmatched_negative=unmatched,
                    skipped_notice=skipped)
                json.dump(report,backup,default=lambda x:x.isoformat(),ensure_ascii=False,indent=2)
                backup.flush()
                os.fsync(backup.fileno())
                if args.apply:
                    q.execute("SELECT NULLABLE FROM USER_TAB_COLUMNS WHERE TABLE_NAME='DCP_DATOS' AND COLUMN_NAME='VALOR'")
                    if q.fetchone() != ('Y',):
                        raise ValueError('VALOR no permite datos faltantes; no se aplicó la reparación')
                    note=f'Reprocesado {args.station} desde trama SMN_ver2; reparación voltajes 2026-09-29'
                    for rid,stamp,sensor,value in updates:
                        q.execute('''UPDATE DCP_DATOS SET VALOR=:v,VALIDO=1,
                            DESCRIPCION=:note,QC_FLAG=NULL,QC_DETAIL=NULL
                            WHERE ROWID=CHARTOROWID(:rid) AND DCP_ID=:d AND (VALOR<0 OR VALOR IS NULL)''',
                            v=value,note=note,rid=rid,d=DCP)
                        if q.rowcount != 1:
                            raise ValueError('La fila cambió durante la reparación')
                    for row in unmatched:
                        reason=f"Voltaje negativo inválido ({row['VALOR']}); sin muestra cruda a esta hora. {args.station} 2026-09-29"
                        q.execute('''UPDATE DCP_DATOS SET VALOR=NULL,VALIDO=0,
                            DESCRIPCION=:note,QC_DETAIL=:note WHERE ROWID=CHARTOROWID(:rid)
                            AND DCP_ID=:d AND VALOR<0''',note=reason,rid=row['RID'],d=DCP)
                        if q.rowcount != 1:
                            raise ValueError('La fila sin respaldo cambió durante la reparación')
                    q.executemany('''INSERT INTO DCP_DATOS
                        (TS,DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,TIPO,VALIDO,
                         DESCRIPCION,ANIO,MES,DIA,HORA,MINUTO)
                        VALUES (:1,:2,:3,:4,:5,:6,:7,1,:8,:9,:10,:11,:12,:13)''',
                        [(t,DCP,args.station,s,SENSORS[s][1],v,SENSORS[s][1],note,
                          t.year,t.month,t.day,t.hour,t.minute) for t,s,v in inserts])
                    for sensor,(_,variable,_) in SENSORS.items():
                        t=max(stamp for stamp,s in samples if s==sensor)
                        value=samples[(t,sensor)]
                        aliases={variable}|{r['VARIABLE'] for r in summaries
                            if normalize(r['VARIABLE'])==normalize(variable)}
                        for alias in aliases:
                            q.execute('''MERGE INTO ULTIMAS_MEDICIONES u
                                USING (SELECT :d DCP_ID,:var VARIABLE FROM DUAL) src
                                ON (u.DCP_ID=src.DCP_ID AND u.VARIABLE=src.VARIABLE)
                                WHEN MATCHED THEN UPDATE SET u.TS=:t,u.VALOR=:v,u.TIPO=:typ
                                  WHERE u.TS<=:t
                                WHEN NOT MATCHED THEN INSERT (DCP_ID,VARIABLE,TS,VALOR,TIPO)
                                  VALUES (:d,:var,:t,:v,:typ)''',d=DCP,var=alias,t=t,v=value,typ=variable)
                    c.commit()
                print(json.dumps(dict(station=args.station,applied=args.apply,raw_messages=len(messages),
                    raw_samples=len(samples),updated=len(updates),inserted=len(inserts),
                    unmatched_negative=len(unmatched),skipped_notice=len(skipped),
                    latest={s: max((t.isoformat(),v) for (t,k),v in samples.items() if k==s)
                            for s in SENSORS}),ensure_ascii=False))
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()


if __name__ == '__main__':
    main()
