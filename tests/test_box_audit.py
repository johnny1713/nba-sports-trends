"""Box score 稽核 v1 與中立場表：恆等式、同場關係、整季系統性（含趨勢與汙染鄰居）、中立場規則。"""
import unittest

from nba_quant import box_audit as B
from nba_quant import neutral_table as N

GAME = {'game_id': 'g1', 'home': 'H', 'away': 'A', 'home_pts': 100, 'away_pts': 95, 'complete': True}


def box(team='H', **kw):
    b = {'game_id': 'g1', 'team': team, 'pts': 100, 'fgm': 38, 'fga': 85, 'fg3m': 10, 'fg3a': 30,
         'ftm': 14, 'fta': 18, 'oreb': 10, 'dreb': 33, 'tov': 14, 'source': 'espn:summary', 'players': []}
    b.update(kw)
    return b


def checks(b, g=GAME):
    return {c for c, _, _ in B.record_checks(b, g)}


class RecordChecks(unittest.TestCase):
    def test_clean_record_has_no_flags(self):
        self.assertEqual(checks(box()), set())

    def test_identities(self):
        self.assertIn('fgm_gt_fga', checks(box(fgm=90, pts=2 * 90 + 10 + 14)))
        self.assertIn('fg3m_gt_fg3a', checks(box(fg3m=31, pts=2 * 38 + 31 + 14)))
        self.assertIn('ftm_gt_fta', checks(box(ftm=19, pts=2 * 38 + 10 + 19)))
        self.assertIn('fg3m_gt_fgm', checks(box(fgm=9, fg3m=10, pts=2 * 9 + 10 + 14)))
        self.assertIn('pts_identity', checks(box(pts=101)))

    def test_scoreboard_and_zero_and_missing(self):
        self.assertIn('pts_vs_scoreboard', checks(box(team='A')))
        self.assertIn('zero_value', checks(box(tov=0)))
        self.assertIn('field_missing', checks(box(tov=None)))
        self.assertIn('team_not_in_game', checks(box(team='X')))

    def test_player_points_sum(self):
        self.assertIn('player_pts_sum', checks(box(players=[{'pts': 50}, {'pts': 40}])))
        self.assertNotIn('player_pts_sum', checks(box(players=[{'pts': 60}, {'pts': 40}])))


class GameChecks(unittest.TestCase):
    def test_missing_team_and_possessions_and_rebounds(self):
        self.assertEqual(B.game_checks(GAME, {'H': box()})[0][0], 'box_missing_team')
        h, a = box(), box(team='A', pts=95)
        self.assertEqual(B.game_checks(GAME, {'H': h, 'A': a}), [])
        self.assertIn('possessions_mismatch', {c[0] for c in B.game_checks(GAME, {'H': h, 'A': box(team='A', tov=1)})})
        # H 的投籃不中 47 + 罰球不中 4 = 51 < oreb 10 + A dreb 45
        self.assertIn('rebounds_exceed_misses', {c[0] for c in B.game_checks(GAME, {'H': h, 'A': box(team='A', dreb=45)})})


def stats(series, field='tov', zero=None):
    return {s: {'espn': {field: {'mean': m, 'zero_share': (zero or {}).get(s, 0.0), 'n': 2000}}} for s, m in series.items()}


class SeasonSystematic(unittest.TestCase):
    def flagged(self, st):
        return {r['season'] for r in B.season_systematic(st) if r['source'] == 'espn' and r['systematic_suspect']}

    def test_bad_season_found_and_neighbors_not_contaminated(self):
        st = stats({2015: 14.5, 2016: 14.5, 2017: 14.0, 2018: 1.2, 2019: 14.1, 2020: 14.5, 2021: 13.8},
                   zero={2018: 0.33})
        self.assertEqual(self.flagged(st), {2018})

    def test_linear_trend_is_not_flagged(self):
        st = stats({s: 20 + 2.5 * (s - 2015) for s in range(2015, 2026)}, field='fg3a')
        self.assertEqual(self.flagged(st), set())

    def test_moderate_shift_detected(self):
        st = stats({2015: 14.0, 2016: 14.1, 2017: 14.0, 2018: 16.0, 2019: 14.1, 2020: 14.0}, field='tov')
        self.assertEqual(self.flagged(st), {2018})

    def test_robust_bounds_needs_sample(self):
        self.assertIsNone(B.robust_bounds([1, 2, 3]))
        lo, hi, med, _ = B.robust_bounds(list(range(10, 50)))
        self.assertTrue(lo < med < hi)


class NeutralRules(unittest.TestCase):
    def g(self, **kw):
        g = {'game_id': 'x', 'season': 2020, 'season_type': 2, 'start_utc': '2020-08-01T22:00:00Z', 'neutral': False, 'notes': []}
        g.update(kw)
        return g

    def test_bubble_window_by_et_date(self):
        self.assertEqual(N.classify(self.g(), None, None)[:2], ('neutral', 'bubble_regular'))
        # 8/15 01:00 UTC = 8/14 美東晚上 → 仍在泡泡區例行賽內
        self.assertEqual(N.classify(self.g(start_utc='2020-08-15T01:00:00Z'), None, None)[1], 'bubble_regular')
        self.assertIsNone(N.classify(self.g(start_utc='2020-07-29T23:00:00Z'), None, None))
        self.assertIsNone(N.classify(self.g(start_utc='2020-03-01T23:00:00Z'), None, None))

    def test_bubble_postseason_separate(self):
        self.assertEqual(N.classify(self.g(season_type=3, start_utc='2020-08-17T17:30:00Z'), None, None)[1], 'bubble_postseason')

    def test_flag_only_games_stay_unknown_even_with_bbref_venue(self):
        r = N.classify(self.g(game_id='400900010', season=2017, start_utc='2017-01-12T20:00:00Z', neutral=True),
                       None, 'The O2 Arena, London, United Kingdom')
        self.assertEqual(r[0], 'unknown')
        self.assertIn('輔助證據', r[3])

    def test_bbref_alone_or_espn_alone_is_not_enough(self):
        intl = self.g(season=2019, start_utc='2019-01-17T20:00:00Z', neutral=True, notes=['NBA LONDON GAME'])
        self.assertEqual(N.classify(intl, None, None)[0], 'unknown')
        self.assertEqual(N.classify(intl, None, 'The O2 Arena, London, United Kingdom')[0], 'neutral')
        self.assertEqual(N.classify(intl, None, 'Capital One Arena, Washington, District of Columbia')[0], 'unknown')
        plain = self.g(season=2019, start_utc='2019-01-17T20:00:00Z')
        self.assertIsNone(N.classify(plain, None, 'The O2 Arena, London, United Kingdom'))

    def test_ist_semis_user_specified(self):
        r = N.classify(self.g(game_id='401607494', season=2024, start_utc='2023-12-07T22:00:00Z'), None, None)
        self.assertEqual(r[:2], ('neutral', 'ist_knockout'))


class NoAutoCorrection(unittest.TestCase):
    def test_compare_report_never_writes_derived(self):
        """使用者 2026-11-20：一致率 ≥ 99% 只列候選，核准前不得產生 derived 修正版。"""
        import os
        src = open(os.path.join(os.path.dirname(__file__), '..', 'tools', 'source_compare_report.py'), encoding='utf-8').read()
        code = '\n'.join(l for l in src.splitlines() if not l.lstrip().startswith('#'))
        self.assertNotIn("os.path.join('data', 'derived'", code)
        self.assertIn("'derived_generated': False", code)


class BBRefVenue(unittest.TestCase):
    def test_venue_follows_time_line(self):
        self.assertEqual(N.bbref_venue(['9:30 PM, November 9, 2023', 'Mexico City Arena, Mexico City, Mexico', 'Logos']),
                         'Mexico City Arena, Mexico City, Mexico')
        self.assertEqual(N.bbref_venue(['NBA Cup', '4:30 PM, December 14, 2024', 'T-Mobile Arena, Las Vegas, Nevada']),
                         'T-Mobile Arena, Las Vegas, Nevada')
        self.assertIsNone(N.bbref_venue(['NBA Cup', '4:30 PM, December 14, 2024']))
