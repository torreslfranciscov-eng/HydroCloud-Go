"""Resolve AC531D10 in favor of its verified 70-COATEPEC catalog entry.

The NESDIS/DADDS metadata identifies AC531D10 as 70 COATEPEC at the same
coordinates stored for COATEP070Q.  PABASO078Q remains available through its
independent GPRS configuration; only its stale GOES flag is disabled.
"""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import gs300_payload_words, payload_family


DCP = 'AC531D10'
COATEPEC = 'COATEP070Q'
ABASOLO = 'PABASO078Q'
DADDS_COORDINATES = (19.3850, -98.8478)


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
            raise ValueError('COATEPEC: DCP discordante en trama')
        payload = raw[37:].encode('latin1')
        if payload_family(payload) != 'pseudobinary_b':
            raise ValueError('COATEPEC: familia de trama inesperada')
        words = gs300_payload_words(payload, station=COATEPEC)
        if len(words) != 62:
            raise ValueError('COATEPEC: se esperaban 62 palabras GS300')
        battery, temperature = words[-2:]
        if battery is not None and not 1000 <= battery <= 1700:
            raise ValueError('COATEPEC: escala de batería no comprobada')
        if temperature is not None and not -1500 <= temperature <= 5000:
            raise ValueError('COATEPEC: escala de temperatura no comprobada')
        evidence.append((received, battery, temperature))
    if len(evidence) < 24:
        raise ValueError('COATEPEC: evidencia reciente insuficiente')
    return {
        'frames': len(evidence),
        'word_count': 62,
        'tail_scale': 2,
        'first': evidence[0],
        'last': evidence[-1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config.ini')
    source = config['oracle_cloud']
    dsn = source['dsn']
    with oracledb.connect(user=source['user'], password=source['password'],
                          dsn=dsn) as history:
        proof = prove_wire_format(history)

    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                          password=os.environ['ORACLE_CATALOG_PASSWORD'],
                          dsn=dsn) as catalog:
        cursor = catalog.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            """SELECT E.ID,E.IDASIGNADO,E.NOMBRE,E.GOES,E.GPRS,E.ACTIVO,
                      E.LATITUD,E.LONGITUD,G.ID,TRIM(G.IDSATELITAL),
                      G.PRIMERATRANSMISION,G.INTERVALOTRANSMISION,
                      G.RANGOTRANSMISION,TRIM(G.DECODIFICADOR)
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO IN (:coatepec,:abasolo)
               ORDER BY E.IDASIGNADO""" + lock,
            coatepec=COATEPEC, abasolo=ABASOLO)
        stations = cursor.fetchall()
        if len(stations) != 2:
            raise ValueError('COATEPEC: catálogo duplicado cambió')
        by_code = {row[1]: row for row in stations}
        if set(by_code) != {COATEPEC, ABASOLO}:
            raise ValueError('COATEPEC: estaciones inesperadas')
        if any(row[9] != DCP or row[13] != 'GS300' for row in stations):
            raise ValueError('COATEPEC: DCP o decoder cambió')
        coatepec = by_code[COATEPEC]
        abasolo = by_code[ABASOLO]
        if (coatepec[3:6] != (1, 1, 1) or
                abs(float(coatepec[6]) - DADDS_COORDINATES[0]) > 0.0001 or
                abs(float(coatepec[7]) - DADDS_COORDINATES[1]) > 0.0001):
            raise ValueError('COATEPEC: identidad o coordenadas no coinciden')
        if abasolo[3:6] != (1, 1, 1):
            raise ValueError('PLANTA ABASOLO: estado GOES/GPRS cambió')

        cursor.execute(
            """SELECT S.ID,TRIM(S.NUMEROSENSOR),S.PUNTODECIMAL,
                      S.PERIODOMUESTRA,S.ORDEN,S.ACTIVO,S.VISIBLE
               FROM SENSOR S JOIN ESTACION E ON E.ID=S.IDESTACION
               WHERE E.IDASIGNADO=:station ORDER BY S.ORDEN""" + lock,
            station=COATEPEC)
        sensors = cursor.fetchall()
        if ([row[1] for row in sensors] != ['1001', '2001', '2002'] or
                [float(row[3]) for row in sensors] != [1.0, 60.0, 60.0] or
                any(row[5:7] != (1, 1) for row in sensors)):
            raise ValueError('COATEPEC: sensores cambiaron')
        decimals = {row[1]: int(row[2]) for row in sensors}
        if decimals not in ({'1001': 2, '2001': 1, '2002': 1},
                            {'1001': 2, '2001': 2, '2002': 2}):
            raise ValueError('COATEPEC: decimales inesperados')

        backup = {
            'applied': args.apply,
            'dcp': DCP,
            'stations': stations,
            'coatepec_sensors': sensors,
            'proof': proof,
            'decision': {
                'owner': COATEPEC,
                'source': 'NESDIS/DADDS metadata: 70 COATEPEC',
                'coordinates': DADDS_COORDINATES,
                'abasolo_keeps_gprs': True,
            },
        }
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
                     AND PUNTODECIMAL IN (1,2)""", station_id=coatepec[0])
            if cursor.rowcount != 2:
                raise ValueError('COATEPEC: no se actualizaron las dos escalas')
            cursor.execute(
                """UPDATE ESTACION SET GOES=0
                   WHERE ID=:station_id AND GOES=1 AND GPRS=1 AND ACTIVO=1""",
                station_id=abasolo[0])
            if cursor.rowcount != 1:
                raise ValueError('PLANTA ABASOLO: no se desactivó el enlace GOES')
            catalog.commit()

    print(json.dumps({
        'applied': args.apply,
        'dcp': DCP,
        'goes_owner': COATEPEC,
        'disabled_stale_goes': ABASOLO,
        'coatepec_decimals': {'1001': 2, '2001': 2, '2002': 2},
        'proof': proof,
    }, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
