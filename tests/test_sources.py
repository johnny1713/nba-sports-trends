import gzip
import json
import os
import unittest

from nba_quant.sources import espn, taiwan

FX = os.path.join(os.path.dirname(__file__), 'fixtures')
T = '2026-11-20T03:00:00Z'


def load(name):
    return gzip.open(os.path.join(FX, name)).read()


class EspnTests(unittest.TestCase):
    def test_american_to_decimal(self):
        self.assertAlmostEqual(espn.american_to_decimal('-110'), 1.909091, places=5)
        self.assertAlmostEqual(espn.american_to_decimal(250), 3.5)
        self.assertIsNone(espn.american_to_decimal('-50'))      # 不可能的美式賠率
        self.assertIsNone(espn.american_to_decimal(None))

    def test_modern_odds_have_open_and_close_with_prices(self):
        q, raw, notes = espn.parse_odds(json.loads(load('odds_s2024_401585183.gz')), '401585183', True, T)
        books = [x for x in q if x['provider_type'] == 'book']
        self.assertTrue(any(x['stage'] == 'open' for x in books))
        self.assertTrue(any(x['stage'] == 'close' for x in books))
        bf = {(x['stage'], x['market'], x['side']): x for x in books if x['provider'] == 'BetfairSportsbook'}
        self.assertEqual(bf[('open', 'spread', 'home')]['line'], -7.5)
        self.assertEqual(bf[('close', 'spread', 'home')]['line'], -8.0)
        self.assertAlmostEqual(bf[('close', 'ml', 'home')]['price_decimal'], 1 + 100 / 350, places=5)
        self.assertTrue(all(x['timestamp_available'] is False for x in q))   # ESPN 沒給時間，不能假裝有
        self.assertEqual(len(raw), 12)                                        # 原始資料全數保留
        self.assertEqual(notes, [])

    def test_pregame_close_field_is_not_treated_as_close(self):
        q, _, _ = espn.parse_odds(json.loads(load('odds_today_401910022.gz')), '401910022', False, T)
        stages = {x['stage'] for x in q}
        self.assertNotIn('close', stages)
        self.assertIn('snapshot', stages)
        self.assertTrue(all(x['observed_at'] == T for x in q if x['stage'] == 'snapshot'))

    def test_legacy_odds_current_is_eval_only_and_initial_is_open_without_price(self):
        q, _, _ = espn.parse_odds(json.loads(load('odds_s2016_400828480.gz')), '400828480', True, T)
        cur = [x for x in q if x['stage'] == 'current_postgame' and x['provider'] == '5Dimes.eu']
        self.assertEqual({(x['market'], x['side']) for x in cur},
                         {('spread', 'home'), ('spread', 'away'), ('ml', 'home'), ('ml', 'away'), ('total', 'over'), ('total', 'under')})
        op = [x for x in q if x['stage'] == 'open' and x['provider'] == '5Dimes.eu']
        self.assertEqual({x['line'] for x in op if x['market'] == 'spread' and x['side'] == 'home'}, {-8.0})
        self.assertTrue(all(x['price_decimal'] is None for x in op))          # 開盤線沒有價格，不補
        types = {x['provider']: x['provider_type'] for x in q}
        self.assertEqual(types['consensus'], 'non_book')
        self.assertEqual(types['Opening'], 'opening_feed')

    def test_boxscore_points_reconcile(self):
        boxes = espn.parse_boxscore(json.loads(load('summary_s2025_401705127.gz')), '401705127', T)
        self.assertEqual(sorted(b['pts'] for b in boxes), [119, 125])
        self.assertEqual({b['overtimes'] for b in boxes}, {1})
        self.assertTrue(all(len(b['players']) >= 8 for b in boxes))

    def test_scoreboard_filters(self):
        evs = json.loads(load('scoreboard_playin2024.gz'))['events']
        self.assertTrue(all(espn.parse_scoreboard_event(e, T)[0] is None for e in evs))      # play-in 不收
        evs = json.loads(load('scoreboard_post2024.gz'))['events']
        self.assertTrue(all(espn.parse_scoreboard_event(e, T)[0]['season_type'] == 3 for e in evs))


class PlaysportTests(unittest.TestCase):
    def html(self, name):
        return load(name).decode('utf-8')

    def test_parses_only_bank_columns(self):
        games, problems = taiwan.parse(self.html('playsport_tomorrow.gz'), T)
        self.assertEqual(problems, [])
        self.assertEqual(len(games), 5)
        g = games[0]
        self.assertEqual((g['away_zh'], g['home_zh']), ('黃蜂', '老鷹'))
        q = {(x['market'], x['side']): (x['line'], x['price_decimal']) for x in g['quotes']}
        self.assertEqual(q[('spread', 'away')], (5.5, 1.7))
        self.assertEqual(q[('spread', 'home')], (-5.5, 1.73))
        self.assertEqual(q[('ml', 'away')], (None, 2.25))
        self.assertEqual(q[('ml', 'home')], (None, 1.38))
        self.assertEqual(q[('total', 'over')], (218.5, 1.7))
        self.assertTrue(all(x['source'] == 'playsport' for x in g['quotes']))
        self.assertFalse(g['verified'])

    def test_rejects_page_when_header_changes(self):
        h = self.html('playsport_default.gz').replace('運彩盤', '國際盤二')
        with self.assertRaises(taiwan.ParseRejected):
            taiwan.parse(h, T)

    def test_cross_check_with_espn_same_game(self):
        """同一場（馬刺主場 vs 快艇）：運彩盤與 ESPN 的主隊讓分方向一致。"""
        games, _ = taiwan.parse(self.html('playsport_default.gz'), T)
        g = [x for x in games if x['home_zh'] == '馬刺'][0]
        tw = {(x['market'], x['side']): x['line'] for x in g['quotes']}
        self.assertLess(tw[('spread', 'home')], 0)
        q, _, _ = espn.parse_odds(json.loads(load('odds_today_401910022.gz')), '401910022', False, T)
        us = [x['line'] for x in q if x['stage'] == 'snapshot' and x['market'] == 'spread' and x['side'] == 'home']
        self.assertLess(us[0], 0)


if __name__ == '__main__':
    unittest.main()
