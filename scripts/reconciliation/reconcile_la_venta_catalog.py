"""Resolve AC522A70 in favor of its verified 22-LA VENTA entry.

Atlas contains the same stale duplicate as Oracle, but its LA VENTA coordinates
match the NESDIS/DADDS entry for AC522A70.  PRESA TARANGO keeps GPRS service.
"""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words, payload_family


DCP = 'AC522A70'
OWNER = 'LVENTA022Q'
STALE = 'PTARAN077Q'
DADDS_COORDINATES = (19.3334, -99.3107)


def prove_wire_format(connection):
    cursor = connection.cursor()
    cursor.execute(
        """SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
           FROM DCP_HEADERS WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(30,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
             AND INSTR(RAW_MESSAGE,'SATLINK DATA BUFFER EMPTY')=0
           ORDER BY TIMESTAMP_MSG""", dcp=DCP)
    evidence = []
    for received, raw in cursor:
        if raw[:8] != DCP:
            raise ValueError('LA VENTA: DCP discordante en trama')
        payload = raw[37:].encode('latin1')
        if payload_family(payload) != 'pseudobinary_b':
            raise ValueError('LA VENTA: familia de trama inesperada')
        words = gs300_payload_words(payload, station=OWNER)
        if len(words) != 62:
            raise ValueError('LA VENTA: se esperaban 62 palabras GS300')
        battery, temperature = words[-2:]
        if battery is not None and not 1000 <= battery <= 1700:
            raise ValueError('LA VENTA: escala de batería no comprobada')
        if temperature is not None and not -2000 <= temperature <= 5000:
            raise ValueError('LA VENTA: escala de temperatura no comprobada')
        evidence.append((received, battery, temperature))
    if len(evidence) < 24:
        raise ValueError('LA VENTA: evidencia reciente insuficiente')
    return {'frames': len(evidence), 'word_count': 62, 'tail_scale': 2,
            'first': evidence[0], 'last': evidence[-1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read('config.ini')
    source = config['oracle_cloud']
    with oracledb.connect(user=source['user'], password=source['password'],
                          dsn=source['dsn']) as history:
        proof = prove_wire_format(history)

    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                          password=os.environ['ORACLE_CATALOG_PASSWORD'],
                          dsn=source['dsn']) as catalog:
        cursor = catalog.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            """SELECT E.ID,E.IDASIGNADO,E.NOMBRE,E.GOES,E.GPRS,E.ACTIVO,
                      E.LATITUD,E.LONGITUD,G.ID,TRIM(G.IDSATELITAL),
                      G.PRIMERATRANSMISION,G.INTERVALOTRANSMISION,
                      G.RANGOTRANSMISION,TRIM(G.DECODIFICADOR)
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO IN (:owner,:stale)
               ORDER BY E.IDASIGNADO""" + lock,
            owner=OWNER, stale=STALE)
        stations = cursor.fetchall()
        by_code = {row[1]: row for row in stations}
        if set(by_code) != {OWNER, STALE} or len(stations) != 2:
            raise ValueError('LA VENTA: catálogo duplicado cambió')
        if any(row[9] != DCP or row[13] != 'GS300' for row in stations):
            raise ValueError('LA VENTA: DCP o decoder cambió')
        owner, stale = by_code[OWNER], by_code[STALE]
        if (owner[3:6] != (1, 1, 1) or
                abs(float(owner[6]) - DADDS_COORDINATES[0]) > 0.0001 or
                abs(float(owner[7]) - DADDS_COORDINATES[1]) > 0.0001):
            raise ValueError('LA VENTA: identidad o coordenadas no coinciden')
        if stale[3:6] != (1, 1, 1):
            raise ValueError('PRESA TARANGO: estado GOES/GPRS cambió')

        cursor.execute(
            """SELECT S.ID,TRIM(S.NUMEROSENSOR),S.PUNTODECIMAL,
                      S.PERIODOMUESTRA,S.ORDEN,S.ACTIVO,S.VISIBLE
               FROM SENSOR S JOIN ESTACION E ON E.ID=S.IDESTACION
               WHERE E.IDASIGNADO=:station ORDER BY S.ORDEN""" + lock,
            station=OWNER)
        sensors = cursor.fetchall()
        if ([row[1] for row in sensors] != ['1001', '2001', '2002'] or
                [float(row[3]) for row in sensors] != [1.0, 60.0, 60.0] or
                any(row[5:7] != (1, 1) for row in sensors)):
            raise ValueError('LA VENTA: sensores cambiaron')
        decimals = {row[1]: int(row[2]) for row in sensors}
        if decimals not in ({'1001': 2, '2001': 1, '2002': 1},
                            {'1001': 2, '2001': 2, '2002': 2}):
            raise ValueError('LA VENTA: decimales inesperados')

        backup = {'applied': args.apply, 'dcp': DCP, 'stations': stations,
                  'owner_sensors': sensors, 'proof': proof,
                  'decision': {'owner': OWNER,
                    'atlas_result': 'duplicate',
                    'source': 'NESDIS/DADDS metadata: 22 LA VENTA',
                    'coordinates': DADDS_COORDINATES,
                    'presa_tarango_keeps_gprs': True}}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            cursor.execute(
                """UPDATE SENSOR SET PUNTODECIMAL=2
                   WHERE IDESTACION=:station_id
                     AND TRIM(NUMEROSENSOR) IN ('2001','2002')
                     AND PUNTODECIMAL IN (1,2)""", station_id=owner[0])
            if cursor.rowcount != 2:
                raise ValueError('LA VENTA: no se actualizaron las escalas')
            cursor.execute(
                """UPDATE ESTACION SET GOES=0
                   WHERE ID=:station_id AND GOES=1 AND GPRS=1 AND ACTIVO=1""",
                station_id=stale[0])
            if cursor.rowcount != 1:
                raise ValueError('PRESA TARANGO: no se desactivó GOES residual')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'dcp': DCP,
        'goes_owner': OWNER, 'disabled_stale_goes': STALE,
        'owner_decimals': {'1001': 2, '2001': 2, '2002': 2},
        'proof': proof}, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
