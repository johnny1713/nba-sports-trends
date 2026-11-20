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

    def test_periods_do_not_overlap(self):
        groups = [config.WARMUP_SEASONS, config.DEV_SEASONS, config.TUNE_SEASONS, config.HOLDOUT_SEASONS]
        flat = [s for g in groups for s in g]
        self.assertEqual(len(flat), len(set(flat)))
        self.assertLess(max(config.TUNE_SEASONS), min(config.HOLDOUT_SEASONS))   # 測試期在調參期之後

    def test_holdout_locked_unless_final_and_logged(self):
        config.check_seasons([2017, 2024])                      # 不碰鎖定期間：放行
        with self.assertRaises(config.HoldoutLocked):
            config.check_seasons([2024, 2025])
        self.assertEqual(config.holdout_views(), 0)
        config.check_seasons([2025], final=True, purpose='test')
        config.check_seasons([2026], final=True, purpose='test')
        self.assertEqual(config.holdout_views(), 2)


if __name__ == '__main__':
    unittest.main()
