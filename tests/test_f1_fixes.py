"""F1 四個程式缺口修正（2026-11-21）。T37。公式與先驗規則不變（先驗 B 待核准）。"""
import os
import tempfile
import unittest
from unittest import mock

from nba_quant import config, data_access as DA, store
from nba_quant.features import f1

from test_f1 import make_root

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
PRIOR_SEASON = [('p1', 2019, '2019-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
                ('p2', 2019, '2019-01-04T00:30:00Z', 'C', 'D', 100, 104, 'REGULAR_SEASON')]
ZERO = {'fga': 10, 'oreb': 10, 'tov': 0, 'fta': 0}           # 回合數 = 0


def compute(games, season=2020, mutate=None):
    with tempfile.TemporaryDirectory() as d:
        make_root(d, games)
        if mutate:
            p = os.path.join(d, 'data', 'raw', 'espn', str(season), 'teambox.jsonl.gz')
            bx = list(store.read_jsonl_gz(p))
            mutate(bx)
            store.write_jsonl_gz(p, bx)
        return f1.compute(season, root=d)


def row(res, gid, team):
    return [r for r in res.rows if r['game_id'] == gid and r['team'] == team][0]


G = [('g1', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
     ('g2', 2020, '2020-01-04T00:30:00Z', 'A', 'B', 105, 95, 'REGULAR_SEASON'),
     ('g3', 2020, '2020-01-06T00:30:00Z', 'A', 'C', 100, 90, 'REGULAR_SEASON')]


class MissingBoxes(unittest.TestCase):
    def test_1_target_game_without_box_still_has_rows(self):
        def drop(bx):
            bx[:] = [b for b in bx if b['game_id'] != 'g3']             # 預測目標 g3 完全沒有 box
        res = compute(PRIOR_SEASON + G, mutate=drop)
        rows = [r for r in res.rows if r['game_id'] == 'g3']
        self.assertEqual({r['team'] for r in rows}, {'A', 'C'})
        self.assertEqual(row(res, 'g3', 'A')['n_games'], 2)
        self.assertIsNotNone(row(res, 'g3', 'A')['F1.ortg'])

    def test_2_history_game_with_one_box_missing_excluded_for_both(self):
        def drop(bx):
            for b in bx:
                if b['game_id'] == 'g1' and b['team'] == 'B':
                    b['tov'] = None                                     # 只有 B 缺欄位
        res = compute(PRIOR_SEASON + G, mutate=drop)
        self.assertEqual(row(res, 'g2', 'A')['n_games'], 0)            # A 也不累計 g1
        self.assertEqual(row(res, 'g2', 'B')['n_games'], 0)
        self.assertEqual(row(res, 'g2', 'A')['excluded_history_games'], 1)
        e = [x for x in res.excluded if x['game_id'] == 'g1'][0]
        self.assertEqual((e['missing_teams'], e['reason']), (['B'], 'missing_field'))
        self.assertEqual(sorted(e['teams']), ['A', 'B'])
        self.assertIn('both', e['affected'])


class Possessions(unittest.TestCase):
    def test_3_single_game_zero_poss_not_used(self):
        g = [('z', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON', ZERO, ZERO), G[1]]
        res = compute(PRIOR_SEASON + g)
        r = row(res, 'g2', 'A')
        self.assertEqual(r['n_games'], 0)                               # 不被當成 0 納入
        self.assertEqual(r['F1.ortg'], r['prior_ortg'])                 # 只剩先驗，不被拉向 0
        e = res.excluded[0]
        self.assertEqual(e['reason'], 'invalid_possessions')
        self.assertEqual(e['poss'], {'A': 0.0, 'B': 0.0})
        self.assertEqual(e['raw_boxes']['A']['fga'], 10)               # 保留原始數據

    def test_3b_one_team_nonpositive_poss_is_invalid(self):
        g = [('z', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON', ZERO, {}), G[1]]
        res = compute(PRIOR_SEASON + g)
        self.assertEqual(res.excluded[0]['reason'], 'invalid_possessions')
        self.assertEqual(row(res, 'g2', 'B')['n_games'], 0)

    def test_4_cumulative_zero_poss_gives_invalid_status(self):
        acc = f1.Acc()
        acc.add({'pf': 100, 'pa': 90, 'poss': 0.0, 'mf': 1.0, 'start_utc': '2020-01-02T00:30:00Z'})
        self.assertIsNone(acc.values())
        real = f1.build_history

        def poisoned(da, season, schedule=None):
            h = real(da, season, schedule)
            for r in h.rows:
                r['poss'] = 0.0                                         # 模擬累計回合數為 0
            return h
        with mock.patch.object(f1, 'build_history', poisoned):
            res = compute(PRIOR_SEASON + G)
        r = row(res, 'g2', 'A')
        self.assertEqual(r['status'], 'invalid')
        self.assertTrue(all(r[f] is None for f in f1.FEATURES))

    def test_5_outlier_flagged_not_silently_used(self):
        base = [(f'n{i}', 2020, f'2020-01-{(i % 28) + 1:02d}T{"00" if i < 28 else "17"}:30:00Z',
                 f'T{i % 6}', f'U{i % 6}', 100, 95, 'REGULAR_SEASON', {'fga': 80 + i % 9}, {'fga': 82 + i % 7})
                for i in range(40)]
        odd = [('odd', 2020, '2020-01-20T03:00:00Z', 'X', 'Y', 140, 130, 'REGULAR_SEASON', {'fga': 300}, {'fga': 300})]
        res = compute(PRIOR_SEASON + base + odd)
        self.assertEqual([w['game_id'] for w in res.warnings], ['odd'])
        self.assertEqual(res.warnings[0]['action'], 'flag_only')        # 標記但不排除
        self.assertFalse([e for e in res.excluded if e['game_id'] == 'odd'])

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_5b_real_data_exclusions_only_audit_errors_and_no_pace_band_warnings(self):
        for s in (2016, 2019, 2021):
            res = f1.compute(s)
            self.assertEqual(res.excluded, [], s)                                   # 這三季沒有 box 稽核 error
            self.assertFalse([w for w in res.warnings if w['source'] == 'f1_pace_band'], s)
            self.assertTrue(all(w['action'] == 'kept_with_warning' for w in res.warnings if w['source'] == 'box_audit_v1'))


class PriorFields(unittest.TestCase):
    REQUIRED = ('prior_ortg', 'prior_drtg', 'prior_net_rating', 'prior_pace', 'prior_value', 'prior_source', 'prior_season',
                'prior_weight', 'prior_weight_basis', 'team_shrinkage_M', 'prior_team_weight_W', 'league_prior_K',
                'league_games_asof', 'league_games_asof_excl_team', 'n_games',
                'raw_ortg', 'raw_drtg', 'raw_net_rating', 'raw_pace', 'F1.ortg', 'F1.drtg', 'F1.net_rating', 'F1.pace',
                'status')

    def check(self, rows):
        for r in rows:
            for k in self.REQUIRED:
                self.assertIn(k, r)
            self.assertNotIn('prior_effective_games', r)                    # 已移除（易與 K 混淆）
            self.assertIsNone(r['league_prior_K'])                             # 方案 A 不使用 K
            if r['status'] in ('available', 'available_prior_excluded'):
                self.assertEqual(r['prior_value'], {k: r[f'prior_{k}'] for k in f1.KEYS})
                for k in f1.KEYS:
                    self.assertIsNotNone(r[f'prior_{k}'])
                    raw = r[f'raw_{k}'] if r[f'raw_{k}'] is not None else 0.0
                    want = (r['n_games'] * raw + r['team_shrinkage_M'] * r[f'prior_{k}']) / (r['n_games'] + r['team_shrinkage_M'])
                    self.assertAlmostEqual(r[f'F1.{k}'], want, places=9)

    def test_6_synthetic(self):
        self.check(compute(PRIOR_SEASON + G).rows)

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_6_real_data(self):
        for s in (2015, 2016, 2018, 2019, 2023):
            self.check(f1.compute_season(s))


class Purpose(unittest.TestCase):
    BAD = ('data_quality', 'training', 'feature_selection', 'tuning', 'model_selection', 'evaluation', 'backtest')

    def test_7_data_quality_cannot_call_f1(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, [(x[0], 2025, x[2].replace('2020', '2025'), *x[3:]) for x in G])    # 合成 2025，不讀真實鎖定期
            for p in self.BAD:
                with self.assertRaises(f1.PurposeNotAllowed):
                    f1.compute_season(2025, purpose=p, root=d)                 # 直接呼叫
                da = DA.DataAccess(p, root=d)
                for call in (lambda: f1.compute(2025, da=da),                    # 批次
                             lambda: f1.compute_season(2025, purpose='feature_computation', da=da),   # 參數不一致
                             lambda: f1.season_totals(da, 2025),                 # 其他函式
                             lambda: f1.build_history(da, 2025),
                             lambda: f1.f1_reference(da, 'A', '2025-01-06T00:30:00Z')):
                    with self.assertRaises(f1.PurposeNotAllowed):
                        call()

    def test_8_bypass_attempts_refused(self):
        da = DA.DataAccess('data_quality')
        with self.assertRaises(AttributeError):
            da.purpose = 'feature_computation'                                 # 建立後改用途
        with self.assertRaises(AttributeError):
            da.run_id = 'x'

        class Fake:
            purpose = 'feature_computation'
        with self.assertRaises(f1.PurposeNotAllowed):
            f1.compute(2020, da=Fake())                                        # 非 DataAccess 物件
        with self.assertRaises(f1.PurposeNotAllowed):
            f1.season_totals(Fake(), 2020)

    def test_8b_allowed_purposes_still_respect_locks(self):
        for s in (2024, 2025, 2026):
            for p in f1.ALLOWED_PURPOSES:
                with self.assertRaises(config.HoldoutLocked):
                    f1.compute_season(s, purpose=p)
        with self.assertRaises(config.HoldoutLocked):
            f1.compute_season(2017, purpose='history_features')               # 沒有 as_of


@unittest.skipUnless(HAS_DATA, 'no data')
class Regression(unittest.TestCase):
    def test_period_uses_et_dates(self):
        r = [x for x in f1.compute_season(2019) if x['n_games'] == 10][0]
        self.assertRegex(r['period'][0], r'^\d{4}-\d{2}-\d{2}$')
