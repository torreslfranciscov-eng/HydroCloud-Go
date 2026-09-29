import unittest
import ast
import datetime as dt
from pathlib import Path
from unittest.mock import patch
import telemetry_decoders as d


def sensor(code, order, period=10, name='Temperatura', unit='°C'):
    return dict(numero_sensor=code,orden=order,periodo=period,nombre=name,
                unidad=unit,calculada=0,decoder='SMN',decimales=0)


class CatalogTests(unittest.TestCase):
    def test_catalog_order_not_sensor_number_or_json(self):
        sensors=[sensor('0001',20),sensor('0002',10)]
        with patch.object(d,'profile',side_effect=AssertionError('JSON no debe consultarse')):
            mapped=d.record_sensors('station',d.Values([17.6,12.3],'2'),sensors)
        self.assertEqual([s['numero_sensor'] for s in mapped],['0002','0001'])

    def test_hourly_voltage_group(self):
        sensors=[sensor('0001',1),sensor('0010',10,60,'Voltaje de batería','V'),sensor('0011',11,60,'Voltaje del panel solar','V')]
        self.assertEqual([s['numero_sensor'] for s in d.record_sensors('x',d.Values([13.1,13.0],'4'),sensors)],['0010','0011'])

    def test_no_truncation_unknown_tables_or_duplicate_order(self):
        for values,sensors in [(d.Values([1],'2'),[sensor('1',1),sensor('2',2)]),
                               (d.Values([1,2],'2'),[sensor('1',1),sensor('2',1)]),
                               (d.Values([1],'10'),[sensor('1',1)]),
                               (d.Values([1],'2'),[sensor('1',None)]),
                               (d.Values([1],'2'),[sensor('1',1,unit=None)])]:
            with self.subTest(values=values,sensors=sensors),self.assertRaises(ValueError):
                d.record_sensors('x',values,sensors)

    def test_wrong_voltage_unit_rejected(self):
        sensors=[sensor('10',10,60,'Voltaje de batería','mV'),sensor('11',11,60,'Voltaje del panel solar','V')]
        with self.assertRaises(ValueError):d.record_sensors('x',d.Values([12,13],'4'),sensors)

    def test_message_transaction_and_rollback(self):
        tree=ast.parse(Path('mycloud_all_timescale.py').read_text())
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('insertar_datos_por_registro','insertar_mensaje_textual')]
        class Connection:
            def __init__(self):self.commits=0;self.rollbacks=0
            def cursor(self):return self
            def commit(self):self.commits+=1
            def rollback(self):self.rollbacks+=1
        for fail in (False,True):
            conn=Connection();rows=[];released=[]
            def write(cur,sql,batch):
                rows.extend(batch)
                if fail and len(rows)>1:raise RuntimeError('Fallo Oracle simulado')
            scope=dict(datetime=dt,SENSORES={'x':[sensor('0001',1)]},DB_BACKEND='oracle',get_pg_conn=lambda:conn,release_pg_conn=released.append,oracle_bulk_upsert=write,_actualizar_ultimas_mediciones_oracle=lambda c,r:None)
            exec(compile(ast.Module(body=functions,type_ignores=[]),'isolated','exec'),scope)
            records=[(dt.datetime(2026,9,29,12),d.Values([17.6],'2')),(dt.datetime(2026,9,29,12,10),d.Values([18.3],'2'))]
            if fail:
                with self.assertRaises(RuntimeError):scope['insertar_mensaje_textual']('d','x',records)
            else:
                scope['insertar_mensaje_textual']('d','x',records)
                self.assertEqual([r[5] for r in rows],[17.6,18.3])
            self.assertEqual((conn.commits,conn.rollbacks),(0,1) if fail else (1,0))
            self.assertEqual(released,[conn])


if __name__=='__main__':unittest.main()
