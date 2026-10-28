import datetime as dt
import unittest
from repair_so06_voltages import decode_voltages, STATIONS


class SO06RepairTests(unittest.TestCase):
    def setUp(self):
        self.received = dt.datetime(2026,9,29,14,30,1)
        self.header = '15B6A15026272143001G33-0NN169EXE00472'
        self.line = '13:50:00 328 333 013.4 018.0 26.4 086 1000.5 1000.9 00.00 0020 12.33 014.1'

    def decode(self, messages):
        return decode_voltages(messages,dt.datetime(2026,9,22),dt.datetime(2026,9,30))

    def test_values_and_timestamp_preserved(self):
        result, skipped = self.decode([(self.received,self.header+self.line)])
        self.assertEqual(result, {(dt.datetime(2026,9,29,13,50),'0011'):12.33,
                                  (dt.datetime(2026,9,29,13,50),'0012'):14.1})
        self.assertEqual(skipped,[])

    def test_repeated_identical_message_is_idempotent(self):
        msg = self.received,self.header+self.line
        self.assertEqual(len(self.decode([msg,msg])[0]),2)

    def test_conflicting_retransmission_rejected(self):
        with self.assertRaises(ValueError):
            self.decode([(self.received,self.header+self.line),
                         (self.received,self.header+self.line.replace('12.33','13.33'))])

    def test_negative_missing_or_wrong_columns_rejected(self):
        for line in [self.line.replace('12.33','-12.33'),self.line.replace('12.33','///'),
                     self.line+' 99',self.line.replace('13:50:00','13:55:00')]:
            with self.subTest(line=line),self.assertRaises(ValueError):
                self.decode([(self.received,self.header+line)])

    def test_mc38_voltage_table_is_not_weather_table(self):
        dcp,sensors,table,count=STATIONS['MC38']
        raw=dcp+self.header[8:]+'2 13:50:00 2,3,4,5,6,7,8,9,10,#2,#2\r\n4 14:00:00 12.9,13.0'
        result,_=decode_voltages([(self.received,raw)],dt.datetime(2026,9,22),dt.datetime(2026,9,30),dcp,sensors,table,count)
        self.assertEqual(result,{(dt.datetime(2026,9,29,14),'0012'):12.9,(dt.datetime(2026,9,29,14),'0013'):13.0})


if __name__=='__main__':unittest.main()
