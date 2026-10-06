"""Replay verified SMN table-4 battery samples into Oracle.

The station/DCP inventory comes from the prior read-only SMN audit.  A series is
eligible only when it is unique and recent stored values already match the first
column of table 4, which certifies the channel without guessing from magnitude.
The command is read-only unless --apply is supplied and always creates an
exclusive, private JSON backup before any write.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os

from telemetry_decoders import MISSING, text_records

MAX_BATTERY_VOLTS = 30.0


def utc_naive(value):
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


def same_value(left, right):
    return left is not None and math.isclose(
        float(left), float(right), rel_tol=1e-6, abs_tol=1e-5
    )


def main():
    import oracledb

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', default='smn-audit-20260929.json')
    parser.add_argument('--backup', required=True)
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.days <= 14:
        raise ValueError('La ventana debe estar entre 1 y 14 días')

    inventory = json.load(open(args.inventory, encoding='utf-8'))['stations']
    station_by_dcp = {}
    invalid_inventory = []
    for item in inventory:
        code = str(item['code']).strip()
        dcp = str(item['dcp']).strip().upper()
        if not code or len(dcp) != 8:
            invalid_inventory.append({'code': code, 'dcp': dcp})
            continue
        if dcp in station_by_dcp:
            raise ValueError('DCP duplicado en inventario SMN')
        station_by_dcp[dcp] = code

    connection = oracledb.connect(
        user=os.environ['ORACLE_USER'],
        password=os.environ['ORACLE_PASSWORD'],
        dsn=os.environ['ORACLE_DSN'],
    )
    connection.call_timeout = 180000
    try:
        cursor = connection.cursor()
        cursor.execute("ALTER SESSION SET TIME_ZONE='UTC'")
        cursor.execute('SELECT SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM DUAL')
        end = utc_naive(cursor.fetchone()[0])
        start = end - dt.timedelta(days=args.days)

        samples = collections.defaultdict(lambda: collections.defaultdict(set))
        evidence = []
        cursor.execute(
            '''SELECT DCP_ID,SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
               FROM DCP_HEADERS
               WHERE TIMESTAMP_MSG BETWEEN :start_time AND :end_time
                 AND RAW_MESSAGE IS NOT NULL''',
            start_time=start, end_time=end,
        )
        for raw_dcp, received, raw in cursor:
            dcp = str(raw_dcp).strip().upper()
            code = station_by_dcp.get(dcp)
            raw = str(raw) if raw is not None else ''
            if not code or raw[:8].upper() != dcp:
                continue
            try:
                records = text_records(raw[37:].encode('latin1'), received, 'SMN')
            except (ValueError, UnicodeError):
                continue
            used = False
            for stamp, values in records:
                stamp = utc_naive(stamp)
                if (values.table == '4' and values and values[0] != MISSING
                        and math.isfinite(float(values[0])) and start <= stamp <= end):
                    samples[code][stamp].add(float(values[0]))
                    used = True
            if used:
                evidence.append({
                    'code': code,
                    'dcp': dcp,
                    'received': received,
                    'sha256': hashlib.sha256(raw.encode('latin1')).hexdigest(),
                    'raw_message': raw,
                })

        cursor.execute(
            '''SELECT ROWIDTOCHAR(ROWID),ID_ASIGNADO,DCP_ID,SENSOR_ID,VARIABLE,
                      SYS_EXTRACT_UTC(TS),VALOR,VALIDO,DESCRIPCION,TIPO,
                      QC_FLAG,QC_DETAIL
               FROM DCP_DATOS
               WHERE TS BETWEEN :start_time AND :end_time
                 AND LOWER(VARIABLE) LIKE '%bater%' ''',
            start_time=start, end_time=end,
        )
        stored = collections.defaultdict(list)
        for row in cursor:
            code = str(row[1]).strip() if row[1] is not None else ''
            dcp = str(row[2]).strip().upper() if row[2] is not None else ''
            if station_by_dcp.get(dcp) == code:
                stored[code].append(row)

        changes = []
        stations = []
        skipped = []
        recent_cutoff = end - dt.timedelta(hours=36)
        dcp_by_station = {code: dcp for dcp, code in station_by_dcp.items()}
        for code in sorted(samples):
            value_sets = samples[code]
            ambiguous = [stamp for stamp, values in value_sets.items() if len(values) != 1]
            raw_values = {
                stamp: next(iter(values)) for stamp, values in value_sets.items()
                if len(values) == 1
            }
            rows = stored.get(code, [])
            series = {(str(r[3]).strip(), str(r[4])) for r in rows}
            rows_by_time = collections.defaultdict(list)
            for row in rows:
                rows_by_time[utc_naive(row[5])].append(row)
            duplicate_times = [stamp for stamp, items in rows_by_time.items() if len(items) != 1]
            exact = [
                stamp for stamp, value in raw_values.items()
                if len(rows_by_time.get(stamp, [])) == 1
                and same_value(rows_by_time[stamp][0][6], value)
                and int(rows_by_time[stamp][0][7]) == 1
            ]
            reasons = []
            if ambiguous:
                reasons.append('tramas contradictorias')
            if len(series) != 1:
                reasons.append('serie de batería ausente o no unívoca')
            if duplicate_times:
                reasons.append('timestamps duplicados en DCP_DATOS')
            if len(exact) < 3 or sum(stamp >= recent_cutoff for stamp in exact) < 3:
                reasons.append('menos de tres coincidencias recientes de certificación')
            if any(
                value < 0 or value > MAX_BATTERY_VOLTS or not math.isfinite(value)
                for value in raw_values.values()
            ):
                reasons.append('primera columna de tabla 4 fuera de 0..30 V')
            if reasons:
                skipped.append({
                    'code': code, 'dcp': dcp_by_station[code],
                    'raw_samples': len(raw_values), 'stored_rows': len(rows),
                    'exact': len(exact), 'reasons': reasons,
                })
                continue

            sensor_id, variable = next(iter(series))
            template = max(
                (row for row in rows if utc_naive(row[5]) in exact),
                key=lambda row: utc_naive(row[5]),
            )
            tipo = str(template[9]) if template[9] is not None else variable
            station_changes = []
            for stamp, value in sorted(raw_values.items()):
                existing = rows_by_time.get(stamp, [])
                if existing and same_value(existing[0][6], value) and int(existing[0][7]) == 1:
                    continue
                before = existing[0] if existing else None
                item = {
                    'code': code, 'dcp': dcp_by_station[code],
                    'sensor_id': sensor_id, 'variable': variable, 'tipo': tipo,
                    'timestamp': stamp, 'value': value, 'before': before,
                }
                changes.append(item)
                station_changes.append(item)
            stations.append({
                'code': code, 'dcp': dcp_by_station[code], 'sensor_id': sensor_id,
                'raw_samples': len(raw_values), 'certifying_matches': len(exact),
                'updates': sum(item['before'] is not None for item in station_changes),
                'inserts': sum(item['before'] is None for item in station_changes),
                'latest_timestamp': max(raw_values),
                'latest_value': raw_values[max(raw_values)],
                'variable': variable, 'tipo': tipo,
            })

        summary_rows = []
        for item in stations:
            cursor.execute(
                '''SELECT ROWIDTOCHAR(ROWID),VARIABLE,SYS_EXTRACT_UTC(TS),VALOR,TIPO
                   FROM ULTIMAS_MEDICIONES
                   WHERE DCP_ID=:dcp AND VARIABLE=:variable''',
                dcp=item['dcp'], variable=next(
                    change['variable'] for change in changes
                    if change['code'] == item['code']
                ) if item['updates'] + item['inserts'] else '',
            )
            summary_rows.extend((item['code'], item['dcp'], *row) for row in cursor)

        fd = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as backup:
            json.dump({
                'created_utc': dt.datetime.now(dt.timezone.utc),
                'window_start': start, 'window_end': end,
                'inventory': args.inventory,
                'invalid_inventory': invalid_inventory, 'stations': stations,
                'skipped': skipped, 'changes': changes,
                'latest_before': summary_rows, 'evidence': evidence,
            }, backup, default=str, ensure_ascii=False, indent=2)
            backup.flush()
            os.fsync(backup.fileno())
        print('Respaldo verificado; iniciando DML' if args.apply else 'Respaldo de simulación verificado', flush=True)

        updates = inserts = 0
        if args.apply:
            note = 'Reprocesado SMN tabla 4: voltaje de batería verificado por DCP y timestamp'
            update_rows = [{
                'value': item['value'], 'note': note,
                'row_id': item['before'][0], 'dcp': item['dcp'],
                'sensor_id': item['sensor_id'],
                'old_value': item['before'][6],
                'old_valid': int(item['before'][7]),
            } for item in changes if item['before']]
            if update_rows:
                cursor.executemany(
                    '''UPDATE DCP_DATOS
                       SET VALOR=:value,VALIDO=1,DESCRIPCION=:note,
                           QC_FLAG=NULL,QC_DETAIL=NULL
                       WHERE ROWID=CHARTOROWID(:row_id)
                         AND DCP_ID=:dcp AND SENSOR_ID=:sensor_id
                         AND VALIDO=:old_valid
                         AND (VALOR=:old_value OR (VALOR IS NULL AND :old_value IS NULL))''',
                    update_rows,
                )
                updates = cursor.rowcount
                if updates != len(update_rows):
                    raise ValueError('Una o más filas cambiaron durante la reparación')
                print(f'Actualizaciones preparadas: {updates}', flush=True)

            insert_rows = []
            for item in changes:
                if item['before']:
                    continue
                stamp = item['timestamp']
                insert_rows.append({
                    'stamp': stamp, 'dcp': item['dcp'], 'code': item['code'],
                    'sensor_id': item['sensor_id'], 'variable': item['variable'],
                    'value': item['value'], 'note': note, 'tipo': item['tipo'],
                    'year': stamp.year, 'month': stamp.month, 'day': stamp.day,
                    'hour': stamp.hour, 'minute': stamp.minute,
                })
            if insert_rows:
                cursor.executemany(
                    '''INSERT INTO DCP_DATOS
                       (TS,DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,VALIDO,
                        DESCRIPCION,TIPO,ANIO,MES,DIA,HORA,MINUTO)
                       VALUES
                       (:stamp,:dcp,:code,:sensor_id,:variable,:value,1,
                        :note,:tipo,:year,:month,:day,:hour,:minute)''',
                    insert_rows,
                )
                inserts = cursor.rowcount
                if inserts != len(insert_rows):
                    raise ValueError('No se insertaron todas las muestras reconstruidas')
                print(f'Inserciones preparadas: {inserts}', flush=True)

            cursor.execute(
                '''SELECT DCP_ID,SENSOR_ID,SYS_EXTRACT_UTC(TS),VALOR,VALIDO
                   FROM DCP_DATOS
                   WHERE TS BETWEEN :start_time AND :end_time
                     AND LOWER(VARIABLE) LIKE '%bater%' ''',
                start_time=start, end_time=end,
            )
            observed = collections.defaultdict(list)
            for dcp, sensor_id, stamp, value, valid in cursor:
                observed[(str(dcp).strip().upper(), str(sensor_id).strip(), utc_naive(stamp))].append((value, valid))
            for item in changes:
                verified = observed[(item['dcp'], item['sensor_id'], item['timestamp'])]
                if (len(verified) != 1 or int(verified[0][1]) != 1
                        or not same_value(verified[0][0], item['value'])):
                    raise ValueError('Falló verificación previa al commit')
            print('Verificación previa al commit completada', flush=True)
            connection.commit()

        print(json.dumps({
            'applied': args.apply, 'eligible_stations': len(stations),
            'skipped_stations': len(skipped),
            'invalid_inventory': len(invalid_inventory),
            'certifying_matches': sum(x['certifying_matches'] for x in stations),
            'updates_planned': sum(x['updates'] for x in stations),
            'inserts_planned': sum(x['inserts'] for x in stations),
            'updates_applied': updates, 'inserts_applied': inserts,
        }, ensure_ascii=False))
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == '__main__':
    main()
