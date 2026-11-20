"""讓分方向與正負號、盤口品質標記的測試（防止讓分方向顛倒）。"""
import gzip
import json
import os
import unittest

from nba_quant import lines, odds_flags
from nba_quant.sources import espn, taiwan

FX = os.path.join(os.path.dirname(__file__), 'fixtures')
T = '2026-11-20T03:00:00Z'


def load(n):
    return gzip.open(os.path.join(FX, n)).read()


def q(side, line, price, market='spread', stage='close', prov='BookA', gid='g1'):
    return {'game_id': gid, 'provider': prov, 'provider_type': 'book', 'stage': stage, 'market': market,
            'side': side, 'line': line, 'price_decimal': price}


class SettleTests(unittest.TestCase):
    def test_spread_sign_convention(self):
        # 主隊 -7.5（讓分）：贏 8 分過盤、贏 7 分不過
        self.assertEqual(lines.settle('spread', 'home', -7.5, 110, 102), 'win')
        self.assertEqual(lines.settle('spread', 'home', -7.5, 109, 102), 'loss')
        # 客隊 +7.5（受讓）：輸 7 分過盤
        self.assertEqual(lines.settle('spread', 'away', 7.5, 109, 102), 'win')
        self.assertEqual(lines.settle('spread', 'away', 7.5, 110, 102), 'loss')
        # 整數盤走盤
        self.assertEqual(lines.settle('spread', 'home', -7, 109, 102), 'push')
        self.assertEqual(lines.settle('spread', 'away', 7, 109, 102), 'push')

    def test_home_and_away_always_opposite_outcomes(self):
        for hp, ap in [(110, 102), (100, 101), (120, 95)]:
            for line in (-7.5, -1.5, 3.5, 12.5):
                self.assertNotEqual(lines.settle('spread', 'home', line, hp, ap),
                                    lines.settle('spread', 'away', -line, hp, ap))

    def test_total_and_ml(self):
        self.assertEqual(lines.settle('total', 'over', 210.5, 110, 101), 'win')
        self.assertEqual(lines.settle('total', 'under', 211, 110, 101), 'push')
        self.assertEqual(lines.settle('ml', 'away', None, 99, 101), 'win')
        with self.assertRaises(ValueError):
            lines.settle('ml', 'home', None, 100, 100)


class SourceDirectionTests(unittest.TestCase):
    def test_espn_home_line_matches_home_favorite(self):
        """ESPN 所有年代：主隊讓分為負 ⇔ 主隊獨贏賠率較低（熱門）。"""
        for name, gid, final in [('odds_s2016_400828480.gz', '400828480', True), ('odds_s2024_401585183.gz', '401585183', True),
                                 ('odds_s2025_401705127.gz', '401705127', True), ('odds_today_401910022.gz', '401910022', False)]:
            qs, _, _ = espn.parse_odds(json.loads(load(name)), gid, final, T)
            grp = odds_flags.group_quotes(qs)
            checked = 0
            for (g, prov, stage, market), sd in grp.items():
                if market != 'spread' or 'home' not in sd or 'away' not in sd:
                    continue
                self.assertEqual(sd['home']['line'], -sd['away']['line'], (name, prov, stage))
                ml = grp.get((g, prov, stage, 'ml'), {})
                if 'home' in ml and 'away' in ml and abs(sd['home']['line']) >= 2:
                    self.assertEqual(lines.favorite_side(sd['home']['line']) == 'home',
                                     ml['home']['price_decimal'] < ml['away']['price_decimal'], (name, prov, stage))
                    checked += 1
            self.assertGreater(checked, 0, name)

    def test_playsport_side_tags_match_signs(self):
        games, _ = taiwan.parse(load('playsport_tomorrow.gz').decode(), T)
        for g in games:
            sp = {x['side']: x['line'] for x in g['quotes'] if x['market'] == 'spread'}
            ml = {x['side']: x['price_decimal'] for x in g['quotes'] if x['market'] == 'ml'}
            if len(sp) == 2 and len(ml) == 2:
                self.assertEqual(sp['home'], -sp['away'])
                self.assertEqual(lines.favorite_side(sp['home']) == 'home', ml['home'] < ml['away'], g['game_no'])


class FlagTests(unittest.TestCase):
    def test_clean_group_has_no_flags(self):
        qs = [q('home', -5.5, 1.91), q('away', 5.5, 1.91), q('home', None, 1.45, 'ml'), q('away', None, 2.8, 'ml'),
              q('over', 221.5, 1.91, 'total'), q('under', 221.5, 1.91, 'total')]
        flags, n = odds_flags.flag_quotes(qs)
        self.assertEqual(flags, [])
        self.assertGreater(n, 0)

    def test_detects_reversed_spread_and_typos(self):
        qs = [q('home', 7.5, 1.91), q('away', -7.5, 1.91), q('home', None, 1.3, 'ml'), q('away', None, 3.6, 'ml'),  # 讓分方向與獨贏相反
              q('over', 2001.0, 1.91, 'total', prov='B'), q('under', 2001.0, 1.91, 'total', prov='B'),             # 總分打錯字
              q('home', -5.5, 1.91, prov='C'), q('away', -5.5, 1.91, prov='C')]                                    # 兩邊同號
        flags, _ = odds_flags.flag_quotes(qs)
        kinds = {(f['provider'], f['flag']) for f in flags}
        self.assertIn(('BookA', 'spread_ml_direction_conflict'), kinds)
        self.assertIn(('B', 'total_out_of_range'), kinds)
        self.assertIn(('C', 'spread_sign_mismatch'), kinds)
        self.assertTrue(all(f['severity'] == 'error' for f in flags))

    def test_extreme_price_is_warning_and_excluded_unless_allowed(self):
        qs = [q('home', None, 1.0076, 'ml'), q('away', None, 26.0, 'ml')]
        flags, _ = odds_flags.flag_quotes(qs)
        self.assertEqual({f['severity'] for f in flags}, {'warning'})
        self.assertEqual(odds_flags.usable_quotes(qs, flags), [])
        allowed = odds_flags.usable_quotes(qs, flags, allow_warnings={('g1', 'BookA', 'close', 'ml')})
        self.assertEqual(len(allowed), 2)

    def test_flagging_never_mutates_raw_quotes(self):
        qs = [q('over', 2001.0, 1.91, 'total'), q('under', 2001.0, 1.91, 'total')]
        before = json.dumps(qs, sort_keys=True)
        odds_flags.flag_quotes(qs)
        self.assertEqual(json.dumps(qs, sort_keys=True), before)


if __name__ == '__main__':
    unittest.main()
