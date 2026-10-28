import ast
import datetime as dt
from pathlib import Path
import unittest
from unittest.mock import patch

import telemetry_decoders as d


class VoltageValidationTests(unittest.TestCase):
    def test_names_and_negative_catalog_bound(self):
        for name in ('voltaje_de_batería', 'Voltaje de bateria', 'Voltaje del panel solar'):
            sensor = dict(nombre=name, valor_minimo=-999, valor_maximo=100)
            value, valid, note = d.engineering_value(-1.7, sensor)
            self.assertIsNone(value)
            self.assertFalse(valid)
            self.assertIn('-1.7', note)

    def test_no_rescaling_or_absolute_value(self):
        self.assertEqual(d.engineering_value(13.12, dict(nombre='Voltaje de batería', decimales=2)), (13.12, True, 'OK'))
        self.assertEqual(d.engineering_value(-8, dict(nombre='Temperatura')), (-8, True, 'OK'))
        self.assertEqual(d.engineering_value(0, dict(nombre='Voltaje del panel solar')), (0, True, 'OK'))

    def test_nonfinite(self):
        for value in (None, float('nan'), float('inf')):
            self.assertEqual(d.engineering_value(value, dict(nombre='Voltaje de batería'))[:2], (None, False))

    def test_actual_text_and_cila_writers(self):
        tree = ast.parse(Path('mycloud_all_timescale.py').read_text())
        for function in ('insertar_datos_por_registro', 'insertar_datos_cila'):
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            rows = []
            class Connection:
                def cursor(self): return self
                def commit(self): pass
                def rollback(self): pass
            conn = Connection()
            sensor = dict(numero_sensor='0011', nombre='Voltaje del panel solar', valor_minimo=-999, unidad='V', periodo=60)
            scope = dict(datetime=dt, SENSORES={'x': [sensor]}, DB_BACKEND='oracle',
                         get_pg_conn=lambda: conn, release_pg_conn=lambda c: None,
                         oracle_bulk_upsert=lambda c,s,r: rows.extend(r),
                         _actualizar_ultimas_mediciones_oracle=lambda c,r: None,
                         hora_concurrente=lambda t,p: t, actualizar_resumenes_dcp=lambda *a: None)
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'isolated', 'exec'), scope)
            stamp = dt.datetime(2026, 9, 30, 12)
            with patch.object(d, 'record_sensors', return_value=[sensor]), patch.object(d, 'profile', return_value={}):
                if function == 'insertar_datos_por_registro':
                    scope[function]('d', 'x', stamp, [-1.7])
                else:
                    scope[function]('d', 'x', {'11': [(stamp, -1.7)]})
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0][5])
            self.assertFalse(rows[0][7])
            self.assertIn('-1.7', rows[0][8])


if __name__ == '__main__':
    unittest.main()
