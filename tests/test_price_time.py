"""價格時間性質：沒有時間戳就不推測；CLV 只能用供應商標記的收盤。"""
import gzip
import json
import os
import unittest

from nba_quant import price_time as pt
from nba_quant.sources import espn

START = '2026-01-10T00:30:00Z'
FX = os.path.join(os.path.dirname(__file__), 'fixtures')


def q(stage, **kw):
    d = {'game_id': 'g1', 'provider': 'B', 'provider_type': 'book', 'stage': stage, 'market': 'spread', 'side': 'home',
         'line': -5.5, 'price_decimal': 1.91, 'fetched_at': '2026-01-11T09:00:00Z', 'observed_at': None}
    d.update(kw)
    return d


class ClassifyTests(unittest.TestCase):
    def test_espn_open_close_without_timestamp_are_provider_labeled(self):
        self.assertEqual(pt.classify(q('open'), START), pt.PROVIDER_LABELED_OPEN)
        self.assertEqual(pt.classify(q('close'), START), pt.PROVIDER_LABELED_CLOSE)

    def test_fetched_at_is_never_used_as_price_time(self):
        """fetched_at 是我們抓取的時間（這裡在開賽後），不能拿來推測收盤時間 → 仍是 PROVIDER_LABELED，不升級、不判無效。"""
        self.assertEqual(pt.classify(q('close', fetched_at='2026-01-11T09:00:00Z'), START), pt.PROVIDER_LABELED_CLOSE)
        self.assertEqual(pt.classify(q('close', fetched_at='2026-01-09T09:00:00Z'), START), pt.PROVIDER_LABELED_CLOSE)

    def test_timestamp_verified_only_when_before_start(self):
        self.assertEqual(pt.classify(q('close', provider_timestamp='2026-01-10T00:25:00Z'), START), pt.TIMESTAMP_VERIFIED_CLOSE)
        self.assertEqual(pt.classify(q('open', provider_timestamp='2026-01-08T15:00:00Z'), START), pt.TIMESTAMP_VERIFIED_OPEN)
        self.assertEqual(pt.classify(q('close', provider_timestamp='2026-01-10T00:30:00Z'), START), pt.INVALID_AFTER_START)
        self.assertEqual(pt.classify(q('close', provider_timestamp='2026-01-10T01:10:00Z'), START), pt.INVALID_AFTER_START)

    def test_postgame_and_snapshots(self):
        self.assertEqual(pt.classify(q('current_postgame'), START), pt.POSTGAME_SNAPSHOT)
        self.assertEqual(pt.classify(q('snapshot', observed_at='2026-01-09T13:30:00Z'), START), pt.PREGAME_SNAPSHOT)
        self.assertEqual(pt.classify(q('snapshot', observed_at='2026-01-10T01:00:00Z'), START), pt.INVALID_AFTER_START)


class ClvTests(unittest.TestCase):
    def test_clv_accepts_only_provider_labeled_or_verified_close(self):
        quotes = [q('open'), q('close'), q('current_postgame'), q('snapshot', observed_at='2026-01-09T13:30:00Z'),
                  q('close', provider='V', provider_timestamp='2026-01-10T00:20:00Z'),
                  q('close', provider='LATE', provider_timestamp='2026-01-10T02:00:00Z')]
        got = pt.clv_closing_quotes(quotes, START)
        self.assertEqual({(x['provider'], x['time_class']) for x in got},
                         {('B', pt.PROVIDER_LABELED_CLOSE), ('V', pt.TIMESTAMP_VERIFIED_CLOSE)})
        pt.assert_clv_close(got, START)

    def test_clv_rejects_postgame_snapshot(self):
        with self.assertRaises(pt.PriceTimeError):
            pt.assert_clv_close([q('current_postgame')], START)
        with self.assertRaises(pt.PriceTimeError):
            pt.assert_clv_close([q('open')], START)

    def test_real_espn_quotes_carry_no_fabricated_time(self):
        """真實 ESPN 盤口：開盤／收盤都沒有 provider_timestamp，分類一定是 PROVIDER_LABELED_*。"""
        payload = json.loads(gzip.open(os.path.join(FX, 'odds_s2024_401585183.gz')).read())
        quotes, _, _ = espn.parse_odds(payload, '401585183', True, '2026-11-20T03:00:00Z')
        self.assertTrue(all(x.get('provider_timestamp') is None for x in quotes))
        classes = {pt.classify(x, '2024-01-15T18:00:00Z') for x in quotes if x['provider_type'] == 'book'}
        self.assertEqual(classes, {pt.PROVIDER_LABELED_OPEN, pt.PROVIDER_LABELED_CLOSE})

    def test_summary_counts(self):
        s = pt.verification_summary([q('close'), q('close', provider='V', provider_timestamp='2026-01-10T00:20:00Z'),
                                     q('current_postgame')], {'g1': START})
        self.assertEqual(s, {pt.PROVIDER_LABELED_CLOSE: 1, pt.TIMESTAMP_VERIFIED_CLOSE: 1, pt.POSTGAME_SNAPSHOT: 1})


if __name__ == '__main__':
    unittest.main()
