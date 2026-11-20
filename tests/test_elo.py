"""Elo（stage 1）：T6、T20、T23。"""
import csv
import os
import re
import tempfile
import unittest

from nba_quant import config, data_access as DA, game_class, store
from nba_quant.models import elo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))


def make_root(d, games):
    """games: [(gid, season, start_utc, home, away, hp, ap, game_type)]"""
    os.makedirs(os.path.join(d, 'data', 'reference'), exist_ok=True)
    with open(os.path.join(d, 'data', 'reference', 'game_classification.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=game_class.FIELDS)
        w.writeheader()
        for gid, s, t, h, a, hp, ap, gt in games:
            w.writerow({'game_id': gid, 'season': s, 'start_utc': t, 'away': a, 'home': h, 'status': 'final',
                        'espn_season_type': 3 if gt == 'POSTSEASON' else 2, 'game_type': gt,
                        'counts_for_standings': game_class.COUNTS[gt], **game_class.uses(gt), 'source_file': 'x', 'basis': 't'})
    by = {}
    for gid, s, t, h, a, hp, ap, gt in games:
        by.setdefault(s, []).append({'game_id': gid, 'season': s, 'season_type': 3 if gt == 'POSTSEASON' else 2, 'start_utc': t,
                                     'home': h, 'away': a, 'home_pts': hp, 'away_pts': ap, 'status': 'final', 'complete': True})
    for s, gs in by.items():
        store.write_jsonl_gz(os.path.join(d, 'data', 'raw', 'espn', str(s), 'games.jsonl.gz'), gs)


# 美東日期：01-02T00:30Z = 1/1 晚；01-02T17:00Z = 1/2 中午；01-03T00:30Z = 1/2 晚
G = [('a1', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
     ('a2', 2020, '2020-01-02T17:00:00Z', 'C', 'D', 120, 90, 'REGULAR_SEASON'),     # 1/2 中午
     ('a3', 2020, '2020-01-03T00:30:00Z', 'A', 'C', 100, 99, 'REGULAR_SEASON'),     # 1/2 晚上（同日較晚）
     ('a4', 2020, '2020-01-04T00:30:00Z', 'B', 'D', 105, 104, 'REGULAR_SEASON'),    # 1/3
     ('p1', 2020, '2020-04-20T00:30:00Z', 'A', 'D', 101, 95, 'POSTSEASON'),
     ('n1', 2021, '2020-12-23T00:30:00Z', 'C', 'A', 100, 90, 'REGULAR_SEASON')]     # 下一季開幕


def build(games, seasons=(2020, 2021)):
    with tempfile.TemporaryDirectory() as d:
        make_root(d, games)
        e, _ = elo.build(seasons, root=d)
        return e


def preds(e, games):
    return {g[0]: e.predict({'start_utc': g[2], 'season': g[1], 'home': g[3], 'away': g[4]}) for g in games}


class T23_Timing(unittest.TestCase):
    def test_update_order_and_game_type_recorded(self):
        e = build(G)
        self.assertEqual([u['game_id'] for u in e.updates], ['a1', 'a2', 'a3', 'a4', 'p1', 'n1'])
        self.assertEqual({u['game_type'] for u in e.updates}, {'REGULAR_SEASON', 'POSTSEASON'})

    def test_same_day_earlier_result_does_not_affect_later_prediction(self):
        base = preds(build(G), G)
        changed = [x if x[0] != 'a2' else ('a2', 2020, x[2], 'C', 'D', 80, 130, x[7]) for x in G]   # 同日中午那場結果反轉
        alt = preds(build(changed), G)
        self.assertEqual(base['a3'], alt['a3'])          # 同日晚上那場（C 也有出賽）預測不變
        self.assertNotEqual(base['a4'], alt['a4'])       # 隔天才會反映（D 的評分變了）

    def test_same_day_uses_previous_day_snapshot_for_all_games(self):
        e = build(G)
        r_noon = e.ratings_before('2020-01-02T17:00:00Z', 2020)
        r_night = e.ratings_before('2020-01-03T00:30:00Z', 2020)
        self.assertEqual(r_noon, r_night)

    def test_game_id_tiebreak_does_not_change_predictions(self):
        tie = [('z9', 2020, '2020-01-02T17:00:00Z', 'E', 'F', 100, 90, 'REGULAR_SEASON'),
               ('b0', 2020, '2020-01-02T17:00:00Z', 'G', 'H', 100, 95, 'REGULAR_SEASON')]
        renamed = [('a0', *x[1:]) if x[0] == 'z9' else ('zz', *x[1:]) for x in tie]
        e1, e2 = build(G + tie), build(G + renamed)
        p1, p2 = preds(e1, G), preds(e2, G)
        self.assertEqual(p1, p2)
        self.assertEqual(e1.ratings, e2.ratings)

    def test_future_game_does_not_change_past_predictions(self):
        fut = G + [('f1', 2021, '2021-03-01T00:30:00Z', 'A', 'B', 150, 60, 'REGULAR_SEASON')]
        self.assertEqual(preds(build(G), G), preds(build(fut), G))

    def test_season_opener_uses_carryover_consistent_with_update(self):
        e = build(G)
        u = [x for x in e.updates if x['game_id'] == 'n1'][0]
        r = e.ratings_before('2020-12-23T00:30:00Z', 2021)
        self.assertAlmostEqual(r['C'], u['pre_home'])
        self.assertAlmostEqual(r['A'], u['pre_away'])

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_real_data_pre_rating_equals_prediction_time_rating(self):
        """開發期實際資料：每一場更新用的賽前評分 = 前一美東日期結束時可得的評分（含新球季的季間回歸）。"""
        e, _ = elo.build(range(2015, 2024))
        known = {r['game_id'] for r in csv.DictReader(open(os.path.join(ROOT, 'data', 'reference', 'start_time_flags.csv'),
                                                           encoding='utf-8')) if 'same_team_two_games_same_et_date' in r['flag']}
        seen = {}
        exceptions = set()
        for u in e.updates:                       # 同一隊同一美東日期兩場 → 只允許資料表登記過的已知時間異常
            for t in (u['home'], u['away']):
                k = (t, u['et_date'])
                if k in seen:
                    exceptions.add(u['game_id'])
                    self.assertTrue(seen[k] in known or u['game_id'] in known, f'未登記的同日兩場：{seen[k]} {u["game_id"]}')
                seen[k] = u['game_id']
        self.assertEqual(exceptions, {'401161543'})
        for u in e.updates:
            if u['game_id'] in exceptions:
                continue
            r = e.ratings_before(u['start_utc'], u['season'])
            self.assertAlmostEqual(r.get(u['home'], elo.MEAN), u['pre_home'], places=9, msg=u['game_id'])
            self.assertAlmostEqual(r.get(u['away'], elo.MEAN), u['pre_away'], places=9, msg=u['game_id'])


class T20_Separation(unittest.TestCase):
    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_elo_includes_all_types_training_excludes_playin_postseason(self):
        e, _ = elo.build([2021])
        types = {u['game_type'] for u in e.updates}
        self.assertTrue({'REGULAR_SEASON', 'PLAY_IN', 'POSTSEASON'} <= types)
        train = DA.DataAccess('training').games(2021, 'train_sample')
        self.assertFalse({g['game_type'] for g in train} & {'PLAY_IN', 'POSTSEASON'})
        self.assertEqual(len(e.updates) - len(train), sum(1 for u in e.updates if u['game_type'] in ('PLAY_IN', 'POSTSEASON')))

    def test_training_list_independent_of_elo_input(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, G)
            t1 = DA.DataAccess('training', root=d).games(2020, 'train_sample')
            no_post = [x for x in G if x[7] != 'POSTSEASON']
            e_all = elo.Elo().run(DA.DataAccess('feature_computation', root=d).games(2020, 'use_elo'))
        with tempfile.TemporaryDirectory() as d:
            make_root(d, no_post)
            t2 = DA.DataAccess('training', root=d).games(2020, 'train_sample')
            e_np = elo.Elo().run(DA.DataAccess('feature_computation', root=d).games(2020, 'use_elo'))
        self.assertEqual(t1, t2)                                   # 拿掉季後賽，訓練樣本不變
        self.assertNotEqual(len(e_all.updates), len(e_np.updates))  # Elo 更新清單會變

    def test_elo_module_never_touches_training_sample(self):
        src = open(elo.__file__, encoding='utf-8').read()
        code = '\n'.join(l for l in src.splitlines() if not l.strip().startswith('#'))
        self.assertNotIn("'train_sample'", code)


class T6_ParamsDevOnly(unittest.TestCase):
    def test_select_params_rejects_non_dev_seasons(self):
        for bad in ([2024], [2025], [2026], [2015], [2020, 2024]):
            with self.assertRaises(config.HoldoutLocked):
                elo.select_params(bad, [elo.DEFAULT_PARAMS], lambda p, s: 0.0)

    def test_select_params_accepts_dev_seasons(self):
        best = elo.select_params([2016, 2017], [{'k': 10.0}, {'k': 30.0}], lambda p, s: abs(p['k'] - 25))
        self.assertEqual(best, {'k': 30.0})

    def test_build_refuses_locked_seasons(self):
        for p in ('feature_computation', 'training', 'tuning', 'model_selection', 'backtest', 'evaluation'):
            with self.assertRaises(config.HoldoutLocked):
                elo.build([2025], purpose=p)
            with self.assertRaises(config.HoldoutLocked):
                elo.build([2026], purpose=p)


class EloMisc(unittest.TestCase):
    def test_no_odds_or_box_inputs(self):
        src = open(elo.__file__, encoding='utf-8').read()
        for w in ('odds', 'team_boxes', 'tov', 'possessions', 'read_jsonl_gz'):
            self.assertNotIn(w, src.replace('不用盤口', '').replace('不用 box score', ''), w)

    def test_neutral_site_gets_no_home_advantage(self):
        e = elo.Elo()
        g = {'game_id': 'x', 'season': 2020, 'start_utc': '2020-01-02T00:30:00Z', 'home': 'A', 'away': 'B',
             'home_pts': 100, 'away_pts': 99, 'game_type': 'REGULAR_SEASON'}
        e.run([g], {'x': 'neutral'})
        u = e.updates[0]
        self.assertEqual(u['site'], 'neutral')
        self.assertAlmostEqual(elo.expected(1505, 1505, 0), 0.5)
        self.assertAlmostEqual(u['post_home'] - u['pre_home'], elo.DEFAULT_PARAMS['k'] * elo.mov_multiplier(1, 0) * 0.5)

    def test_zero_sum(self):
        e = build(G)
        for u in e.updates:
            self.assertAlmostEqual(u['post_home'] - u['pre_home'], -(u['post_away'] - u['pre_away']))
