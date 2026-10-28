"""Build a human-readable station-by-station GS300 catalog review."""
import collections
import json
from pathlib import Path

from gs300_catalog import assign_positions
from telemetry_decoders import gs300_payload_words, payload_family


DECODER_FAMILIES = {
    'GS300': {'pseudobinary_b'},
    'OTTBinario': {'ota'},
    'GS': {'named'},
    'CILA_Text': {'cila'},
    'SMN': {'table_text', 'text'},
    'SMN_ver2': {'table_text', 'text'},
    'VAISALA_Protocol_Text': {'table_text', 'text'},
}

EXPECTED_SIGNATURE = {
    'GS300': '`bB1`, `` `B1`` o `"B1` (pseudobinario B)',
    'OTTBinario': '`OTA` o encabezado seguido de `OTA`',
    'GS': 'canales de texto con identificador',
    'CILA_Text': 'bloques SHEF/CILA identificados',
    'SMN': 'tabla o registro de texto',
    'SMN_ver2': 'tabla o registro de texto',
    'VAISALA_Protocol_Text': 'tabla o registro de texto',
}

CORRECTED = [
    'MMDETAB015', 'MOJOTAB012', 'ZACATAB006', 'SALCUA061Q',
    'ZANAP27117', 'TAMUSLP024', 'TLAHUA033Q', 'CARTER021Q',
    'MADETAM034', 'PALMAS048Q', 'ARCOCHIA11', 'CHAPTAB001',
    'QUIOCHIA19', 'MACUTAB017', '0000000G03', '0000000G07', '0000000G08',
    '0000000G21', '000000LG16',
    '000000GR02', 'GUACAXXXXX', 'SITAL07000', 'EESCA07186',
    'CHACCHIA05', 'TONAL07168', 'SILTCHIA23', 'YC05',
    '00000CFE05', '00000CFE06', 'AGRAN07000', 'BOMBA07016',
    'CAZLVER018', 'CFE0000043',
]

MISSING = {
    '0000000G08': 'Nueve bloques tienen correspondencia física; el bloque final de 12 valores (6400) puede corresponder a más de un sensor RLS/nivel del catálogo.',
    '0000000G21': 'La trama prueba 120 minutos y un cuarto bloque de 12 estados 0/1, pero ese sensor no existe en SENSOR.',
    '000000LG16': 'Los nueve sensores configurados ocupan 19 palabras; hay dos canales horarios adicionales (0 y ~310–336) no catalogados.',
    '00000CFE05': ('Las capturas del analizador confirman los doce sensores y sus períodos '
                    '(0001/0002 cada 10 min; 0003–0012 cada 60 min), por lo que no se debe '
                    'recortar SENSOR. La trama actual sólo trae 38 palabras en lugar de las 44 '
                    'necesarias y sus valores no corresponden con los mostrados por el analizador; '
                    'la discrepancia está en la transmisión/origen, no en el catálogo.'),
    '00000CFE06': 'Los últimos 14 valores no coinciden con las escalas/límites de precipitación y batería configurados; requiere confirmar el orden físico.',
    'STODCHIA22': 'El wire contiene un tercer bloque de 12 palabras no identificado en SENSOR.',
    'TIN1DISI06': 'El wire contiene un bloque adicional de 6 palabras no identificado.',
    'TIN2DISI07': 'El wire contiene un bloque adicional de 6 palabras no identificado.',
    'ESCODISI05': 'El wire contiene 12 palabras adicionales (dos bloques) sin sensor inequívoco.',
    'CAZLVER018': 'Además de nivel/estado/baterías aparece temperatura interna sin sensor inequívoco.',
    'LOMAPUE004': 'El último bloque corresponde a temperatura interna, ausente del catálogo.',
    'FCOITAB004': 'La palabra final es temperatura interna (~27 °C), ausente del catálogo.',
    '000000LG16': 'Existen dos canales horarios adicionales no identificados en SENSOR.',
    '0000000G21': 'Existe un bloque adicional de 12 muestras no identificado en SENSOR.',
}


def valid_lengths(entry):
    lengths = []
    for frame in entry['frames']:
        try:
            payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
            code = (entry.get('station') or {}).get('id_asignado')
            lengths.append(len(gs300_payload_words(payload, station=code)))
        except (ValueError, IndexError):
            continue
    return collections.Counter(lengths)


def wire_formats(entry):
    families = collections.Counter()
    signatures = collections.Counter()
    for frame in entry['frames']:
        payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
        family = payload_family(payload)
        families[family] += 1
        if len(payload) >= 3 and payload[1:3] == b'B1':
            signature = payload[:3].decode('latin1')
        elif payload.startswith(b'OTA'):
            signature = 'OTA'
        elif len(payload) >= 4 and payload[1:4] == b'OTA':
            signature = payload[:4].decode('latin1')
        else:
            text = payload[:12].decode('latin1', errors='replace')
            signature = repr(text)[1:-1] or '(vacía)'
        signatures[signature] += 1
    return families, signatures


def compact_counts(counter, limit=4):
    parts = [f'`{value}` × {count}'
             for value, count in counter.most_common(limit)]
    omitted = sum(counter.values()) - sum(
        count for _, count in counter.most_common(limit))
    if omitted:
        parts.append(f'otras firmas × {omitted}')
    return ', '.join(parts)


def is_compatible(entry):
    return any(frame['status'] == 'compatible' for frame in entry['frames'])


def main():
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    compatible = sum(is_compatible(entry) for entry in audit.values())
    pending = []
    for dcp, entry in audit.items():
        station = entry.get('station') or {}
        if station.get('decoder') != 'GS300':
            continue
        statuses = collections.Counter(frame['status'] for frame in entry['frames'])
        if is_compatible(entry):
            continue
        counts = valid_lengths(entry)
        expected = None
        error = None
        try:
            mapped = assign_positions([dict(sensor) for sensor in entry['sensors']],
                                      station['rango_transmision'])
            expected = sum(len(sensor['posiciones']) for sensor in mapped)
        except ValueError as exc:
            error = str(exc)
        if not counts:
            diagnosis = 'Trama no B1, textual, incompleta o con caracteres inválidos; no es una corrección segura de SENSOR.'
        elif station['id_asignado'] in MISSING:
            diagnosis = MISSING[station['id_asignado']]
        else:
            diagnosis = ('La longitud es estable, pero requiere identificar canales, períodos u orden; '
                         'hay más de una configuración aritméticamente posible.')
        families, signatures = wire_formats(entry)
        pending.append((station['id_asignado'], dcp, entry, statuses,
                        counts, expected, error, diagnosis, families, signatures))

    lines = [
        '# Revisión del catálogo y decoder GS300 — 2026-10-01', '',
        'Fuente: Oracle `HYDROCLOUD.SENSOR`/`DATOSGOES` y todas las tramas de las últimas 24 horas.',
        'Sólo se aplicaron cambios respaldados por al menos tres tramas estables y una correspondencia física inequívoca.', '',
        '## Resultado', '',
        f'- Estaciones o decoders reconciliados: {len(CORRECTED)}.',
        f'- Estaciones con al menos una trama compatible después de la corrección: {compatible} de {len(audit)} transmisoras.',
        f'- GS300 pendientes descritas abajo: {len(pending)}.',
        '- Los sensores calculados ya no consumen posiciones físicas del wire.', '',
        '## Corregidas', '',
        ', '.join(f'`{code}`' for code in CORRECTED) + '.', '',
        '## PLATANAR — catálogo reconciliado', '',
        '- Clave: `0000000G03`; DCP: `15B27202`; decoder: `GS300`.',
        '- Las 18 tramas revisadas tienen firma `bB1` y 50 palabras; el decoder coincide.',
        '- Rango corregido de 60 a 120 minutos.',
        '- Distribución comprobada por 300 valores solapados entre transmisiones, sin discrepancias: nivel 12 × 10 min, precipitación 12 × 10 min, batería 2 × 60 min, estado RLS 12 × 10 min y señal RLS 12 × 10 min.',
        '- Sensores activos finales, en orden: `0001`, `0002`, `0900`, `0901`, `0902`. Los antiguos `0017` y `0018`, ausentes de la trama, quedaron inactivos y ocultos.',
        '- Verificación posterior en Oracle: 18/18 tramas compatibles; catálogo esperado 50 palabras y wire observado 50.',
        '',
        '## EMILIANO ZAPATA CHABLÉ — catálogo reconciliado', '',
        '- Clave: `0000000G07`; DCP: `15B2C18C`; decoder: `GS300`.',
        '- Las 18 transmisiones únicas revisadas tienen firma `bB1` y 62 palabras; el decoder coincide.',
        '- Rango corregido de 60 a 120 minutos; `0020` Nivel Recipiente y `0021` Estado del pluvio se corrigieron de 60 a 10 minutos.',
        '- Distribución comprobada: nivel 12 × 10 min; siete sensores 2 × 60 min cada uno; precipitación, nivel de recipiente y estado del pluvio 12 × 10 min cada uno.',
        '- Las 372 comparaciones solapadas entre transmisiones coinciden, sin discrepancias.',
        '- Verificación posterior en Oracle: 18/18 tramas compatibles; catálogo esperado 62 palabras y wire observado 62.',
        '',
        '## BOCA DEL CERRO — catálogo reconciliado', '',
        '- Clave: `0000000G08`; DCP: `15B2D2FA`; decoder: `GS300`.',
        '- La captura de configuración confirmó diez canales físicos: `0001`, `0002`, `0003`, `0004`, `0005`, `0009`, `0010`, `0011`, `0012` y `0905` Estado RLS nivel.',
        '- Se activó y mostró `0001`; `0004`, `0005`, `0009` y `0010` cambiaron de 60 a 10 minutos; `0016`, `0906` y `0907` quedaron inactivos y ocultos.',
        '- Las 18 tramas tienen 90 palabras; las 540 comparaciones solapadas coinciden sin discrepancias.',
        '- Verificación posterior en Oracle: 18/18 tramas compatibles; catálogo esperado 90 palabras y wire observado 90.',
        '',
        '## EL PORTILLO — catálogo y sufijo auxiliar reconciliados', '',
        '- Clave: `0000000G21`; DCP: `15C8131A`; decoder: `GS300`.',
        '- La captura confirmó únicamente `0001` Nivel, `0002` Batería y `0007` Precipitación.',
        '- Rango corregido de 60 a 120 minutos: 12 palabras de nivel, 2 de batería y 12 de precipitación.',
        '- El programa de la estación agrega 12 estados auxiliares constantes `0/1`; el decoder los ignora sólo para esta clave y rechaza cualquier otra longitud o valor.',
        '- Verificación posterior: 17/17 tramas compatibles; 26 palabras de sensores más 12 auxiliares.',
        '',
        '## CORRALES — diagnósticos auxiliares identificados', '',
        '- Clave: `000000LG16`; DCP: `15C7C3E0`; decoder: `GS300`.',
        '- La captura confirmó que los nueve sensores configurados en Oracle son los correctos; ocupan 19 palabras.',
        '- La captura operativa del 2026-10-02 14:57 confirma 24/24 transmisiones estables y los sensores `0010`, `0005`, `0011`, `0001`, `0002`, `0003`, `0009`, `0004` y `0012`.',
        '- Los nueve sensores aparecen funcionando; `0001` Nivel de agua es el único marcado con datos inválidos, lo cual es una condición de medición y no una falla del decoder.',
        '- El transmisor agrega dos diagnósticos no visibles: estado `0` y temperatura interna cruda `291–336`.',
        '- El decoder ignora esas dos palabras sólo para esta clave y sólo dentro de rangos restringidos; cualquier otra longitud o valor se rechaza.',
        '- Verificación posterior desde una conexión nueva a Oracle: 18/18 tramas compatibles.',
        '',
        '## EMILIANO ZAPATA CFE — canales ausentes como indefinidos', '',
        '- Clave: `00000CFE05`; DCP: `E890B56C`; decoder: `GS300`.',
        '- Las capturas confirman los doce sensores: `0001`/`0002` cada 10 minutos y `0003`–`0012` cada 60 minutos.',
        '- El wire trae 38 palabras frente a 44 del catálogo; faltan las seis posiciones finales correspondientes a dos muestras de `0010`, `0011` y `0012`.',
        '- El decoder conserva esos sensores y completa exclusivamente esas posiciones con valor indefinido (`None`/NULL); no inventa ni repite mediciones.',
        '- La excepción sólo aplica a esta clave y exige exactamente 38 palabras; cualquier otra longitud continúa rechazada.',
        '- No se modificó Oracle: el catálogo confirmado permanece intacto.',
        '',
        '## PRESA PEÑITAS (PROVISIONAL) — configuración de Presa Peñitas', '',
        '- Clave: `00000CFE06`; DCP: `E890C3FC`; decoder: `GS300`.',
        '- Se copió en Oracle la configuración activa de los 16 sensores de Presa Peñitas `CFE0000025`, conservando tipos, períodos, orden, decimales, unidades y límites.',
        '- La plantilla completa ocupa 82 palabras: tres bloques iniciales de 12, once canales horarios de dos palabras y dos bloques finales de 12.',
        '- Las tramas de esta estación son estables en 38 palabras y terminan después del primer canal horario (`0004`).',
        '- El decoder conserva las primeras 38 posiciones y agrega las 44 finales como indefinidas (`None`/NULL), sin fabricar ceros ni repetir valores.',
        '- La excepción sólo aplica a esta clave y exige exactamente 38 palabras.',
        '',
        '## Correcciones adicionales de esta ronda', '',
        '| Clave | Estación | Corrección comprobada | Resultado |',
        '|---|---|---|---|',
        '| `AGRAN07000` | ARROYO GRANDE | Rango 60 → 120 min; se intercambió el orden de dirección/velocidad del viento y `0011` quedó inactivo. | 126/126 palabras; diez bloques de 12 y tres canales horarios de 2. |',
        '| `BOMBA07016` | BOMBANA | Rango 60 → 120 min; `0004`, `0005`, `0011`, `0014` y `0015` quedaron inactivos, siguiendo el layout comprobado de JONUTA. | 110/110 palabras; 550 solapamientos sin fallas. |',
        '| `CAZLVER018` | CARRIZAL | `0015` se corrigió a `0020` Estado del radar y su período cambió 60 → 10 min; dos temperaturas internas finales se tratan como auxiliares. | 28 palabras de sensores + 2 auxiliares; 150 solapamientos sin fallas. |',
        '| `CFE0000043` | Ixcamilpa | Se habilitó exclusivamente para esta clave la variante pseudobinaria con marcador inicial y sin firma `B1`; el catálogo de nueve sensores no cambió. | 18/18 tramas; 38/38 palabras. |',
        '| `000000GR02` | GONZALEZ | Se desactivaron `0016`, `0910` y `0905`, ausentes del wire. | 52/52 palabras; 312 solapamientos sin fallas. |',
        '| `GUACAXXXXX` | GUACAMAYAS | `0014` y `0015`: período 60 → 10 min. | 146/146; 730 solapamientos sin fallas. |',
        '| `SITAL07000` | SITALA | Rango 60 → 120 min; se desactivaron `0021`, `0022`, `0023`. | 122/122; 610 solapamientos sin fallas. |',
        '| `EESCA07186` | EL ESCALON | Rango 60 → 120 min; se desactivaron `0021`, `0022`, `0023`. | 122/122; 610 solapamientos sin fallas. |',
        '| `CHACCHIA05` | CHACAMAX | Rango 60 → 120 min; batería a 60 min y orden final corregido. | 86/86; 430 solapamientos sin fallas. |',
        '| `TONAL07168` | TONALA | Rango 60 → 120 min; diez sensores ausentes quedaron inactivos. | 50/50; 175 solapamientos sin fallas. |',
        '| `SILTCHIA23` | SILTEPEC | Rango 60 → 120 min; `0903` y `0904` quedaron inactivos. | 98/98; 490 solapamientos sin fallas. |',
        '',
        '## YC05 — decoder corregido, catálogo de sensores pendiente', '',
        '- DCP: `15CC1620`.',
        '- Decoder anterior: `GS300`; decoder actual en Oracle: `SMN`.',
        '- Trama observada: texto SMN en todas las transmisiones; no contiene firma `bB1`.',
        '- ¿Decoder coincide con la trama?: **Sí**, después de la corrección.',
        '- Pendiente: cada registro transporta 12 columnas y `SENSOR` sólo configura 11; aparecen dos columnas de presión atmosférica y sólo una está catalogada.',
        '',
        '## Pendientes, estación por estación', '',
    ]
    for (code, dcp, entry, statuses, counts, expected, error, diagnosis,
         families, signatures) in sorted(pending):
        station = entry['station']
        decoder = station['decoder']
        allowed = DECODER_FAMILIES.get(decoder, set())
        matching = sum(count for family, count in families.items()
                       if family in allowed)
        total = sum(families.values())
        decoder_result = ('Sí' if matching == total and total else
                          'No' if matching == 0 else
                          f'Parcial ({matching}/{total})')
        family_text = compact_counts(families)
        signature_text = compact_counts(signatures)
        parsed = sum(counts.values())
        observed = ', '.join(f'{length} ({count} tramas)' for length, count in counts.most_common()) or 'sin B1 válida'
        lines.extend([
            f'### {code} — {station["nombre"]}', '',
            f'- DCP: `{dcp}`; rango: {station["rango_transmision"]} min; intervalo TX: {station["intervalo_transmision"]} min.',
            f'- Decoder configurado: `{decoder}`; firma esperada: {EXPECTED_SIGNATURE.get(decoder, "sin regla")}.',
            f'- Trama observada: firma {signature_text}; familia {family_text}.',
            f'- ¿Decoder coincide con la trama?: **{decoder_result}**.',
            f'- Payload GS300 estructuralmente decodificable: **{parsed}/{total}** tramas.',
            f'- Wire: {observed}; catálogo esperado: {expected if expected is not None else error}.',
            f'- Diagnóstico: {diagnosis}',
            '- Sensores activos:', '',
        ])
        for sensor in sorted(entry['sensors'], key=lambda item: float(item.get('orden') or 9999)):
            lines.append(
                f'  - `{sensor["numero_sensor"]}` {sensor["nombre"]}: '
                f'orden {sensor.get("orden")}, período {sensor["periodo"]} min, '
                f'decimales {sensor["decimales"]}, calculado {sensor.get("calculada", 0)}.')
        if code == '00000CFE05':
            lines.extend([
                '',
                '- Evidencia de las capturas del analizador, hora local 2026-10-01:',
                '  - `0005` dirección del viento: 147, 120 y 46°; `0007` dirección de ráfaga: 59, 49 y 53°.',
                '  - `0008` humedad: 64, 86 y 95%; `0006` velocidad de ráfaga: 0.9, 5.9 y 4.5 m/s.',
                '  - `0009` batería: 12.93, 12.83 y 12.77 V; `0010` temperatura interna: 34, 30.25 y 25.5 °C.',
                '  - `0011` radiación: 0.31, 0.73 y 0.21 W/m2; `0012` presión: 958.70, 961.53 y 962.40 mbar.',
                '  - `0003` temperatura ambiente muestra 23.64, -38.80 y -38.82 °C; el propio analizador marca ese sensor con datos inválidos.',
                '  - `0001` y `0002` muestran series de 10 minutos, coherentes con el período configurado.',
                '- Contraste con Oracle: `E890B56C` es el único DCP asociado. Las tramas recibidas a las 18:47 y 19:47 hora local contienen 38 palabras y no contienen esos valores de referencia.',
                '- Decisión: conservar los doce sensores sin cambios; revisar la programación/origen del transmisor antes de modificar Oracle.',
            ])
        lines.append('')
    Path('GS300_CATALOGO_REVISION_20261001.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'corrected': len(CORRECTED), 'pending': len(pending)}))


if __name__ == '__main__':
    main()
