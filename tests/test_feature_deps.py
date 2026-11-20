"""特徵依賴關係與資料可用性（使用者 2026-11-20 第五輪）。"""
import unittest

from nba_quant import feature_deps as D
from nba_quant import game_class

TOV = {'tov', 'opp_tov'}


class Graph(unittest.TestCase):
    def test_every_feature_resolves_to_base_fields(self):
        for f in D.FEATURES:
            c = D.closure(f)
            self.assertTrue(c)
            self.assertTrue(c <= D.BASE, f)

    def test_cycle_detected(self):
        D.DERIVED['_a'] = ('_b',)
        D.DERIVED['_b'] = ('_a',)
        try:
            with self.assertRaises(ValueError):
                D.closure('_a')
        finally:
            del D.DERIVED['_a'], D.DERIVED['_b']

    def test_unregistered_feature_rejected(self):
        with self.assertRaises(KeyError):
            D.check_model_inputs(['F9.something'], 2020)

    def test_scope_f3_f4_f7_same_as_f1_f2(self):
        for fam in ('F1', 'F2', 'F3', 'F4', 'F7'):
            self.assertEqual(D.FAMILY_SCOPE[fam], 'use_team_stats')
        self.assertEqual(D.FAMILY_SCOPE['F5'], 'use_fatigue')
        self.assertEqual(D.FAMILY_SCOPE['ELO'], 'use_elo')
        for gt in ('PLAY_IN', 'POSTSEASON'):
            self.assertFalse(game_class.uses(gt)['use_team_stats'])
        self.assertTrue(game_class.uses('CUP_FINAL')['use_team_stats'])

    def test_fatigue_and_elo_do_not_touch_box_fields(self):
        box = set(D.BOX_FIELDS) | {f'opp_{f}' for f in D.BOX_FIELDS}
        for f, (fam, _, _) in D.FEATURES.items():
            if fam in ('F5', 'ELO'):
                self.assertFalse(D.closure(f) & box, f)


class Season2017_18(unittest.TestCase):
    def test_exact_unavailable_set(self):
        bad = {f for f in D.FEATURES if D.availability(f, 2018)[0] == 'unavailable'}
        self.assertEqual(bad, {'F1.ortg', 'F1.drtg', 'F1.net_rating', 'F1.pace',
                               'F2.ewm_net_rating', 'F2.last5_net_rating', 'F2.last10_net_rating',
                               'F3.tov_rate_off', 'F3.tov_rate_def', 'F4.srs_net_rating', 'F7.pace_sum'})

    def test_independent_factors_stay_available(self):
        for f in ('F3.efg_off', 'F3.efg_def', 'F3.orb_rate_off', 'F3.orb_rate_def', 'F3.ft_rate_off', 'F3.ft_rate_def',
                  'F4.srs_margin', 'F7.league_recent_points', 'F5.rest_days', 'ELO.rating'):
            self.assertEqual(D.availability(f, 2018)[0], 'available', f)

    def test_no_indirect_path(self):
        """性質測試：依賴鏈（任何深度）碰到失誤的特徵 2017-18 全部不可用；沒碰到的全部可用。"""
        for f in D.FEATURES:
            st = D.availability(f, 2018)[0]
            self.assertEqual(st == 'unavailable', bool(D.closure(f) & TOV), f)

    def test_reason_shows_chain(self):
        st, why = D.availability('F1.pace', 2018)
        self.assertIn('pace -> possessions', why)


class CrossSeason(unittest.TestCase):
    def test_2018_19_prior_and_window_exclude_2017_18(self):
        for f in ('F1.ortg', 'F1.pace', 'F2.ewm_net_rating', 'F2.last5_net_rating', 'F7.pace_sum'):
            self.assertEqual(D.availability(f, 2019)[0], 'available_prior_excluded', f)
        # 比分類的跨季視窗不受影響
        self.assertEqual(D.availability('F7.league_recent_points', 2019)[0], 'available')
        self.assertEqual(D.availability('F3.tov_rate_off', 2019)[0], 'available')

    def test_other_seasons_fully_available(self):
        for s in (2015, 2016, 2017, 2020, 2021, 2022, 2023, 2024, 2025):
            self.assertEqual({D.availability(f, s)[0] for f in D.FEATURES}, {'available'}, s)


class NoImputation(unittest.TestCase):
    def test_box_field_check_does_not_count_unavailable_tov(self):
        g = [{'game_id': 'x', 'home': 'H', 'away': 'A'}]
        boxes = {('x', 'H'): {f: 1 for f in D.BOX_FIELDS}, ('x', 'A'): {f: 1 for f in D.BOX_FIELDS}}
        chk = D.box_field_check(2018, g, boxes, lambda b, g: True)
        self.assertEqual(chk['tov'], (0, 2))
        self.assertEqual(chk['fga'], (2, 2))
