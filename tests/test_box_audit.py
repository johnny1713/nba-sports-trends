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
        self.assertEqual(N.classify(self.g(), None, None)[:2], ('neutral', 'bubble'))
        # 8/15 01:00 UTC = 8/14 美東晚上 → 仍在泡泡區例行賽內
        self.assertEqual(N.classify(self.g(start_utc='2020-08-15T01:00:00Z'), None, None)[1], 'bubble')
        self.assertIsNone(N.classify(self.g(start_utc='2020-07-29T23:00:00Z'), None, None))
        self.assertIsNone(N.classify(self.g(start_utc='2020-03-01T23:00:00Z'), None, None))

    def test_bubble_postseason_separate(self):
        self.assertEqual(N.classify(self.g(season_type=3, start_utc='2020-08-17T17:30:00Z'), None, None)[1], 'bubble')

    def test_flag_only_games_unknown_with_bbref_venue_alone(self):
        # 2026-11-20 修訂：BBRef 單一來源仍不足以判定（需 ESPN 場館 + BBRef 場館兩源）
        r = N.classify(self.g(game_id='400900010', season=2017, start_utc='2017-01-12T20:00:00Z', neutral=True),
                       None, 'The O2 Arena, London, United Kingdom')
        self.assertEqual(r[0], 'unknown')
        self.assertIn('證據不足', r[3])

    def test_bbref_alone_or_espn_alone_is_not_enough(self):
        intl = self.g(season=2019, start_utc='2019-01-17T20:00:00Z', neutral=True, notes=['NBA LONDON GAME'])
        self.assertEqual(N.classify(intl, None, None)[0], 'unknown')
        self.assertEqual(N.classify(intl, None, 'The O2 Arena, London, United Kingdom')[0], 'neutral')
        self.assertEqual(N.classify(intl, None, 'Capital One Arena, Washington, District of Columbia')[0], 'unknown')
        plain = self.g(season=2019, start_utc='2019-01-17T20:00:00Z')
        self.assertIsNone(N.classify(plain, None, 'The O2 Arena, London, United Kingdom'))

    def test_ist_semis_user_specified(self):
        r = N.classify(self.g(game_id='401607494', season=2024, start_utc='2023-12-07T22:00:00Z'), None, None)
        self.assertEqual(r[:2], ('neutral', 'cup_las_vegas'))


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


class NeutralDecisions20261120(unittest.TestCase):
    """使用者 2026-11-20 決策：盃賽淘汰賽 4 場 neutral；無備註 6 場需 ESPN 與 BBRef 場館兩源皆在倫敦／墨西哥城。"""
    G = {'game_id': '400578877', 'season': 2015, 'season_type': 2, 'start_utc': '2015-01-15T20:00:00Z', 'neutral': True, 'notes': []}

    def test_no_note_two_sources_same_city_neutral(self):
        r = N.classify(self.G, 'O2 Arena (ENG), London', 'The O2 Arena, London, United Kingdom')
        self.assertEqual(r[:2], ('neutral', 'international_no_espn_note'))
        self.assertEqual(r[2], 'espn_venue;bbref_venue')

    def test_no_note_insufficient_evidence_stays_unknown(self):
        self.assertEqual(N.classify(self.G, None, 'The O2 Arena, London, United Kingdom')[0], 'unknown')
        self.assertEqual(N.classify(self.G, 'O2 Arena (ENG), London', None)[0], 'unknown')
        self.assertEqual(N.classify(self.G, 'Fiserv Forum, Milwaukee', 'The O2 Arena, London, United Kingdom')[0], 'unknown')
        self.assertEqual(N.classify(self.G, 'O2 Arena (ENG), London', 'Mexico City Arena, Mexico City, Mexico')[0], 'unknown')

    def test_cup_knockout_user_approved(self):
        for gid in ('401607495', '401734906', '401734907', '401734908'):
            r = N.classify({'game_id': gid, 'season': 2025, 'season_type': 2, 'start_utc': '2024-12-14T21:30:00Z',
                            'neutral': True, 'notes': ['NBA Cup - Semifinals']}, 'T-Mobile Arena', 'T-Mobile Arena, Las Vegas, Nevada')
            self.assertEqual(r[:2], ('neutral', 'cup_las_vegas'))
            self.assertIn('使用者 2026-11-20 核准', r[3])


class GameClassification(unittest.TestCase):
    def c(self, st, notes=()):
        from nba_quant import game_class
        return game_class.classify({'game_id': 'x', 'season_type': st, 'notes': list(notes)})

    def test_types_and_standings(self):
        self.assertEqual(self.c(2), ('REGULAR_SEASON', True, 'ESPN season_type 2，無盃賽備註'))
        self.assertEqual(self.c(2, ['NBA Cup - Group Play'])[:2], ('CUP_GROUP', True))
        self.assertEqual(self.c(2, ['NBA In-Season Tournament - Quarterfinals'])[:2], ('CUP_QUARTERFINAL', True))
        self.assertEqual(self.c(2, ['NBA Cup - Semifinals'])[:2], ('CUP_SEMIFINAL', True))
        # 冠軍戰：ESPN 仍是 season_type 2，但不計入例行賽戰績
        self.assertEqual(self.c(2, ['NBA Cup Championship'])[:2], ('CUP_FINAL', False))
        self.assertEqual(self.c(2, ['NBA In-Season Tournament Championship'])[:2], ('CUP_FINAL', False))
        self.assertEqual(self.c(5)[:2], ('PLAY_IN', False))
        self.assertEqual(self.c(3)[:2], ('POSTSEASON', False))

    def test_unknown_inputs_raise(self):
        with self.assertRaises(ValueError):
            self.c(1)
        with self.assertRaises(ValueError):
            self.c(2, ['NBA Cup - Something New'])

    def test_real_data_each_team_82_counted_games(self):
        """以實際資料檢查：counts_for_standings 的完賽場數每隊 82 場（2019-20、2020-21 例外：縮水球季）。"""
        import os
        from collections import Counter
        from nba_quant import game_class, store
        for season in (2024, 2025):
            p = os.path.join('data', 'raw', 'espn', str(season), 'games.jsonl.gz')
            if not os.path.exists(p):
                self.skipTest('no data')
            c = Counter()
            for g in store.read_jsonl_gz(p):
                if g['status'] == 'final' and game_class.classify(g)[1]:
                    c[g['home']] += 1
                    c[g['away']] += 1
            self.assertEqual(set(c.values()), {82}, season)


class ClassificationConsistency(unittest.TestCase):
    """第三輪：賽事類型只有一個來源（game_classification）；中立場表的 game_type 必須與分類表一致，
    且不得再出現 bubble_play_in 之類自設的賽事類型名稱。"""

    def test_neutral_table_game_type_matches_classification(self):
        import csv
        import os
        p, q = os.path.join('data', 'reference', 'neutral_sites.csv'), os.path.join('data', 'reference', 'game_classification.csv')
        if not (os.path.exists(p) and os.path.exists(q)):
            self.skipTest('no reference tables')
        gc = {r['game_id']: r['game_type'] for r in csv.DictReader(open(q, encoding='utf-8'))}
        rows = list(csv.DictReader(open(p, encoding='utf-8')))
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r['game_type'], gc[r['game_id']], r['game_id'])
            self.assertNotIn(r['venue_category'], ('bubble_play_in', 'bubble_regular', 'bubble_postseason'))
        self.assertEqual({r['venue_category'] for r in rows} - {'bubble', 'international', 'international_no_espn_note',
                                                                'cup_las_vegas'}, set())


class UsageRules(unittest.TestCase):
    """第三輪：counts_for_standings 只管戰績；其他用途各自獨立。"""

    def test_usage_matrix(self):
        from nba_quant import game_class as C
        exp = {  # game_type: (standings, F1/F2 team stats, F5 fatigue, elo, train, eval) — 使用者 2026-11-20 第四輪
            'REGULAR_SEASON': (True, True, True, True, True, 'regular'),
            'CUP_GROUP': (True, True, True, True, True, 'regular'),
            'CUP_QUARTERFINAL': (True, True, True, True, True, 'regular'),
            'CUP_SEMIFINAL': (True, True, True, True, True, 'regular'),
            'CUP_FINAL': (False, True, True, True, True, 'regular'),
            'PLAY_IN': (False, False, True, True, False, 'play_in'),
            'POSTSEASON': (False, False, True, True, False, 'postseason')}
        self.assertEqual(set(exp), set(C.COUNTS))
        for gt, (st, ts, fa, el, tr, ev) in exp.items():
            u = C.uses(gt)
            self.assertEqual((C.COUNTS[gt], u['use_team_stats'], u['use_fatigue'], u['use_elo'], u['train_sample'],
                              u['eval_group']), (st, ts, fa, el, tr, ev), gt)

    def test_elo_inclusion_does_not_imply_training(self):
        from nba_quant import game_class as C
        for gt in ('PLAY_IN', 'POSTSEASON'):
            self.assertTrue(C.uses(gt)['use_elo'])
            self.assertFalse(C.uses(gt)['train_sample'])

    def test_standings_flag_not_used_as_feature_gate(self):
        from nba_quant import game_class as C
        # 戰績不計但其他用途納入的例子：冠軍戰、附加賽、季後賽
        self.assertFalse(C.COUNTS['CUP_FINAL'])
        self.assertTrue(C.uses('CUP_FINAL')['train_sample'] and C.uses('CUP_FINAL')['use_fatigue'])
