"""Audit recent Oracle frames; optionally correct unambiguous *format labels*.

Does not import the ingestion process or rewrite measurements. Sensor profiles
are a separate requirement: a corrected label does not certify channel mapping.
Connection secrets are read from environment, never included in the report.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import os

from gs300_catalog import assign_positions, load_sensors
from telemetry_decoders import payload_family, text_records


def main():
    import oracledb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply-classification', action='store_true')
    parser.add_argument('--report', required=True, help='New JSON audit file (never overwritten)')
    args = parser.parse_args()
    # Reserve report before opening a write transaction. Existing reports survive.
    with open(args.report, 'x', encoding='utf-8') as output:
        catalog = oracledb.connect(user=os.environ['ORACLE_CATALOG_USER'],
            password=os.environ['ORACLE_CATALOG_PASSWORD'],
            dsn=os.environ.get('ORACLE_CATALOG_DSN') or os.environ['ORACLE_DSN'])
        history = oracledb.connect(user=os.environ['ORACLE_USER'],
            password=os.environ['ORACLE_PASSWORD'], dsn=os.environ['ORACLE_DSN'])
        report = {'checked_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'applied': False, 'stations': []}
        try:
            catalog.call_timeout = history.call_timeout = 60000
            sensors = load_sensors(catalog)
            with catalog.cursor() as cur:
                cur.execute('''SELECT G.IDESTACION, G.IDSATELITAL, E.IDASIGNADO,
                    G.DECODIFICADOR, G.RANGOTRANSMISION
                    FROM HYDROCLOUD.DATOSGOES G JOIN HYDROCLOUD.ESTACION E
                    ON E.ID=G.IDESTACION WHERE E.ACTIVO=1 AND E.GOES=1''')
                rows = cur.fetchall()
            counts = collections.Counter(str(r[1]).strip().upper() for r in rows)
            messages = collections.defaultdict(list)
            with history.cursor() as cur:
                cur.execute('''SELECT DCP_ID, STAMP, RAW_MESSAGE FROM (
                    SELECT DCP_ID, SYS_EXTRACT_UTC(TIMESTAMP_MSG) STAMP, RAW_MESSAGE,
                    ROW_NUMBER() OVER (PARTITION BY DCP_ID ORDER BY TIMESTAMP_MSG DESC) RN
                    FROM DCP_HEADERS WHERE TIMESTAMP_MSG>SYSTIMESTAMP-INTERVAL '2' DAY
                    AND RAW_MESSAGE IS NOT NULL) WHERE RN<=3''')
                for dcp, stamp, raw in cur:
                    if len(raw) < 37 or raw[:8].strip().upper() != dcp.strip().upper():
                        continue
                    payload = raw[37:].encode('latin1')
                    family = payload_family(payload)
                    if family in ('text', 'table_text'):
                        try:
                            text_records(payload, stamp, 'audit')
                        except (ValueError, UnicodeError):
                            family = 'unknown'
                    messages[dcp.strip().upper()].append((stamp, payload, family))
            from gs300_catalog import duration_minutes
            for station_id, raw_dcp, code, old, coverage in rows:
                dcp, code = str(raw_dcp).strip().upper(), str(code).strip()
                old = str(old).strip() if old is not None else None
                samples = messages[dcp]
                entry = dict(station_id=station_id, dcp=dcp, station=code,
                    old_decoder=old, proposed_decoder=None, evidence=[],
                    channel_mapping_verified=False)
                for stamp, payload, family in samples:
                    entry['evidence'].append(dict(utc=stamp.isoformat(), family=family,
                        sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)))
                families = {x[2] for x in samples}
                # No automatic conversion to GS300: a bB header alone cannot
                # prove channel order, decimals, coverage, or missing-data codes.
                if old == 'GS300' and len(samples) == 3 and counts[dcp] == 1:
                    entry['proposed_decoder'] = {
                        frozenset(['table_text']): 'SMN',
                        frozenset(['ota']): 'OTTBinario',
                        frozenset(['named']): 'GS',
                    }.get(frozenset(families))
                if 'pseudobinary_b' in families:
                    try:
                        configured = assign_positions(sensors.get(code, []), duration_minutes(coverage))
                        entry['expected_words'] = sum(len(s['posiciones']) for s in configured)
                        entry['received_words'] = [len(p.strip(b' \r\n')[4:])/3
                            for _, p, f in samples if f == 'pseudobinary_b']
                    except (ValueError, TypeError) as exc:
                        entry['catalog_error'] = str(exc)
                report['stations'].append(entry)
            proposals = [e for e in report['stations'] if e['proposed_decoder']]
            # Persist the before-image/evidence before any update. The report
            # remains marked false if a later operation fails.
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
            if args.apply_classification:
                with catalog.cursor() as cur:
                    for entry in proposals:
                        cur.execute('''UPDATE HYDROCLOUD.DATOSGOES SET DECODIFICADOR=:new
                            WHERE IDESTACION=:station AND UPPER(TRIM(IDSATELITAL))=:dcp
                            AND TRIM(DECODIFICADOR)=:old''',
                            new=entry['proposed_decoder'], station=entry['station_id'],
                            dcp=entry['dcp'], old=entry['old_decoder'])
                        if cur.rowcount != 1:
                            raise RuntimeError('Catálogo cambió o no es único: '+entry['dcp'])
                catalog.commit()
                report['applied'] = True
                output.seek(0)
                json.dump(report, output, ensure_ascii=False, indent=2)
                output.truncate()
                output.flush()
                os.fsync(output.fileno())
            print(json.dumps({'catalog_rows': len(rows),
                'with_recent_frames': sum(bool(e['evidence']) for e in report['stations']),
                'proposals': [(e['station'], e['old_decoder'], e['proposed_decoder']) for e in proposals],
                'applied': report['applied']}, ensure_ascii=False))
        except Exception:
            catalog.rollback()
            raise
        finally:
            history.close()
            catalog.close()


if __name__ == '__main__':
    main()
