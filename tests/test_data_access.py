"""資料存取層：模型實作前必須完成的防護測試（使用者 2026-11-20 第六輪）。

T1  未來資料：在預測日之後插入極端比賽，回傳資料完全不變
T2  同日較早比賽：同一美東日期較早結束的比賽不回傳
T3  盤口隔離：不 import 盤口模組；回傳欄位沒有 odds_*
T4  訓練／選模流程讀 2024-25、2025-26 → HoldoutLocked
T13 2017-18 失誤欄位隔離
T19 資料範圍（資料存取層部分）
T29 鎖定測試期在資料存取層強制
T30 需要 tov 的讀取排除 tov_usable = False 的 box
加上：F2／F1 跨球季 fallback、F4／F7 只用預測日前資料、依賴鏈防繞道、結構測試（特徵／模型／回測程式不得直接讀原始資料）
"""
import csv
import os
import re
import tempfile
import unittest

from nba_quant import config, data_access as DA, feature_deps, game_class, store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
RESTRICTED = ('feature_selection', 'tuning', 'model_selection', 'evaluation', 'backtest')


# ---------------------------------------------------------------- 合成資料（T1、T2、F4/F7 時間測試）
def make_root(d, games):
    """games: [(gid, start_utc, home, away, hp, ap, game_type)]，全部放在 2023 球季。"""
    os.makedirs(os.path.join(d, 'data', 'reference'))
    with open(os.path.join(d, 'data', 'reference', 'game_classification.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=game_class.FIELDS)
        w.writeheader()
        for gid, t, h, a, hp, ap, gt in games:
            w.writerow({'game_id': gid, 'season': 2023, 'start_utc': t, 'away': a, 'home': h, 'status': 'final',
                        'espn_season_type': 2, 'game_type': gt, 'counts_for_standings': game_class.COUNTS[gt],
                        **game_class.uses(gt), 'source_file': 'x', 'basis': 'test'})
    raw = os.path.join(d, 'data', 'raw', 'espn', '2023')
    gs, bx = [], []
    for gid, t, h, a, hp, ap, gt in games:
        gs.append({'game_id': gid, 'season': 2023, 'season_type': 2, 'start_utc': t, 'home': h, 'away': a,
                   'home_pts': hp, 'away_pts': ap, 'status': 'final', 'complete': True, 'odds_books': ['X'], 'odds_final': True})
        for team, pts in ((h, hp), (a, ap)):
            bx.append({'game_id': gid, 'team': team, 'pts': pts, 'fgm': 40, 'fga': 88, 'fg3m': 12, 'fg3a': 35, 'ftm': pts - 92,
                       'fta': 20, 'oreb': 10, 'dreb': 33, 'tov': 14, 'source': 'espn:summary'})
    store.write_jsonl_gz(os.path.join(raw, 'games.jsonl.gz'), gs)
    store.write_jsonl_gz(os.path.join(raw, 'teambox.jsonl.gz'), bx)


BASE_GAMES = [('g1', '2023-01-02T00:30:00Z', 'H', 'A', 110, 100, 'REGULAR_SEASON'),   # 美東 1/1 晚上
              ('g2', '2023-01-03T00:30:00Z', 'H', 'B', 105, 101, 'REGULAR_SEASON'),   # 美東 1/2
              ('g3', '2023-01-03T17:00:00Z', 'A', 'B', 99, 98, 'REGULAR_SEASON'),     # 美東 1/3 中午
              ('g4', '2023-01-04T00:30:00Z', 'H', 'A', 101, 97, 'REGULAR_SEASON')]    # 美東 1/3 晚上（預測對象）
AS_OF = '2023-01-04T00:30:00Z'


class Synthetic(unittest.TestCase):
    def run_with(self, games, scope='use_team_stats'):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, games)
            da = DA.DataAccess('feature_computation', root=d)
            return da.games(2023, scope, AS_OF), da.team_boxes(2023, scope, ['pts', 'fga', 'tov'], AS_OF)

    def test_T1_future_extreme_game_changes_nothing(self):
        base = self.run_with(BASE_GAMES)
        fut = self.run_with(BASE_GAMES + [('g9', '2023-02-01T00:30:00Z', 'H', 'A', 199, 50, 'REGULAR_SEASON')])
        self.assertEqual(base, fut)
        self.assertNotIn('g9', [g['game_id'] for g in fut[0]])

    def test_T2_same_et_day_earlier_game_excluded(self):
        gs, _ = self.run_with(BASE_GAMES)
        self.assertEqual([g['game_id'] for g in gs], ['g1', 'g2'])     # g3（同日中午、已完賽）不回傳
        changed = [x if x[0] != 'g3' else ('g3', x[1], 'A', 'B', 150, 60, x[6]) for x in BASE_GAMES]
        self.assertEqual(self.run_with(BASE_GAMES), self.run_with(changed))

    def test_T3_no_odds_fields_returned(self):
        gs, _ = self.run_with(BASE_GAMES)
        for g in gs:
            self.assertFalse([k for k in g if 'odds' in k])
            self.assertEqual(set(g), set(DA.GAME_FIELDS))

    def test_F4_F7_league_wide_reads_only_before_prediction_date(self):
        """F4（SRS 重解）與 F7（聯盟近期得分）是聯盟層級：不論哪一隊，都只看得到預測日前的比賽。"""
        gs, boxes = self.run_with(BASE_GAMES + [('g9', '2023-02-01T00:30:00Z', 'C', 'D', 150, 140, 'REGULAR_SEASON')])
        from nba_quant import asof
        cut = asof.et_date(AS_OF)
        self.assertTrue(all(asof.et_date(g['start_utc']) < cut for g in gs))
        self.assertTrue(all(asof.et_date(b['start_utc']) < cut for b in boxes))


class T3_OddsIsolation(unittest.TestCase):
    def test_module_does_not_import_odds(self):
        src = open(DA.__file__, encoding='utf-8').read()
        for m in ('odds_flags', 'clv', 'price_time', 'lines', 'taiwan', 'quality'):
            self.assertIsNone(re.search(rf'\bimport\s+.*\b{m}\b|from\s+\.\s*{m}\b|from\s+\.{m}\b', src), m)


class T4_T29_Locks(unittest.TestCase):
    def test_T4_training_and_selection_refuse_holdout(self):
        for p in ('training', 'model_selection', 'feature_computation'):
            da = DA.DataAccess(p)
            for s in (2025, 2026):
                with self.assertRaises(config.HoldoutLocked):
                    da.games(s, 'use_team_stats')

    def test_T29_all_restricted_purposes_blocked_2024_25(self):
        for p in RESTRICTED:
            da = DA.DataAccess(p)
            with self.assertRaises(config.HoldoutLocked):
                da.games(2025, 'use_team_stats')
            with self.assertRaises(config.HoldoutLocked):
                da.team_boxes(2025, 'use_fatigue', ['pts'])
            with self.assertRaises(config.HoldoutLocked):
                da.require_features(['F5.rest_days'], 2025)

    def test_T29_2025_26_refused_for_every_purpose(self):
        for p in DA.PURPOSES:
            with self.assertRaises(config.HoldoutLocked):
                DA.DataAccess(p).games(2026, 'use_elo')

    def test_T29_play_in_2024_25_also_locked(self):
        with self.assertRaises(config.HoldoutLocked):
            DA.DataAccess('backtest').games(2025, 'use_fatigue')     # use_fatigue 含附加賽

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_T29_data_quality_may_read_2024_25(self):
        gs = DA.DataAccess('data_quality').games(2025, 'use_fatigue')
        self.assertEqual(sum(1 for g in gs if g['game_type'] == 'PLAY_IN'), 6)

    def test_T29_registered_final_run_only_for_evaluation_and_never_2025_26(self):
        with tempfile.TemporaryDirectory() as d:
            old = config.HOLDOUT_LOG
            config.HOLDOUT_LOG = os.path.join(d, 'ops', 'holdout_log.jsonl')
            try:
                rid = config.holdout_begin([2025, 2026], 'final', 'v2.0.0', 'data', require_clean=False)
                DA.DataAccess('evaluation', run_id=rid).check_season(2025)          # 原定鎖定測試規則：放行
                for p in ('tuning', 'model_selection', 'feature_selection', 'backtest'):
                    with self.assertRaises(config.HoldoutLocked):
                        DA.DataAccess(p, run_id=rid).check_season(2025)
                with self.assertRaises(config.HoldoutLocked):                     # 2025-26 仍完全鎖定
                    DA.DataAccess('evaluation', run_id=rid).check_season(2026)
                with self.assertRaises(config.HoldoutLocked):                     # 未登記的 run_id
                    DA.DataAccess('evaluation', run_id='made-up').check_season(2025)
            finally:
                config.HOLDOUT_LOG = old

    def test_unknown_purpose_rejected(self):
        with self.assertRaises(ValueError):
            DA.DataAccess('exploration')


class Structural(unittest.TestCase):
    """不能只靠開發者自律：特徵、模型、回測程式不得直接讀原始資料或分類表，只能用 data_access。"""
    GUARDED = ('features', 'models', 'backtest', 'render')
    FORBIDDEN = (r'read_jsonl_gz', r"data['\"]?\s*,\s*['\"]raw", r'data/raw', r'game_classification\.csv', r'espn_playin')

    def test_feature_model_backtest_code_uses_data_access_only(self):
        pkg = os.path.join(ROOT, 'nba_quant')
        checked = 0
        for sub in self.GUARDED:
            for dp, _, files in os.walk(os.path.join(pkg, sub)):
                for f in files:
                    if f.endswith('.py'):
                        src = open(os.path.join(dp, f), encoding='utf-8').read()
                        checked += 1
                        for pat in self.FORBIDDEN:
                            self.assertIsNone(re.search(pat, src), f'{sub}/{f} 直接讀原始資料（{pat}）')
        self.assertGreaterEqual(checked, 1)        # backtest/stats.py 至少被檢查到


@unittest.skipUnless(HAS_DATA, 'no data')
class T13_T19_T30_RealData(unittest.TestCase):
    def setUp(self):
        self.da = DA.DataAccess('feature_computation')

    def test_T13_2017_18_tov_isolated(self):
        with self.assertRaises(DA.FieldUnavailable):
            self.da.team_boxes(2018, 'use_team_stats', ['pts', 'tov'])
        boxes = self.da.team_boxes(2018, 'use_team_stats', ['pts', 'fga', 'oreb', 'dreb', 'fta'])   # 其他欄位可讀
        self.assertEqual(len(boxes), 2460)
        self.assertTrue(all('tov' not in b for b in boxes))
        for f in ('F1.pace', 'F1.net_rating', 'F2.last5_net_rating', 'F3.tov_rate_off', 'F4.srs_net_rating', 'F7.pace_sum'):
            with self.assertRaises(DA.FeatureRejected):
                self.da.require_features([f], 2018)
        ok = self.da.require_features(['F3.efg_off', 'F3.orb_rate_off', 'F3.ft_rate_off', 'F4.srs_margin',
                                       'F7.league_recent_points', 'F5.rest_days', 'ELO.rating'], 2018)
        self.assertEqual({v[0] for v in ok.values()}, {'available'})

    def test_T19_scope(self):
        types = lambda s, sc: {g['game_type'] for g in self.da.games(s, sc)}
        self.assertFalse(types(2021, 'use_team_stats') & {'PLAY_IN', 'POSTSEASON'})
        self.assertTrue({'PLAY_IN', 'POSTSEASON'} <= types(2021, 'use_fatigue'))
        self.assertTrue({'PLAY_IN', 'POSTSEASON'} <= types(2021, 'use_elo'))
        self.assertIn('CUP_FINAL', types(2024, 'use_team_stats'))
        self.assertNotIn('CUP_FINAL', types(2024, 'counts_for_standings'))
        self.assertFalse(types(2021, 'train_sample') & {'PLAY_IN', 'POSTSEASON'})
        with self.assertRaises(ValueError):
            self.da.games(2021, 'regular_season')

    def test_T30_tov_excludes_unusable_boxes_but_games_stay_for_fatigue_and_elo(self):
        with_tov = self.da.team_boxes(2021, 'use_fatigue', ['tov'])
        without = self.da.team_boxes(2021, 'use_fatigue', ['pts'])
        box_logs = [x for x in self.da.log if x['call'] == 'team_boxes']
        excl = [e for e in box_logs[-2]['excluded'] if e[2] == 'bbref_player_only']
        self.assertEqual(box_logs[-1]['excluded'], [])                   # 不要求 tov 時不排除
        self.assertEqual(len(excl), 12)                                   # 6 場附加賽 × 2 隊
        self.assertEqual(len(without) - len(with_tov), 12)
        pi = [g for g in self.da.games(2021, 'use_elo') if g['game_type'] == 'PLAY_IN']
        self.assertEqual(len(pi), 6)                                      # 同場仍進 Elo／F5

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            self.da.team_boxes(2021, 'use_team_stats', ['possessions'])


@unittest.skipUnless(HAS_DATA, 'no data')
class Fallback2018_19(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.da = DA.DataAccess('feature_computation')
        g = [x for x in cls.da.games(2019, 'use_team_stats') if 'BOS' in (x['home_abbr'], x['away_abbr'])]
        cls.team = g[0]['home'] if g[0]['home_abbr'] == 'BOS' else g[0]['away']
        cls.g = g

    def test_f2_never_reaches_2017_18(self):
        for i, (n_used, status) in {0: (0, 'missing'), 3: (3, 'partial'), 10: (10, 'ok')}.items():
            w = self.da.f2_window(self.team, self.g[i]['start_utc'], 10, 'F2.last10_net_rating')
            self.assertEqual((w['n_used'], w['status']), (n_used, status), i)
            self.assertNotIn(2018, w['seasons'])
            if w['games']:
                ids2018 = {x['game_id'] for x in DA.DataAccess('feature_computation').games(2018, 'use_elo')}
                self.assertFalse(set(w['games']) & ids2018)

    def test_f2_below_minimum_is_missing_not_imputed(self):
        w = self.da.f2_window(self.team, self.g[1]['start_utc'], 5, 'F2.last5_net_rating')
        self.assertEqual((w['n_used'], w['status']), (1, 'missing'))
        self.assertEqual(len(w['games']), 1)

    def test_f2_window_crosses_into_available_previous_season(self):
        g = [x for x in self.da.games(2017, 'use_team_stats') if self.team in (x['home'], x['away'])][0]
        w = self.da.f2_window(self.team, g['start_utc'], 5, 'F2.last5_net_rating')
        self.assertEqual((w['status'], w['seasons']), ('ok', [2016]))

    def test_f1_prior_uses_league_average_not_2017_18(self):
        p = self.da.f1_prior_source(self.team, self.g[0]['start_utc'])
        self.assertEqual(p['source'], 'league_average_latest_available_season')
        self.assertEqual(p['seasons'], [2017])
        self.assertEqual(p['excluded_seasons'], [2018])
        p = self.da.f1_prior_source(self.team, self.g[10]['start_utc'])
        self.assertEqual(p['source'], 'league_average_current_season_to_date')
        self.assertEqual(p['seasons'], [2019])

    def test_f1_prior_normal_season_uses_team_previous_season(self):
        g = [x for x in self.da.games(2020, 'use_team_stats') if self.team in (x['home'], x['away'])][0]
        p = self.da.f1_prior_source(self.team, g['start_utc'])
        self.assertEqual((p['source'], p['seasons']), ('team_previous_season', [2019]))

    def test_records_games_and_period(self):
        w = self.da.f2_window(self.team, self.g[10]['start_utc'], 10, 'F2.last10_net_rating')
        self.assertEqual(len(w['games']), w['n_used'])
        self.assertEqual(len(w['period']), 2)


class NoBypass(unittest.TestCase):
    """依賴鏈防繞道。"""

    def test_every_downstream_of_unavailable_base_is_unavailable(self):
        for s, bases in feature_deps.SEASON_UNAVAILABLE.items():
            for f in feature_deps.FEATURES:
                self.assertEqual(feature_deps.availability(f, s)[0] == 'unavailable', bool(feature_deps.closure(f) & bases), f)

    def test_new_intermediate_cannot_launder_tov(self):
        """新增一個中間欄位，即使名稱看不出來，只要依賴鏈碰到 tov 就不可用。"""
        feature_deps.DERIVED['_ball_security'] = ('possessions',)
        feature_deps.FEATURES['_X.custom'] = ('F3', ('_ball_security',), None)
        try:
            self.assertEqual(feature_deps.availability('_X.custom', 2018)[0], 'unavailable')
            with self.assertRaises(DA.FeatureRejected):
                DA.DataAccess('feature_computation').require_features(['_X.custom'], 2018)
        finally:
            del feature_deps.DERIVED['_ball_security'], feature_deps.FEATURES['_X.custom']

    def test_unregistered_feature_rejected_by_access_layer(self):
        with self.assertRaises(KeyError):
            DA.DataAccess('feature_computation').require_features(['F1.ortg', 'F9.unregistered'], 2020)

    def test_raw_tov_cannot_be_requested_for_2017_18_under_any_scope(self):
        for sc in DA.SCOPES:
            with self.assertRaises(DA.FieldUnavailable):
                DA.DataAccess('feature_computation').team_boxes(2018, sc, ['tov'])
