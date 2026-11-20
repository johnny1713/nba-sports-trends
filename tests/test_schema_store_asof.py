import os
import tempfile
import unittest
from datetime import datetime, timezone

from nba_quant import asof, store
from nba_quant.schema import Game, OddsQuote, TaiwanQuote, TeamBox, SchemaError

NOW = '2026-11-20T02:00:00Z'


def game(gid, start, status='final', hp=110, ap=100):
    return Game(gid, 2027, 2, start, 'BOS', 'NYK', status, 'espn', NOW,
                hp if status == 'final' else None, ap if status == 'final' else None).validate()


class SchemaTests(unittest.TestCase):
    def test_final_requires_score_and_no_tie(self):
        with self.assertRaises(SchemaError):
            Game('1', 2027, 2, NOW, 'BOS', 'NYK', 'final', 'espn', NOW).validate()
        with self.assertRaises(SchemaError):
            Game('1', 2027, 2, NOW, 'BOS', 'NYK', 'final', 'espn', NOW, 100, 100).validate()

    def test_preseason_rejected(self):
        with self.assertRaises(SchemaError):
            Game('1', 2027, 1, NOW, 'BOS', 'NYK', 'scheduled', 'espn', NOW).validate()

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(SchemaError):
            Game('1', 2027, 2, '2026-11-20T02:00:00', 'BOS', 'NYK', 'scheduled', 'espn', NOW).validate()

    def test_teambox_points_must_add_up(self):
        TeamBox('1', 'BOS', 40, 85, 12, 35, 18, 22, 10, 33, 13, 110, 0, 'espn', NOW).validate()
        with self.assertRaises(SchemaError):
            TeamBox('1', 'BOS', 40, 85, 12, 35, 18, 22, 10, 33, 13, 111, 0, 'espn', NOW).validate()

    def test_odds_rules(self):
        OddsQuote('1', 'dk', 'open', 'spread', 'home', -5.5, 1.91, 'espn', NOW).validate()
        OddsQuote('1', 'dk', 'close', 'ml', 'away', None, None, 'espn', NOW).validate()   # 缺價格允許，但不補
        for bad in [dict(stage='snapshot'),                      # snapshot 必須有 observed_at
                    dict(market='ml', line=-5.5),                # 獨贏不該有盤口數字
                    dict(price_decimal=0.95),                    # 小數賠率必須 > 1
                    dict(side='over')]:                          # 讓分沒有 over
            kw = dict(game_id='1', provider='dk', stage='open', market='spread', side='home',
                      line=-5.5, price_decimal=1.91, source='espn', fetched_at=NOW)
            kw.update(bad)
            with self.assertRaises(SchemaError, msg=bad):
                OddsQuote(**kw).validate()

    def test_taiwan_source_cannot_be_us_book(self):
        with self.assertRaises(SchemaError):
            TaiwanQuote('2026-11-20', 'BOS', 'NYK', 'ml', 'home', None, 1.55, 'draftkings', NOW).validate()
        TaiwanQuote('2026-11-20', 'BOS', 'NYK', 'ml', 'home', None, 1.55, 'manual', NOW).validate()


class AsofTests(unittest.TestCase):
    def test_games_before_excludes_same_et_day_and_future(self):
        def c(g, ok=True):
            d = vars(g).copy(); d['complete'] = ok; return d
        gs = [c(game('a', '2026-11-18T00:30:00Z')),
              c(game('f', '2026-11-17T00:30:00Z'), ok=False),      # 完賽但 box score 不完整
              vars(game('g', '2026-11-16T00:30:00Z')),             # 沒有 complete 欄位 → 不採用       # 美東 11/17 晚上
              c(game('b', '2026-11-18T17:00:00Z')),          # 美東 11/18 中午（同一天較早）
              c(game('c', '2026-11-19T01:00:00Z')),          # 美東 11/18 晚上（目標場次本身）
              c(game('d', '2026-11-20T01:00:00Z')),          # 未來
              c(game('e', '2026-11-17T01:00:00Z', status='postponed'))]
        got = [g['game_id'] for g in asof.games_before(gs, '2026-11-19T01:00:00Z')]
        self.assertEqual(got, ['a'])

    def test_closing_line_never_reaches_prediction(self):
        T = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
        q = lambda stage, obs=None: dict(stage=stage, observed_at=obs)
        quotes = [q('open'), q('close'), q('current_postgame'),
                  q('snapshot', '2026-11-19T11:00:00Z'), q('snapshot', '2026-11-19T12:00:00Z')]
        got = asof.quotes_for_prediction(quotes, T)
        self.assertEqual([x['stage'] for x in got], ['open', 'snapshot'])
        self.assertEqual(got[1]['observed_at'], '2026-11-19T11:00:00Z')   # 剛好等於 T 的不放行
        self.assertEqual([x['stage'] for x in asof.closing_quotes(quotes)], ['close'])          # 賽後快照不算收盤
        self.assertEqual([x['stage'] for x in asof.postgame_snapshots_for_audit(quotes)], ['current_postgame'])
        with self.assertRaises(asof.LeakageError):
            asof.assert_no_postgame(quotes)
        asof.assert_no_postgame(asof.closing_quotes(quotes))
        with self.assertRaises(asof.LeakageError):
            asof.assert_no_eval_stage(quotes)
        with self.assertRaises(asof.LeakageError):
            asof.quotes_for_prediction(quotes, datetime(2026, 11, 19))


class StageLabelTests(unittest.TestCase):
    def test_postgame_is_never_labeled_closing(self):
        from nba_quant.schema import STAGE_TIME_CLASS, CLOSING_STAGES, POSTGAME_STAGES
        self.assertEqual(STAGE_TIME_CLASS['current_postgame'], 'POSTGAME_SNAPSHOT')
        self.assertEqual(STAGE_TIME_CLASS['close'], 'CLOSING')
        self.assertFalse(CLOSING_STAGES & POSTGAME_STAGES)
        self.assertFalse(hasattr(asof, 'quotes_for_evaluation'))     # 舊的混用介面已移除


class StoreTests(unittest.TestCase):
    def test_roundtrip_and_deterministic_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x', 'a.jsonl.gz')
            recs = [{'b': 1, 'a': '中文'}, {'a': None}]
            h1 = store.write_jsonl_gz(p, recs)
            h2 = store.write_jsonl_gz(p, recs)
            self.assertEqual(h1, h2)
            self.assertEqual(h1, store.sha256_file(p))
            self.assertEqual(list(store.read_jsonl_gz(p)), recs)


if __name__ == '__main__':
    unittest.main()
