import ast
import copy
import datetime as dt
import pathlib
import unittest
from gs300_catalog import assign_positions, validate_words, next_fetch, duration_minutes


class GS300Tests(unittest.TestCase):
    def sensors(self):
        return [dict(numero_sensor=n, periodo=p) for n,p in [('1001',1),('2001',60),('2002',60)]]

    def test_hour_of_minute_rain_and_hourly_auxiliary(self):
        s=assign_positions(self.sensors(),60)
        self.assertEqual(s[0]['posiciones'],list(range(60)))
        self.assertEqual(s[1]['posiciones'],[60])
        self.assertEqual(s[2]['posiciones'],[61])
        validate_words([0]*62,s)
        for count in [3,61,63]:
            with self.assertRaises(ValueError): validate_words([0]*count,s)

    def test_coverage_not_cadence(self):
        s=assign_positions(self.sensors(),180)
        self.assertEqual(s[1]['posiciones'],[180,181,182])
        data=dict(primera_transmision='00:55:35',intervalo_transmision=60,rango_transmision=180)
        now=dt.datetime(2026,9,28,16,0,tzinfo=dt.timezone.utc)
        self.assertEqual(next_fetch(data,now),now.replace(minute=57,second=35))
        data['intervalo_transmision']=180
        self.assertEqual(next_fetch(data,now),now.replace(hour=18,minute=57,second=35))

    def test_subminute_and_midnight(self):
        self.assertEqual(duration_minutes('00:00:30'),.5)
        data=dict(primera_transmision='00:59:35',intervalo_transmision=60)
        now=dt.datetime(2026,9,28,23,59,tzinfo=dt.timezone.utc)
        self.assertEqual(next_fetch(data,now),dt.datetime(2026,9,29,0,1,35,tzinfo=dt.timezone.utc))

    def test_invalid_period_rejected(self):
        with self.assertRaises(ValueError):assign_positions([dict(numero_sensor='1',periodo=7)],60)
        with self.assertRaises(ValueError):assign_positions([dict(numero_sensor='1',periodo=0)],60)

    def test_actual_binary_converter(self):
        # Import only the pure decoder, never start the ingestion module.
        tree=ast.parse(pathlib.Path('mycloud_all_timescale.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ConvertFrom6BitsSutron')
        scope={};exec(compile(ast.Module(body=[node],type_ignores=[]),'decoder','exec'),scope)
        # San Bartolo 2026-09-28 16:55:35: 60 rain zeros + 1360 + 2650.
        words=scope['ConvertFrom6BitsSutron'](b'@'*180+b'@UP@iZ')
        validate_words(words,assign_positions(self.sensors(),60))
        self.assertEqual(words[60]/100,13.60)
        self.assertEqual(words[61]/100,26.50)

    def test_radiocomunicacion_catalog_order(self):
        sensors=[dict(numero_sensor=n,periodo=p,orden=o,decoder='GS300') for n,p,o in
                 [('1001',5,1),('1010',5,4),('1011',5,5),('1012',5,6),('1015',5,10),('1016',5,11),('1017',5,7),('2001',60,2),('2002',60,3)]]
        mapped=assign_positions(sensors,60)
        self.assertEqual(next(s['posiciones'] for s in mapped if s['numero_sensor']=='2001'),[12])
        self.assertEqual(next(s['posiciones'] for s in mapped if s['numero_sensor']=='2002'),[13])
        validate_words([0]*86,mapped)
        sensors[0]['orden']=None
        with self.assertRaises(ValueError):assign_positions(sensors,60)

    def test_missing_is_not_minimum_signed_word(self):
        from telemetry_decoders import gs300_words,scaled_gs300_value
        self.assertEqual(gs300_words(b'@UM@lI`@@///'),[1357,2825,-131072,None])
        for word in [b'@U',b'//@',b'!!!']:
            with self.assertRaises(ValueError):gs300_words(word)
        battery=dict(nombre='Voltaje de batería',decimales=2,valor_minimo=0,valor_maximo=17)
        self.assertEqual(scaled_gs300_value(1357,battery),(13.57,True,'OK'))
        self.assertEqual(scaled_gs300_value(-131072,battery)[:2],(None,False))
        self.assertEqual(scaled_gs300_value(-100,dict(nombre='Temperatura',decimales=2))[:2],(-1,True))

    def test_invalid_sensor_cannot_replace_valid_legacy_summary(self):
        tree=ast.parse(pathlib.Path('mycloud_all_timescale.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_actualizar_ultimas_mediciones_oracle')
        captured=[]
        scope=dict(DB_BACKEND='oracle',_clean_oracle_bind_val=lambda x:x,oracle_bulk_upsert=lambda c,q,r:captured.extend(r))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated','exec'),scope)
        t=dt.datetime(2026,9,29,16)
        rows=[(t,'DCP','RIO','0012','voltaje_de_batería',13.45,'voltaje',True),
              (t,'DCP','RIO','0013','voltaje_de_batería',-1310.72,'voltaje',False)]
        scope['_actualizar_ultimas_mediciones_oracle'](None,rows)
        self.assertEqual(len(captured),1)
        self.assertEqual(captured[0][3],13.45)


if __name__=='__main__':unittest.main()
