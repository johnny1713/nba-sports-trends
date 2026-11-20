"""2019-20 Play-In 獨立抓取：正式回補仍不收 play-in；獨立存放；不覆寫原始檔；驗證邏輯。"""
import gzip
import json
import os
import tempfile
import unittest

from nba_quant import playin_fetch as P
from nba_quant.sources import espn

FX = os.path.join(os.path.dirname(__file__), 'fixtures')
T = '2026-11-20T00:00:00Z'


class PlayIn(unittest.TestCase):
    def events(self):
        return json.loads(gzip.open(os.path.join(FX, 'scoreboard_playin2024.gz')).read())['events']

    def test_regular_backfill_still_skips_play_in(self):
        for ev in self.events():
            g, why = espn.parse_scoreboard_event(ev, T)
            self.assertIsNone(g)
            self.assertEqual(why, 'season type 5')
        self.assertEqual(espn.SEASON_TYPE_KEEP, {2, 3})

    def test_independent_fetch_keeps_play_in(self):
        g, _ = espn.parse_scoreboard_event(self.events()[0], T, keep={P.PLAY_IN_TYPE})
        self.assertEqual(g['season_type'], 5)

    def test_stored_separately_from_season_data(self):
        self.assertEqual(P.OUT, os.path.join('data', 'raw', 'espn_playin', '2020'))
        self.assertNotIn(os.path.join('data', 'raw', 'espn', '2020'), P.OUT)

    def test_raw_write_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.json.gz')
            P._write_raw(p, b'{}')
            with self.assertRaises(FileExistsError):
                P._write_raw(p, b'{"changed": 1}')
            self.assertEqual(gzip.open(p).read(), b'{}')

    def test_verify(self):
        g = {'game_id': 'g', 'season_type': 5, 'home': 'H', 'away': 'A', 'home_abbr': 'POR', 'away_abbr': 'MEM',
             'home_pts': 126, 'away_pts': 122}
        b = lambda t, pts, fgm: {'team': t, 'pts': pts, 'fgm': fgm, 'fga': 90, 'fg3m': 10, 'fg3a': 30, 'ftm': pts - 2 * fgm - 10,
                                 'fta': 30, 'oreb': 10, 'dreb': 35, 'tov': 12, 'players': [{}] * 10}
        es = [b('H', 126, 45), b('A', 122, 44)]
        v = P.verify(g, es, {'H': dict(es[0]), 'A': dict(es[1], tov=13)})
        self.assertTrue(v['both_teams_present'])
        self.assertTrue(v['teams']['H']['all_fields_match_bbref'])
        self.assertFalse(v['teams']['A']['all_fields_match_bbref'])
        self.assertTrue(all(x['pts_eq_scoreboard'] and x['pts_identity_ok'] for x in v['teams'].values()))


class PlayInSeasons(unittest.TestCase):
    def test_locked_season_refused(self):
        with self.assertRaises(PermissionError):
            P.run((2026,))

    def test_existing_season_not_refetched(self):
        if not os.path.exists(os.path.join(P.out_dir(2020), 'provenance.json')):
            self.skipTest('no 2020 play-in data')
        msgs = []
        P.run((2020,), log=msgs.append)          # 已存在 → 不連網、不覆寫
        self.assertIn('已存在', msgs[0])

    def test_candidate_dates_cover_gap_between_phases(self):
        if not os.path.exists(os.path.join('data', 'raw', 'espn', '2024', 'games.jsonl.gz')):
            self.skipTest('no data')
        d = P.candidate_dates(2024)
        self.assertEqual((d[0].isoformat(), d[-1].isoformat(), len(d)), ('2024-04-14', '2024-04-20', 7))

    def test_out_dir_separate(self):
        self.assertEqual(P.out_dir(2022), os.path.join('data', 'raw', 'espn_playin', '2022'))


class SingleSourceVerify(unittest.TestCase):
    def test_bbref_only_checks_against_espn_scoreboard(self):
        g = {'game_id': 'g', 'home': 'H', 'away': 'A', 'home_abbr': 'IND', 'away_abbr': 'CHA', 'home_pts': 144, 'away_pts': 117}
        b = lambda t, pts: {'team': t, 'pts': pts, 'fgm': 40, 'fga': 90, 'fg3m': 10, 'fg3a': 30, 'ftm': pts - 90,
                            'fta': 40, 'oreb': 10, 'dreb': 35, 'tov': 12, 'players': [{}] * 10}
        v = P.verify_single_source(g, [b('H', 144), b('A', 116)])
        self.assertTrue(v['teams']['H']['pts_eq_espn_scoreboard'])
        self.assertFalse(v['teams']['A']['pts_eq_espn_scoreboard'])
        self.assertEqual(v['box_source'], 'bbref')

    def test_fallback_refuses_locked(self):
        with self.assertRaises(PermissionError):
            P.bbref_fallback(2026)
