import ast
import datetime as dt
import pathlib
import struct
import unittest
from unittest.mock import patch
import telemetry_decoders as d

NOW = dt.datetime(2026, 9, 28, 17, 47, 46, tzinfo=dt.timezone.utc)


class DecoderTests(unittest.TestCase):
    def test_wire_family_not_plausibility(self):
        cases = [(b'bB1A@UP', 'pseudobinary_b'), (b'`B1A@UP', 'pseudobinary_b'),
                 (b'`OTA@xyz', 'ota'), (b'bOTA@xyz', 'ota'),
                 (b'2 22:40:00 82,62,8.5', 'table_text'),
                 (b'23:00:00 12.4 7.2', 'text'),
                 (b'"\r\nNI 15 1.59\r\nVB 60 13.23', 'named'),
                 (b'":TA 47 #60 27.26', 'cila'),
                 (b'Missing message from 12345678 expected by 00:00', 'notice'),
                 (b'"SATLINK DATA BUFFER EMPTY test', 'notice')]
        for payload, family in cases:
            with self.subTest(payload=payload):self.assertEqual(d.payload_family(payload), family)

    def test_reject_wrong_decoder_and_partial_word(self):
        for payload in [b'2 22:40:00 82,62,8.5', b'`OTA@xyz',
                        b'Missing message from station', b'bB1A@U', b'bB1A!!!']:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                d.validate_decoder_payload('GS300', payload)
        self.assertEqual(d.validate_decoder_payload('GS300',b'bB1A@UP\r\n'),'pseudobinary_b')
        with self.assertRaises(ValueError):d.validate_decoder_payload('OTTBinario',b'bB1A@UP')

    def test_smn_columns_decimals_and_table(self):
        row=d.text_records(b'2 17:40:00 27.5,,13.9,#2', NOW, 'SMN')[0][1]
        self.assertEqual(row,[27.5,d.MISSING,13.9,d.MISSING])
        self.assertEqual(row.table,'2')

    def test_smn_ver2_text_and_midnight(self):
        stamp,values=d.text_records(b'23:50:00 348 324 14.4',NOW.replace(hour=0,minute=5),'SMN_ver2')[0]
        self.assertEqual(stamp.day,27)
        self.assertEqual(values,[348,324,14.4])
        self.assertEqual(values.table,'default')

    def test_smn_flag(self):
        stamp,values=d.text_records(b'02 202609281700,1,,3',NOW,'SMN')[0]
        self.assertEqual(values,[1,d.MISSING,3])
        self.assertEqual(stamp.hour,17)

    def test_vaisala_engineering_units(self):
        values=d.text_records(b'16:00:00 144 135 009.2 013.7 23.4 072 0880.4 1016.6 00.00 0210 13.36 015.2',NOW,'VAISALA')[0][1]
        self.assertEqual(values[4],23.4)
        self.assertEqual(values[10],13.36)
        with self.assertRaises(ValueError):d.record_sensors('unknown',values,[])

    def test_cila_offset_interval_precision(self):
        data=d.named_records(b'":TA 47 #60 27.26 :PP 2 #15 1.25 0.00 :BL 12.84"',NOW,True)
        self.assertEqual(data['TA'][0],(NOW.replace(minute=0,second=0),27.26))
        self.assertEqual(data['PP'][0][0].minute,45)
        self.assertEqual(data['PP'][1][0].minute,30)
        self.assertEqual(data['BL'][0][1],12.84)

    def test_gasir_alphanumeric_channels(self):
        data=d.named_records(b'"\r\nNI 10 4.60 4.60\r\nN2 10 4.55 4.55\r\nVB 60 13.93\r\n"',NOW)
        self.assertEqual(list(data),['NI','N2','VB'])
        self.assertEqual(len(data['NI']),2)
        self.assertEqual(data['N2'][0][1],4.55)

    def test_named_catalog_ids_partial_without_column_shift(self):
        data=d.named_records(b'NI 10 4.60 4.61\r\nTI 60 28.5\r\nVB 60 13.93',NOW)
        sensors=[dict(numero_sensor='00NI',nombre='Nivel',unidad='m',periodo=10),
                 dict(numero_sensor='00VB',nombre='Voltaje de batería',unidad='V',periodo=60)]
        with patch.object(d,'profile',return_value={}):
            mapped,rejected=d.named_sensor_channels('x',data,sensors)
        self.assertEqual({k:v['numero_sensor'] for k,v in mapped.items()},{'NI':'00NI','VB':'00VB'})
        self.assertEqual(set(rejected),{'TI'})
        sensors[0]['periodo']=15
        with patch.object(d,'profile',return_value={}):
            mapped,rejected=d.named_sensor_channels('x',data,sensors)
        self.assertEqual(set(mapped),{'VB'})
        self.assertIn('NI',rejected)
        sensors[1]['periodo']=10
        with patch.object(d,'profile',return_value={}):
            with self.assertRaises(ValueError):d.named_sensor_channels('x',data,sensors)

    def test_named_duplicate_or_unknown_does_not_guess(self):
        data={'NI':[(NOW,4.6)]}
        sensor=dict(numero_sensor='00NI',nombre='Nivel',unidad='m',periodo=10)
        with patch.object(d,'profile',return_value={}):
            with self.assertRaises(ValueError):d.named_sensor_channels('x',data,[sensor,sensor])
            with self.assertRaises(ValueError):d.named_sensor_channels('x',data,[])

    def test_ott_complete_and_truncated(self):
        raw=b'\0'*4+struct.pack('<hhhh',30,2,2920,2913)
        self.assertEqual(d.ott_blocks(b'"OTA@abc',lambda _:raw),[(30,[2920,2913])])
        for damaged in [raw[:-2],raw[:4]+struct.pack('<hh',30,3)+raw[8:],raw+b'\x01\x02\x03']:
            with self.assertRaises(ValueError):d.ott_blocks(b'"OTA@abc',lambda _:damaged)
        with self.assertRaises(ValueError):d.ott_blocks(b'bB1Ftest',lambda _:raw)

    def test_profiles_fail_closed(self):
        sensors=[dict(numero_sensor='0001',periodo=30)]
        with patch.object(d,'profile',return_value={}):
            with self.assertRaises(ValueError):d.ott_sensors('test',[(30,[1,2])],sensors,60)
        with patch.object(d,'profile',return_value={'ott_order':['0001'],'tables':{'2':['0001']}}):
            with self.assertRaises(ValueError):d.ott_sensors('test',[(30,[1,2])],sensors,60)
            sensors[0].update(orden=1,decimales=2,nombre='Nivel')
            self.assertEqual(d.ott_sensors('test',[(30,[1,2])],sensors,60),sensors)
            with self.assertRaises(ValueError):d.ott_sensors('test',[(30,[1,2,3,4])],sensors,60)
            self.assertEqual(d.record_sensors('test',d.Values([23.4],'2'),sensors),sensors)

    def test_period_90_minutes(self):
        self.assertEqual(d.align(NOW.replace(hour=2,minute=50),90).time(),dt.time(1,30))

    def test_insertion_preserves_text_decimals(self):
        tree=ast.parse(pathlib.Path('mycloud_all_timescale.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='insertar_datos_por_registro')
        captured=[]
        class Connection:
            def cursor(self):return self
            def commit(self):pass
            def rollback(self):pass
        sensor=dict(numero_sensor='0001',nombre='Temperatura',decimales=1,periodo=10)
        summaries=[]
        scope=dict(datetime=dt,SENSORES={'test':[sensor]},DB_BACKEND='oracle',get_pg_conn=lambda:Connection(),release_pg_conn=lambda _:None,oracle_bulk_upsert=lambda c,s,rows:captured.extend(rows),_actualizar_ultimas_mediciones_oracle=lambda c,rows:summaries.extend(rows))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated','exec'),scope)
        with patch.object(d,'profile',return_value={'tables':{'2':['0001']}}):scope['insertar_datos_por_registro']('dcp','test',NOW,d.Values([23.4],'2'))
        self.assertEqual(captured[0][5],23.4)
        self.assertEqual(summaries,captured)

    def test_so06_battery_and_panel_precision(self):
        row=d.text_records(b'13:50:00 328 333 013.4 018.0 26.4 086 1000.5 1000.9 00.00 0020 12.33 014.1', NOW, 'SMN_ver2')[0][1]
        sensors=[dict(numero_sensor=f'{n:04d}') for n in range(1,13)]
        with patch.dict(d.os.environ, {'DECODER_PROFILES_PATH':''}):
            ordered=d.record_sensors('SO06',row,sensors)
        self.assertEqual((ordered[10]['numero_sensor'],row[10]),('0011',12.33))
        self.assertEqual((ordered[11]['numero_sensor'],row[11]),('0012',14.1))
        with patch.dict(d.os.environ, {'DECODER_PROFILES_PATH':''}),self.assertRaises(ValueError):
            d.record_sensors('SO06',d.Values(row[:-1],'default'),sensors)

    def test_mixed_smn_tables_keep_voltage_order(self):
        sensors=[dict(numero_sensor=f'{n:04d}') for n in range(1,14)]
        records=d.text_records(b'2 15:00:00 349,346,4.8,7.9,27.2,77,979.0,0.00,268,#2,#2\r\n4 15:00:00 12.9,13.0',NOW,'SMN_ver2')
        with patch.dict(d.os.environ, {'DECODER_PROFILES_PATH':''}):
            self.assertEqual(len(d.record_sensors('MC38',records[0][1],sensors)),11)
            self.assertEqual([s['numero_sensor'] for s in d.record_sensors('MC38',records[1][1],sensors)],['0012','0013'])
        self.assertEqual(records[1][1],[12.9,13.0])

    def test_qr15_explicit_partial_profile_does_not_shift_columns(self):
        sensors=[dict(numero_sensor=f'{n:04d}') for n in range(1,13)]
        values=d.Values([171,14,1.7,4.3,26.2,d.MISSING,d.MISSING,d.MISSING,0,220,12.38,0],'default')
        with patch.dict(d.os.environ, {'DECODER_PROFILES_PATH':''}):
            mapped=d.record_sensors('QR15',values,sensors)
        self.assertEqual([i for i,s in enumerate(mapped) if s is not None],[10])
        self.assertEqual(mapped[10]['numero_sensor'],'0010')
        self.assertEqual(values[10],12.38)


if __name__=='__main__':unittest.main()
