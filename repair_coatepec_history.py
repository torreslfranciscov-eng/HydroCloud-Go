"""Back up and repair AC531D10 rows affected by the duplicate catalog entry."""
import argparse
import configparser
import json
import os

import oracledb


DCP = 'AC531D10'
COATEPEC = 'COATEP070Q'
ABASOLO = 'PABASO078Q'
RANGES = {'2001': (0.0, 17.0), '2002': (-15.0, 50.0)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read('config.ini')
    source = config['oracle_cloud']

    with oracledb.connect(user=source['user'], password=source['password'],
                          dsn=source['dsn']) as connection:
        cursor = connection.cursor()
        connection.call_timeout = 120000
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            """SELECT ROWIDTOCHAR(ROWID),SYS_EXTRACT_UTC(TS),DCP_ID,
                      ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,VALIDO,DESCRIPCION,
                      QC_FLAG,QC_DETAIL
               FROM DCP_DATOS
               WHERE DCP_ID=:dcp AND ID_ASIGNADO=:station
               ORDER BY TS,SENSOR_ID""" + lock,
            dcp=DCP, station=ABASOLO)
        misplaced = cursor.fetchall()

        cursor.execute(
            """SELECT ROWIDTOCHAR(ROWID),SYS_EXTRACT_UTC(TS),DCP_ID,
                      ID_ASIGNADO,SENSOR_ID,VARIABLE,VALOR,VALIDO,DESCRIPCION,
                      QC_FLAG,QC_DETAIL
               FROM DCP_DATOS
               WHERE DCP_ID=:dcp AND ID_ASIGNADO=:station
                 AND SENSOR_ID IN ('2001','2002') AND VALIDO=0
                 AND VALOR IS NOT NULL
                 AND TS>SYSTIMESTAMP-NUMTODSINTERVAL(30,'DAY')
               ORDER BY TS,SENSOR_ID""" + lock,
            dcp=DCP, station=COATEPEC)
        mis_scaled = cursor.fetchall()
        corrected = []
        for row in mis_scaled:
            sensor = row[4]
            value = round(float(row[6]) / 10.0, 2)
            low, high = RANGES[sensor]
            if not low <= value <= high:
                raise ValueError(
                    f'COATEPEC: el valor {row[6]} de {sensor} no prueba escala 2')
            corrected.append((row[0], value))
        if not misplaced:
            raise ValueError('COATEPEC: no hay filas mal asignadas para reparar')
        if not corrected:
            raise ValueError('COATEPEC: no hay valores históricos mal escalados')

        backup = {
            'applied': args.apply,
            'dcp': DCP,
            'misplaced_rows': misplaced,
            'mis_scaled_rows': mis_scaled,
            'corrected_values': corrected,
        }
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            cursor.execute(
                """UPDATE DCP_DATOS SET ID_ASIGNADO=:coatepec
                   WHERE DCP_ID=:dcp AND ID_ASIGNADO=:abasolo""",
                coatepec=COATEPEC, dcp=DCP, abasolo=ABASOLO)
            if cursor.rowcount != len(misplaced):
                raise ValueError('COATEPEC: cambió el conjunto mal asignado')
            note = ('Reprocesado AC531D10: escala GS300 de dos decimales '
                    'verificada por trama')
            for rowid, value in corrected:
                cursor.execute(
                    """UPDATE DCP_DATOS
                       SET VALOR=:value,VALIDO=1,DESCRIPCION=:note,
                           QC_FLAG=NULL,QC_DETAIL=NULL
                       WHERE ROWID=CHARTOROWID(:rid) AND DCP_ID=:dcp
                         AND ID_ASIGNADO=:station AND VALIDO=0""",
                    value=value, note=note, rid=rowid, dcp=DCP,
                    station=COATEPEC)
                if cursor.rowcount != 1:
                    raise ValueError('COATEPEC: una fila histórica cambió')
            connection.commit()

        print(json.dumps({
            'applied': args.apply,
            'dcp': DCP,
            'rows_reassigned': len(misplaced),
            'values_rescaled': len(corrected),
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
