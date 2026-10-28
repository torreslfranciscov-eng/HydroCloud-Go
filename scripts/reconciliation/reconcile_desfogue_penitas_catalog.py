"""Clone the proven Presa Peñitas GS300 sensor layout into Desfogue Malpaso.

Creates an exclusive JSON backup before an optional transactional commit.
The decoder separately represents Desfogue's absent trailing 44 words as NULL.
"""
import argparse
import json
import os
import uuid
from pathlib import Path

from gs300_catalog import assign_positions, validate_words
from telemetry_decoders import gs300_words


SOURCE = 'CFE0000025'
SOURCE_DCP = 'E8900830'
TARGET = '00000CFE06'
TARGET_DCP = 'E890C3FC'
CONFIG_COLUMNS = (
    'IDTIPOSENSOR', 'VISIBLE', 'ACTIVO', 'VALORMINIMO', 'VALORMAXIMO',
    'ESPECIFICACION', 'PERIODOMUESTRA', 'TIPOGRAFICA', 'IDUNIDADMEDIDA',
    'VALORMAXERROR', 'VALORMINERROR', 'MODOALMACENAMIENTO', 'ORDEN',
    'PUNTODECIMAL', 'FECHAREGISTRO', 'USUARIOREGISTRO',
    'FECHAMODIFICACION', 'USUARIOMODIFICACION', 'APLICACOTA', 'FUNCIONA',
    'VALIDO',
)


def raw_evidence():
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    entry = audit[TARGET_DCP]
    lengths = []
    for frame in entry['frames']:
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        if len(payload) < 4 or payload[1:3] != b'B1':
            raise ValueError('DESFOGUE MALPASO: trama no B1')
        lengths.append(len(gs300_words(payload[4:])))
    if len(lengths) < 3 or set(lengths) != {38}:
        raise ValueError('DESFOGUE MALPASO: longitud insuficiente o inestable')
    return {'frames': len(lengths), 'wire_words': 38,
            'template_words': 82, 'undefined_suffix_words': 44}


def rows_for(cursor, station_id, lock=''):
    cursor.execute(
        'SELECT ID,TRIM(NUMEROSENSOR),' + ','.join(CONFIG_COLUMNS) +
        ' FROM SENSOR WHERE IDESTACION=:station ORDER BY ORDEN,NUMEROSENSOR' + lock,
        station=station_id)
    names = ('ID', 'NUMEROSENSOR') + CONFIG_COLUMNS
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    proof = raw_evidence()
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                           password=os.environ['ORACLE_CATALOG_PASSWORD'],
                           dsn=os.environ['ORACLE_DSN']) as connection:
        cursor = connection.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            '''SELECT E.ID,E.IDASIGNADO,TRIM(G.IDSATELITAL),
                      TRIM(G.DECODIFICADOR),G.RANGOTRANSMISION
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO IN (:source,:target)''' + lock,
            source=SOURCE, target=TARGET)
        stations = {row[1]: row for row in cursor.fetchall()}
        if set(stations) != {SOURCE, TARGET}:
            raise ValueError('Plantilla o destino ausente/duplicado')
        expected = {
            SOURCE: (SOURCE_DCP, 'GS300', '02:00:00'),
            TARGET: (TARGET_DCP, 'GS300', '02:00:00'),
        }
        for code, (_, _, dcp, decoder, coverage) in stations.items():
            if (dcp, decoder, str(coverage)) != expected[code]:
                raise ValueError(f'{code}: DATOSGOES cambió')
        source_rows = rows_for(cursor, stations[SOURCE][0], lock)
        target_rows = rows_for(cursor, stations[TARGET][0], lock)
        source_active = [row for row in source_rows if int(row['ACTIVO']) == 1]
        source_by_number = {row['NUMEROSENSOR']: row for row in source_active}
        if (len(source_active) != 16 or len(source_by_number) != 16 or
                set(source_by_number) != {str(i).zfill(4) for i in range(1, 17)}):
            raise ValueError('Presa Peñitas: plantilla activa cambió')
        sensors_for_validation = [
            dict(numero_sensor=row['NUMEROSENSOR'],
                 periodo=float(row['PERIODOMUESTRA']), orden=row['ORDEN'],
                 decoder='GS300')
            for row in source_active
        ]
        mapped = assign_positions(sensors_for_validation, 120)
        if sum(len(sensor['posiciones']) for sensor in mapped) != 82:
            raise ValueError('Presa Peñitas: la plantilla ya no ocupa 82 palabras')
        sample = [0] * 38
        validate_words(sample, mapped, station=TARGET)
        if len(sample) != 82 or sample[38:] != [None] * 44:
            raise ValueError('DESFOGUE MALPASO: normalización indefinida falló')

        backup = {
            'applied': args.apply, 'source': SOURCE, 'target': TARGET,
            'proof': proof, 'source_sensors': source_rows,
            'target_sensors_before': target_rows,
        }
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        if args.apply:
            target_by_number = {row['NUMEROSENSOR']: row for row in target_rows}
            assignments = ','.join(column + '=:' + column for column in CONFIG_COLUMNS)
            for number, source in source_by_number.items():
                values = {column: source[column] for column in CONFIG_COLUMNS}
                existing = target_by_number.get(number)
                if existing:
                    values['ID'] = existing['ID']
                    cursor.execute('UPDATE SENSOR SET ' + assignments + ' WHERE ID=:ID', values)
                else:
                    new_id = str(uuid.uuid4()).upper()
                    names = ('ID', 'NUMEROSENSOR', 'IDESTACION') + CONFIG_COLUMNS
                    binds = ('ID', 'NUMEROSENSOR', 'IDESTACION') + CONFIG_COLUMNS
                    values.update(ID=new_id, NUMEROSENSOR=number,
                                  IDESTACION=stations[TARGET][0])
                    cursor.execute(
                        'INSERT INTO SENSOR (' + ','.join(names) + ') VALUES (' +
                        ','.join(':' + name for name in binds) + ')', values)
                if cursor.rowcount != 1:
                    raise ValueError(f'{TARGET}/{number}: no se actualizó')
            for number, existing in target_by_number.items():
                if number not in source_by_number and int(existing['ACTIVO']) == 1:
                    cursor.execute(
                        'UPDATE SENSOR SET ACTIVO=0,VISIBLE=0 WHERE ID=:id',
                        id=existing['ID'])
            connection.commit()
    print(json.dumps({'applied': args.apply, 'source': SOURCE,
                      'target': TARGET, 'proof': proof}, ensure_ascii=False))


if __name__ == '__main__':
    main()
