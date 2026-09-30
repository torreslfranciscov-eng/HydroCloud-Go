import datetime as dt
import struct
import unittest
import ast
from pathlib import Path
from telemetry_decoders import ott_blocks, ott_sensors, ott_value

EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
NOW = dt.datetime(2026, 9, 30, 15, 0, tzinfo=dt.timezone.utc)


class OttTests(unittest.TestCase):
    def frame(self, body, stamp=NOW, prefix=b'"OTA@'):
        raw = struct.pack('<i', int((stamp-EPOCH).total_seconds())) + body
        return ott_blocks(prefix+b'abcd', lambda _: raw, NOW)

    def test_time_order_and_exact_boundary(self):
        block = self.frame(struct.pack('<hhhh', 30, 2, 1200, 1300))[0][1]
        self.assertEqual(block.times, [NOW-dt.timedelta(hours=1), NOW-dt.timedelta(minutes=30)])
        self.assertEqual(block, [1200, 1300])

    def test_prefixes_and_nonboundary(self):
        for prefix in (b'"OTA@', b'`OTA@', b'bOTA@', b' OTA@'):
            block = self.frame(struct.pack('<hhh', 60, 1, 1417), NOW-dt.timedelta(minutes=1), prefix)[0][1]
            self.assertEqual(block.times[0], NOW-dt.timedelta(hours=1))

    def test_async(self):
        seconds = int((NOW-EPOCH).total_seconds())-42
        block = self.frame(struct.pack('<hhhi', 0, 1, 1234, seconds))[0][1]
        self.assertEqual(block.times, [NOW-dt.timedelta(seconds=42)])

    def test_stale_clock_rejected(self):
        with self.assertRaises(ValueError):
            self.frame(struct.pack('<hhh',60,1,1417), NOW-dt.timedelta(days=8))

    def test_main_wrapper(self):
        tree = ast.parse(Path('mycloud_all_timescale.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'decode_ott_binary')
        raw = struct.pack('<ihhh', int((NOW-EPOCH).total_seconds()),60,1,1417)
        scope = {'ConvertFrom6BitsTo8Bits': lambda _: raw}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated','exec'),scope)
        self.assertEqual(scope['decode_ott_binary'](b'"OTA@abcd',NOW)[0][1],[1417])

    def test_flags_and_voltage(self):
        sensor = dict(nombre='voltaje_de_batería', decimales=2)
        for raw in (-32768, -32767, -32763, -32758, -32701):
            self.assertEqual(ott_value(raw, sensor)[:2], (None, False))
        self.assertEqual(ott_value(1417, sensor)[:2], (14.17, True))
        self.assertEqual(ott_value(-120, sensor)[:2], (None, False))

    def test_catalog_order(self):
        sensors = [dict(numero_sensor='0001', orden=2, periodo=60,decimales=2,nombre='Nivel'), dict(numero_sensor='0002', orden=1, periodo=10,decimales=2,nombre='Nivel')]
        self.assertEqual(ott_sensors('x', [(10,[1]*6), (60,[2])], sensors,60), sensors[::-1])
        with self.assertRaises(ValueError):
            ott_sensors('x', [(10,[1]*6)], sensors,60)
        # Different sample counts are explicit in OTT; missing samples are not fabricated.
        self.assertEqual(ott_sensors('x',[(10,[1]*5),(60,[2])],sensors,60),sensors[::-1])
        sensors[1]['orden']=2
        with self.assertRaises(ValueError):ott_sensors('x',[(10,[1]*6),(60,[2])],sensors,60)

    def test_footer_and_truncation(self):
        body = struct.pack('<hhh',60,1,1417)
        self.assertEqual(len(self.frame(body+b'\x20\x00')),1)
        for tail in (b'\x01',b'\x31\x50'):
            self.assertEqual(len(self.frame(body+tail)),1)
        for tail in (b'\x01\x02\x03',b'\x01\x02\x03\x04'):
            with self.assertRaises(ValueError): self.frame(body+tail)
        with self.assertRaises(ValueError): self.frame(body[:-1])

    def test_ott_insertion_uses_wire_times_and_rolls_back(self):
        tree=ast.parse(Path('mycloud_all_timescale.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='insertar_datos_ott')
        sensor=dict(numero_sensor='0011',nombre='Voltaje de batería',unidad='V',orden=1,periodo=30,decimales=2)
        class Connection:
            def __init__(self):self.commits=0;self.rollbacks=0
            def cursor(self):return self
            def commit(self):self.commits+=1
            def rollback(self):self.rollbacks+=1
        for fail in (False,True):
            conn=Connection();rows=[];summaries=[]
            def write(c,sql,batch):
                rows.extend(batch)
                if fail:raise RuntimeError('Oracle simulado')
            scope=dict(datetime=dt,SENSORES={'x':[sensor]},ESTACIONES={'d':{'rango_transmision':60}},
                get_pg_conn=lambda:conn,release_pg_conn=lambda c:None,DB_BACKEND='oracle',
                oracle_bulk_upsert=write,_actualizar_ultimas_mediciones_oracle=lambda c,r:summaries.extend(r),
                hora_concurrente=lambda t,p:t,actualizar_resumenes_dcp=lambda *a:None)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated','exec'),scope)
            blocks=self.frame(struct.pack('<hhhh',30,2,1417,-32758))
            if fail:
                with self.assertRaises(RuntimeError):scope['insertar_datos_ott']('d','x',NOW,blocks)
            else:
                scope['insertar_datos_ott']('d','x',NOW,blocks)
                self.assertEqual([r[0] for r in rows],blocks[0][1].times)
                self.assertEqual([r[5] for r in rows],[14.17,None])
                self.assertEqual([r[7] for r in rows],[True,False])
                self.assertEqual(summaries,rows)
            self.assertEqual((conn.commits,conn.rollbacks),(0,1) if fail else (1,0))


if __name__ == '__main__':
    unittest.main()
