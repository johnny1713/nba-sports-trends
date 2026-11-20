import math
import unittest

import numpy as np

from nba_quant.backtest import stats


class StatsTests(unittest.TestCase):
    def test_wilson_known_values(self):
        lo, hi = stats.wilson_ci(50, 100)
        self.assertAlmostEqual(lo, 0.4038, places=3)
        self.assertAlmostEqual(hi, 0.5962, places=3)
        self.assertEqual(stats.wilson_ci(0, 0), (None, None))

    def test_settlement_and_push(self):
        bets = [{'result': 'win', 'price': 1.9}, {'result': 'loss', 'price': 1.9},
                {'result': 'push', 'price': 1.9}, {'result': 'win', 'price': 2.5}]
        s = stats.betting_summary(bets)
        self.assertEqual((s['wins'], s['losses'], s['pushes']), (2, 1, 1))
        self.assertAlmostEqual(s['profit'], 0.9 - 1 + 0 + 1.5)
        self.assertAlmostEqual(s['roi'], 1.4 / 4)
        self.assertAlmostEqual(s['hit_rate'], 2 / 3)        # push 不計入分母
        self.assertIn('樣本只有 4 筆', s['warning'])

    def test_no_edge_coinflip_ci_contains_zero(self):
        rng = np.random.default_rng(0)
        bets = [{'result': 'win' if rng.random() < 1 / 1.909 else 'loss', 'price': 1.909} for _ in range(2000)]
        s = stats.betting_summary(bets)
        self.assertLess(s['roi_ci'][0], 0)
        self.assertGreater(s['roi_ci'][1], 0)
        self.assertGreater(s['roi_p_value_gt0'], 0.05)
        self.assertIn('包含 0', s['warning'])

    def test_drawdown_and_streak(self):
        self.assertEqual(stats.max_drawdown([1, -1, -1, -1, 2, -3]), 4.0)
        self.assertEqual(stats.max_losing_streak(['loss', 'push', 'loss', 'win', 'loss']), 2)

    def test_brier_logloss(self):
        self.assertAlmostEqual(stats.brier([0.5, 0.5], [1, 0]), 0.25)
        self.assertAlmostEqual(stats.log_loss([0.5], [1]), math.log(2))

    def test_paired_diff_detects_only_real_differences(self):
        rng = np.random.default_rng(1)
        y = rng.integers(0, 2, 3000)
        p_true = np.where(y == 1, 0.6, 0.4)
        base = stats.per_game_brier(np.full(3000, 0.5), y)
        better = stats.per_game_brier(p_true, y)
        self.assertTrue(stats.paired_diff(better, base)['model_better'])
        same = stats.paired_diff(base, base)
        self.assertFalse(same['model_better'] or same['model_worse'])

    def test_calibration_bins_cover_all(self):
        p = np.linspace(0, 1, 101)
        y = (p > 0.5).astype(int)
        bins = stats.calibration_bins(p, y)
        self.assertEqual(sum(b['n'] for b in bins), 101)


if __name__ == '__main__':
    unittest.main()
