"""Export latest raw frames for stations without or with invalid battery data."""
import datetime as dt
import json
import os


DECODER_FAMILIES = {
    'GS300': {'pseudobinary_b'},
    'OTTBinario': {'ota'},
    'GS': {'named'},
    'CILA_Text': {'cila'},
    'SMN': {'table_text', 'text'},
    'SMN_ver2': {'table_text', 'text'},
    'VAISALA_Protocol_Text': {'table_text', 'text'},
}


def wire_format_validation(raw_message, decoder, station=None):
    from telemetry_decoders import payload_family, GS300_HEADERLESS_STATIONS

    payload = raw_message[37:].encode('latin1').strip(b' \r\n')
    family = payload_family(payload)
    if len(payload) >= 3 and payload[1:3] == b'B1':
        signature = payload[:3].decode('latin1')
    elif payload.startswith(b'OTA'):
        signature = 'OTA'
    elif len(payload) >= 4 and payload[1:4] == b'OTA':
        signature = payload[:4].decode('latin1')
    else:
        signature = repr(payload[:12].decode('latin1', errors='replace'))[1:-1]
    return {
        'configured_decoder': decoder,
        'observed_signature': signature,
        'observed_family': family,
        'decoder_matches_wire_family': (
            family in DECODER_FAMILIES.get(decoder, set()) or
            (decoder == 'GS300' and family == 'pseudobinary_headerless' and
             station in GS300_HEADERLESS_STATIONS)),
    }


def duration_minutes(value):
    hours, minutes, seconds = map(int, str(value).strip().split(':'))
    return hours * 60 + minutes + seconds / 60


def gs300_validation(entry):
    """Compare the wire word count with Oracle and decode proven MMDET layout."""
    from telemetry_decoders import gs300_payload_words

    payload = entry['raw_message'][37:].encode('latin1').strip(b' \r\n')
    words = gs300_payload_words(payload, station=entry['station'])
    coverage = duration_minutes(entry['goes_configuration']['transmission_range'])
    expected = 0
    expected_by_sensor = []
    for sensor in entry['sensors']:
        if int(sensor.get('active') or 0) != 1:
            continue
        if int(sensor.get('calculated') or 0) == 1:
            continue
        period = float(sensor['sample_period_minutes'])
        count = max(1, int(round(coverage / period)))
        expected += count
        expected_by_sensor.append({
            'sensor_id': sensor['sensor_id'],
            'expected_words': count,
        })
    auxiliary_words = 0
    try:
        from gs300_catalog import (GS300_AUXILIARY_SUFFIX,
                                   GS300_UNDEFINED_SUFFIX,
                                   valid_auxiliary_suffix)
        rule = GS300_AUXILIARY_SUFFIX.get(entry['station'])
        if (rule and len(words) == expected + rule['words'] and
                valid_auxiliary_suffix(entry['station'], words[expected:])):
            auxiliary_words = rule['words']
    except (KeyError, TypeError):
        pass
    undefined_words = 0
    try:
        configured_missing = GS300_UNDEFINED_SUFFIX.get(entry['station'], 0)
        if configured_missing and len(words) == expected - configured_missing:
            undefined_words = configured_missing
    except (KeyError, TypeError):
        pass
    validation = {
        'wire_format': 'pseudobinary_b_signed_18_bit',
        'observed_words': len(words),
        'catalog_expected_words': expected,
        'ignored_auxiliary_suffix_words': auxiliary_words,
        'undefined_trailing_words': undefined_words,
        'catalog_matches_wire': (len(words) + undefined_words ==
                                 expected + auxiliary_words),
        'catalog_expected_by_sensor': expected_by_sensor,
    }
    if entry['station'] != 'MMDETAB015' or len(words) != 72:
        return validation

    sensors = {item['sensor_id']: item for item in entry['sensors']}
    # The six contiguous 12-word blocks are unambiguous by decimal scale and
    # engineering range. 0905 would require a seventh block, which is absent.
    layout = ('0001', '0011', '0901', '0902', '0903', '0904')
    channels = []
    for index, sensor_id in enumerate(layout):
        sensor = sensors[sensor_id]
        raw_values = words[index * 12:(index + 1) * 12]
        divisor = 10 ** int(sensor['decimals'])
        values = [None if value is None else round(value / divisor, int(sensor['decimals']))
                  for value in raw_values]
        channels.append({
            'sensor_id': sensor_id,
            'name': sensor['name'],
            'raw_positions': [index * 12, (index + 1) * 12 - 1],
            'sample_period_minutes_in_wire': 10,
            'values_newest_to_oldest': values,
        })
    conflicts = []
    if coverage != 120:
        conflicts.append(
            'RANGOTRANSMISION does not match the 120 minutes carried by the wire.')
    if float(sensors['0901']['sample_period_minutes']) != 10:
        conflicts.append(
            '0901 battery period does not match its 10-minute wire spacing.')
    if int(sensors['0905'].get('active') or 0) == 1:
        conflicts.append(
            '0905 internal temperature is active but has no seventh wire block.')
    validation.update({
        'decoded_layout_status': (
            'wire_layout_catalog_consistent' if not conflicts
            else 'wire_layout_determined_catalog_inconsistent'
        ),
        'wire_channel_count': 6,
        'wire_samples_per_channel': 12,
        'wire_effective_coverage_minutes': 120,
        'decoded_channels': channels,
        'sensor_absent_from_wire': '0905',
        'catalog_conflicts': conflicts,
    })
    return validation


def main():
    import oracledb

    inventory = json.load(open('live-ingestion-audit.json', encoding='utf-8'))
    catalog = {str(dcp).strip().upper(): item for dcp, item in inventory.items()}
    connection = oracledb.connect(
        user=os.environ['ORACLE_USER'],
        password=os.environ['ORACLE_PASSWORD'],
        dsn=os.environ['ORACLE_DSN'],
    )
    catalog_connection = oracledb.connect(
        user=os.environ['ORACLE_CATALOG_USER'],
        password=os.environ['ORACLE_CATALOG_PASSWORD'],
        dsn=os.environ.get('ORACLE_CATALOG_DSN', os.environ['ORACLE_DSN']),
    )
    connection.call_timeout = 120000
    catalog_connection.call_timeout = 120000
    try:
        cursor = connection.cursor()
        cursor.execute("ALTER SESSION SET TIME_ZONE='UTC'")
        cursor.execute('SELECT SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM DUAL')
        checked = cursor.fetchone()[0]
        cursor.execute(
            '''SELECT TRIM(DCP_ID),TRIM(SENSOR_ID),NOMBRE
               FROM CATALOGO_SENSORES ORDER BY DCP_ID,SENSOR_ID'''
        )
        oracle_sensors = {}
        for key, sensor_id, name in cursor:
            oracle_sensors.setdefault(str(key).strip(), []).append({
                'sensor_id': str(sensor_id).strip(),
                'name': str(name).strip(),
            })

        catalog_cursor = catalog_connection.cursor()
        catalog_cursor.execute(
            '''SELECT TRIM(E.IDASIGNADO),TRIM(G.IDSATELITAL),E.NOMBRE,
                      G.RANGOTRANSMISION,G.INTERVALOTRANSMISION,
                      G.DECODIFICADOR,G.TRANSMITE,G.PRIMERATRANSMISION,
                      G.VENTANATRANSMISION,G.CANALPRIMARIO,G.VELOCIDAD,
                      G.CANALALARMA,G.VELOCIDADALARMA
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID'''
        )
        live_stations = {}
        for row in catalog_cursor:
            station_id = str(row[0]).strip()
            dcp = str(row[1]).strip().upper()
            item = {
                'station': station_id,
                'dcp': dcp,
                'name': str(row[2]).strip() if row[2] is not None else None,
                'transmission_range': row[3],
                'transmission_interval': row[4],
                'decoder': str(row[5]).strip() if row[5] is not None else None,
                'transmits': row[6],
                'first_transmission': row[7],
                'transmission_window': row[8],
                'primary_channel': row[9],
                'speed': row[10],
                'alarm_channel': row[11],
                'alarm_speed': row[12],
            }
            live_stations[dcp] = item
            live_stations[station_id.upper()] = item

        catalog_cursor.execute(
            '''SELECT TRIM(E.IDASIGNADO),TRIM(G.IDSATELITAL),
                      TRIM(S.NUMEROSENSOR),T.NOMBRE,S.PUNTODECIMAL,
                      S.PERIODOMUESTRA,S.VALORMINIMO,S.VALORMAXIMO,S.ORDEN,
                      U.ABREVIATURA,S.ACTIVO,S.VISIBLE,S.FUNCIONA,S.VALIDO,
                      S.MODOALMACENAMIENTO,S.TIPOGRAFICA,S.APLICACOTA,
                      S.ESPECIFICACION,T.ESCALCULADA
               FROM ESTACION E
               JOIN DATOSGOES G ON G.IDESTACION=E.ID
               JOIN SENSOR S ON S.IDESTACION=E.ID
               JOIN TIPOSENSOR T ON T.ID=S.IDTIPOSENSOR
               LEFT JOIN UNIDADMEDIDA U ON U.ID=S.IDUNIDADMEDIDA
               ORDER BY E.IDASIGNADO,S.ORDEN,S.NUMEROSENSOR'''
        )
        live_sensors = {}
        for row in catalog_cursor:
            station_id = str(row[0]).strip()
            dcp = str(row[1]).strip().upper()
            item = {
                'sensor_id': str(row[2]).strip(),
                'name': str(row[3]).strip(),
                'decimals': row[4],
                'sample_period_minutes': row[5],
                'minimum': row[6],
                'maximum': row[7],
                'order': row[8],
                'unit': str(row[9]).strip() if row[9] is not None else None,
                'active': row[10],
                'visible': row[11],
                'working': row[12],
                'valid': row[13],
                'storage_mode': row[14],
                'chart_type': row[15],
                'applies_offset': row[16],
                'specification': row[17],
                'calculated': row[18],
            }
            live_sensors.setdefault(dcp, []).append(item)
            live_sensors.setdefault(station_id.upper(), []).append(item)
        cursor.execute(
            '''SELECT DCP_ID,SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
               FROM DCP_HEADERS
               WHERE TIMESTAMP_MSG>=SYSTIMESTAMP-INTERVAL '24' HOUR
                 AND RAW_MESSAGE IS NOT NULL
               ORDER BY TIMESTAMP_MSG DESC'''
        )
        latest_raw = {}
        for raw_dcp, received, raw in cursor:
            dcp = str(raw_dcp).strip().upper()
            raw = str(raw)
            if dcp in catalog and raw[:8].upper() == dcp and dcp not in latest_raw:
                latest_raw[dcp] = (received, raw)

        cursor.execute(
            '''SELECT DCP_ID,ID_ASIGNADO,SENSOR_ID,VARIABLE,
                      SYS_EXTRACT_UTC(TS),VALOR,VALIDO,DESCRIPCION
               FROM (
                 SELECT D.*,ROW_NUMBER() OVER(
                   PARTITION BY UPPER(TRIM(DCP_ID)) ORDER BY TS DESC,ROWID DESC
                 ) RN
                 FROM DCP_DATOS D
                 WHERE TS>=SYSTIMESTAMP-INTERVAL '24' HOUR
                   AND LOWER(VARIABLE) LIKE '%bater%'
               ) WHERE RN=1'''
        )
        latest_battery = {
            str(row[0]).strip().upper(): row for row in cursor
            if str(row[0]).strip().upper() in latest_raw
        }

        def station_entry(dcp):
            station = catalog[dcp]['station']
            received, raw = latest_raw[dcp]
            station_id = str(station['id_asignado']).strip()
            live_station = live_stations.get(dcp, live_stations.get(station_id.upper()))
            entry = {
                'station': station_id,
                'name': (live_station or {}).get('name', station['nombre']),
                'dcp': dcp,
                'decoder': (live_station or {}).get('decoder', station['decoder']),
                'goes_configuration': live_station,
                'sensors': live_sensors.get(
                    dcp,
                    live_sensors.get(station_id.upper(), []),
                ),
                'oracle_catalog_sensors': oracle_sensors.get(
                    station_id,
                    oracle_sensors.get(dcp, []),
                ),
                'received_utc': received,
                'raw_message': raw,
            }
            entry['wire_format_validation'] = wire_format_validation(
                raw, entry['decoder'], station=entry['station'])
            if entry['decoder'] == 'GS300' and entry['goes_configuration']:
                try:
                    entry['decoder_validation'] = gs300_validation(entry)
                except (KeyError, TypeError, ValueError) as exc:
                    entry['decoder_validation'] = {'error': str(exc)}
            return entry

        without = []
        invalid = []
        for dcp in sorted(latest_raw):
            battery = latest_battery.get(dcp)
            entry = station_entry(dcp)
            if battery is None:
                without.append(entry)
                continue
            value, valid = battery[5], battery[6]
            if value is None or not 0 <= float(value) <= 30 or int(valid) != 1:
                entry['latest_battery'] = {
                    'sensor_id': str(battery[2]).strip(),
                    'variable': battery[3],
                    'timestamp_utc': battery[4],
                    'value': value,
                    'valid': valid,
                    'description': battery[7],
                }
                invalid.append(entry)

        output = {
            'checked_utc': checked,
            'window_hours': 24,
            'sensor_configuration_source': {
                'current_oracle_names': 'MYCLOUD_TS.CATALOGO_SENSORES',
                'full_configuration': (
                    'HYDROCLOUD.SENSOR + TIPOSENSOR + UNIDADMEDIDA'
                ),
                'transmission_configuration': 'HYDROCLOUD.DATOSGOES',
            },
            'without_recent_battery_count': len(without),
            'invalid_battery_count': len(invalid),
            'without_recent_battery': without,
            'invalid_battery': invalid,
        }
        path = 'TX_VOLTAJE_MENSAJES_CRUDOS_20261001.json'
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump(output, stream, default=str, ensure_ascii=False, indent=2)
        os.chmod(path, 0o600)
        print(json.dumps({
            'path': path,
            'without_recent_battery': len(without),
            'invalid_battery': len(invalid),
        }, ensure_ascii=False))
    finally:
        catalog_connection.close()
        connection.close()


if __name__ == '__main__':
    main()
