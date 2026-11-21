"""稽核完整性（fail closed）與 F1 有效比賽集合一致性（使用者 2026-11-21 核准的問題 1、問題 2 修正）。T41、T42。

T41 稽核涵蓋清單：缺 flag 檔、缺清單、ID 缺漏／多餘／重複、原始檔改動、新增比賽、稽核版本不符 → 一律拒絕計算。
T42 唯一有效比賽入口 get_valid_f1_games：F1 累計、league_games_asof、league_games_asof_excl_team、100 場門檻、
    f1_prior_source 全部得到相同結果；ERROR／缺 box／回合數無效的排除一致；LOTO 一致；99 場不過、100 場過。
"""
import csv
import json
import os
import tempfile
import unittest

from nba_quant import audit_coverage, config, data_access as DA, store
from nba_quant.audit_coverage import AuditIntegrityError
from nba_quant.features import f1

from test_f1 import make_root, seal
from test_f1_loto_audit import league_schedule

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
ERR_GAMES = {2020: ['401161297'], 2023: ['401468217', '401468616']}
ZERO = {'fga': 10, 'oreb': 10, 'tov': 0, 'fta': 0}                  # 回合數 = 0
G = [('g1', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
     ('g2', 2020, '2020-01-04T00:30:00Z', 'C', 'D', 100, 90, 'REGULAR_SEASON'),
     ('g3', 2020, '2020-01-06T00:30:00Z', 'A', 'C', 105, 95, 'REGULAR_SEASON')]


def manifest_path(d, s=2020):
    return audit_coverage.paths(s, d)['manifest']


def edit_manifest(d, fn, s=2020):
    p = manifest_path(d, s)
    m = store.read_json(p)
    fn(m)
    with open(p, 'w', encoding='utf-8') as fh:                       # 刻意繞過 build_manifest，模擬被竄改／過期的清單
        json.dump(m, fh)


class AuditFailClosed(unittest.TestCase):
    """T41：任何完整性檢查不通過 → AuditIntegrityError，F1 不得計算。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        make_root(self.d, G)

    def tearDown(self):
        self.tmp.cleanup()

    def refused(self, code):
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.compute(2020, root=self.d)
        self.assertEqual(cm.exception.code, code)
        with self.assertRaises(AuditIntegrityError):                  # 資料存取層與唯一入口同樣拒絕
            DA.DataAccess('feature_computation', root=self.d).box_audit_flags(2020)
        with self.assertRaises(AuditIntegrityError):
            f1.get_valid_f1_games(DA.DataAccess('feature_computation', root=self.d), 2020)

    def test_01_flag_file_missing_refused(self):
        os.remove(audit_coverage.paths(2020, self.d)['flags'])
        self.refused('flags_missing')

    def test_02_empty_flag_file_without_manifest_refused(self):
        self.assertEqual(list(store.read_jsonl_gz(audit_coverage.paths(2020, self.d)['flags'])), [])   # 空 flag 檔
        os.remove(manifest_path(self.d))
        self.refused('manifest_missing')

    def test_03_one_audited_id_missing_refused(self):
        def drop(m):
            m['audited_game_ids'] = m['audited_game_ids'][1:]
            m['audited_game_count'] -= 1
        edit_manifest(self.d, drop)
        self.refused('not_all_audited')

    def test_03b_id_missing_from_both_lists_refused(self):
        def drop(m):
            for k in ('expected', 'audited'):
                m[f'{k}_game_ids'] = m[f'{k}_game_ids'][1:]
                m[f'{k}_game_count'] -= 1
        edit_manifest(self.d, drop)
        self.refused('scope_mismatch')                                  # 原始資料有、清單沒有 → 未稽核的比賽

    def test_04_extra_nonexistent_id_refused(self):
        def add(m):
            for k in ('expected', 'audited'):
                m[f'{k}_game_ids'] = m[f'{k}_game_ids'] + ['zzz']
                m[f'{k}_game_count'] += 1
        edit_manifest(self.d, add)
        self.refused('scope_mismatch')

    def test_04b_extra_id_in_audited_only_refused(self):
        def add(m):
            m['audited_game_ids'] = m['audited_game_ids'] + ['zzz']
            m['audited_game_count'] += 1
        edit_manifest(self.d, add)
        self.refused('not_all_audited')

    def test_05_duplicate_id_refused(self):
        def dup(m):
            m['audited_game_ids'] = m['audited_game_ids'] + m['audited_game_ids'][:1]
            m['audited_game_count'] += 1
        edit_manifest(self.d, dup)
        self.refused('duplicate_ids')

    def test_05b_count_field_mismatch_refused(self):
        edit_manifest(self.d, lambda m: m.update(audited_game_count=m['audited_game_count'] + 1))
        self.refused('count')

    def test_06_one_raw_box_field_changed_refused(self):
        p = audit_coverage.paths(2020, self.d)['teambox']
        bx = list(store.read_jsonl_gz(p))
        bx[0]['tov'] += 1                                               # 只改一個欄位
        store.write_jsonl_gz(p, bx)
        self.refused('raw_boxscore_hash')

    def test_07_new_game_invalidates_old_manifest(self):
        old = store.read_json(manifest_path(self.d))
        p = audit_coverage.paths(2020, self.d)
        bx = list(store.read_jsonl_gz(p['teambox']))
        gs = list(store.read_jsonl_gz(p['games']))
        bx += [dict(bx[0], game_id='g9'), dict(bx[1], game_id='g9')]
        gs.append(dict(gs[0], game_id='g9', start_utc='2020-01-08T00:30:00Z'))
        store.write_jsonl_gz(p['teambox'], bx)
        store.write_jsonl_gz(p['games'], gs)
        cls = os.path.join(self.d, 'data', 'reference', 'game_classification.csv')   # 回補時分類表也會跟著重建
        with open(cls, encoding='utf-8', newline='') as fh:
            rows = list(csv.DictReader(fh))
        rows.append(dict(rows[0], game_id='g9', start_utc='2020-01-08T00:30:00Z'))
        with open(cls, 'w', encoding='utf-8', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        self.refused('raw_boxscore_hash')
        # 即使有人只把指紋改成新檔的（不重新稽核），新增的比賽仍不在清單內 → 拒絕
        edit_manifest(self.d, lambda m: m.update(raw_boxscore_file_hash=store.sha256_file(p['teambox']),
                                                 raw_games_file_hash=store.sha256_file(p['games'])))
        self.refused('scope_mismatch')
        self.assertNotIn('g9', old['audited_game_ids'])                 # 舊清單不會自動沿用

    def test_07b_flag_file_changed_refused(self):
        p = audit_coverage.paths(2020, self.d)['flags']
        store.write_jsonl_gz(p, [{'game_id': 'g1', 'team': 'B', 'check': 'x', 'detail': '', 'severity': 'warning'}])
        self.refused('flags_hash')

    def test_08_audit_version_incompatible_refused(self):
        edit_manifest(self.d, lambda m: m.update(audit_version='box_quality_v0'))
        self.refused('version')

    def test_08c_audit_code_changed_version_not_bumped_refused(self):
        """稽核程式改變但 audit_version 忘記更新：保留舊清單 → 以程式指紋拒絕。"""
        from unittest import mock
        self.assertEqual(store.read_json(manifest_path(self.d))['audit_version'], audit_coverage.AUDIT_VERSION)
        with mock.patch.object(audit_coverage, '_code_sha', lambda: '0' * 64):
            self.refused('audit_code_hash')

    def test_08d_real_code_file_change_refused(self):
        """不靠 mock：實際換一份內容不同的稽核程式檔（只加一行註解），舊清單必須失效。"""
        import shutil
        from unittest import mock
        from nba_quant import box_audit
        alt = os.path.join(self.d, 'box_audit_changed.py')
        shutil.copy(box_audit.__file__, alt)
        with open(alt, 'a', encoding='utf-8') as fh:
            fh.write('\n# changed\n')
        with mock.patch.object(box_audit, '__file__', alt):
            self.refused('audit_code_hash')

    def test_08e_required_version_bumped_old_manifest_refused(self):
        """程式要求的稽核版本升級，但舊清單仍存在 → 拒絕。"""
        from unittest import mock
        with mock.patch.object(audit_coverage, 'REQUIRED_AUDIT_VERSION', 'box_quality_v2'):
            self.refused('version')

    def test_08f_matching_code_and_manifest_pass(self):
        m = audit_coverage.verify(2020, self.d)
        self.assertEqual(m['audit_code_sha256'], audit_coverage._code_sha())
        self.assertEqual(m['audit_version'], audit_coverage.REQUIRED_AUDIT_VERSION)
        self.assertEqual(m['content_sha256'], audit_coverage.content_sha(m))

    def test_08g_content_fingerprint_tamper_refused(self):
        edit_manifest(self.d, lambda m: m.update(audited_team_box_count=m['audited_team_box_count'] + 1))
        self.refused('content_hash')
        edit_manifest(self.d, lambda m: m.pop('content_sha256'))
        self.refused('content_hash')

    def test_content_fingerprint_independent_of_timestamp(self):
        """相同原始資料、flag、稽核程式：不同時間重建 → 內容指紋相同；檔案只有 audit_timestamp 不同。"""
        a = audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='2026-01-01T00:00:00+00:00')
        fa = store.sha256_file(manifest_path(self.d))
        b = audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='2026-02-01T00:00:00+00:00')
        fb = store.sha256_file(manifest_path(self.d))
        self.assertEqual(a['content_sha256'], b['content_sha256'])
        self.assertNotEqual(fa, fb)                                    # 檔案位元組含事件時間，本來就會不同
        self.assertEqual({k for k in a if a[k] != b[k]}, {'audit_timestamp'})
        audit_coverage.verify(2020, self.d)

    def test_content_fingerprint_changes_with_content(self):
        a = audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='t')
        seal(self.d, {2020: [{'game_id': 'g1', 'team': 'B', 'check': 'x', 'detail': '', 'severity': 'warning'}]})
        b = store.read_json(manifest_path(self.d))
        self.assertNotEqual(a['content_sha256'], b['content_sha256'])  # flag 不同 → 內容指紋不同

    def test_08b_flag_outside_audited_scope_refused(self):
        p = audit_coverage.paths(2020, self.d)['flags']
        store.write_jsonl_gz(p, [{'game_id': 'nope', 'team': 'B', 'check': 'x', 'detail': '', 'severity': 'error'}])
        audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='t')
        self.refused('flag_outside_scope')

    def test_09_fully_audited_season_without_error_passes(self):
        m = audit_coverage.verify(2020, self.d)
        self.assertEqual(m['expected_game_ids'], ['g1', 'g2', 'g3'])
        self.assertEqual(m['expected_game_ids'], m['audited_game_ids'])
        h = f1.get_valid_f1_games(DA.DataAccess('feature_computation', root=self.d), 2020)
        self.assertEqual((h.game_ids, h.excluded), (['g1', 'g2', 'g3'], []))
        self.assertTrue(f1.compute(2020, root=self.d).rows)

    def test_manifest_is_deterministic(self):
        a = open(manifest_path(self.d), 'rb').read()
        audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='synthetic')
        self.assertEqual(open(manifest_path(self.d), 'rb').read(), a)

    def test_stale_audit_refused_when_building(self):
        """產生清單時重新稽核：結果與既有 flag 檔不同 → 拒絕產生（不得把舊稽核套到新原始資料）。"""
        p = audit_coverage.paths(2020, self.d)['teambox']
        bx = list(store.read_jsonl_gz(p))
        bx[0]['tov'] = 0                                                # 會被 box 稽核 v1 標記的值
        store.write_jsonl_gz(p, bx)
        with self.assertRaises(AuditIntegrityError) as cm:
            audit_coverage.build_manifest(2020, self.d)
        self.assertEqual(cm.exception.code, 'stale_audit')


def bad_season(n_valid, season=2020):
    """n_valid 場有效的非 A 隊比賽 + 6 場無效（ERROR 3、缺 box 2、回合數無效 1），之後一天 A 出賽。
    重現原問題：舊 f1_prior_source 會數到 n_valid + 6。"""
    teams = [chr(ord('B') + i) for i in range(12)]
    g, i = [], 0
    for k in range(n_valid + 6):
        day, slot = divmod(k, 6)
        h, a = teams[(2 * slot + day) % 12], teams[(2 * slot + 1 + day) % 12]
        kw = [ZERO, {}] if k == 5 else []
        g.append((f'h{k:03d}', season, f'2020-01-{day + 1:02d}T00:30:00Z', h, a, 100 + k % 9, 95 + k % 7,
                  'REGULAR_SEASON', *kw))
    target = ('tA', season, '2020-01-28T00:30:00Z', 'A', 'B', 100, 99, 'REGULAR_SEASON')
    return g + [target], ['h000', 'h001', 'h002'], ['h003', 'h004'], ['h005']


def build_bad(d, n_valid):
    games, err, miss, zero = bad_season(n_valid)
    make_root(d, games)
    p = audit_coverage.paths(2020, d)['teambox']
    bx = [b for b in store.read_jsonl_gz(p) if not (b['game_id'] in miss and b['team'] == next(
        x[4] for x in games if x[0] == b['game_id']))]                 # 缺客隊 box
    store.write_jsonl_gz(p, bx)
    seal(d, {2020: [{'game_id': x, 'team': None, 'level': 'game', 'check': 'synthetic', 'detail': '', 'severity': 'error'}
                    for x in err]})
    return games, set(err), set(miss), set(zero)


class SharedValidSet(unittest.TestCase):
    """T42：所有計數都來自 get_valid_f1_games。"""

    def test_10_error_missing_and_invalid_poss_excluded_consistently(self):
        with tempfile.TemporaryDirectory() as d:
            games, err, miss, zero = build_bad(d, 30)
            da = DA.DataAccess('feature_computation', root=d)
            h = f1.get_valid_f1_games(da, 2020)
            reasons = {e['game_id']: e['reason'] for e in h.excluded}
            self.assertEqual({k for k, v in reasons.items() if v == 'box_audit_error'}, err)
            self.assertEqual({k for k, v in reasons.items() if v == 'invalid_possessions'}, zero)
            self.assertEqual({k for k, v in reasons.items() if v not in ('box_audit_error', 'invalid_possessions')}, miss)
            bad = err | miss | zero
            self.assertEqual(set(h.game_ids), {x[0] for x in games} - bad)
            self.assertEqual(len({r['game_id'] for r in h.rows}), len(h.game_ids))
            res = f1.compute(2020, da=da)
            self.assertEqual(res.excluded, h.excluded)
            for x in bad:                                               # 無效比賽不進任一隊的累計
                self.assertFalse([r for r in h.rows if r['game_id'] == x])

    def test_11_prior_source_and_f1_use_identical_valid_set(self):
        """f1_prior_source（資料存取層）與 F1 批次計算的每一列：有效比賽、場數、先驗來源全部相同。"""
        with tempfile.TemporaryDirectory() as d:
            make_root(d, league_schedule(days=25))
            flags = [{'game_id': f'd{x:02d}k2', 'team': None, 'level': 'game', 'check': 's', 'detail': '', 'severity': 'error'}
                     for x in range(0, 24, 3)]
            seal(d, {2020: flags})
            da = DA.DataAccess('feature_computation', root=d)
            res = f1.compute(2020, da=da)
            self.assertTrue(res.excluded)
            for r in res.rows[::7]:
                full = f1.get_valid_f1_games(da, 2020, r['as_of'])
                loto = f1.get_valid_f1_games(da, 2020, r['as_of'], exclude_team=r['team'])
                src = da.f1_prior_source(r['team'], r['as_of'])
                self.assertEqual(r['league_games_asof'], len(full.game_ids))
                self.assertEqual(r['league_games_asof_excl_team'], len(loto.game_ids))
                self.assertEqual(src['current_season_valid_game_ids'], loto.game_ids)
                self.assertEqual((src['source'], src['seasons']), (r['prior_source'], r['prior_season']))
                self.assertEqual(r['n_games'], sum(1 for x in full.rows if x['team'] == r['team']))
                # LOTO：= 全部有效比賽 − 本隊參與的有效比賽
                own = {x['game_id'] for x in full.rows if x['team'] == r['team']}
                self.assertEqual(set(loto.game_ids), set(full.game_ids) - own)
                self.assertEqual(set(loto.loto_excluded), own)

    def test_threshold_99_fails_100_passes(self):
        for n, src in ((99, 'missing'), (100, 'league_average_current_season_to_date')):
            with tempfile.TemporaryDirectory() as d:
                games, err, miss, zero = build_bad(d, n)
                da = DA.DataAccess('feature_computation', root=d)
                r = [x for x in f1.compute(2020, da=da).rows if x['game_id'] == 'tA' and x['team'] == 'A'][0]
                p = da.f1_prior_source('A', r['as_of'])
                self.assertEqual(r['league_games_asof_excl_team'], n)
                self.assertEqual(p['current_season_games_to_date'], n)
                self.assertEqual((r['prior_source'], p['source']), (src, src), n)
                raw = [g for g in da.games(2020, 'use_team_stats', r['as_of']) if 'A' not in (g['home'], g['away'])]
                self.assertEqual(len(raw), n + 6)                       # 舊寫法會數到 n + 6（原問題 99 vs 105）

    def test_prior_source_refuses_without_audit(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, G)
            os.remove(audit_coverage.paths(2020, d)['flags'])
            with self.assertRaises(AuditIntegrityError):
                DA.DataAccess('feature_computation', root=d).f1_prior_source('A', '2020-01-06T00:30:00Z')

    def test_season_without_any_raw_data_needs_no_audit(self):
        """完全沒有原始資料的球季（例：2014-15 的上一季）回傳空集合，不視為稽核缺失；有資料就一定要稽核。"""
        with tempfile.TemporaryDirectory() as d:
            make_root(d, G)
            h = f1.get_valid_f1_games(DA.DataAccess('feature_computation', root=d), 2019)
            self.assertEqual((h.status, h.game_ids), ('no_raw_data', []))


@unittest.skipUnless(HAS_DATA, 'no data')
class RealData(unittest.TestCase):
    def test_10_real_error_games_excluded(self):
        da = DA.DataAccess('feature_computation')
        for s, ids in ERR_GAMES.items():
            h = f1.get_valid_f1_games(da, s)
            self.assertEqual({e['game_id'] for e in h.excluded if e['reason'] == 'box_audit_error'}, set(ids), s)
            self.assertFalse(set(ids) & set(h.game_ids))

    def test_all_seasons_coverage_verified(self):
        files = sorted(os.listdir(os.path.join(ROOT, 'data', 'audit', 'box_quality', 'v1', 'coverage')))
        self.assertEqual(files, [f'{s}.json' for s in range(2015, 2026)])          # 11 份完整
        for s in range(2015, 2026):
            m = audit_coverage.verify(s, ROOT)
            self.assertEqual(m['audit_code_sha256'], audit_coverage._code_sha())
            self.assertEqual(m['expected_game_ids'], m['audited_game_ids'])
            self.assertEqual(m['expected_game_count'], m['audited_game_count'])

    def test_11_real_prior_source_matches_f1(self):
        da = DA.DataAccess('feature_computation')
        for s in (2015, 2019):                                           # 用到「當季至今」門檻的兩個開發期球季
            rows = f1.compute(s, da=da).rows
            hits = set()
            for r in rows[:: 97]:
                p = da.f1_prior_source(r['team'], r['as_of'])
                self.assertEqual((p['source'], p['seasons']), (r['prior_source'], r['prior_season']))
                self.assertEqual(p['current_season_games_to_date'], r['league_games_asof_excl_team'])
                hits.add(r['prior_source'])
            self.assertIn('league_average_current_season_to_date', hits)

    def test_12_2017_18_isolated(self):
        da = DA.DataAccess('feature_computation')
        h = f1.get_valid_f1_games(da, 2018)
        self.assertEqual((h.status, h.rows), ('unavailable', []))
        self.assertFalse([x for x in da.log if x.get('season') == 2018])    # 不讀任何 2017-18 資料（含稽核）
        self.assertEqual(da.f1_prior_source('X', '2018-01-02T00:30:00Z')['status'], 'unavailable')

    def test_13_locked_seasons_refused_before_audit(self):
        for s in (2024, 2025, 2026):
            da = DA.DataAccess('feature_computation')
            with self.assertRaises(config.HoldoutLocked):
                f1.get_valid_f1_games(da, s)
            with self.assertRaises(config.HoldoutLocked):
                da.box_audit_flags(s)
            self.assertFalse([x for x in da.log if x.get('call') == 'box_audit_flags' and x.get('coverage_verified')])


if __name__ == '__main__':
    unittest.main()
