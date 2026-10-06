"""Insert the proven missing PALMAS048Q battery channel; dry-run by default."""
import argparse
import json
import os
import uuid
from pathlib import Path

from telemetry_decoders import gs300_words


COLUMNS = (
    'IDTIPOSENSOR,VISIBLE,ACTIVO,VALORMINIMO,VALORMAXIMO,ESPECIFICACION,'
    'PERIODOMUESTRA,TIPOGRAFICA,IDUNIDADMEDIDA,VALORMAXERROR,VALORMINERROR,'
    'MODOALMACENAMIENTO,ORDEN,PUNTODECIMAL,FECHAREGISTRO,USUARIOREGISTRO,'
    'FECHAMODIFICACION,USUARIOMODIFICACION,APLICACOTA,FUNCIONA,VALIDO'
).split(',')


def raw_evidence():
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    entry = audit['AC52B1C0']
    frames = battery = temperature = 0
    for frame in entry['frames']:
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        if len(payload) < 4 or payload[1:3] != b'B1':
            continue
        words = gs300_words(payload[4:])
        if len(words) != 62:
            raise ValueError('PALMAS048Q: longitud inestable')
        if words[60] is not None and not 700 <= words[60] <= 1800:
            raise ValueError('PALMAS048Q: posición 60 no es batería')
        if words[61] is not None and not -4000 <= words[61] <= 8000:
            raise ValueError('PALMAS048Q: posición 61 no es temperatura')
        frames += 1
        battery += words[60] is not None
        temperature += words[61] is not None
    if frames < 3:
        raise ValueError('PALMAS048Q: evidencia insuficiente')
    return {'frames': frames, 'words': 62,
            'battery_values': battery, 'temperature_values': temperature}


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    proof = raw_evidence()
    new_id = str(uuid.uuid4()).upper()
    with oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
                           password=os.environ['ORACLE_CATALOG_PASSWORD'],
                           dsn=os.environ['ORACLE_DSN']) as connection:
        cursor = connection.cursor()
        lock = ' FOR UPDATE' if args.apply else ''
        cursor.execute(
            '''SELECT E.ID,G.RANGOTRANSMISION,G.DECODIFICADOR
               FROM ESTACION E JOIN DATOSGOES G ON G.IDESTACION=E.ID
               WHERE E.IDASIGNADO='PALMAS048Q' AND TRIM(G.IDSATELITAL)='AC52B1C0' ''' + lock)
        rows = cursor.fetchall()
        if len(rows) != 1 or str(rows[0][1]) != '01:00:00' or str(rows[0][2]).strip() != 'GS300':
            raise ValueError('PALMAS048Q: estación cambió')
        station_id = rows[0][0]
        cursor.execute(
            "SELECT COUNT(*) FROM SENSOR WHERE IDESTACION=:station AND TRIM(NUMEROSENSOR)='2001'",
            station=station_id)
        if cursor.fetchone()[0] != 0:
            raise ValueError('PALMAS048Q: ya existe sensor 2001')
        cursor.execute(
            'SELECT ' + ','.join('S.' + column for column in COLUMNS) + ''' FROM SENSOR S JOIN ESTACION E
               ON E.ID=S.IDESTACION WHERE E.IDASIGNADO='ZARCO0023Q'
               AND TRIM(S.NUMEROSENSOR)='2001' ''')
        source = cursor.fetchall()
        if len(source) != 1:
            raise ValueError('Sensor homólogo ausente o duplicado')
        source = dict(zip(COLUMNS, source[0]))
        backup = {'applied': args.apply, 'new_id': new_id,
                  'target_station_id': station_id, 'source': source,
                  'proof': proof}
        with open(args.backup, 'x', encoding='utf-8') as stream:
            os.chmod(args.backup, 0o600)
            json.dump(backup, stream, ensure_ascii=False, default=str, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if args.apply:
            values = [source[column] for column in COLUMNS]
            names = ['ID', 'NUMEROSENSOR', 'IDESTACION'] + COLUMNS
            binds = ['sensor_pk', 'sensor_number', 'station_pk'] + [f'v{i}' for i in range(len(COLUMNS))]
            cursor.execute(
                f"INSERT INTO SENSOR ({','.join(names)}) VALUES ({','.join(':'+b for b in binds)})",
                dict(zip(binds, [new_id, '2001', station_id] + values)))
            if cursor.rowcount != 1:
                raise ValueError('No se insertó el sensor')
            connection.commit()
    print(json.dumps({'applied': args.apply, 'station': 'PALMAS048Q',
                      'sensor': '2001', 'new_id': new_id, 'proof': proof},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
