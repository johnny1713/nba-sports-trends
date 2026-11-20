"""來源探查：抽樣可重現、只寫 data/audit/、解析 ESPN 與 BBRef 的失誤相關欄位。"""
import gzip
import json
import os
import unittest

from nba_quant import source_audit

FX = os.path.join(os.path.dirname(__file__), 'fixtures')


class SourceAuditTests(unittest.TestCase):
    def test_espn_raw_turnover_fields_and_player_sum(self):
        s = json.loads(gzip.open(os.path.join(FX, 'summary_s2024_401585183.gz')).read())
        ts, pto, venue, raw = source_audit.espn_raw_fields(s)
        for tid, d in ts.items():
            self.assertIn('turnovers', d)
            self.assertIn('totalTurnovers', d)
            self.assertIn('teamTurnovers', d)
        self.assertEqual(set(pto), set(ts))
        self.assertTrue(all(isinstance(v, int) for v in pto.values()))
        self.assertIn('現在的名稱', venue['note'])

    def test_bbref_totals_and_player_tov(self):
        h = gzip.open(os.path.join(FX, 'bbref_box_202401150PHI.gz')).read().decode()
        g = {'game_id': '401585183', 'start_utc': '2024-01-15T18:00:00Z', 'home': '20', 'away': '10'}
        tot, ptov, meta = source_audit.bbref_fields(h, g)
        self.assertEqual(tot['10']['tov'], 13)
        self.assertEqual(tot['10']['pts'], 115)
        self.assertTrue(all(isinstance(v, int) for v in ptov.values()))
        self.assertTrue(meta['raw_meta'])

    def test_output_location_is_audit_dir_only(self):
        self.assertTrue(source_audit.OUT.startswith(os.path.join('data', 'audit')))
