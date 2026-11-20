"""F1 第二輪審查的補充測試（唯讀；不改公式）。T36。"""
import os
import random
import shutil
import tempfile
import unittest

from nba_quant import config, data_access as DA, store
from nba_quant.features import f1

from test_f1 import make_root

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
M = f1.SHRINK_GAMES


def backed_out_prior(r, k):
    """由輸出反推先驗值：F1 = (n × raw + M × prior)/(n + M)。"""
    raw = r['raw'][k] if r['raw'] else 0.0
    return ((r['n_games'] + M) * r[f'F1.{k}'] - r['n_games'] * raw) / M


class HandCalculations(unittest.TestCase):
    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_real_game_0ot_phi_at_bos(self):
        """2022-10-18 PHI@BOS：PHI poss = 80-4+14+0.44*28 = 102.32；BOS = 82-6+11+0.44*28 = 99.32；平均 100.82。"""
        r = [x for x in f1.compute_season(2023) if x['game_id'] == '401468170' and x['n_games'] == 1]
        r = [x for x in r if x['raw'] and abs(x['raw']['pace'] - 100.82) < 1e-9][0]   # PHI 第 2 場，賽前只打過那一場
        self.assertAlmostEqual(r['raw']['ortg'], 100 * 117 / 100.82, places=9)
        self.assertAlmostEqual(r['raw']['drtg'], 100 * 126 / 100.82, places=9)
        self.assertAlmostEqual(r['raw']['pace'], 100.82, places=9)

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_real_game_1ot_ny_at_mem(self):
        """2022-10-19 NY@MEM（1 OT）：(110.92 + 112.12)/2 = 111.52；Pace = 111.52 / (53/48) = 101.00。"""
        r = [x for x in f1.compute_season(2023) if x['game_id'] == '401468178' and x['n_games'] == 1]
        r = [x for x in r if abs(x['raw']['ortg'] - 100 * 112 / 111.52) < 1e-9][0]
        self.assertAlmostEqual(r['raw']['drtg'], 100 * 115 / 111.52, places=9)
        self.assertAlmostEqual(r['raw']['pace'], 111.52 / (53 / 48), places=9)

    def test_2ot_synthetic_with_real_numbers(self):
        """MIL@OKC 2022-11-10（2 OT）數據：(121.68 + 116.36)/2 = 119.02；Pace = 119.02 / (58/48) = 98.50。"""
        g = [('o2', 2020, '2020-01-02T00:30:00Z', 'OKC', 'MIL', 132, 136, 'REGULAR_SEASON',
              {'fga': 111, 'oreb': 16, 'tov': 13, 'fta': 19, 'ot': 2}, {'fga': 106, 'oreb': 11, 'tov': 17, 'fta': 22, 'ot': 2}),
             ('nx', 2020, '2020-01-04T00:30:00Z', 'MIL', 'OKC', 100, 90, 'REGULAR_SEASON')]
        with tempfile.TemporaryDirectory() as d:
            make_root(d, g)
            r = [x for x in f1.compute_season(2020, root=d) if x['game_id'] == 'nx' and x['team'] == 'MIL'][0]
        self.assertAlmostEqual(r['raw']['pace'], 119.02 / (58 / 48), places=9)
        self.assertAlmostEqual(r['raw']['ortg'], 100 * 136 / 119.02, places=9)
        self.assertAlmostEqual(round(r['raw']['pace'], 2), 98.50)


class FormulaProperties(unittest.TestCase):
    def run_rows(self, games, season=2020):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, games)
            return f1.compute_season(season, root=d)

    def test_totals_not_mean_of_game_ratings(self):
        g = [('a', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 120, 100, 'REGULAR_SEASON', {'fga': 100}, {'fga': 100}),
             ('b', 2020, '2020-01-04T00:30:00Z', 'A', 'B', 90, 95, 'REGULAR_SEASON', {'fga': 70}, {'fga': 70}),
             ('c', 2020, '2020-01-06T00:30:00Z', 'A', 'B', 100, 100, 'REGULAR_SEASON')]
        r = [x for x in self.run_rows(g) if x['game_id'] == 'c' and x['team'] == 'A'][0]
        pa, pb = 100 - 10 + 14 + 0.44 * 20, 70 - 10 + 14 + 0.44 * 20
        self.assertAlmostEqual(r['raw']['ortg'], 100 * (120 + 90) / (pa + pb))
        mean_of_games = (100 * 120 / pa + 100 * 90 / pb) / 2
        self.assertNotAlmostEqual(r['raw']['ortg'], mean_of_games, places=3)

    def test_overtime_changes_only_pace(self):
        base = [('a', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 120, 110, 'REGULAR_SEASON'),
                ('z', 2020, '2020-01-04T00:30:00Z', 'A', 'B', 100, 90, 'REGULAR_SEASON')]
        ot = [('a', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 120, 110, 'REGULAR_SEASON', {'ot': 2}, {'ot': 2}), base[1]]
        r0 = [x for x in self.run_rows(base) if x['game_id'] == 'z' and x['team'] == 'A'][0]
        r2 = [x for x in self.run_rows(ot) if x['game_id'] == 'z' and x['team'] == 'A'][0]
        self.assertEqual(r0['raw']['ortg'], r2['raw']['ortg'])           # 回合數沒有被延長賽改動
        self.assertEqual(r0['raw']['drtg'], r2['raw']['drtg'])
        self.assertAlmostEqual(r2['raw']['pace'], r0['raw']['pace'] * 48 / 58)

    def test_team_fields_come_from_own_box(self):
        """本隊回合數只用本隊的 FGA／OREB／TOV／FTA：改對手的 OREB 只透過『兩隊平均』影響，幅度為一半。"""
        g = [('a', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
             ('z', 2020, '2020-01-04T00:30:00Z', 'A', 'B', 100, 90, 'REGULAR_SEASON')]
        g2 = [('a', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON', {}, {'oreb': 20}), g[1]]
        p0 = [x for x in self.run_rows(g) if x['game_id'] == 'z' and x['team'] == 'A'][0]['raw']['pace']
        p1 = [x for x in self.run_rows(g2) if x['game_id'] == 'z' and x['team'] == 'A'][0]['raw']['pace']
        self.assertAlmostEqual(p0 - p1, 10 / 2)


@unittest.skipUnless(HAS_DATA, 'no data')
class PriorRules(unittest.TestCase):
    def test_normal_season_prior_fixed_for_whole_season(self):
        rows = f1.compute_season(2016)
        by = {}
        for r in rows:
            by.setdefault(r['team'], set()).add(round(backed_out_prior(r, 'ortg'), 9))
        self.assertTrue(all(len(v) == 1 for v in by.values()))

    def test_prior_team_and_league_combination(self):
        """先驗 = W × 該隊上季全季值 + (1 − W) × 上季聯盟平均（以 DataAccess 重算上季全季值）。"""
        rows = f1.compute_season(2016)
        da = DA.DataAccess('feature_computation')
        teams, league = f1.season_totals(da, 2015)
        lv = f1.league_values(league)
        r = rows[0]
        tv = teams[r['team']].values()
        self.assertAlmostEqual(backed_out_prior(r, 'ortg'), 0.5 * tv['ortg'] + 0.5 * lv['ortg'], places=9)
        self.assertAlmostEqual(backed_out_prior(r, 'net_rating'), 0.5 * tv['net_rating'], places=9)   # 聯盟淨值 = 0

    def test_current_season_league_prior_is_as_of(self):
        """2018-19 改用本季至今聯盟平均後，反推的先驗 = 以 DataAccess(as_of) 重算的聯盟平均（只含預測日前的比賽）。"""
        rows = [r for r in f1.compute_season(2019) if r['prior_source'] == 'league_average_current_season_to_date']
        da = DA.DataAccess('feature_computation')
        for r in random.Random(7).sample(rows, 15):
            acc = f1.Acc()
            for x in f1.game_rows(da.team_boxes(2019, f1.SCOPE, list(f1.FIELDS), r['as_of'])):
                acc.add(x)
            lv = f1.league_values(acc)
            self.assertAlmostEqual(backed_out_prior(r, 'ortg'), lv['ortg'], places=6)
            self.assertAlmostEqual(backed_out_prior(r, 'pace'), lv['pace'], places=6)

    def test_2018_19_switch_point(self):
        rows = sorted(f1.compute_season(2019), key=lambda r: (r['as_of'], r['game_id']))
        srcs = [r['prior_source'] for r in rows]
        k = srcs.index('league_average_current_season_to_date')
        self.assertTrue(all(s == 'league_average_latest_available_season' for s in srcs[:k]))
        self.assertTrue(all(s == 'league_average_current_season_to_date' for s in srcs[k:]))   # 切換後不再切回
        self.assertTrue(all(r['prior_seasons'] == [2017] for r in rows[:k]))
        self.assertTrue(all(r['prior_seasons'] == [2019] for r in rows[k:]))


@unittest.skipUnless(HAS_DATA, 'no data')
class Isolation2017_18(unittest.TestCase):
    def test_extreme_2017_18_data_leaves_2018_19_unchanged(self):
        """把 2017-18 原始 box（失誤及所有欄位）與比分全部換成極端值：2018-19 F1 逐位相同，且資料存取紀錄從未讀取 2017-18。"""
        with tempfile.TemporaryDirectory() as d:
            for p in ('data/reference',):
                shutil.copytree(os.path.join(ROOT, p), os.path.join(d, p))
            for s in (2016, 2017, 2018, 2019):
                shutil.copytree(os.path.join(ROOT, 'data', 'raw', 'espn', str(s)), os.path.join(d, 'data', 'raw', 'espn', str(s)))
            raw = os.path.join(d, 'data', 'raw', 'espn', '2018')
            bx = list(store.read_jsonl_gz(os.path.join(raw, 'teambox.jsonl.gz')))
            for b in bx:
                b.update({'tov': 99, 'pts': 999, 'fga': 1, 'fgm': 1, 'fta': 500, 'ftm': 500, 'oreb': 0, 'dreb': 0, 'overtimes': 9})
            store.write_jsonl_gz(os.path.join(raw, 'teambox.jsonl.gz'), bx)
            gs = list(store.read_jsonl_gz(os.path.join(raw, 'games.jsonl.gz')))
            for g in gs:
                g['home_pts'], g['away_pts'] = 300, 1
            store.write_jsonl_gz(os.path.join(raw, 'games.jsonl.gz'), gs)
            da = DA.DataAccess('feature_computation', root=d)
            altered = f1.compute_season(2019, da=da)
            self.assertFalse([x for x in da.log if x['season'] == 2018])
        self.assertEqual(altered, f1.compute_season(2019))

    def test_no_cache_or_module_state(self):
        src = open(f1.__file__, encoding='utf-8').read()
        for w in ('lru_cache', 'cache', 'pickle', 'data/audit', 'model_data', 'summary.json'):
            self.assertNotIn(w, src)


class LocksNotBypassed(unittest.TestCase):
    def test_history_features_without_as_of_refused(self):
        with self.assertRaises(config.HoldoutLocked):
            f1.compute_season(2017, purpose='history_features')

    def test_validation_and_final_purposes_refused_without_runs(self):
        for p, s in (('validation', 2024), ('final_evaluation', 2025), ('final_evaluation', 2026)):
            with self.assertRaises(config.HoldoutLocked):
                f1.compute_season(s, purpose=p)

    def test_f1_outputs_no_metrics(self):
        src = open(f1.__file__, encoding='utf-8').read()
        for w in ('brier', 'log_loss', 'rmse', 'mae', 'assert_metrics_allowed'):
            self.assertNotIn(w, src.lower())
