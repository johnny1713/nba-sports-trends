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
