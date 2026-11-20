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

    def begin(self, seasons=(2025,)):
        return config.holdout_begin(list(seasons), 'test', 'v2.0.0', 'data-abc', require_clean=False)

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
        self.assertEqual([r['type'] for r in recs], ['begin', 'result'])
        self.assertEqual(recs[0]['model_version'], 'v2.0.0')
        self.assertEqual(recs[0]['data_version'], 'data-abc')
        self.assertIn('code_sha', recs[0])
        self.assertEqual(config.holdout_views(), 1)

    def test_tampering_is_detected(self):
        rid = self.begin()
        config.holdout_finish(rid, {'roi': -0.031})
        with open(config.HOLDOUT_LOG, encoding='utf-8') as f:
            lines = f.read().splitlines()
        # 偷改結果
        r = json.loads(lines[1]); r['results']['roi'] = 0.08
        with open(config.HOLDOUT_LOG, 'w', encoding='utf-8') as f:
            f.write(lines[0] + '\n' + json.dumps(r) + '\n')
        with self.assertRaises(config.HoldoutLogCorrupted):
            config.verify_holdout_log()
        # 刪掉第一筆
        with open(config.HOLDOUT_LOG, 'w', encoding='utf-8') as f:
            f.write(lines[1] + '\n')
        with self.assertRaises(config.HoldoutLogCorrupted):
            config.verify_holdout_log()


class RepoHoldoutLogIntegrity(unittest.TestCase):
    def test_committed_log_chain_is_intact(self):
        """repo 裡真正的紀錄檔（若存在）每次 CI 都要驗證。"""
        config.verify_holdout_log()


if __name__ == '__main__':
    unittest.main()
