import datetime as dt
import unittest
from reconcile_goes_lrgs import proposal,wire_decoder


class ReconcileTests(unittest.TestCase):
    def row(self):return dict(decoder='OTTBinario',primary=55,alarm=0)
    def frames(self,decoder='GS300',channel=95):
        return [dict(utc=f'2026-09-30T{h:02}:00:00',decoder=decoder,channel=channel) for h in (10,11,12)]
    def test_consistent_changes(self):
        self.assertEqual(proposal(self.row(),self.frames())['changes'],dict(decoder='GS300',primary=95))
    def test_no_alarm_reassignment(self):
        r=self.row();r['alarm']=95
        self.assertNotIn('primary',proposal(r,self.frames())['changes'])
    def test_conflict_and_insufficient(self):
        f=self.frames();f.append(dict(f[0],channel=100))
        self.assertEqual(proposal(self.row(),f)['changes'],{})
        self.assertEqual(proposal(self.row(),self.frames()[:2])['changes'],{})
        self.assertEqual(proposal(self.row(),self.frames(),True)['changes'],{})
    def test_keep_compatible_text(self):
        r=self.row();r['decoder']='SMN_ver2'
        self.assertNotIn('decoder',proposal(r,self.frames('SMN'))['changes'])
    def test_wire_signature(self):
        now=dt.datetime(2026,9,30,12)
        self.assertEqual(wire_decoder(b'bB1F@UP',now),'GS300')
        with self.assertRaises(ValueError):wire_decoder(b'bB1F@U',now)
        self.assertIsNone(wire_decoder(b'12:00:00 12.4,13.1',now))


if __name__=='__main__':unittest.main()
