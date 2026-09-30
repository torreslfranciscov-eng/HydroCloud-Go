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
        gs300_words(payload.strip(b' \r\n')[4:])
    return family


def gs300_words(data):
    """Strict signed 18-bit words; /// is missing, not a numeric sentinel."""
    if not data or len(data) % 3:
        raise ValueError('GS300: palabras de 18 bits incompletas')
    values = []
    for pos in range(0,len(data),3):
        word=data[pos:pos+3]
        if word == b'///':
            values.append(None)
            continue
        if any(not 63 <= ch <= 126 for ch in word):
            raise ValueError('GS300: caracteres inválidos')
        value=0
        for ch in word:
            value=(value<<6)|(ch if ch<64 else ch-64)
        values.append(value-(1<<18) if value & (1<<17) else value)
    return values


def scaled_gs300_value(raw, sensor):
    if raw is None:
        return None, False, 'Dato faltante en trama (///)'
    value=round(raw/(10**sensor['decimales']),sensor['decimales'])
    low=sensor.get('valor_minimo',-math.inf)
    high=sensor.get('valor_maximo',math.inf)
    voltage='voltaje' in sensor['nombre'].lower() and ('bater' in sensor['nombre'].lower() or 'panel' in sensor['nombre'].lower())
    if voltage:
        low=max(0,low)
    valid=low<=value<=high
    description='OK' if valid else f'Fuera de rango: {value} [{low}, {high}]'
    # Preserve invalid numeric evidence in description and raw_message, not as
    # a physical battery/panel voltage. Other variables retain signed values.
    return (None if voltage and not valid else value),valid,description


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
    active = [s for s in sensors if not s.get('calculada')]
    orders = [s.get('orden') for s in active]
    if active and all(o is not None and math.isfinite(float(o)) and float(o).is_integer() for o in orders) and len(set(orders)) == len(orders):
        ordered = sorted(active, key=lambda s: float(s['orden']))
        if len(ordered) != len(blocks):
            raise ValueError('OTT: cantidad de bloques no coincide con Sensor')
    else:
        raise ValueError('OTT: Sensor.Orden ausente, inválido o duplicado; no se usan perfiles supuestos')
    ids = [s['numero_sensor'] for s in ordered]
    if len(set(ids)) != len(ids):
        raise ValueError('OTT: número de sensor duplicado')
    for sensor in ordered:
        decimals = sensor.get('decimales')
        if decimals is None or not math.isfinite(float(decimals)) or float(decimals) != int(decimals) or not 0 <= decimals <= 5:
            raise ValueError('OTT: PuntoDecimal inválido en Sensor')
        if not sensor.get('nombre') or not math.isfinite(float(sensor['periodo'])) or sensor['periodo'] < 0:
            raise ValueError('OTT: nombre o periodo inválido en Sensor')
        if 'voltaje' in sensor['nombre'].lower() and str(sensor.get('unidad','')).upper() != 'V':
            raise ValueError('OTT: voltaje sin unidad V confirmada en Sensor')
    for (interval, values), sensor in zip(blocks, ordered):
        if interval != 0 and (interval != sensor['periodo'] or len(values) * interval > coverage):
            raise ValueError('OTT: intervalo/cantidad de muestras no coincide con catálogo')
    return ordered


class OttValues(list):
    """Raw samples in wire order, with times decoded from the OTT message."""
    def __init__(self, values, times):
        super().__init__(values)
        self.times = times


def ott_value(raw, sensor):
    # IGS DcpMessageParser.IsOttFlag: evaluate BEFORE applying decimal scale.
    if raw < -32700:
        return None, False, f'Bandera OTT: {raw}'
    return scaled_gs300_value(raw, sensor)


def ott_blocks(payload, convert, received=None):
    data = payload if isinstance(payload, bytes) else payload.encode('ascii')
    data = data.rstrip(b' \r\n')
    if data.startswith(b'bB'):
        raise ValueError('Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar')
    # Only the observed OTA envelope is accepted; arbitrary offsets are unsafe.
    if len(data) <= 5 or data[1:4] != b'OTA' or data[0] not in (32, 34, 96, 98) or data[4:5] != b'@':
        raise ValueError('Cabecera OTT no soportada')
    if any(not 32 <= ch <= 127 for ch in data[5:]):
        raise ValueError('OTT: caracteres inválidos')
    raw = convert(data[5:])
    if len(raw) < 8:
        raise ValueError('OTT incompleto')
    epoch = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    stamp = epoch + dt.timedelta(seconds=struct.unpack_from('<i', raw)[0])
    if received is not None:
        received = received.replace(tzinfo=dt.timezone.utc) if received.tzinfo is None else received.astimezone(dt.timezone.utc)
        if stamp < received - dt.timedelta(days=7) or stamp > received + dt.timedelta(minutes=5):
            raise ValueError('OTT: fecha interna fuera de ventana de recepción (-7 días / +5 minutos)')
    pos, blocks = 4, []
    while pos < len(raw):
        if len(raw)-pos <= 2:
            # IGS ParseOttDcpMessage stops when Position+2 >= Length before
            # reading the next interval. These are residual bytes, not samples.
            # Truncated declared samples are still rejected below.
            break
        if raw[pos:] in (b'\x20\x00', b'\x20\x00\x00'):
            break  # IGS termination word (32), optionally followed by padding.
        if len(raw)-pos < 4:
            raise ValueError('OTT: cola sin formato confirmado o cabecera de bloque truncada')
        interval, count = struct.unpack_from('<hh', raw, pos)
        pos += 4
        width = 6 if interval == 0 else 2
        if not 0 <= interval <= 1000 or not 0 <= count <= 1000 or pos+width*count > len(raw):
            raise ValueError('Bloque OTT inválido o truncado')
        values, times = [], []
        for i in range(count):
            values.append(struct.unpack_from('<h', raw, pos)[0])
            pos += 2
            if interval == 0:
                sample_time = epoch + dt.timedelta(seconds=struct.unpack_from('<i', raw, pos)[0])
                pos += 4
                if sample_time < epoch or sample_time > stamp:
                    raise ValueError('OTT: fecha de muestra asíncrona inválida')
            else:
                midnight = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
                slot = math.ceil((stamp-midnight).total_seconds() / (interval*60)) - 1
                sample_time = midnight + dt.timedelta(minutes=(slot-(count-1-i))*interval)
            times.append(sample_time)
        blocks.append((interval, OttValues(values, times)))
    if not blocks:
        raise ValueError('OTT: mensaje sin bloques')
    return blocks
