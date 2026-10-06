"""Apply only GS300 catalog repairs proven by repeated raw frames.

Creates an exclusive backup before any commit and verifies current Oracle
values under row locks. Dry-run unless --apply is supplied.
"""
import argparse
import json
import os
from pathlib import Path

from gs300_catalog import assign_positions, validate_words
from telemetry_decoders import gs300_words


CASES = {
    'AGRAN07000': {
        'dcp': '15F02456', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': {'0011'},
        'orders': {'0006': (4, 5), '0007': (5, 4)},
    },
    'BOMBA07016': {
        'dcp': '15F1D628', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {},
        'deactivate': {'0004', '0005', '0011', '0014', '0015'},
    },
    'MMDETAB015': {
        'dcp': '1563D3FA', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {'0901': (60, 10)}, 'deactivate': {'0905'},
    },
    'MOJOTAB012': {
        'dcp': '1A542096', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': set(),
    },
    'ZACATAB006': {
        'dcp': '1A54150C', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': set(),
    },
    'SALCUA061Q': {
        'dcp': 'AC5300B4', 'old_range': '01:00:01', 'new_range': '01:00:00',
        'periods': {}, 'deactivate': set(),
    },
    'ZANAP27117': {
        'dcp': '15647136', 'old_range': '02:00:00', 'new_range': '02:00:00',
        'periods': {'0906': (60, 10)}, 'deactivate': set(),
    },
    'TAMUSLP024': {
        'dcp': '15D5C18A', 'old_range': '03:00:00', 'new_range': '03:00:00',
        'periods': {'0013': (60, 10)}, 'deactivate': set(),
    },
    'TLAHUA033Q': {
        'dcp': 'AC5267A8', 'old_range': '01:00:00', 'new_range': '01:00:00',
        'periods': {'1001': (2, 1)}, 'deactivate': set(),
    },
    'CARTER021Q': {
        'dcp': 'AC5224A2', 'old_range': '01:00:00', 'new_range': '01:00:00',
        'periods': {'1001': (2, 1)}, 'deactivate': set(),
    },
    'MADETAM034': {
        'dcp': '15AF76FA', 'old_range': '03:00:00', 'new_range': '03:00:00',
        'periods': {}, 'deactivate': {'0016', '0017'},
    },
    'ARCOCHIA11': {
        'dcp': '1A549318', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {'0900': (10, 60)}, 'deactivate': set(),
    },
    'CHAPTAB001': {
        'dcp': '1A53912C', 'old_range': '01:00:00', 'new_range': '01:00:00',
        'periods': {},
        'deactivate': {'0036', '0041', '0046', '0047', '0048', '0049'},
    },
    'QUIOCHIA19': {
        'dcp': '1A5470EA', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {'0900': (10, 60)}, 'deactivate': set(),
        'orders': {'0031': (2, 1), '0900': (3, 2), '0001': (1, 3)},
    },
    'MACUTAB017': {
        'dcp': '15B077F6', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {'0011': (10, 60), '0900': (10, 60)},
        'deactivate': set(),
    },
    '000000GR02': {
        'dcp': '15B7C64C', 'old_range': '02:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': {'0016', '0910', '0905'},
    },
    'GUACAXXXXX': {
        'dcp': '15F2F7CA', 'old_range': '02:00:00', 'new_range': '02:00:00',
        'periods': {'0014': (60, 10), '0015': (60, 10)},
        'deactivate': set(),
    },
    'SITAL07000': {
        'dcp': '15F041B0', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': {'0021', '0022', '0023'},
    },
    'EESCA07186': {
        'dcp': '15F052C6', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': {'0021', '0022', '0023'},
    },
    'CHACCHIA05': {
        'dcp': '159FE5E8', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {'0900': (10, 60)}, 'deactivate': set(),
        'orders': {'0900': (6, 8), '0048': (7, 6), '0049': (8, 7)},
    },
    'TONAL07168': {
        'dcp': '15F2C250', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {},
        'deactivate': {
            '0005', '0006', '0007', '0008', '0009',
            '0011', '0012', '0013', '0014', '0015',
        },
    },
    'SILTCHIA23': {
        'dcp': '157144F2', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': {'0903', '0904'},
    },
    '0000000G21': {
        'dcp': '15C8131A', 'old_range': '01:00:00', 'new_range': '02:00:00',
        'periods': {}, 'deactivate': set(),
    },
}


def evidence(audit, code, case):
    entry = next((item for dcp, item in audit.items()
                  if dcp == case['dcp'] and
                  (item.get('station') or {}).get('id_asignado') == code), None)
    if not entry:
        raise ValueError(f'{code}: no está en la auditoría')
    sensors = []
    for original in entry['sensors']:
        sensor = dict(original)
        number = sensor['numero_sensor']
        if number in case['deactivate']:
            continue
        if number in case['periods']:
            old, new = case['periods'][number]
            if float(sensor['periodo']) != old:
                raise ValueError(f'{code}/{number}: periodo de evidencia cambió')
            sensor['periodo'] = new
        if number in case.get('orders', {}):
            old, new = case['orders'][number]
            if float(sensor['orden']) != old:
                raise ValueError(f'{code}/{number}: orden de evidencia cambió')
            sensor['orden'] = new
        sensors.append(sensor)
    coverage = int(case['new_range'][:2]) * 60 + int(case['new_range'][3:5])
    mapped = assign_positions(sensors, coverage)
    checked = 0
    for frame in entry['frames']:
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        if len(payload) < 4 or payload[1:3] != b'B1':
            continue
        words = gs300_words(payload[4:])
        validate_words(words, mapped, station=code)
        checked += 1
    if checked < 3:
        raise ValueError(f'{code}: sólo {checked} tramas verificables')
    return {'frames': checked, 'expected_words': sum(
        len(sensor['posiciones']) for sensor in mapped)}


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--station', action='append', choices=sorted(CASES))
    args = parser.parse_args()
    selected = args.station or list(CASES)
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    proofs = {code: evidence(audit, code, CASES[code]) for code in selected}
    dsn = os.environ['ORACLE_DSN']
    original = []
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                           password=os.environ['ORACLE_CATALOG_PASSWORD'],
                           dsn=dsn) as connection:
        connection.call_timeout = 60000
        cursor = connection.cursor()
        for code in selected:
            case = CASES[code]
            lock = ' FOR UPDATE' if args.apply else ''
            cursor.execute(
                '''SELECT G.ID,G.IDESTACION,G.RANGOTRANSMISION,G.DECODIFICADOR
                   FROM DATOSGOES G JOIN ESTACION E ON E.ID=G.IDESTACION
                   WHERE E.IDASIGNADO=:code AND TRIM(G.IDSATELITAL)=:dcp''' + lock,
                code=code, dcp=case['dcp'])
            rows = cursor.fetchall()
            if len(rows) != 1:
                raise ValueError(f'{code}: DATOSGOES ausente o duplicado')
            goes_id, station_id, old_range, decoder = rows[0]
            if str(old_range) != case['old_range'] or str(decoder).strip() != 'GS300':
                raise ValueError(f'{code}: DATOSGOES cambió desde la auditoría')
            sensor_rows = []
            affected = (set(case['periods']) | set(case['deactivate']) |
                        set(case.get('orders', {})))
            for sensor_id in affected:
                cursor.execute(
                    '''SELECT ID,PERIODOMUESTRA,ACTIVO,ORDEN FROM SENSOR
                       WHERE IDESTACION=:station AND TRIM(NUMEROSENSOR)=:sensor''' + lock,
                    station=station_id, sensor=sensor_id)
                found = cursor.fetchall()
                if len(found) != 1 or found[0][2] != 1:
                    raise ValueError(f'{code}/{sensor_id}: configuración cambió')
                old_period = found[0][1]
                new_period = old_period
                if sensor_id in case['periods']:
                    expected, new_period = case['periods'][sensor_id]
                    if float(old_period) != expected:
                        raise ValueError(f'{code}/{sensor_id}: periodo cambió')
                old_order = found[0][3]
                new_order = old_order
                if sensor_id in case.get('orders', {}):
                    expected, new_order = case['orders'][sensor_id]
                    if float(old_order) != expected:
                        raise ValueError(f'{code}/{sensor_id}: orden cambió')
                sensor_rows.append({
                    'id': found[0][0], 'sensor_id': sensor_id,
                    'old_period': old_period, 'new_period': new_period,
                    'old_active': found[0][2],
                    'new_active': 0 if sensor_id in case['deactivate'] else 1,
                    'old_order': old_order, 'new_order': new_order,
                })
            original.append({
                'code': code, 'dcp': case['dcp'], 'goes_id': goes_id,
                'old_range': old_range, 'new_range': case['new_range'],
                'sensors': sensor_rows, 'proof': proofs[code],
            })
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump({'applied': args.apply, 'original': original}, stream,
                      ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if args.apply:
            for item in original:
                cursor.execute(
                    '''UPDATE DATOSGOES SET RANGOTRANSMISION=:new
                       WHERE ID=:id AND RANGOTRANSMISION=:old''',
                    new=item['new_range'], id=item['goes_id'], old=item['old_range'])
                if cursor.rowcount != 1:
                    raise ValueError(f"{item['code']}: no se actualizó DATOSGOES")
                for sensor in item['sensors']:
                    cursor.execute(
                        '''UPDATE SENSOR SET PERIODOMUESTRA=:period,ACTIVO=:active,
                               ORDEN=:sensor_order
                           WHERE ID=:id AND PERIODOMUESTRA=:old_period
                             AND ACTIVO=:old_active AND ORDEN=:old_order''',
                        period=sensor['new_period'], active=sensor['new_active'],
                        sensor_order=sensor['new_order'], old_order=sensor['old_order'],
                        id=sensor['id'], old_period=sensor['old_period'],
                        old_active=sensor['old_active'])
                    if cursor.rowcount != 1:
                        raise ValueError(
                            f"{item['code']}/{sensor['sensor_id']}: no se actualizó")
            connection.commit()
    print(json.dumps({'applied': args.apply, 'stations': original},
                     ensure_ascii=False, default=str, indent=2))


if __name__ == '__main__':
    main()
