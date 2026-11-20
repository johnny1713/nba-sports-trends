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
        self.assertIn(('BookA', 'spread_ml_direction_conflict'), kinds)      # 沒有其他莊家可比 → 保守兩市場都標
        self.assertIn(('B', 'total_out_of_range'), kinds)
        self.assertIn(('C', 'spread_sign_mismatch'), kinds)
        self.assertTrue(all(f['severity'] == 'error' for f in flags))

    def test_extreme_price_is_warning_and_excluded_unless_allowed(self):
        qs = [q('home', None, 1.0076, 'ml'), q('away', None, 26.0, 'ml')]
        flags, _ = odds_flags.flag_quotes(qs)
        self.assertEqual({f['severity'] for f in flags}, {'warning'})
        self.assertEqual(odds_flags.usable_quotes(qs, flags), [])
        allowed = odds_flags.usable_quotes(qs, flags, allow_warnings={('g1', 'BookA', 'close', 'ml', 'home'),
                                                                      ('g1', 'BookA', 'close', 'ml', 'away')})
        self.assertEqual(len(allowed), 2)

    def test_exclusion_is_per_record_not_per_game(self):
        """一家莊家一筆異常：只排除那一筆；同場其他莊家、同家其他盤口、同組另一邊（若正常）全部保留。"""
        qs = [q('home', None, 1.0076, 'ml'), q('away', None, 9.5, 'ml'),          # BookA 獨贏：只有主隊那邊極端
              q('home', -14.5, 1.91), q('away', 14.5, 1.91),                         # BookA 讓分：正常
              q('over', 2001.0, 1.91, 'total'), q('under', 2001.0, 1.91, 'total'),   # BookA 總分：打錯字
              q('home', -14.0, 1.91, prov='BookB'), q('away', 14.0, 1.91, prov='BookB'),
              q('over', 221.5, 1.91, 'total', prov='BookB'), q('under', 221.5, 1.91, 'total', prov='BookB')]
        flags, _ = odds_flags.flag_quotes(qs)
        kept = {odds_flags.record_key(x) for x in odds_flags.usable_quotes(qs, flags)}
        dropped = {odds_flags.record_key(x) for x in qs} - kept
        self.assertEqual(dropped, {('g1', 'BookA', 'close', 'ml', 'home'),
                                   ('g1', 'BookA', 'close', 'total', 'over'), ('g1', 'BookA', 'close', 'total', 'under')})
        self.assertIn(('g1', 'BookA', 'close', 'ml', 'away'), kept)            # 同組另一邊正常 → 保留
        self.assertIn(('g1', 'BookA', 'close', 'spread', 'home'), kept)        # 同家其他盤口 → 保留
        self.assertIn(('g1', 'BookB', 'close', 'total', 'over'), kept)         # 同場其他莊家 → 保留

    def test_espn_total_placeholder_is_missing_not_error(self):
        qs = [q('over', -1.0, 1.91, 'total'), q('under', -1.0, 1.91, 'total'),
              q('over', 217.5, 1.91, 'total', prov='BookB'), q('under', 217.5, 1.91, 'total', prov='BookB')]
        flags, _ = odds_flags.flag_quotes(qs)
        self.assertEqual({(f['flag'], f['severity']) for f in flags}, {('total_placeholder_missing', 'missing')})
        kept = odds_flags.usable_quotes(qs, flags)
        self.assertEqual({x['provider'] for x in kept}, {'BookB'})                 # 佔位符不進模型，其他莊家保留

    def test_every_flag_points_to_one_record(self):
        qs = [q('home', 7.5, 1.91), q('away', -7.5, 1.91), q('home', None, 1.3, 'ml'), q('away', None, 3.6, 'ml')]
        flags, _ = odds_flags.flag_quotes(qs)
        self.assertTrue(all(f['side'] in ('home', 'away', 'over', 'under') for f in flags))

    def test_flagging_never_mutates_raw_quotes(self):
        qs = [q('over', 2001.0, 1.91, 'total'), q('under', 2001.0, 1.91, 'total')]
        before = json.dumps(qs, sort_keys=True)
        odds_flags.flag_quotes(qs)
        self.assertEqual(json.dumps(qs, sort_keys=True), before)


if __name__ == '__main__':
    unittest.main()


def market(prov, home_line, ml_home, ml_away, gid='g1', stage='close'):
    return [q('home', home_line, 1.91, prov=prov, gid=gid, stage=stage), q('away', -home_line, 1.91, prov=prov, gid=gid, stage=stage),
            q('home', None, ml_home, 'ml', prov=prov, gid=gid, stage=stage), q('away', None, ml_away, 'ml', prov=prov, gid=gid, stage=stage)]


PEERS = market('P1', -7.5, 1.30, 3.60) + market('P2', -7.0, 1.31, 3.50) + market('P3', -7.5, 1.29, 3.70)


class ConflictAttributionTests(unittest.TestCase):
    def kept(self, qs):
        flags, _ = odds_flags.flag_quotes(qs)
        return flags, {odds_flags.record_key(x) for x in odds_flags.usable_quotes(qs, flags)}

    def test_spread_sign_flipped_excludes_only_spread_both_sides(self):
        qs = PEERS + market('BAD', +7.5, 1.30, 3.60)           # 讓分寫反，獨贏正確
        flags, kept = self.kept(qs)
        self.assertEqual({(f['market'], f['side']) for f in flags if f['provider'] == 'BAD'},
                         {('spread', 'home'), ('spread', 'away')})                  # 只有讓分盤（兩邊）被標
        self.assertIn('spread_deviates_from_market', {f['flag'] for f in flags if f['provider'] == 'BAD'})
        self.assertIn(('g1', 'BAD', 'close', 'ml', 'home'), kept)                # 正確的獨贏保留
        self.assertIn(('g1', 'BAD', 'close', 'ml', 'away'), kept)
        self.assertNotIn(('g1', 'BAD', 'close', 'spread', 'home'), kept)        # 讓分線是兩隊共用：兩邊都不留
        self.assertNotIn(('g1', 'BAD', 'close', 'spread', 'away'), kept)
        for p in ('P1', 'P2', 'P3'):                                             # 其他莊家完全不受影響
            self.assertTrue(all(k in kept for k in [('g1', p, 'close', m, s) for m in ('spread', 'ml') for s in ('home', 'away')]))

    def test_ml_swapped_excludes_only_ml(self):
        qs = PEERS + market('BAD', -7.5, 3.60, 1.30)           # 讓分正確，獨贏主客對調
        flags, kept = self.kept(qs)
        self.assertEqual({f['market'] for f in flags if f['provider'] == 'BAD'}, {'ml'})   # 只有獨贏盤被標
        self.assertIn('ml_deviates_from_market', {f['flag'] for f in flags if f['provider'] == 'BAD'})
        self.assertIn(('g1', 'BAD', 'close', 'spread', 'home'), kept)
        self.assertIn(('g1', 'BAD', 'close', 'spread', 'away'), kept)
        self.assertNotIn(('g1', 'BAD', 'close', 'ml', 'home'), kept)

    def test_fewer_than_three_peers_is_conservative(self):
        qs = market('P1', -7.5, 1.30, 3.60) + market('P2', -7.0, 1.31, 3.50) + market('BAD', +7.5, 1.30, 3.60)
        flags, kept = self.kept(qs)
        self.assertEqual({f['market'] for f in flags if f['provider'] == 'BAD'}, {'spread', 'ml'})
        self.assertFalse(any(k[1] == 'BAD' for k in kept))

    def test_split_market_is_unattributable(self):
        # 其他莊家對熱門方向沒有 2/3 共識 → 不歸因，兩市場都標
        qs = (market('P1', -2.5, 1.70, 2.20) + market('P2', -2.5, 2.20, 1.70) + market('P3', -2.5, 1.95, 1.90)
              + market('BAD', -2.5, 2.30, 1.65))
        flags, _ = self.kept(qs)
        self.assertEqual({f['flag'] for f in flags if f['provider'] == 'BAD'}, {'spread_ml_direction_conflict'})

    def test_both_deviate_is_unattributable(self):
        qs = PEERS + market('BAD', +12.5, 3.60, 1.30)          # 讓分與獨贏都和市場相反（彼此一致→不是方向矛盾）
        flags, _ = self.kept(qs)
        bad = [f for f in flags if f['provider'] == 'BAD']
        self.assertNotIn('spread_ml_direction_conflict', {f['flag'] for f in bad})
        self.assertEqual({f['market'] for f in bad}, {'spread', 'ml'})            # 但兩個市場都偏離市場 → 偏離規則都標

    def test_conflicting_books_are_not_used_as_peers(self):
        # 兩家都寫反讓分：互相不能當比較基準；P1~P3 仍足夠 → 兩家都歸因為讓分錯
        qs = PEERS + market('BAD1', +7.5, 1.30, 3.60) + market('BAD2', +7.0, 1.31, 3.50)
        flags, kept = self.kept(qs)
        self.assertEqual({f['provider'] for f in flags}, {'BAD1', 'BAD2'})
        self.assertEqual({(f['provider'], f['market']) for f in flags}, {('BAD1', 'spread'), ('BAD2', 'spread')})
        self.assertIn(('g1', 'BAD1', 'close', 'ml', 'home'), kept)

    def test_no_kept_spread_settles_against_its_own_moneyline(self):
        """不變式：保留下來的同家同階段讓分＋獨贏，熱門方向一定一致（不會留下無法正確結算的錯誤讓分）。"""
        cases = [PEERS + market('BAD', +7.5, 1.30, 3.60), PEERS + market('BAD', -7.5, 3.60, 1.30),
                 market('P1', -7.5, 1.30, 3.60) + market('BAD', +7.5, 1.30, 3.60)]
        for qs in cases:
            flags, _ = odds_flags.flag_quotes(qs)
            kept = odds_flags.usable_quotes(qs, flags)
            grp = odds_flags.group_quotes(kept)
            for (g, p, st, m), sd in grp.items():
                if m != 'spread':
                    continue
                self.assertEqual(set(sd), {'home', 'away'})                       # 讓分不會只剩一邊
                ml = grp.get((g, p, st, 'ml'), {})
                if len(ml) == 2 and abs(sd['home']['line']) >= 2:
                    self.assertEqual(sd['home']['line'] < 0, ml['home']['price_decimal'] < ml['away']['price_decimal'], p)


class OverroundTierTests(unittest.TestCase):
    def ml_pair(self, a, b):
        return [q('home', None, a, 'ml'), q('away', None, b, 'ml')]

    def tier(self, a, b):
        flags, _ = odds_flags.flag_quotes(self.ml_pair(a, b))
        return {(f['flag'], f['severity']) for f in flags if f['flag'].startswith('overround')}

    def test_normal(self):
        self.assertEqual(self.tier(1.91, 1.91), set())                       # 1.047
        self.assertEqual(odds_flags.overround_tier(1.10), None)

    def test_high_but_plausible_is_warning_not_error(self):
        self.assertEqual(odds_flags.overround_tier(1.1515), 'warning')
        self.assertEqual(odds_flags.overround_tier(1.1859), 'warning')
        self.assertEqual(odds_flags.overround_tier(0.99), 'warning')

    def test_clearly_wrong_is_error(self):
        self.assertEqual(odds_flags.overround_tier(1.4615), 'error')
        self.assertEqual(odds_flags.overround_tier(0.95), 'error')

    def test_uses_same_book_same_stage_pair_only(self):
        # 兩家各自正常；若錯把不同家的價格配在一起會算出異常 → 不應出現任何抽水標記
        qs = [q('home', None, 1.30, 'ml', prov='A'), q('away', None, 3.60, 'ml', prov='A'),
              q('home', None, 1.10, 'ml', prov='B'), q('away', None, 7.00, 'ml', prov='B'),
              q('home', None, 1.30, 'ml', prov='A', stage='open'), q('away', None, 3.50, 'ml', prov='A', stage='open')]
        flags, _ = odds_flags.flag_quotes(qs)
        self.assertFalse([f for f in flags if f['flag'].startswith('overround')])


class DeviationTests(unittest.TestCase):
    def totals(self, prov, line, gid='g1'):
        return [q('over', line, 1.91, 'total', prov=prov, gid=gid), q('under', line, 1.91, 'total', prov=prov, gid=gid)]

    def test_live_contaminated_total_is_flagged_and_noted(self):
        qs = self.totals('A', 218.5) + self.totals('B', 217.0) + self.totals('C', 219.5) + self.totals('DK', 252.5)
        flags, _ = odds_flags.flag_quotes(qs, results={'g1': (126, 125)})
        dk = [f for f in flags if f['provider'] == 'DK']
        self.assertEqual({(f['flag'], f['side']) for f in dk}, {('line_deviates_from_market', 'over'), ('line_deviates_from_market', 'under')})
        self.assertIn('滾球', dk[0]['detail'])
        self.assertFalse([f for f in flags if f['provider'] != 'DK'])          # 其他莊家不受影響

    def test_small_differences_are_normal(self):
        qs = self.totals('A', 218.5) + self.totals('B', 214.0) + self.totals('C', 219.5) + self.totals('D', 222.5)
        flags, _ = odds_flags.flag_quotes(qs)
        self.assertEqual(flags, [])

    def test_needs_three_peers(self):
        qs = self.totals('A', 218.5) + self.totals('B', 217.0) + self.totals('DK', 252.5)
        flags, _ = odds_flags.flag_quotes(qs)
        self.assertEqual(flags, [])

    def test_spread_deviation_flags_both_sides(self):
        qs = (market('P1', -7.5, 1.30, 3.60) + market('P2', -7.0, 1.31, 3.50) + market('P3', -7.5, 1.29, 3.70)
              + market('LIVE', -19.5, 1.02, 14.0))                               # 方向一致但數字離譜（滾球盤）
        flags, _ = odds_flags.flag_quotes(qs)
        live = {(f['market'], f['side']) for f in flags if f['provider'] == 'LIVE' and f['flag'] == 'line_deviates_from_market'}
        self.assertIn(('spread', 'home'), live)
        self.assertIn(('spread', 'away'), live)
        self.assertIn(('ml', 'home'), live)
