"""F1 球季累計效率（stage 2）：公式、防洩漏、範圍、2017-18 不可用、2018-19 先驗、鎖定期。"""
import csv
import os
import random
import tempfile
import unittest

from nba_quant import audit_coverage, config, data_access as DA, feature_deps, game_class, store
from nba_quant.features import f1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))


def box(gid, team, pts, fga=85, fta=20, oreb=10, tov=14, ot=0):
    fgm = (pts - 20) // 2
    return {'game_id': gid, 'team': team, 'pts': pts, 'fgm': fgm, 'fga': fga, 'fg3m': 0, 'fg3a': 0, 'ftm': 20, 'fta': fta,
            'oreb': oreb, 'dreb': 33, 'tov': tov, 'overtimes': ot, 'source': 'espn:summary'}


CUP_NOTES = {'CUP_GROUP': ['NBA Cup Group Play'], 'CUP_QUARTERFINAL': ['NBA Cup Quarterfinals'],
             'CUP_SEMIFINAL': ['NBA Cup Semifinals'], 'CUP_FINAL': ['NBA Cup Championship']}
SEASON_TYPE = {'POSTSEASON': 3, 'PLAY_IN': 5}


def make_root(d, games, real_audit=False, empty_prev=True):
    """games: [(gid, season, start_utc, home, away, hp, ap, game_type, home_box_kw, away_box_kw)]
    原始賽程依 game_type 帶上 ESPN 的 season_type 與盃賽備註；分類表以 game_class.row 從這些原始賽程產生
    （與真實分類表的產生方式相同），附加賽放在 data/raw/espn_playin/<季>/。"""
    os.makedirs(os.path.join(d, 'data', 'reference'), exist_ok=True)
    gs, bx, pgs, pbx = {}, {}, {}, {}
    cls_rows = []
    for gid, s, t, h, a, hp, ap, gt, *kw in games:
        hk, ak = (kw + [{}, {}])[:2]
        g = {'game_id': gid, 'season': s, 'season_type': SEASON_TYPE.get(gt, 2), 'start_utc': t, 'home': h, 'away': a,
             'home_abbr': h, 'away_abbr': a, 'home_pts': hp, 'away_pts': ap, 'status': 'final', 'complete': True,
             'notes': CUP_NOTES.get(gt, [])}
        assert game_class.classify(g)[0] == gt, (gid, gt)
        kind = 'espn_playin' if gt == 'PLAY_IN' else 'espn'
        cls_rows.append(game_class.row(g, game_class.source_file(kind, s)))
        gs.setdefault(s, [])
        bx.setdefault(s, [])
        if kind == 'espn_playin':              # 附加賽與真實資料相同：獨立放在 data/raw/espn_playin/<季>/
            pgs.setdefault(s, []).append(g)
            pbx.setdefault(s, []).extend([box(gid, h, hp, **hk), box(gid, a, ap, **ak)])
            continue
        gs[s].append(g)
        bx[s].extend([box(gid, h, hp, **hk), box(gid, a, ap, **ak)])
    cls_rows.sort(key=lambda r: (r['start_utc'], r['game_id']))
    with open(os.path.join(d, 'data', 'reference', 'game_classification.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=game_class.FIELDS)
        w.writeheader()
        w.writerows(cls_rows)
    for s in gs:
        store.write_jsonl_gz(os.path.join(d, 'data', 'raw', 'espn', str(s), 'games.jsonl.gz'), gs[s])
        store.write_jsonl_gz(os.path.join(d, 'data', 'raw', 'espn', str(s), 'teambox.jsonl.gz'), bx[s])
    for s in pgs:
        store.write_jsonl_gz(os.path.join(d, 'data', 'raw', 'espn_playin', str(s), 'games.jsonl.gz'), pgs[s])
        store.write_jsonl_gz(os.path.join(d, 'data', 'raw', 'espn_playin', str(s), 'teambox.jsonl.gz'), pbx[s])
    if empty_prev:
        # 2026-11-21 起只有 2013-14 可以「完全沒有資料」。合成球季的前幾季改成「已稽核、0 場」的空球季
        # （空的原始檔 + 空 flag + 清單），行為等同過去的「沒有上一季資料」，但走完整驗證。
        for s in list(gs):
            for k in (1, 2, 3):
                if s - k not in gs and not os.path.isdir(os.path.join(d, 'data', 'raw', 'espn', str(s - k))):
                    for f in ('games.jsonl.gz', 'teambox.jsonl.gz'):
                        store.write_jsonl_gz(os.path.join(d, 'data', 'raw', 'espn', str(s - k), f), [])
    seal(d, real_audit=real_audit)


def seal(d, flags=None, real_audit=False):
    """合成資料的稽核封存（fail closed 之後必要）。
    real_audit=False：每季的稽核結果是「宣告的」——flags={季: [...]} 指定，否則沿用既有宣告、預設 []；
      宣告寫到 synthetic_audit/<季>.json，由 tests/conftest.py 在測試期間當成該根目錄的稽核結果。
    real_audit=True：不宣告，flag 檔 = 真實 box 稽核 v1 的結果。
    兩種情況 flag 檔都寫成稽核結果本身，並以 verify_flags=True 產生清單（產生時就逐筆比對）。
    修改原始檔或 flag 之後必須重新呼叫，否則 F1 會拒絕計算。"""
    import json
    from nba_quant import box_audit
    raw = os.path.join(d, 'data', 'raw', 'espn')
    for s in sorted(int(x) for x in os.listdir(raw) if x.isdigit()):
        marker = os.path.join(d, 'synthetic_audit', f'{s}.json')
        if real_audit:
            if os.path.exists(marker):
                os.remove(marker)
        else:
            if flags and s in flags:
                decl = flags[s]
            elif os.path.exists(marker):
                decl = json.load(open(marker, encoding='utf-8'))
            else:
                decl = []
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, 'w', encoding='utf-8') as fh:
                json.dump(decl, fh)
        store.write_jsonl_gz(audit_coverage.paths(s, d)['flags'], box_audit.audit_season(s, d)[0])
        audit_coverage.build_manifest(s, d, verify_flags=True, now='synthetic')


S = 2020
G = [('g1', S, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
     ('g2', S, '2020-01-03T17:00:00Z', 'C', 'D', 100, 90, 'REGULAR_SEASON'),       # 美東 1/3 中午
     ('g3', S, '2020-01-04T00:30:00Z', 'A', 'C', 105, 95, 'REGULAR_SEASON')]       # 美東 1/3 晚上


def run(games, season=S):
    with tempfile.TemporaryDirectory() as d:
        make_root(d, games)
        return {(r['game_id'], r['team']): r for r in f1.compute_season(season, root=d)}


class Formula(unittest.TestCase):
    def test_possessions_and_ratings(self):
        r = run(G)[('g3', 'A')]            # A 只打過 g1：poss = 85-10+14+0.44*20 = 97.8（兩隊相同）
        self.assertEqual(r['n_games'], 1)
        self.assertAlmostEqual(r['raw_ortg'], 100 * 110 / 97.8)
        self.assertAlmostEqual(r['raw_drtg'], 100 * 100 / 97.8)
        self.assertAlmostEqual(r['raw_net_rating'], 100 * 10 / 97.8)
        self.assertAlmostEqual(r['raw_pace'], 97.8)

    def test_overtime_pace(self):
        g = [('o1', S, '2020-01-02T00:30:00Z', 'A', 'B', 120, 118, 'REGULAR_SEASON', {'ot': 1}, {'ot': 1}),
             ('o2', S, '2020-01-05T00:30:00Z', 'A', 'B', 100, 90, 'REGULAR_SEASON')]
        r = run(g)[('o2', 'A')]
        self.assertAlmostEqual(r['raw_pace'], 97.8 / (53 / 48))

    def test_shrinkage_formula(self):
        r = run(G)[('g3', 'A')]
        # 合成資料沒有上一季、本季至今 < 100 場 → 沒有先驗 → missing，不補值
        self.assertEqual(r['status'], 'missing')
        self.assertIsNone(r['F1.net_rating'])


class Leakage(unittest.TestCase):
    def test_future_game_changes_nothing(self):
        base = run(G)
        fut = run(G + [('g9', S, '2020-02-01T00:30:00Z', 'A', 'C', 160, 60, 'REGULAR_SEASON')])
        for k, v in base.items():
            self.assertEqual(v, fut[k])

    def test_same_et_day_earlier_game_not_used(self):
        r = run(G)[('g3', 'C')]                          # C 的 g2 在同一美東日期中午已完賽
        self.assertEqual(r['n_games'], 0)
        changed = [x if x[0] != 'g2' else ('g2', S, x[2], 'C', 'D', 60, 140, x[7]) for x in G]
        self.assertEqual(run(G)[('g3', 'C')], run(changed)[('g3', 'C')])

    def test_postseason_and_play_in_not_used(self):
        extra = [('p1', S, '2020-01-02T20:00:00Z', 'A', 'B', 200, 50, 'POSTSEASON'),
                 ('q1', S, '2020-01-02T21:00:00Z', 'A', 'B', 190, 60, 'PLAY_IN')]
        self.assertEqual(run(G)[('g3', 'A')], run(G + extra)[('g3', 'A')])

    def test_cup_final_is_used(self):
        cup = [('c1', S, '2020-01-02T20:00:00Z', 'A', 'B', 130, 100, 'CUP_FINAL')]
        self.assertEqual(run(G + cup)[('g3', 'A')]['n_games'], 2)


class Season2017_18_and_2018_19(unittest.TestCase):
    def test_2017_18_unavailable_with_no_values(self):
        g = [('u1', 2018, '2018-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
             ('u2', 2018, '2018-01-04T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON')]
        rows = run(g, season=2018)
        self.assertTrue(rows)
        for r in rows.values():
            self.assertEqual(r['status'], 'unavailable')
            self.assertTrue(all(r[f] is None for f in f1.FEATURES))

    def test_2018_19_does_not_depend_on_2017_18_data(self):
        g17 = [(f'a{i}', 2017, f'2017-01-{i + 2:02d}T00:30:00Z', 'A', 'B', 100 + i, 100 - i, 'REGULAR_SEASON') for i in range(10)]
        g18 = [(f'b{i}', 2018, f'2018-01-{i + 2:02d}T00:30:00Z', 'A', 'B', 110, 90, 'REGULAR_SEASON') for i in range(10)]
        g19 = [(f'c{i}', 2019, f'2018-11-{i + 2:02d}T00:30:00Z', 'A', 'B', 105, 99, 'REGULAR_SEASON') for i in range(5)]
        base = run(g17 + g18 + g19, season=2019)
        g18x = [(x[0], 2018, x[2], 'A', 'B', 150, 50, x[7], {'tov': 0}, {'tov': 40}) for x in g18]
        alt = run(g17 + g18x + g19, season=2019)
        self.assertEqual(base, alt)                                  # 2017-18 任意改動都不影響 2018-19
        for r in base.values():
            self.assertEqual(r['status'], 'available_prior_excluded')
            self.assertNotIn(2018, r['prior_season'])
            self.assertEqual(r['prior_source'], 'league_average_latest_available_season')
            self.assertEqual(r['prior_season'], [2017])


class Locks(unittest.TestCase):
    def test_validation_and_holdout_seasons_refused(self):
        for s in (2024, 2025, 2026):
            with self.assertRaises(config.HoldoutLocked):
                f1.compute_season(s)
            for p in ('training', 'tuning', 'model_selection', 'evaluation', 'backtest', 'feature_selection'):
                with self.assertRaises(config.HoldoutLocked):
                    f1.compute_season(s, purpose=p)


@unittest.skipUnless(HAS_DATA, 'no data')
class RealData(unittest.TestCase):
    def test_batch_matches_per_game_reference(self):
        """批次結果 = 以 DataAccess(as_of) 逐場重算（場數、期間、原始值、先驗來源）。"""
        rnd = random.Random(20261120)
        for season in (2016, 2019, 2021):
            rows = f1.compute_season(season)
            da = DA.DataAccess('feature_computation')
            for r in rnd.sample(rows, 25):
                acc, src = f1.f1_reference(da, r['team'], r['as_of'])
                self.assertEqual(acc.n, r['n_games'])
                self.assertEqual([acc.first, acc.last] if acc.n else None, r['period'])
                if acc.n:
                    for k, v in acc.values().items():
                        self.assertAlmostEqual(v, r[f'raw_{k}'], places=9)
                self.assertEqual(src['source'], r['prior_source'], (season, r['game_id']))
                self.assertEqual(src['seasons'], r['prior_season'])

    def test_status_matches_dependency_rules(self):
        for season in (2016, 2018, 2019):
            want = feature_deps.availability('F1.net_rating', season)[0]
            got = {r['status'] for r in f1.compute_season(season)}
            self.assertEqual(got, {want})

    def test_prior_never_from_unavailable_season(self):
        for season in range(2015, 2024):
            for r in f1.compute_season(season):
                self.assertNotIn(2018, r.get('prior_season') or [])

    def test_deterministic(self):
        self.assertEqual(f1.compute_season(2021), f1.compute_season(2021))
