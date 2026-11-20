"""2023-24 驗證期鎖定與歷史特徵生成（使用者 2026-11-20 第八輪）。"""
import os
import tempfile
import unittest

from nba_quant import config, data_access as DA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
FORBIDDEN = ('feature_computation', 'training', 'feature_selection', 'tuning', 'model_selection', 'evaluation', 'backtest')
OPENING_2024_25 = '2024-10-23T23:30:00Z'      # 2024-25 開季附近（屬於 2025 球季）
MID_2023_24 = '2024-01-15T00:30:00Z'          # 2023-24 季中（屬於 2024 球季）
MID_2016_17 = '2017-01-15T00:30:00Z'


class LogIsolated(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.old = config.HOLDOUT_LOG
        config.HOLDOUT_LOG = os.path.join(self.d.name, 'ops', 'holdout_log.jsonl')

    def tearDown(self):
        config.HOLDOUT_LOG = self.old
        self.d.cleanup()

    def freeze(self, v='v1'):
        config.freeze_model(v, 'manifest', require_clean=False)


class BeforeFreeze(LogIsolated):
    def test_2023_24_only_data_quality(self):
        for p in FORBIDDEN:
            with self.assertRaises(config.HoldoutLocked):
                DA.DataAccess(p).check_season(2024)
        DA.DataAccess('data_quality').check_season(2024)

    def test_validation_impossible_before_freeze(self):
        with self.assertRaises(config.HoldoutLocked):
            config.validation_begin('v-unfrozen', 'f1', {}, 'd', require_clean=False)
        with self.assertRaises(config.HoldoutLocked):
            DA.DataAccess('validation').check_season(2024)
        with self.assertRaises(config.HoldoutLocked):
            DA.DataAccess('validation', run_id='made-up').check_season(2024)

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_history_features_cannot_bypass_locks(self):
        h = DA.DataAccess('history_features')
        with self.assertRaises(config.HoldoutLocked):          # 沒有 as_of
            h.games(2023, 'use_elo')
        with self.assertRaises(config.HoldoutLocked):          # 2023-24 季中：目標季未授權
            h.games(2024, 'use_elo', as_of=MID_2023_24)
        with self.assertRaises(config.HoldoutLocked):          # 2024-25 開季想讀 2023-24 歷史：目標季未授權
            h.games(2024, 'use_elo', as_of=OPENING_2024_25)
        with self.assertRaises(config.HoldoutLocked):          # 開發期目標不能讀未來球季
            h.games(2018, 'use_elo', as_of=MID_2016_17)

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_history_features_dev_target_reads_only_before_as_of(self):
        h = DA.DataAccess('history_features')
        gs = h.games(2017, 'use_elo', as_of=MID_2016_17) + h.games(2016, 'use_elo', as_of=MID_2016_17)
        from nba_quant import asof
        self.assertTrue(gs)
        self.assertTrue(all(asof.et_date(g['start_utc']) < asof.et_date(MID_2016_17) for g in gs))

    def test_history_features_never_outputs_metrics(self):
        with self.assertRaises(config.HoldoutLocked):
            DA.DataAccess('history_features').assert_metrics_allowed([2017])

    def test_metrics_for_locked_seasons_refused_outside_registered_runs(self):
        for p in FORBIDDEN + ('data_quality',):
            for s in (2024, 2025, 2026):
                with self.assertRaises(config.HoldoutLocked):
                    DA.DataAccess(p).assert_metrics_allowed([s])
        DA.DataAccess('evaluation').assert_metrics_allowed([2019, 2020])        # 開發期可以


class AfterFreeze(LogIsolated):
    def test_one_validation_with_full_record(self):
        self.freeze('v1')
        rid = config.validation_begin('v1', 'features-f1', {'elo_k': 20}, 'data-x', require_clean=False)
        rec = [r for r in config.verify_holdout_log() if r['type'] == 'validation_begin'][0]
        for k in ('model_version', 'feature_version', 'params', 'freeze_at', 'data_version', 'code_sha', 'at'):
            self.assertIn(k, rec)
        self.assertEqual(rec['seasons'], [2024])
        da = DA.DataAccess('validation', run_id=rid)
        da.check_season(2024)
        da.assert_metrics_allowed([2024])
        with self.assertRaises(config.HoldoutLocked):          # 驗證 run 不能碰 2024-25
            da.check_season(2025)
        for p in FORBIDDEN:                                    # 其他用途帶 run_id 仍不行
            with self.assertRaises(config.HoldoutLocked):
                DA.DataAccess(p, run_id=rid).check_season(2024)
        with self.assertRaises(config.HoldoutLocked):          # 第二次登記
            config.validation_begin('v1', 'f', {}, 'd', require_clean=False)
        config.validation_finish(rid, {'brier': 0.21})
        with self.assertRaises(config.HoldoutLocked):          # 完成後不能再讀、不能重跑
            da.check_season(2024)
        with self.assertRaises(config.HoldoutLocked):
            config.validation_finish(rid, {'brier': 0.2})

    def test_independence_lost_if_model_changed_after_results(self):
        self.freeze('v1')
        rid = config.validation_begin('v1', 'f', {}, 'd', require_clean=False)
        self.assertTrue(config.validation_independence()['independent'])
        config.validation_finish(rid, {'brier': 0.21})
        self.freeze('v1.1')
        self.assertFalse(config.validation_independence()['independent'])

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_history_for_2024_25_opening_needs_that_seasons_final_run(self):
        self.freeze('v1')
        r25 = config.holdout_begin([2025], config.FINAL_PURPOSE, 'v1', 'd', require_clean=False)
        h = DA.DataAccess('history_features', run_id=r25)
        gs = h.games(2024, 'use_elo', as_of=OPENING_2024_25)          # 2024-25 開季 Elo 可用 2023-24 已完賽比賽
        self.assertTrue(gs)
        from nba_quant import asof
        self.assertTrue(all(asof.et_date(g['start_utc']) < asof.et_date(OPENING_2024_25) for g in gs))
        with self.assertRaises(config.HoldoutLocked):                 # 不能讀 2025-26
            h.games(2026, 'use_elo', as_of=OPENING_2024_25)
        with self.assertRaises(config.HoldoutLocked):                 # 不能輸出指標
            h.assert_metrics_allowed([2024])
        with self.assertRaises(config.HoldoutLocked):                 # 2023-24 季中的歷史仍需驗證 run
            h.games(2024, 'use_elo', as_of=MID_2023_24)
