"""Infer GS300 wire layouts from repeated frames; read-only and conservative."""
import collections
import datetime as dt
import json
import math
from pathlib import Path

from telemetry_decoders import gs300_words


PERIODS = (1, 2, 5, 10, 15, 30, 60, 120, 180, 360)
COVERAGES = (30, 60, 70, 90, 120, 180, 240, 360)


def physical_range(sensor):
    low = float(sensor.get('valor_minimo', -math.inf))
    high = float(sensor.get('valor_maximo', math.inf))
    name = sensor['nombre'].lower()
    if 'voltaje' in name and 'bater' in name:
        low, high = max(low, 7), min(high, 18)
    elif 'temperatura' in name:
        low, high = max(low, -40), min(high, 80)
    elif 'humedad' in name:
        low, high = max(low, 0), min(high, 101)
    elif 'direcci' in name:
        low, high = max(low, 0), min(high, 360)
    return low, high


def frames(entry):
    result = []
    for frame in entry['frames']:
        try:
            payload = frame['raw'][37:].encode('latin1').strip(b' \r\n')
            if payload[1:3] != b'B1':
                continue
            values = gs300_words(payload[4:])
            result.append((dt.datetime.fromisoformat(frame['received']), values))
        except (ValueError, IndexError):
            continue
    if not result:
        return []
    counts = collections.Counter(len(values) for _, values in result)
    length, _ = counts.most_common(1)[0]
    return sorted((stamp, values) for stamp, values in result if len(values) == length)


def word_count(coverage, period):
    ratio = coverage / period
    if ratio < 1:
        return 1
    if not math.isclose(ratio, round(ratio), abs_tol=1e-9):
        return None
    return int(round(ratio))


def segment_evidence(sensor, period, start, count, samples):
    decimals = int(sensor['decimales'])
    low, high = physical_range(sensor)
    present = bad = 0
    for _, values in samples:
        for raw in values[start:start + count]:
            if raw is None:
                continue
            present += 1
            value = raw / (10 ** decimals)
            bad += not low <= value <= high
    overlap_total = overlap_bad = 0
    for (old_stamp, old), (new_stamp, new) in zip(samples, samples[1:]):
        elapsed = (new_stamp - old_stamp).total_seconds() / 60
        shift = elapsed / period
        if not math.isclose(shift, round(shift), abs_tol=.05):
            continue
        shift = int(round(shift))
        if 0 < shift < count:
            left = old[start:start + count - shift]
            right = new[start + shift:start + count]
            for a, b in zip(left, right):
                if a is None or b is None:
                    continue
                overlap_total += 1
                overlap_bad += a != b
    # A wrong boundary/period is decisively rejected by failed exact overlap.
    cost = bad * 25 + overlap_bad * 100 - (overlap_total - overlap_bad) * 2
    return cost, {
        'range_values': present,
        'range_failures': bad,
        'overlap_values': overlap_total,
        'overlap_failures': overlap_bad,
    }


def candidates(entry):
    samples = frames(entry)
    if len(samples) < 3:
        return []
    target = len(samples[0][1])
    sensors = sorted([item for item in entry['sensors']
                      if not item.get('calculada')],
                     key=lambda item: float(item['orden']))
    evidence_cache = {}
    current_coverage = float(entry['station']['rango_transmision'])
    coverages = sorted(set(COVERAGES + (int(round(current_coverage)),)))
    results = []
    for coverage in coverages:
        states = {(0, 0): [(0, [], [])]}
        for index, sensor in enumerate(sensors):
            next_states = {}
            for (old_index, position), plans in states.items():
                assert old_index == index
                for score, layout, evidence in plans:
                    # Absent physical channel: proposed inactive sensor.
                    key = (index + 1, position)
                    option = (score + 6, layout + [{
                        'sensor_id': sensor['numero_sensor'], 'active': 0,
                        'old_period': sensor['periodo'],
                    }], evidence + [{}])
                    next_states.setdefault(key, []).append(option)
                    periods = sorted(set(PERIODS + (float(sensor['periodo']),)))
                    for period in periods:
                        count = word_count(coverage, period)
                        if count is None or position + count > target:
                            continue
                        cache_key = (index, period, position, count)
                        if cache_key not in evidence_cache:
                            evidence_cache[cache_key] = segment_evidence(
                                sensor, period, position, count, samples)
                        local, proof = evidence_cache[cache_key]
                        change_cost = 0 if math.isclose(
                            period, float(sensor['periodo'])) else 2
                        key = (index + 1, position + count)
                        option = (score + local + change_cost,
                                  layout + [{
                                      'sensor_id': sensor['numero_sensor'],
                                      'active': 1,
                                      'old_period': sensor['periodo'],
                                      'new_period': period,
                                      'start': position,
                                      'count': count,
                                  }], evidence + [proof])
                        next_states.setdefault(key, []).append(option)
            states = {}
            for key, plans in next_states.items():
                states[key] = sorted(plans, key=lambda item: item[0])[:8]
        for score, layout, evidence in states.get((len(sensors), target), []):
            score += 0 if math.isclose(coverage, current_coverage) else 2
            active_evidence = [p for item, p in zip(layout, evidence)
                               if item['active']]
            results.append({
                'score': score,
                'coverage': coverage,
                'old_coverage': current_coverage,
                'observed_words': target,
                'frame_count': len(samples),
                'range_failures': sum(p['range_failures'] for p in active_evidence),
                'range_values': sum(p['range_values'] for p in active_evidence),
                'overlap_failures': sum(p['overlap_failures'] for p in active_evidence),
                'overlap_values': sum(p['overlap_values'] for p in active_evidence),
                'layout': layout,
            })
    return sorted(results, key=lambda item: item['score'])[:5]


def main():
    audit = json.loads(Path('live-ingestion-audit.json').read_text())
    report = {}
    for dcp, entry in audit.items():
        station = entry.get('station') or {}
        if station.get('decoder') != 'GS300' or not entry.get('sensors'):
            continue
        samples = frames(entry)
        if not samples:
            continue
        expected = 0
        valid = True
        for sensor in entry['sensors']:
            if sensor.get('calculada'):
                continue
            count = word_count(station['rango_transmision'], sensor['periodo'])
            if count is None:
                valid = False
                break
            expected += count
        if valid and expected == len(samples[0][1]):
            continue
        report[station['id_asignado']] = {
            'dcp': dcp,
            'name': station['nombre'],
            'current_range': station['rango_transmision'],
            'observed_words': len(samples[0][1]),
            'stable_frames': len(samples),
            'candidates': candidates(entry),
        }
    Path('GS300_CATALOGO_CANDIDATOS_20261001.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({
        'stations': len(report),
        'with_candidates': sum(bool(item['candidates']) for item in report.values()),
        'without_candidates': sum(not item['candidates'] for item in report.values()),
    }))


if __name__ == '__main__':
    main()
