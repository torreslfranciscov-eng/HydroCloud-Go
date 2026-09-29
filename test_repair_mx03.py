import datetime as dt
import unittest
from repair_mx03 import samples_from_raw


class MX03Tests(unittest.TestCase):
    def test_raw_tables_keep_units_and_sample_time(self):
        sensors=[dict(numero_sensor=f'{n:04d}',nombre=f'sensor{n}',decimales=0,
                      periodo=10 if n<10 else 60) for n in range(1,12)]
        raw='15AFD60226271221346G37-0NN059EXE00336"\r\n2 22:00:00 119,129,1.6,1.6,17.6,100,748.3,0.00,56\r\n4 22:00:00 13.1,13.0'
        t=dt.datetime(2026,9,28,22)
        args=([(t+dt.timedelta(minutes=13,seconds=46),raw)],sensors,t-dt.timedelta(days=1),t+dt.timedelta(days=1))
        data=samples_from_raw(*args)
        self.assertEqual(len(data),11)
        for sensor,value in [('0003',1.6),('0005',17.6),('0007',748.3),('0010',13.1),('0011',13.0)]:
            self.assertEqual(data[(t,sensor)][0],value)
        with self.assertRaises(ValueError):
            samples_from_raw([(args[0][0][0],raw.replace('13.1,13.0','13.1'))],*args[1:])


if __name__=='__main__':unittest.main()
