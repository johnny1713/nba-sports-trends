import json
import os
import tempfile
import unittest

from nba_quant import config


class HoldoutTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.old = config.HOLDOUT_LOG
        config.HOLDOUT_LOG = os.path.join(self.d.name, 'ops', 'holdout_log.jsonl')

    def tearDown(self):
        config.HOLDOUT_LOG = self.old
        self.d.cleanup()

    def begin(self, seasons=(2025,), version='v2.0.0'):
        if version not in config.frozen_versions():
            config.freeze_model(version, 'manifest-abc', require_clean=False)
        return config.holdout_begin(list(seasons), config.FINAL_PURPOSE, version, 'data-abc', require_clean=False)

    def test_periods_do_not_overlap(self):
        groups = [config.WARMUP_SEASONS, config.DEV_SEASONS, config.TUNE_SEASONS, config.HOLDOUT_SEASONS]
        flat = [s for g in groups for s in g]
        self.assertEqual(len(flat), len(set(flat)))
        self.assertLess(max(config.TUNE_SEASONS), min(config.HOLDOUT_SEASONS))
        self.assertLess(max(config.HOLDOUT_SEASONS), config.LIVE_SEASON)

    def test_locked_without_registered_run(self):
        config.check_seasons([2017, 2024])                       # 不碰鎖定期：放行
        with self.assertRaises(config.HoldoutLocked):
            config.check_seasons([2024, 2025])
        with self.assertRaises(config.HoldoutLocked):
            config.check_seasons([2025], run_id='made-up')

    def test_run_lifecycle_and_write_once(self):
        rid = self.begin((2025,))
        config.check_seasons([2025], rid)
        with self.assertRaises(config.HoldoutLocked):              # 沒登記的球季
            config.check_seasons([2026], rid)
        config.holdout_finish(rid, {'roi': -0.031, 'n': 1180})
        with self.assertRaises(config.HoldoutLocked):              # 結果只能寫一次
            config.holdout_finish(rid, {'roi': 0.05})
        with self.assertRaises(config.HoldoutLocked):              # 已結束的 run 不能再拿來看
            config.check_seasons([2025], rid)
        recs = config.verify_holdout_log()
        self.assertEqual([r['type'] for r in recs], ['freeze', 'begin', 'result'])
        self.assertEqual(recs[1]['model_version'], 'v2.0.0')
        self.assertEqual(recs[1]['data_version'], 'data-abc')
        self.assertIn('code_sha', recs[1])
        self.assertEqual(recs[2]['seasons'], [2025])
        self.assertEqual(config.holdout_views(), 1)

    def test_tampering_is_detected(self):
        rid = self.begin()
        config.holdout_finish(rid, {'roi': -0.031})
        with open(config.HOLDOUT_LOG, encoding='utf-8') as f:
            lines = f.read().splitlines()
        # 偷改結果
        r = json.loads(lines[2]); r['results']['roi'] = 0.08
        with open(config.HOLDOUT_LOG, 'w', encoding='utf-8') as f:
            f.write(lines[0] + '\n' + lines[1] + '\n' + json.dumps(r) + '\n')
        with self.assertRaises(config.HoldoutLogCorrupted):
            config.verify_holdout_log()
        # 刪掉第一筆
        with open(config.HOLDOUT_LOG, 'w', encoding='utf-8') as f:
            f.write(lines[1] + '\n' + lines[2] + '\n')
        with self.assertRaises(config.HoldoutLogCorrupted):
            config.verify_holdout_log()


class FinalEvaluationRules(HoldoutTests):
    """第七輪：凍結後分別登記、每季一次、只限最終評估、結果分開、看過結果後改模型 → 失去獨立性。"""

    def test_requires_frozen_model(self):
        with self.assertRaises(config.HoldoutLocked):
            config.holdout_begin([2025], config.FINAL_PURPOSE, 'never-frozen', 'd', require_clean=False)

    def test_one_season_per_registration(self):
        config.freeze_model('v1', 'm', require_clean=False)
        with self.assertRaises(config.HoldoutLocked):
            config.holdout_begin([2025, 2026], config.FINAL_PURPOSE, 'v1', 'd', require_clean=False)
        with self.assertRaises(config.HoldoutLocked):
            config.holdout_begin([2024, 2025], config.FINAL_PURPOSE, 'v1', 'd', require_clean=False)

    def test_only_final_evaluation_purpose(self):
        config.freeze_model('v1', 'm', require_clean=False)
        for p in ('training', 'feature_selection', 'tuning', 'model_selection', 'backtest', 'test'):
            with self.assertRaises(config.HoldoutLocked):
                config.holdout_begin([2025], p, 'v1', 'd', require_clean=False)

    def test_each_season_evaluated_once(self):
        rid = self.begin((2025,))
        with self.assertRaises(config.HoldoutLocked):                 # 尚未出結果也不能再登記
            self.begin((2025,))
        config.holdout_finish(rid, {'brier': 0.21})
        with self.assertRaises(config.HoldoutLocked):                 # 出結果後也不能再登記
            self.begin((2025,))
        self.begin((2026,))                                            # 另一季可以

    def test_results_kept_separate(self):
        r1, r2 = self.begin((2025,)), self.begin((2026,))
        config.holdout_finish(r1, {'brier': 0.21})
        config.holdout_finish(r2, {'brier': 0.23})
        self.assertEqual(config.holdout_results(), {2025: [{'brier': 0.21}], 2026: [{'brier': 0.23}]})
        self.assertFalse(hasattr(config, 'holdout_combined'))

    def test_combined_results_rejected(self):
        rid = self.begin((2025,))
        with self.assertRaises(config.HoldoutLocked):
            config.holdout_finish(rid, {'combined': {'brier': 0.22}})

    def test_independence_lost_after_model_change(self):
        rid = self.begin((2025,))
        self.assertTrue(config.holdout_independence()['independent'])
        config.holdout_finish(rid, {'brier': 0.21})
        self.assertTrue(config.holdout_independence()['independent'])
        config.freeze_model('v2.0.1', 'm2', require_clean=False)        # 看過結果後改模型
        st = config.holdout_independence()
        self.assertFalse(st['independent'])
        self.assertTrue(st['reasons'])

    def test_independence_lost_if_second_season_uses_other_version(self):
        rid = self.begin((2025,), version='v1')
        config.holdout_finish(rid, {'brier': 0.21})
        self.begin((2026,), version='v2')                               # 凍結 v2 發生在看過結果後
        self.assertFalse(config.holdout_independence()['independent'])


class RepoHoldoutLogIntegrity(unittest.TestCase):
    def test_committed_log_chain_is_intact(self):
        """repo 裡真正的紀錄檔（若存在）每次 CI 都要驗證。"""
        config.verify_holdout_log()


if __name__ == '__main__':
    unittest.main()
