"""人工有條件放行：只在全部條件成立時有效，且不會變成其他球季的通行規則。"""
import os
import tempfile
import unittest
from collections import defaultdict

from nba_quant import backfill, quality, store

N_GAMES = 40


def build(books, bad_provider='EB', bad_stage='close'):
    """每場每家：讓分＋總分＋獨贏；bad_provider 的收盤讓分/總分欄位填入賠率（-110）。"""
    odds_by_game, flags = defaultdict(list), []
    for i in range(N_GAMES):
        gid = f'g{i}'
        for b in books:
            for m, sides in (('spread', ('home', 'away')), ('total', ('over', 'under')), ('ml', ('home', 'away'))):
                for s in sides:
                    odds_by_game[gid].append({'game_id': gid, 'provider': b, 'provider_type': 'book', 'stage': 'close',
                                              'market': m, 'side': s})
                    if b == bad_provider and m in ('spread', 'total'):
                        flags.append({'game_id': gid, 'provider': b, 'stage': bad_stage, 'market': m, 'side': s,
                                      'flag': 'line_field_contains_price', 'severity': 'error'})
    return odds_by_game, flags


class ConditionalPassTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.old_raw = quality.RAW
        quality.RAW = self.d.name
        os.makedirs(os.path.join(self.d.name, '2023'))
        for name in ('games.jsonl.gz', 'odds.jsonl.gz'):
            store.write_jsonl_gz(os.path.join(self.d.name, '2023', name), [{'x': name}])

    def tearDown(self):
        quality.RAW = self.old_raw
        self.d.cleanup()

    def ack(self, **over):
        a = {'season': 2023, 'decision': 'conditional_pass', 'data_version': quality.data_version(2023),
             'exclusion_scope': [{'provider': 'EB', 'stage': 'close', 'markets': ['spread', 'total'],
                                  'flag': 'line_field_contains_price'}]}
        a.update(over)
        store.write_json(os.path.join(self.d.name, '2023', quality.ACK_FILE), a)

    def run_eval(self, books, reasons=('盤口 error 級標記比例 2.47% ≥ 1%',), n_checks=None):
        obg, flags = build(books)
        n_checks = n_checks or 100 * len(flags)
        return quality.evaluate_conditional_pass(2023, list(reasons), flags, n_checks, len(flags), obg, {f'g{i}' for i in range(N_GAMES)})

    def test_valid_when_all_conditions_hold(self):
        self.ack()
        c = self.run_eval(['EB', 'A', 'B', 'C'])
        self.assertTrue(c['valid'], c['invalid_reasons'])
        self.assertEqual(c['adjusted_error_rate_pct'], 0.0)
        self.assertEqual({(e['market'], e['records_excluded']) for e in c['excluded']}, {('spread', 80), ('total', 80)})
        self.assertTrue(all(e['other_books_usable_coverage_pct'] == 100.0 for e in c['excluded']))

    def test_sole_bookmaker_stays_failed(self):
        """2024-25 起 ESPN BET 可能是唯一來源：沒有其他莊家可交叉驗證 → 放行不成立。"""
        self.ack()
        c = self.run_eval(['EB'])
        self.assertFalse(c['valid'])
        self.assertTrue(any('無法交叉驗證' in r for r in c['invalid_reasons']))

    def test_data_change_invalidates(self):
        self.ack()
        store.write_jsonl_gz(os.path.join(self.d.name, '2023', 'odds.jsonl.gz'), [{'x': 'changed'}])
        c = self.run_eval(['EB', 'A', 'B', 'C'])
        self.assertFalse(c['valid'])
        self.assertIn('資料版本已變更', c['invalid_reasons'])

    def test_ack_for_other_season_does_not_apply(self):
        self.ack(season=2022)
        self.assertFalse(self.run_eval(['EB', 'A', 'B', 'C'])['valid'])

    def test_other_failure_reasons_block(self):
        self.ack()
        c = self.run_eval(['EB', 'A', 'B', 'C'], reasons=('盤口 error 級標記比例 2.47% ≥ 1%', '完賽比賽資料完整率 97.0% < 99%'))
        self.assertFalse(c['valid'])

    def test_non_systematic_error_cannot_be_waived(self):
        self.ack(exclusion_scope=[{'provider': 'EB', 'stage': 'close', 'markets': ['ml'], 'flag': 'line_field_contains_price'}])
        c = self.run_eval(['EB', 'A', 'B', 'C'])
        self.assertFalse(c['valid'])
        self.assertTrue(any('不構成系統性錯誤' in r for r in c['invalid_reasons']))

    def test_threshold_unchanged(self):
        self.assertEqual(quality.GATE_ERROR_RATE, 0.01)
        self.ack()
        c = self.run_eval(['EB', 'A', 'B', 'C'], n_checks=170)       # 排除後雖然是 0，但先確認門檻常數沒動
        self.assertEqual(c['gate_threshold_pct'], 1.0)


class NextSeasonGateTests(unittest.TestCase):
    def test_ack_file_alone_does_not_unblock(self):
        old = backfill.RAW if hasattr(backfill, 'RAW') else None
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            try:
                os.chdir(d)
                sd = backfill.season_dir(2023)
                os.makedirs(sd)
                store.write_json(os.path.join(sd, 'quality.json'), {'verdict_ok': False, 'conditional_pass': False, 'verdict': '不通過'})
                store.write_json(os.path.join(sd, 'quality_ack.json'), {'accepted': True, 'decision': 'conditional_pass'})
                self.assertIsNotNone(backfill.require_previous_ok(2024))
                store.write_json(os.path.join(sd, 'quality.json'), {'verdict_ok': False, 'conditional_pass': True, 'verdict': '有條件通過'})
                self.assertIsNone(backfill.require_previous_ok(2024))
            finally:
                os.chdir(cwd)


if __name__ == '__main__':
    unittest.main()


class ContinueAuthorizationTests(unittest.TestCase):
    """人工繼續回補授權：只放行指定的下一季、不改變前一季 FAILED、資料一變就失效。"""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.d.name)
        self.sd = backfill.season_dir(2023)
        os.makedirs(self.sd)
        for name in ('games.jsonl.gz', 'odds.jsonl.gz'):
            store.write_jsonl_gz(os.path.join(self.sd, name), [{'x': name}])
        store.write_json(os.path.join(self.sd, 'quality.json'),
                         {'verdict_ok': False, 'conditional_pass': False, 'quality_status': 'FAILED', 'verdict': '不通過'})

    def tearDown(self):
        os.chdir(self.cwd)
        self.d.cleanup()

    def auth(self, **over):
        a = {'season': 2023, 'quality_status': 'FAILED', 'authorizes_backfill_of': [2024],
             'data_version': quality.data_version(2023)}
        a.update(over)
        store.write_json(os.path.join(self.sd, backfill.CONTINUE_AUTH), a)

    def test_blocked_without_authorization(self):
        self.assertIsNotNone(backfill.require_previous_ok(2024))

    def test_authorizes_only_named_next_season(self):
        self.auth()
        self.assertIsNone(backfill.require_previous_ok(2024))
        ok, _ = backfill.continue_authorization(2023, 2025)
        self.assertFalse(ok)

    def test_does_not_change_quality_status(self):
        self.auth()
        backfill.require_previous_ok(2024)
        q = store.read_json(os.path.join(self.sd, 'quality.json'))
        self.assertEqual(q['quality_status'], 'FAILED')
        self.assertFalse(q['verdict_ok'] or q['conditional_pass'])

    def test_data_change_invalidates(self):
        self.auth()
        store.write_jsonl_gz(os.path.join(self.sd, 'odds.jsonl.gz'), [{'x': 'changed'}])
        self.assertIsNotNone(backfill.require_previous_ok(2024))

    def test_authorization_must_state_failed(self):
        self.auth(quality_status='PASS')
        self.assertIsNotNone(backfill.require_previous_ok(2024))

    def test_not_inherited_by_later_seasons(self):
        """2023-24 若也不通過，2023 的授權不能讓 2024-25 開跑。"""
        self.auth()
        sd24 = backfill.season_dir(2024)
        os.makedirs(sd24)
        store.write_json(os.path.join(sd24, 'quality.json'), {'verdict_ok': False, 'conditional_pass': False, 'verdict': '不通過'})
        self.assertIsNotNone(backfill.require_previous_ok(2025))


class StrictStageCoverageTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(quality.STRICT_STAGE_FROM, 2024)
        self.assertEqual(quality.STRICT_STAGE_MIN_COVERAGE, 95.0)
        self.assertEqual(quality.ACK_MIN_OTHER_COVERAGE, 95.0)       # 單一莊家出錯 → 有條件通過不可能成立


class SoleBookSeasonEndToEnd(unittest.TestCase):
    """2024-25 起的情境：只有 ESPN BET 一家，收盤讓分欄位系統性錯誤 → 必須 FAILED，放行紀錄也救不了。"""

    def test_sole_book_close_error_stays_failed_even_with_ack(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                sd = os.path.join('data', 'raw', 'espn', '2025')
                games, boxes, odds = [], [], []
                for i in range(40):
                    gid = f'g{i}'
                    games.append({'game_id': gid, 'season': 2025, 'season_type': 2, 'start_utc': '2025-01-01T00:00:00Z',
                                  'home': '1', 'away': '2', 'status': 'final', 'home_pts': 110, 'away_pts': 100,
                                  'complete': True, 'box_source': 'espn'})
                    for t in ('1', '2'):
                        boxes.append({'game_id': gid, 'team': t, 'source': 'espn:summary', 'overtimes': 0, 'players': []})
                    for stage in ('open', 'close'):
                        bad = stage == 'close'
                        for side, line, price in (('home', -110.0 if bad else -5.5, 1.91), ('away', 110.0 if bad else 5.5, 1.91)):
                            odds.append({'game_id': gid, 'provider': 'ESPN BET', 'provider_type': 'book', 'stage': stage,
                                         'market': 'spread', 'side': side, 'line': line, 'price_decimal': price})
                        for side in ('over', 'under'):
                            odds.append({'game_id': gid, 'provider': 'ESPN BET', 'provider_type': 'book', 'stage': stage,
                                         'market': 'total', 'side': side, 'line': 221.5, 'price_decimal': 1.91})
                        for side, price in (('home', 1.45), ('away', 2.8)):
                            odds.append({'game_id': gid, 'provider': 'ESPN BET', 'provider_type': 'book', 'stage': stage,
                                         'market': 'ml', 'side': side, 'line': None, 'price_decimal': price})
                store.write_jsonl_gz(os.path.join(sd, 'games.jsonl.gz'), games)
                store.write_jsonl_gz(os.path.join(sd, 'teambox.jsonl.gz'), boxes)
                store.write_jsonl_gz(os.path.join(sd, 'odds.jsonl.gz'), odds)
                store.write_json(os.path.join(sd, quality.ACK_FILE), {
                    'season': 2025, 'decision': 'conditional_pass', 'data_version': quality.data_version(2025),
                    'exclusion_scope': [{'provider': 'ESPN BET', 'stage': 'close', 'markets': ['spread'],
                                         'flag': 'line_field_contains_price'}]})
                r = quality.season_report(2025, live=True)
            finally:
                os.chdir(cwd)
        self.assertEqual(r['quality_status'], 'FAILED')
        self.assertFalse(r['conditional_pass'])
        self.assertLess(r['strict_stage_coverage']['close/spread'], 95.0)
        self.assertEqual(r['strict_stage_coverage']['open/spread'], 100.0)
        self.assertFalse(r['conditional']['valid'])
