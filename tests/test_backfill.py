"""離線整合測試：以 fixtures 假裝 ESPN，跑完整的單季回補 + 品質報告。"""
import gzip
import json
import os
import tempfile
import unittest

from nba_quant import backfill
from nba_quant.sources import http

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def L(n):
    return gzip.open(os.path.join(FX, n)).read()


class FakeFetcher(http.Fetcher):
    def get_bytes(self, url, headers=None):
        self.calls += 1
        if 'scoreboard' in url:
            return json.dumps(json.loads(L('scoreboard_s2024.gz')) if 'dates=20240115' in url else {'events': []}).encode()
        if '401585183' in url:
            return L('summary_s2024_401585183.gz' if 'summary' in url else 'odds_s2024_401585183.gz')
        self.errors.append((url, 404, 'no fixture'))
        raise http.FetchError(url, 404, 'no fixture')


class BackfillSmoke(unittest.TestCase):
    def test_single_season_pipeline_and_quality_gate(self):
        old_cwd, old_f = os.getcwd(), backfill.Fetcher
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                backfill.Fetcher = FakeFetcher
                rc = backfill.run_season(2024, log=lambda *a: None)
                q = json.load(open('data/raw/espn/2024/quality.json'))
                games = [json.loads(x) for x in gzip.open('data/raw/espn/2024/games.jsonl.gz').read().decode().splitlines()]
                odds = [json.loads(x) for x in gzip.open('data/raw/espn/2024/odds.jsonl.gz').read().decode().splitlines()]
                raw = [json.loads(x) for x in gzip.open('data/raw/espn/2024/odds_raw.jsonl.gz').read().decode().splitlines()]
                self.assertTrue(os.path.exists('docs/reports/data_quality/2024.md'))
            finally:
                backfill.Fetcher = old_f
                os.chdir(old_cwd)
        self.assertEqual(rc, 1)                                   # 只有 1/11 場完整 → 品質不通過，必須擋下
        self.assertFalse(q['verdict_ok'])
        ok = [g for g in games if g['complete']]
        self.assertEqual([g['game_id'] for g in ok], ['401585183'])
        self.assertTrue(all(g['complete_reason'] for g in games if not g['complete']))
        self.assertEqual(q['checks']['fails'], 0)
        self.assertIn('BetfairSportsbook', {x['provider'] for x in odds})
        self.assertEqual(len(raw[0]['items']), 12)                # 原始盤口完整保留
        self.assertEqual(q['completeness']['complete'], 1)


if __name__ == '__main__':
    unittest.main()
