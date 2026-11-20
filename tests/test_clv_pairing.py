"""CLV 開盤／收盤配對：同一家、同一市場、同一方向；缺就排除，不補值。"""
import gzip
import json
import os
import unittest

from nba_quant import clv
from nba_quant.sources import espn

START = {'g1': '2026-01-10T00:30:00Z'}
FX = os.path.join(os.path.dirname(__file__), 'fixtures')


def q(stage, side, price, prov='A', market='spread', line=-5.5, gid='g1', **kw):
    d = {'game_id': gid, 'provider': prov, 'provider_type': 'book', 'stage': stage, 'market': market, 'side': side,
         'line': line if market != 'ml' else None, 'price_decimal': price, 'observed_at': None}
    d.update(kw)
    return d


def book(prov, open_h=1.91, open_a=1.91, close_h=1.87, close_a=1.95, market='spread'):
    s1, s2 = ('over', 'under') if market == 'total' else ('home', 'away')
    return [q('open', s1, open_h, prov, market), q('open', s2, open_a, prov, market),
            q('close', s1, close_h, prov, market), q('close', s2, close_a, prov, market)]


class PairingTests(unittest.TestCase):
    def test_same_book_same_market_same_side(self):
        pairs, excl = clv.pair_open_close(book('A') + book('B'), START)
        self.assertEqual(len(pairs), 4)
        self.assertEqual(excl, [])
        for p in pairs:
            self.assertEqual({p['open']['provider'], p['close']['provider'], p['open_other']['provider'],
                              p['close_other']['provider']}, {p['provider']})
            self.assertEqual(p['open']['side'], p['close']['side'])
            self.assertEqual(p['open']['market'], p['close']['market'])

    def test_no_cross_book_pairing(self):
        """A 只有開盤、B 只有收盤：不得把 A 的開盤配 B 的收盤。"""
        qs = [q('open', 'home', 1.91, 'A'), q('open', 'away', 1.91, 'A'),
              q('close', 'home', 1.87, 'B'), q('close', 'away', 1.95, 'B')]
        pairs, excl = clv.pair_open_close(qs, START)
        self.assertEqual(pairs, [])
        self.assertEqual({(e['provider'], e['reason']) for e in excl},
                         {('A', clv.MISSING_CLOSE), ('B', clv.MISSING_OPEN)})

    def test_no_cross_market_pairing(self):
        """讓分只有開盤、總分只有收盤：不得跨市場配對。"""
        qs = [q('open', 'home', 1.91), q('open', 'away', 1.91),
              q('close', 'over', 1.91, market='total', line=221.5), q('close', 'under', 1.91, market='total', line=221.5)]
        pairs, excl = clv.pair_open_close(qs, START)
        self.assertEqual(pairs, [])
        self.assertEqual({(e['market'], e['reason']) for e in excl},
                         {('spread', clv.MISSING_CLOSE), ('total', clv.MISSING_OPEN)})

    def test_missing_close_is_not_filled_from_postgame_or_other_books(self):
        qs = ([q('open', 'home', 1.91, 'A'), q('open', 'away', 1.91, 'A'),
               q('current_postgame', 'home', 1.80, 'A'), q('current_postgame', 'away', 2.05, 'A')]   # 賽後快照
              + book('B'))                                                                           # 其他莊家有完整配對
        pairs, excl = clv.pair_open_close(qs, START)
        self.assertEqual({p['provider'] for p in pairs}, {'B'})
        self.assertEqual({(e['provider'], e['side'], e['reason']) for e in excl},
                         {('A', 'home', clv.MISSING_CLOSE), ('A', 'away', clv.MISSING_CLOSE)})

    def test_devig_needs_same_book_other_side(self):
        qs = [q('open', 'home', 1.91, 'A'), q('close', 'home', 1.87, 'A'),
              q('open', 'away', 1.91, 'B'), q('close', 'away', 1.95, 'B')]    # 另一邊只有 B 有 → 不可借用
        pairs, excl = clv.pair_open_close(qs, START)
        self.assertEqual(pairs, [])
        self.assertIn(('A', 'home', clv.MISSING_OTHER_SIDE), {(e['provider'], e['side'], e['reason']) for e in excl})

    def test_flagged_and_after_start_records_excluded(self):
        flags = [{'game_id': 'g1', 'provider': 'A', 'stage': 'close', 'market': 'spread', 'side': 'home',
                  'flag': 'line_field_contains_price', 'severity': 'error'}]
        late = [q('open', 'home', 1.91, 'L'), q('open', 'away', 1.91, 'L'),
                q('close', 'home', 1.87, 'L', provider_timestamp='2026-01-10T01:00:00Z'),
                q('close', 'away', 1.95, 'L', provider_timestamp='2026-01-10T01:00:00Z')]
        pairs, excl = clv.pair_open_close(book('A') + late, START, flags)
        reasons = {(e['provider'], e['side'], e['reason']) for e in excl}
        self.assertIn(('A', 'home', clv.FLAGGED), reasons)
        self.assertIn(('A', 'away', clv.MISSING_OTHER_SIDE), reasons)          # 另一邊被標 → 無法同家去水
        self.assertIn(('L', 'home', clv.CLOSE_NOT_ELIGIBLE), reasons)          # 收盤時間晚於開賽
        self.assertEqual(pairs, [])

    def test_timestamp_verified_close_pairs(self):
        ts = {'provider_timestamp': '2026-01-10T00:20:00Z'}
        qs = [q('open', 'home', 1.91, 'V'), q('open', 'away', 1.91, 'V'),
              q('close', 'home', 1.87, 'V', **ts), q('close', 'away', 1.95, 'V', **ts)]
        pairs, excl = clv.pair_open_close(qs, START)
        self.assertEqual(excl, [])
        self.assertEqual({p['close_class'] for p in pairs}, {'TIMESTAMP_VERIFIED_CLOSE'})

    def test_assert_valid_pair_rejects_tampering(self):
        pairs, _ = clv.pair_open_close(book('A') + book('B'), START)
        p = dict(pairs[0])
        p['close'] = [x for x in book('B') if x['stage'] == 'close' and x['side'] == p['side']][0]
        with self.assertRaises(ValueError):
            clv.assert_valid_pair(p)

    def test_clv_value_and_report(self):
        pairs, excl = clv.pair_open_close(book('A', open_h=1.91, open_a=1.91, close_h=1.80, close_a=2.05), START)
        home = [p for p in pairs if p['side'] == 'home'][0]
        self.assertGreater(clv.clv_prob(home), 0)      # 收盤變熱門 → 開盤買主隊得到正 CLV
        rep = clv.pairing_report(pairs, excl + [{'game_id': 'g2', 'provider': 'A', 'market': 'ml', 'side': 'home',
                                                 'reason': clv.MISSING_OPEN}])
        self.assertEqual(rep['valid_pairs'], 2)
        self.assertEqual(rep['excluded_by_reason'], {clv.MISSING_OPEN: 1})
        self.assertEqual(rep['games_without_any_valid_pair'], 1)
        self.assertEqual(rep['close_time_classes'], {'PROVIDER_LABELED_CLOSE': 2})

    def test_real_espn_game(self):
        payload = json.loads(gzip.open(os.path.join(FX, 'odds_s2024_401585183.gz')).read())
        quotes, _, _ = espn.parse_odds(payload, '401585183', True, '2026-11-20T03:00:00Z')
        pairs, excl = clv.pair_open_close(quotes, {'401585183': '2024-01-15T18:00:00Z'})
        self.assertGreater(len(pairs), 0)
        for p in pairs:
            clv.assert_valid_pair(p)
            self.assertEqual(p['close_class'], 'PROVIDER_LABELED_CLOSE')


if __name__ == '__main__':
    unittest.main()


def pair_with(market, side, open_line, close_line, open_p, open_o, close_p, close_o):
    s1 = side
    s2 = clv.OTHER_SIDE[side]
    if market == 'spread':
        ol2, cl2 = -open_line, -close_line
    elif market == 'total':
        ol2, cl2 = open_line, close_line
    else:
        open_line = close_line = ol2 = cl2 = None
    qs = [q('open', s1, open_p, market=market, line=open_line), q('open', s2, open_o, market=market, line=ol2),
          q('close', s1, close_p, market=market, line=close_line), q('close', s2, close_o, market=market, line=cl2)]
    if market == 'ml':
        for x in qs:
            x['line'] = None
    pairs, excl = clv.pair_open_close(qs, START)
    return [p for p in pairs if p['side'] == side][0]


class LinePriceClvTests(unittest.TestCase):
    def test_spread_line_clv_orientation(self):
        self.assertEqual(clv.line_clv(pair_with('spread', 'home', -5.5, -7.5, 1.91, 1.91, 1.91, 1.91)), (2.0, None))
        self.assertEqual(clv.line_clv(pair_with('spread', 'away', 5.5, 3.5, 1.91, 1.91, 1.91, 1.91)), (2.0, None))
        self.assertEqual(clv.line_clv(pair_with('spread', 'home', -7.5, -5.5, 1.91, 1.91, 1.91, 1.91)), (-2.0, None))
        # 主客對稱：同一場線位移動，主隊得 +2 時客隊一定是 −2
        self.assertEqual(clv.line_clv(pair_with('spread', 'away', 5.5, 7.5, 1.91, 1.91, 1.91, 1.91)), (-2.0, None))

    def test_total_line_clv_orientation(self):
        self.assertEqual(clv.line_clv(pair_with('total', 'over', 220.0, 223.0, 1.91, 1.91, 1.91, 1.91)), (3.0, None))
        self.assertEqual(clv.line_clv(pair_with('total', 'under', 223.0, 220.0, 1.91, 1.91, 1.91, 1.91)), (3.0, None))
        self.assertEqual(clv.line_clv(pair_with('total', 'under', 220.0, 223.0, 1.91, 1.91, 1.91, 1.91)), (-3.0, None))

    def test_moneyline_has_no_line_clv(self):
        p = pair_with('ml', 'home', None, None, 2.10, 1.80, 1.90, 2.00)
        self.assertEqual(clv.line_clv(p), (None, clv.NA_ML_LINE))
        v, why = clv.price_clv(p)
        self.assertIsNone(why)
        self.assertGreater(v, 0)          # 主隊從 2.10 縮到 1.90：下注時的價格較好

    def test_line_improvement_does_not_imply_price_advantage(self):
        """線位變好（+2 分），但線不同 → Price CLV 不可比，不會被當成價格優勢。"""
        p = pair_with('spread', 'home', -5.5, -7.5, 1.95, 1.87, 1.80, 2.05)
        self.assertEqual(clv.line_clv(p), (2.0, None))
        self.assertEqual(clv.price_clv(p), (None, clv.LINE_MOVED))
        with self.assertRaises(ValueError):
            clv.clv_prob(p)

    def test_same_line_price_clv_can_be_negative_while_line_is_zero(self):
        p = pair_with('spread', 'home', -5.5, -5.5, 1.80, 2.05, 1.95, 1.87)   # 線不變，下注時賠率較差
        self.assertEqual(clv.line_clv(p), (0.0, None))
        v, _ = clv.price_clv(p)
        self.assertLess(v, 0)

    def test_metrics_report_keeps_them_separate(self):
        ps = [pair_with('spread', 'home', -5.5, -7.5, 1.95, 1.87, 1.80, 2.05),
              pair_with('spread', 'home', -5.5, -5.5, 1.80, 2.05, 1.95, 1.87),
              pair_with('ml', 'home', None, None, 2.10, 1.80, 1.90, 2.00)]
        r = clv.clv_metrics_report(ps)
        self.assertEqual(r['spread']['line_clv']['n'], 2)
        self.assertEqual(r['spread']['price_clv']['n'], 1)
        self.assertEqual(r['spread']['not_computed'], {f'price:{clv.LINE_MOVED}': 1})
        self.assertEqual(r['ml']['line_clv']['n'], 0)
        self.assertEqual(r['ml']['not_computed'], {f'line:{clv.NA_ML_LINE}': 1})
        self.assertEqual(r['ml']['price_clv']['n'], 1)
