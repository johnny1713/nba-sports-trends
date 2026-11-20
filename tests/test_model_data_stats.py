"""模型資料統計 v1（使用者 2026-11-20 第四輪，quality.py 方案 A）。"""
import os
import unittest

from nba_quant import model_data_stats as M
from nba_quant import store

HAS_DATA = os.path.exists(M.CLASSIFICATION) and os.path.exists(os.path.join(M.RAW, '2021', 'games.jsonl.gz'))


class Isolation(unittest.TestCase):
    def test_does_not_use_frozen_quality_module(self):
        src = open(M.__file__, encoding='utf-8').read()
        self.assertNotIn('import quality', src)
        self.assertNotIn('from .quality', src)
        self.assertNotIn('from . import quality', src)

    def test_outputs_are_new_paths(self):
        for p in (M.OUT_JSON, M.OUT_MD):
            self.assertNotIn(os.path.join('docs', 'reports', 'data_quality'), p)
            self.assertFalse(p.startswith(os.path.join('data', 'raw')))

    def test_locked_season_refused(self):
        with self.assertRaises(PermissionError):
            M.season_stats(2026, {})


class TovDefinition(unittest.TestCase):
    def test_rules(self):
        espn, bb = {'source': 'espn:summary'}, {'source': 'bbref:boxscore'}
        self.assertEqual(M.tov_definition(espn, 'REGULAR_SEASON', 2024), ('espn_total_incl_team', True))
        self.assertEqual(M.tov_definition(bb, 'REGULAR_SEASON', 2016), ('bbref_team_total', True))
        # 2017-18 整季停用，BBRef 補值也不用（不以 BBRef 覆蓋）
        self.assertFalse(M.tov_definition(espn, 'REGULAR_SEASON', 2018)[1])
        self.assertFalse(M.tov_definition(bb, 'REGULAR_SEASON', 2018)[1])
        # 2020-21 附加賽 BBRef 不含全隊失誤
        self.assertEqual(M.tov_definition(bb, 'PLAY_IN', 2021), ('bbref_player_only', False))
        self.assertEqual(M.tov_definition(espn, 'PLAY_IN', 2022), ('espn_total_incl_team', True))


@unittest.skipUnless(HAS_DATA, 'no data')
class RealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {s['season']: s for s in M.compute(seasons=[2021, 2024])['seasons']}

    def test_fatigue_and_elo_include_play_in_and_postseason(self):
        for use in ('use_fatigue', 'use_elo'):
            gt = self.res[2021]['uses'][use]['game_types']
            self.assertEqual(gt.get('PLAY_IN'), 6)
            self.assertGreater(gt.get('POSTSEASON', 0), 0)

    def test_team_stats_and_training_exclude_play_in_and_postseason(self):
        for use in ('use_team_stats', 'train_sample', 'counts_for_standings'):
            gt = self.res[2021]['uses'][use]['game_types']
            self.assertNotIn('PLAY_IN', gt)
            self.assertNotIn('POSTSEASON', gt)

    def test_cup_final_in_team_stats_but_not_standings(self):
        u = self.res[2024]['uses']
        self.assertEqual(u['use_team_stats']['game_types'].get('CUP_FINAL'), 1)
        self.assertNotIn('CUP_FINAL', u['counts_for_standings']['game_types'])
        self.assertEqual((u['counts_for_standings']['team_games_min'], u['counts_for_standings']['team_games_max']), (82, 82))
        self.assertTrue(self.res[2024]['standings_check']['ok'])

    def test_play_in_2021_tov_excluded(self):
        d = self.res[2021]['uses']['use_fatigue']['tov_definition']
        self.assertEqual(d.get('bbref_player_only'), 12)

    def test_deterministic_output(self):
        a = store.dumps(M.compute(seasons=[2021]))
        b = store.dumps(M.compute(seasons=[2021]))
        self.assertEqual(a, b)
