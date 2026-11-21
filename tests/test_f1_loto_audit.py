"""F1：leave-one-team-out 聯盟先驗、box 稽核 ERROR 排除、欄位命名（使用者 2026-11-21 決策）。T39。
先驗方案維持 A；100 場是預先登記的資料可用性門檻。"""
import os
import tempfile
import unittest

from nba_quant import asof, store
from nba_quant.features import f1

from test_f1 import make_root, seal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
TEAMS = [chr(ord('A') + i) for i in range(12)]


def league_schedule(days=25, per_day=6, season=2020, start_day=1):
    """沒有上一季資料的合成球季（行為同 2014-15）：每天 6 場，12 隊輪流。"""
    g = []
    for d in range(days):
        for k in range(per_day):
            h, a = TEAMS[(2 * k + d) % 12], TEAMS[(2 * k + 1 + d) % 12]
            g.append((f'd{d:02d}k{k}', season, f'2020-01-{start_day + d:02d}T00:30:00Z', h, a,
                      100 + (d * 7 + k) % 15, 95 + (d * 3 + k) % 13, 'REGULAR_SEASON',
                      {'fga': 84 + (d + k) % 6}, {'fga': 86 + (d * k) % 5}))
    return g


def run(games, flags=None, season=2020):
    with tempfile.TemporaryDirectory() as d:
        make_root(d, games)
        if flags is not None:
            seal(d, {season: flags})                        # 宣告該季的稽核結果（flag 檔 = 宣告內容）並重新封存
        return f1.compute(season, root=d)


def rows_of(res, team):
    return sorted((r for r in res.rows if r['team'] == team), key=lambda r: r['as_of'])


def first_current(res, team):
    return next(r for r in rows_of(res, team) if r['prior_source'] == 'league_average_current_season_to_date')


class LeaveOneTeamOut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.G = league_schedule()
        cls.res = run(cls.G)

    def test_1_loto_value(self):
        r = first_current(self.res, 'A')
        d = asof.et_date(r['as_of'])
        acc = f1.Acc()
        for x in f1.game_rows(self._boxes(self.G)):
            if asof.et_date(x['start_utc']) < d and 'A' not in (x['team'], x['opp']):
                acc.add(x)
        lv = f1.league_values(acc)
        for k in f1.KEYS:
            self.assertAlmostEqual(r[f'prior_{k}'], lv[k], places=9)
        self.assertEqual(r['league_games_asof_excl_team'], acc.n // 2)
        self.assertGreater(r['league_games_asof'], r['league_games_asof_excl_team'])

    def _boxes(self, games):
        out = []
        for gid, s, t, h, a, hp, ap, gt, hk, ak in games:
            for team, pts, kw in ((h, hp, hk), (a, ap, ak)):
                b = {'game_id': gid, 'team': team, 'start_utc': t, 'pts': pts, 'fga': 85, 'fta': 20, 'oreb': 10, 'tov': 14,
                     'overtimes': 0}
                b.update({k: v for k, v in kw.items() if k in b})
                out.append(b)
        return out

    def test_2_own_games_do_not_change_own_prior(self):
        r0 = first_current(self.res, 'A')
        changed = [x if 'A' not in (x[3], x[4]) else x[:5] + (180, 40) + x[7:] for x in self.G]
        r1 = first_current(run(changed), 'A')
        self.assertEqual(r0['as_of'], r1['as_of'])
        for k in f1.KEYS:
            self.assertEqual(r0[f'prior_{k}'], r1[f'prior_{k}'])
        self.assertNotEqual(r0['raw_ortg'], r1['raw_ortg'])                # A 自己的原始值當然會變

    def test_3_other_teams_games_within_as_of_change_prior(self):
        r0 = first_current(self.res, 'A')
        victim = next(x for x in self.G if 'A' not in (x[3], x[4]) and asof.et_date(x[2]) < asof.et_date(r0['as_of']))
        changed = [x if x[0] != victim[0] else x[:5] + (160, 60) + x[7:] for x in self.G]
        r1 = [r for r in run(changed).rows if r['game_id'] == r0['game_id'] and r['team'] == 'A'][0]
        self.assertNotEqual(r0['prior_ortg'], r1['prior_ortg'])

    def test_4_future_data_does_not_change_prior(self):
        r0 = first_current(self.res, 'A')
        fut = self.G + [('fut', 2020, '2020-02-20T00:30:00Z', 'B', 'C', 190, 50, 'REGULAR_SEASON', {}, {})]
        later = [x if asof.et_date(x[2]) <= asof.et_date(r0['as_of']) else x[:5] + (170, 30) + x[7:] for x in self.G]
        for g in (fut, later):
            r1 = [r for r in run(g).rows if r['game_id'] == r0['game_id'] and r['team'] == 'A'][0]
            self.assertEqual({k: r0[f'prior_{k}'] for k in f1.KEYS}, {k: r1[f'prior_{k}'] for k in f1.KEYS})

    def test_5_same_day_games_do_not_leak(self):
        r0 = first_current(self.res, 'A')
        d = asof.et_date(r0['as_of'])
        same_day = [x for x in self.G if asof.et_date(x[2]) == d and 'A' not in (x[3], x[4])]
        self.assertTrue(same_day)
        changed = [x if x[0] not in {y[0] for y in same_day} else x[:5] + (200, 20) + x[7:] for x in self.G]
        r1 = [r for r in run(changed).rows if r['game_id'] == r0['game_id'] and r['team'] == 'A'][0]
        self.assertEqual(r0['prior_ortg'], r1['prior_ortg'])
        self.assertEqual(r0['league_games_asof'], r1['league_games_asof'])

    def test_6_threshold_uses_count_after_excluding_team(self):
        """同一天：聯盟總數已 ≥ 100，但對某些隊排除其比賽後 < 100 → 那些隊仍不得使用當季聯盟平均。"""
        seen = False
        for r in self.res.rows:
            if r['league_games_asof'] is None:
                continue
            if r['prior_source'] == 'league_average_current_season_to_date':
                self.assertGreaterEqual(r['league_games_asof_excl_team'], 100)
            else:
                self.assertLess(r['league_games_asof_excl_team'], 100)
                if r['league_games_asof'] >= 100:
                    seen = True
                    self.assertEqual(r['status'], 'missing')               # 沒有上季 → 未達門檻即 missing（不補值）
        self.assertTrue(seen, '測試資料需包含「總數 ≥ 100 但排除本隊後 < 100」的情況')


class BoxAuditFlags(unittest.TestCase):
    G = [('g1', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
         ('g2', 2020, '2020-01-04T00:30:00Z', 'A', 'B', 105, 95, 'REGULAR_SEASON'),
         ('g3', 2020, '2020-01-06T00:30:00Z', 'A', 'C', 100, 90, 'REGULAR_SEASON')]

    def test_7_error_flag_excludes_game_for_both_teams(self):
        flags = [{'game_id': 'g1', 'team': 'B', 'level': 'record', 'check': 'zero_value', 'detail': 'tov', 'severity': 'error'}]
        res = run(self.G, flags)
        a = [r for r in res.rows if r['game_id'] == 'g3' and r['team'] == 'A'][0]
        self.assertEqual(a['n_games'], 1)                                  # 只剩 g2
        b = [r for r in res.rows if r['game_id'] == 'g2' and r['team'] == 'B'][0]
        self.assertEqual(b['n_games'], 0)
        e = res.excluded[0]
        self.assertEqual((e['game_id'], e['reason']), ('g1', 'box_audit_error'))
        self.assertEqual(e['audit_flags'], [{'team': 'B', 'check': 'zero_value', 'detail': 'tov'}])

    def test_7b_game_level_error_also_excludes(self):
        flags = [{'game_id': 'g1', 'team': None, 'level': 'game', 'check': 'rebounds_exceed_misses', 'detail': 'x',
                  'severity': 'error'}]
        res = run(self.G, flags)
        self.assertEqual(res.excluded[0]['reason'], 'box_audit_error')

    def test_8_warning_kept_and_recorded(self):
        flags = [{'game_id': 'g1', 'team': None, 'level': 'game', 'check': 'possessions_mismatch', 'detail': 'x',
                  'severity': 'warning'}]
        res = run(self.G, flags)
        self.assertEqual(res.excluded, [])
        a = [r for r in res.rows if r['game_id'] == 'g3' and r['team'] == 'A'][0]
        self.assertEqual(a['n_games'], 2)
        w = [x for x in res.warnings if x['source'] == 'box_audit_v1']
        self.assertEqual((w[0]['game_id'], w[0]['check'], w[0]['action']), ('g1', 'possessions_mismatch', 'kept_with_warning'))

    @unittest.skipUnless(HAS_DATA, 'no data')
    def test_7c_real_det_zero_turnover_game_excluded(self):
        res = f1.compute(2023)
        e = [x for x in res.excluded if x['game_id'] == '401468616']
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]['reason'], 'box_audit_error')
        self.assertEqual(e[0]['audit_flags'], [{'team': '8', 'check': 'zero_value', 'detail': 'tov'}])
        self.assertEqual(e[0]['raw_boxes']['8']['tov'], 0)                  # 原始數據保留，未修改
        self.assertEqual({x['game_id'] for x in res.excluded}, {'401468616', '401468217'})


@unittest.skipUnless(HAS_DATA, 'no data')
class RealDataRules(unittest.TestCase):
    def test_10_2018_19_switch_per_team(self):
        by = {}
        for r in sorted(f1.compute_season(2019), key=lambda r: r['as_of']):
            by.setdefault(r['team'], []).append(r)
        for t, rs in by.items():
            src = [r['prior_source'] for r in rs]
            k = src.index('league_average_current_season_to_date')
            self.assertTrue(all(s == 'league_average_latest_available_season' for s in src[:k]), t)
            self.assertTrue(all(s == 'league_average_current_season_to_date' for s in src[k:]), t)   # 切換後不切回
            self.assertTrue(all(r['prior_season'] == [2017] for r in rs[:k]))
            self.assertTrue(all(r['prior_season'] == [2019] for r in rs[k:]))
            self.assertGreaterEqual(rs[k]['league_games_asof_excl_team'], 100)
            self.assertLess(rs[k - 1]['league_games_asof_excl_team'], 100)
            self.assertTrue(all(r['prior_net_rating'] == 0 for r in rs))   # 上季不可用：先驗淨值為 0

    def test_11_2014_15_special_case(self):
        for r in f1.compute_season(2015):
            self.assertNotEqual(r['prior_source'], 'team_previous_season')    # 不虛構上一季
            if r['league_games_asof_excl_team'] < 100:
                self.assertEqual((r['status'], r['prior_source']), ('missing', 'missing'))
                self.assertTrue(all(r[f] is None for f in f1.FEATURES))
            else:
                self.assertEqual((r['prior_source'], r['prior_season']), ('league_average_current_season_to_date', [2015]))

    def test_12_values_unchanged_except_explained(self):
        """與 0d3f446 的快照比對：只有 leave-one-team-out 與 ERROR 排除影響的部分可以不同。"""
        old = {(r['season'], r['game_id'], r['team']): r
               for r in store.read_jsonl_gz(os.path.join(ROOT, 'tests', 'fixtures', 'f1_values_0d3f446.jsonl.gz'))}
        same = lambda a, b: a['status'] == b['status'] and all(
            (a[k] is None and b[k] is None) or (a[k] is not None and b[k] is not None and abs(a[k] - b[k]) < 1e-12)
            for k in f1.FEATURES)
        for s in range(2015, 2024):
            res = f1.compute(s)
            err_first = {}
            for e in res.excluded:
                if e['reason'] == 'box_audit_error':
                    for t in e['teams']:
                        err_first[t] = min(err_first.get(t, e['start_utc']), e['start_utc'])
            for r in res.rows:
                o = old[(s, r['game_id'], r['team'])]
                loto = 'league_average_current_season_to_date' in (r['prior_source'], o['prior_source'])
                own_err = r['team'] in err_first and r['as_of'] > err_first[r['team']]
                if s in (2016, 2017, 2018, 2022):
                    self.assertTrue(same(r, o), (s, r['game_id'], r['team']))
                elif loto:
                    if r['F1.net_rating'] is not None and o['F1.net_rating'] is not None:
                        self.assertAlmostEqual(r['F1.net_rating'], o['F1.net_rating'], places=9)   # 聯盟淨值恆為 0
                elif own_err:
                    self.assertLess(r['n_games'], o['n_games'] + 1)
                elif s == 2021:
                    # 2019-20 全季累計排除 1 場 ERROR → 2020-21 的上季先驗（聯盟與相關球隊）微幅改變；本季累計不變
                    self.assertEqual(r['n_games'], o['n_games'])
                    self.assertTrue(all(abs(r[k] - o[k]) < 0.1 for k in f1.FEATURES))
                else:
                    self.assertTrue(same(r, o), (s, r['game_id'], r['team']))
