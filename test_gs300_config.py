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

    def test_calculated_sensor_does_not_consume_wire_positions(self):
        sensors=[
            dict(numero_sensor='0001',periodo=10,orden=1,decoder='GS300',calculada=0),
            dict(numero_sensor='3001',periodo=10,orden=2,decoder='GS300',calculada=1),
            dict(numero_sensor='0901',periodo=60,orden=3,decoder='GS300',calculada=0),
        ]
        mapped=assign_positions(sensors,60)
        self.assertEqual(mapped[0]['posiciones'],list(range(6)))
        self.assertEqual(mapped[1]['posiciones'],[])
        self.assertEqual(mapped[2]['posiciones'],[6])
        validate_words([0]*7,mapped)

    def test_el_portillo_constrained_auxiliary_suffix(self):
        sensors = [
            dict(numero_sensor='0001', periodo=10, orden=1, decoder='GS300'),
            dict(numero_sensor='0002', periodo=60, orden=2, decoder='GS300'),
            dict(numero_sensor='0007', periodo=10, orden=3, decoder='GS300'),
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 26)
        validate_words([0] * 26 + [1] * 12, mapped, station='0000000G21')
        with self.assertRaises(ValueError):
            validate_words([0] * 26 + [1] * 12, mapped, station='OTRA')
        with self.assertRaises(ValueError):
            validate_words([0] * 26 + [2] * 12, mapped, station='0000000G21')

    def test_corrales_constrained_auxiliary_suffix(self):
        sensors = [
            dict(numero_sensor='0001', periodo=10, orden=1, decoder='GS300'),
            dict(numero_sensor='0002', periodo=10, orden=2, decoder='GS300'),
        ] + [
            dict(numero_sensor=str(index), periodo=60, orden=index,
                 decoder='GS300')
            for index in range(3, 10)
        ]
        mapped = assign_positions(sensors, 60)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 19)
        validate_words([0] * 19 + [0, 336], mapped, station='000000LG16')
        with self.assertRaises(ValueError):
            validate_words([0] * 19 + [1, 336], mapped, station='000000LG16')
        with self.assertRaises(ValueError):
            validate_words([0] * 19 + [0, 1001], mapped, station='000000LG16')

    def test_carrizal_internal_temperature_auxiliary_suffix(self):
        sensors = [
            dict(numero_sensor='0001', periodo=10, orden=1, decoder='GS300'),
            dict(numero_sensor='0020', periodo=10, orden=2, decoder='GS300'),
            dict(numero_sensor='0018', periodo=60, orden=3, decoder='GS300'),
            dict(numero_sensor='0019', periodo=60, orden=4, decoder='GS300'),
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 28)
        validate_words([0] * 28 + [2450, 3475], mapped,
                       station='CAZLVER018')
        with self.assertRaises(ValueError):
            validate_words([0] * 28 + [1499, 3475], mapped,
                           station='CAZLVER018')
        with self.assertRaises(ValueError):
            validate_words([0] * 30, mapped, station='OTRA')

    def test_cotaxtla_internal_temperature_auxiliary_suffix(self):
        sensors = [
            dict(numero_sensor='0001', periodo=10, orden=1, decoder='GS300'),
            dict(numero_sensor='0003', periodo=10, orden=2, decoder='GS300'),
            dict(numero_sensor='0009', periodo=10, orden=3, decoder='GS300'),
            dict(numero_sensor='0020', periodo=10, orden=4, decoder='GS300'),
            dict(numero_sensor='0018', periodo=60, orden=5, decoder='GS300'),
            dict(numero_sensor='0019', periodo=60, orden=6, decoder='GS300'),
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 52)
        validate_words([0] * 52 + [2600, 2425], mapped,
                       station='COTAVER010')
        with self.assertRaises(ValueError):
            validate_words([0] * 52 + [1499, 2425], mapped,
                           station='COTAVER010')
        with self.assertRaises(ValueError):
            validate_words([0] * 54, mapped, station='OTRA')

    def test_escotadura_diagnostic_auxiliary_suffix(self):
        sensors = [
            dict(numero_sensor='0001', periodo=10, orden=1, decoder='GS300'),
            dict(numero_sensor='0002', periodo=10, orden=2, decoder='GS300'),
            dict(numero_sensor='0005', periodo=60, orden=7, decoder='GS300'),
            dict(numero_sensor='0006', periodo=60, orden=8, decoder='GS300'),
            dict(numero_sensor='0007', periodo=10, orden=9, decoder='GS300'),
            dict(numero_sensor='0008', periodo=10, orden=10, decoder='GS300'),
            dict(numero_sensor='0009', periodo=10, orden=11, decoder='GS300'),
        ]
        mapped = assign_positions(sensors, 60)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 32)
        suffix = [-185, 0, 185, 185, 0, 0, -18, 0, 18, 0, -18, 0]
        validate_words([0] * 32 + suffix, mapped, station='ESCODISI05')
        with self.assertRaises(ValueError):
            validate_words([0] * 32 + [2001] + suffix[1:], mapped,
                           station='ESCODISI05')
        with self.assertRaises(ValueError):
            validate_words([0] * 44, mapped, station='OTRA')

    def test_francisco_madero_internal_temperature_suffix(self):
        sensors = [
            dict(numero_sensor=number, periodo=period, orden=order,
                 decoder='GS300')
            for number, period, order in (
                ('0031', 10, 1), ('0036', 10, 2), ('0041', 10, 3),
                ('0046', 10, 4), ('0047', 10, 5), ('0048', 10, 8),
                ('0049', 10, 9), ('0901', 60, 10), ('0902', 10, 11),
                ('0903', 10, 12),
            )
        ]
        mapped = assign_positions(sensors, 60)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 55)
        validate_words([0] * 55 + [2750], mapped, station='FCOITAB004')
        with self.assertRaises(ValueError):
            validate_words([0] * 55 + [1499], mapped, station='FCOITAB004')
        with self.assertRaises(ValueError):
            validate_words([0] * 56, mapped, station='OTRA')

    def test_gonzalez_tam_internal_temperature_suffix(self):
        sensors = [
            dict(numero_sensor=number, periodo=period, orden=order,
                 decoder='GS300')
            for number, period, order in (
                ('0001', 60, 1), ('0002', 60, 2), ('0003', 60, 3),
                ('0004', 60, 4), ('0005', 60, 5), ('0006', 10, 6),
                ('0007', 10, 7), ('0008', 10, 8), ('0009', 10, 9),
                ('0010', 10, 10), ('0011', 10, 11), ('0014', 60, 14),
            )
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 84)
        validate_words([0] * 84 + [2825, 2850], mapped,
                       station='GONZTAM001')
        with self.assertRaises(ValueError):
            validate_words([0] * 84 + [1499, 2850], mapped,
                           station='GONZTAM001')

    def test_huimanguillo_virtual_intensity_uses_no_wire_words(self):
        sensors = [
            dict(numero_sensor=number, periodo=period, orden=order,
                 decoder='GS300', calculada=calculated)
            for number, period, order, calculated in (
                ('0001', 10, 1, 0), ('0002', 10, 2, 0),
                ('0003', 10, 3, 0), ('0006', 10, 8, 0),
                ('0007', 10, 9, 0), ('0008', 10, 10, 0),
                ('0009', 10, 11, 0), ('0011', 10, 12, 1),
                ('0012', 10, 13, 0), ('0013', 10, 14, 0),
                ('0016', 60, 17, 0),
            )
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 110)
        self.assertEqual(next(sensor for sensor in mapped
                              if sensor['numero_sensor'] == '0011')['posiciones'], [])
        validate_words([0] * 110, mapped, station='HUIMA27XXX')

    def test_huixtla_verified_physical_layout_uses_110_words(self):
        sensors = [
            dict(numero_sensor=number, periodo=period, orden=order,
                 decoder='GS300', calculada=0)
            for number, period, order in (
                ('0001', 10, 1), ('0002', 10, 2), ('0003', 10, 3),
                ('0006', 10, 6), ('0007', 10, 7), ('0008', 10, 8),
                ('0009', 10, 9), ('0012', 10, 11), ('0013', 10, 12),
                ('0016', 60, 15),
            )
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 110)
        validate_words([0] * 110, mapped, station='HUIXT07077')

    def test_jamapa_layout_accepts_final_logger_temperature(self):
        sensors = [
            dict(numero_sensor=str(number).zfill(4), periodo=period,
                 orden=order, decoder='GS300', calculada=0)
            for order, (number, period) in enumerate(
                [(number, 10) for number in range(1, 14)] + [(19, 60)],
                start=1)
        ]
        mapped = assign_positions(sensors, 60)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 79)
        validate_words([0] * 79 + [3000], mapped, station='JAMAVER008')
        with self.assertRaisesRegex(ValueError, 'sufijo auxiliar inválido'):
            validate_words([0] * 79 + [1000], mapped, station='JAMAVER008')

    def test_lacantun_verified_layout_uses_148_words(self):
        periods = [10] * 10 + [60, 10, 10, 60]
        sensors = [
            dict(numero_sensor=str(order).zfill(4), periodo=period,
                 orden=order, decoder='GS300', calculada=0)
            for order, period in enumerate(periods, start=1)
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 148)
        validate_words([0] * 148, mapped, station='LACAN07337')

    def test_la_encrucijada_verified_layout_uses_110_words(self):
        sensors = [
            dict(numero_sensor=number, periodo=period, orden=order,
                 decoder='GS300', calculada=0)
            for number, period, order in (
                ('0001', 10, 1), ('0002', 10, 2), ('0003', 10, 3),
                ('0006', 10, 6), ('0007', 10, 7), ('0008', 10, 8),
                ('0009', 10, 9), ('0012', 10, 11), ('0013', 10, 12),
                ('0016', 60, 15),
            )
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 110)
        validate_words([0] * 110, mapped, station='LENCR07XXX')

    def test_emiliano_zapata_missing_channels_are_undefined(self):
        sensors = [
            dict(numero_sensor='0001', periodo=10, orden=1, decoder='GS300'),
            dict(numero_sensor='0002', periodo=10, orden=2, decoder='GS300'),
        ] + [
            dict(numero_sensor=str(index).zfill(4), periodo=60, orden=index,
                 decoder='GS300')
            for index in range(3, 13)
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 44)
        words = [0] * 38
        validate_words(words, mapped, station='00000CFE05')
        self.assertEqual(len(words), 44)
        self.assertEqual(words[-6:], [None] * 6)
        with self.assertRaises(ValueError):
            validate_words([0] * 38, mapped, station='OTRA')
        with self.assertRaises(ValueError):
            validate_words([0] * 37, mapped, station='00000CFE05')

    def test_desfogue_uses_penitas_layout_with_undefined_suffix(self):
        sensors = [
            dict(numero_sensor=str(index).zfill(4),
                 periodo=10 if index in (1, 2, 3, 15, 16) else 60,
                 orden=index, decoder='GS300')
            for index in range(1, 17)
        ]
        mapped = assign_positions(sensors, 120)
        self.assertEqual(sum(len(sensor['posiciones']) for sensor in mapped), 82)
        words = list(range(38))
        validate_words(words, mapped, station='00000CFE06')
        self.assertEqual(words[:38], list(range(38)))
        self.assertEqual(words[38:], [None] * 44)
        with self.assertRaises(ValueError):
            validate_words([0] * 39, mapped, station='00000CFE06')

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
