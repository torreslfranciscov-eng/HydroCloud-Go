"""Correct NICOLAS BRAVO from GS300 to its verified SMN table-2 format."""
import argparse
import configparser
import json
import os

import oracledb

from telemetry_decoders import MISSING, payload_family, text_records


STATION = 'QR05'
DCP = '15CC60B0'
SENSORS = tuple(f'{number:04d}' for number in range(1, 12))


def prove_format(connection):
    cursor = connection.cursor()
    cursor.execute(
        '''SELECT SYS_EXTRACT_UTC(TIMESTAMP_MSG),RAW_MESSAGE
           FROM DCP_HEADERS WHERE DCP_ID=:dcp
             AND TIMESTAMP_MSG>SYSTIMESTAMP-NUMTODSINTERVAL(30,'DAY')
             AND RAW_MESSAGE IS NOT NULL
             AND INSTR(RAW_MESSAGE,'Missing message from')=0
           ORDER BY TIMESTAMP_MSG''', dcp=DCP)
    frames = []
    complete_records = 0
    rejected_frames = []
    for received, raw in cursor:
        payload = raw[37:].encode('ascii')
        if payload_family(payload) != 'table_text':
            raise ValueError('NICOLAS BRAVO: familia de trama inesperada')
        try:
            records = text_records(payload, received, 'SMN')
        except ValueError as error:
            rejected_frames.append({'received': received, 'error': str(error)})
            continue
        # LRGS can deliver a shortened transmission after a retransmission or
        # partial buffer read.  Every record still has to prove the same table
        # and column layout; an empty payload is rejected by text_records.
        if len(records) > 6:
            raise ValueError('NICOLAS BRAVO: cantidad de registros inesperada')
        for _, values in records:
            if values.table != '2' or len(values) not in (7, 11):
                raise ValueError(
                    'NICOLAS BRAVO: tabla o columnas inesperadas '
                    f'({received}, tabla={values.table}, columnas={len(values)}, '
                    f'valores={list(values)!r})')
            if values[:4] != [MISSING] * 4:
                raise ValueError('NICOLAS BRAVO: columnas faltantes cambiaron')
            if len(values) == 11 and any(value == MISSING for value in values[4:]):
                raise ValueError('NICOLAS BRAVO: dato válido ausente')
            complete_records += len(values) == 11
        frames.append({
            'received': received,
            'records': len(records),
            'tables': sorted({values.table for _, values in records}),
            'widths': sorted({len(values) for _, values in records}),
        })
    if not frames or complete_records < 12:
        raise ValueError('NICOLAS BRAVO: evidencia SMN insuficiente')
    return {'frames': len(frames),
            'records_per_frame': sorted({frame['records'] for frame in frames}),
            'table': '2', 'columns': [7, 11],
            'complete_records': complete_records,
            'rejected_frames': rejected_frames, 'evidence': frames}


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
        proof = prove_format(history)

    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                          password=os.environ['ORACLE_CATALOG_PASSWORD'],
                          dsn=dsn) as catalog:
        cursor = catalog.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            '''SELECT E.ID,G.ID,TRIM(G.DECODIFICADOR),G.RANGOTRANSMISION,
                      G.INTERVALOTRANSMISION
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO=:station AND TRIM(G.IDSATELITAL)=:dcp''' + lock,
            station=STATION, dcp=DCP)
        station_rows = cursor.fetchall()
        if len(station_rows) != 1:
            raise ValueError('NICOLAS BRAVO: estación o DCP ambiguo')
        station_id, goes_id, decoder, coverage, cadence = station_rows[0]
        if decoder != 'GS300' or str(coverage) != '01:00:00' or str(cadence) != '01:00:00':
            raise ValueError('NICOLAS BRAVO: DATOSGOES cambió')

        cursor.execute(
            '''SELECT ID,TRIM(NUMEROSENSOR),PERIODOMUESTRA,ORDEN,ACTIVO,
                      VISIBLE,PUNTODECIMAL
               FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN''' + lock,
            station=station_id)
        sensors = cursor.fetchall()
        if len(sensors) != 11 or any(row[4] != 1 for row in sensors):
            raise ValueError('NICOLAS BRAVO: catálogo cambió')
        if tuple(row[1] for row in sensors) != SENSORS:
            raise ValueError('NICOLAS BRAVO: orden de sensores inesperado')
        if any(float(row[2]) != 10 for row in sensors):
            raise ValueError('NICOLAS BRAVO: periodo de sensores inesperado')

        backup = {'applied': args.apply, 'station': STATION, 'dcp': DCP,
                  'datos_goes': station_rows[0], 'sensors': sensors,
                  'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            cursor.execute(
                '''UPDATE DATOSGOES SET DECODIFICADOR='SMN'
                   WHERE ID=:id AND TRIM(DECODIFICADOR)='GS300' ''', id=goes_id)
            if cursor.rowcount != 1:
                raise ValueError('NICOLAS BRAVO: no se actualizó el decoder')
            catalog.commit()

    print(json.dumps({'applied': args.apply, 'station': STATION,
                      'dcp': DCP, 'old_decoder': 'GS300',
                      'new_decoder': 'SMN', 'proof': proof},
                     ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
