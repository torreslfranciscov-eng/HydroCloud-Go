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


if __name__=='__main__':unittest.main()
