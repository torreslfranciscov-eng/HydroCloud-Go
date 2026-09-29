"""Pure decoding/validation. Unknown layouts require an explicit station profile."""
import datetime as dt
import json
import math
import os
import re
import struct
from pathlib import Path

MISSING = -32763.0


def payload_family(payload):
    """Identify wire syntax, not sensor order or manufacturer from plausible values."""
    data = payload.strip(b' \r\n')
    text = data.decode('ascii', errors='replace').strip(' \r\n"')
    if text.startswith(('Missing message from ', 'SATLINK DATA BUFFER EMPTY')):
        return 'notice'
    if data.startswith(b'OTA') or data[1:4] == b'OTA':
        return 'ota'
    if len(data) >= 4 and data[1:3] == b'B1' and data[0] in (34, 96, 98):
        return 'pseudobinary_b'
    if re.match(r':?[A-Z][A-Z0-9]{1,3}\s+\d+\s+#\d+\s', text):
        return 'cila'
    if re.match(r'[A-Z][A-Z0-9]{1,3}\s+\d+\s+', text):
        return 'named'
    if re.match(r'\d{1,2}\s+\d{2}:\d{2}:\d{2}\s', text):
        return 'table_text'
    if re.match(r'(?:(?:\d{4}-\d{2}-\d{2})\s+)?\d{2}:\d{2}:\d{2}\s', text):
        return 'text'
    if re.match(r'(02|04|2|4)\s*\d{8}(?:\d{2}){0,2},', text):
        return 'table_text'
    return 'unknown'


def validate_decoder_payload(decoder, payload):
    family = payload_family(payload)
    allowed = {'GS300': {'pseudobinary_b'}, 'OTTBinario': {'ota'},
               'GS': {'named'}, 'CILA_Text': {'cila'},
               'SMN': {'table_text', 'text'}, 'SMN_ver2': {'table_text', 'text'},
               'VAISALA_Protocol_Text': {'table_text', 'text'}}
    if family not in allowed.get(decoder, set()):
        raise ValueError(f'Decoder {decoder} incompatible con trama {family}; no se insertan mediciones')
    if family == 'pseudobinary_b':
        words = payload.strip(b' \r\n')[4:]
        if not words or len(words) % 3 or any(not 63 <= ch <= 126 for ch in words):
            raise ValueError('GS300: palabras de 18 bits incompletas o caracteres inválidos')
    return family


def number(token):
    token = token.strip()
    if not token or '#' in token or '/' in token or token.upper() in ('NAN', 'M', 'INF', '-INF'):
        return MISSING
    value = float(token)
    return value if math.isfinite(value) else MISSING


def align(stamp, minutes):
    seconds = float(minutes) * 60
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Periodo de muestra inválido')
    epoch = dt.datetime(1970, 1, 1, tzinfo=stamp.tzinfo)
    return epoch + dt.timedelta(seconds=math.floor((stamp - epoch).total_seconds() / seconds) * seconds)


class Values(list):
    def __init__(self, values, table):
        super().__init__(values)
        self.table = table


def text_records(payload, received, decoder):
    """Preserve every column, engineering-unit decimal and table identifier."""
    if received is None:
        raise ValueError('Falta fecha de recepción')
    if received.tzinfo is None:
        received = received.replace(tzinfo=dt.timezone.utc)
    records = []
    for line in re.split(r'[\r\n\x04]+', payload.decode('ascii').strip(' \r\n"')):
        line = line.strip(' "')
        if not line:
            continue
        m = re.fullmatch(r'(?:(\d{1,2})\s+)?(\d{4}-\d{2}-\d{2}\s+)?(\d{2}:\d{2}:\d{2})\s+(.+)', line)
        if m:
            table, date, clock, body = m.groups()
            stamp = dt.datetime.fromisoformat((date.strip() if date else received.date().isoformat()) + 'T' + clock).replace(tzinfo=dt.timezone.utc)
            if not date and stamp > received:
                stamp -= dt.timedelta(days=1)
            tokens = body.split(',') if ',' in body else body.split()
            records.append((stamp, Values([number(v) for v in tokens], table or 'default')))
            continue
        m = re.fullmatch(r'(02|04|2|4)\s*(\d{8}(?:\d{2}){0,2}),(.*)', line)
        if m:
            table, date, body = m.groups()
            fmt = {8:'%Y%m%d',10:'%Y%m%d%H',12:'%Y%m%d%H%M'}[len(date)]
            stamp = dt.datetime.strptime(date, fmt).replace(tzinfo=dt.timezone.utc)
            records.append((stamp, Values([number(v) for v in body.split(',')], table)))
            continue
        raise ValueError(f'{decoder}: registro textual no reconocido')
    if not records:
        raise ValueError('Mensaje textual sin registros')
    return records


def named_records(payload, received, cila=False):
    text = payload.decode('ascii').strip(' \r\n"')
    result = {}
    if received.tzinfo is None:
        received = received.replace(tzinfo=dt.timezone.utc)
    chunks = text.split(':') if cila else re.split(r'[\r\n]+', text)
    for chunk in chunks:
        parts = chunk.split()
        if not parts:
            continue
        code = parts.pop(0).upper()
        if code == 'NAME':
            continue
        if not re.fullmatch(r'[A-Z][A-Z0-9]{1,3}', code) or code in result:
            raise ValueError('Canal textual inválido o duplicado: ' + code)
        if cila and code == 'BL' and len(parts) == 1:
            result[code] = [(received, number(parts[0]))]
            continue
        if cila:
            if len(parts) < 3 or not parts[1].startswith('#'):
                raise ValueError('Bloque SHEF incompleto')
            offset, interval = int(parts.pop(0)), int(parts.pop(0)[1:])
            latest = received.replace(second=0, microsecond=0) - dt.timedelta(minutes=offset)
        else:
            interval = int(parts.pop(0))
            latest = align(received, interval)
        if interval <= 0:
            raise ValueError('Intervalo textual inválido')
        result[code] = [(latest - dt.timedelta(minutes=i * interval), number(value)) for i, value in enumerate(parts)]
    if not result:
        raise ValueError('Mensaje sin canales')
    return result


def profile(station):
    with Path(__file__).with_name('decoder_profiles.json').open(encoding='utf-8') as handle:
        profiles = json.load(handle)
    path = os.environ.get('DECODER_PROFILES_PATH')
    if path:
        with open(path, encoding='utf-8') as handle:
            profiles.update(json.load(handle))
    return profiles.get(station, {})


def ordered_sensors(sensors, order, count):
    if not order or len(order) != count or len(set(order)) != len(order):
        raise ValueError('Falta perfil explícito o cantidad de canales no coincide')
    by_id = {s['numero_sensor']: s for s in sensors}
    if len(by_id) != len(sensors) or any(code not in by_id for code in order):
        raise ValueError('El perfil no coincide con los sensores activos')
    return [by_id[code] for code in order]


def record_sensors(station, values, sensors):
    if sensors and all(s.get('decoder') == 'SMN' for s in sensors):
        return smn_catalog_sensors(values, sensors)
    tables = profile(station).get('tables', {})
    order = tables.get(getattr(values, 'table', 'default'))
    if not order or len(order) != len(values):
        raise ValueError('Falta perfil textual o cantidad de columnas no coincide')
    active = [code for code in order if code is not None]
    mapped = iter(ordered_sensors(sensors, active, len(active)))
    # Explicit null slots retain column positions without guessing a sensor.
    return [next(mapped) if code is not None else None for code in order]


def smn_catalog_sensors(values, sensors):
    """Verified numbered SMN tables; authoritative order comes from Sensor.

    No inference by plausible readings, no slicing excess columns, no fallback
    from unknown tables to a different group. Unnumbered formats stay explicit.
    """
    table = getattr(values, 'table', None)
    if table not in ('2', '4'):
        raise ValueError(f'SMN: tabla {table} sin correspondencia comprobada en Sensor')
    period = 10 if table == '2' else 60
    selected = [s for s in sensors if s['periodo'] == period and s.get('calculada') == 0]
    if len(selected) != len(values) or not selected:
        raise ValueError(f'SMN tabla {table}: {len(values)} columnas; Sensor configura {len(selected)} canales de {period} min')
    orders = [s.get('orden') for s in selected]
    if any(o is None or not math.isfinite(float(o)) or float(o) != int(o) for o in orders) or len(set(orders)) != len(orders):
        raise ValueError('SMN: Orden ausente, no entero o duplicado en Sensor')
    if len({s['numero_sensor'] for s in sensors}) != len(sensors):
        raise ValueError('SMN: NumeroSensor duplicado')
    if any(not s.get('unidad') for s in selected):
        raise ValueError('SMN: falta unidad de medida en Sensor')
    selected.sort(key=lambda s:s['orden'])
    if table == '4':
        names = [s['nombre'].lower() for s in selected]
        if len(selected) != 2 or 'bater' not in names[0] or 'panel' not in names[1] or any(s['unidad'].upper() != 'V' for s in selected):
            raise ValueError('SMN tabla 4: catálogo no identifica batería y panel en V, en ese orden')
    return selected


def ott_sensors(station, blocks, sensors, coverage):
    ordered = ordered_sensors(sensors, profile(station).get('ott_order'), len(blocks))
    for (interval, values), sensor in zip(blocks, ordered):
        if interval <= 0 or interval != sensor['periodo'] or len(values) * interval != coverage:
            raise ValueError('OTT: intervalo/cantidad de muestras no coincide con catálogo')
    return ordered


def ott_blocks(payload, convert):
    data = payload if isinstance(payload, bytes) else payload.encode('ascii')
    data = data.strip(b' \r\n')
    if data.startswith(b'bB'):
        raise ValueError('Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar')
    # Only the observed OTA envelope is accepted; arbitrary offsets are unsafe.
    if not data.startswith(b'"OTA') or len(data) <= 5:
        raise ValueError('Cabecera OTT no soportada')
    raw = convert(data[5:])
    if len(raw) < 8:
        raise ValueError('OTT incompleto')
    pos, blocks = 4, []
    while pos < len(raw):
        if len(raw)-pos == 1 and raw[pos] == 0:
            break  # Zero padding from six-to-eight-bit packing.
        if len(raw)-pos < 4:
            raise ValueError('OTT: cola sin formato confirmado o cabecera de bloque truncada')
        interval, count = struct.unpack_from('<hh', raw, pos)
        pos += 4
        if not 0 < interval <= 1440 or not 0 < count <= 1000 or pos+2*count > len(raw):
            raise ValueError('Bloque OTT inválido o truncado')
        blocks.append((interval, list(struct.unpack_from('<'+'h'*count, raw, pos))))
        pos += 2*count
    return blocks
