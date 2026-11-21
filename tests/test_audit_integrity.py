"""稽核完整性（fail closed）與 F1 有效比賽集合一致性（使用者 2026-11-21 核准）。T41、T42。

T41 稽核涵蓋清單：讀取時一律以目前的稽核程式重新稽核並與 flag 檔逐筆比對；稽核程式指紋涵蓋
    box_audit.py、audit_coverage.py、store.py（CRLF → LF）；任何缺檔、缺欄位、指紋不符、範圍不符、
    重新稽核不一致 → AuditIntegrityError（帶錯誤代碼）。竄改清單的測試**一律重新計算 content_sha256**，
    證明內容指紋不是唯一防線，拒絕來自與原始資料、flag 檔與重新稽核的交叉驗證。
    本類測試的根目錄都用**真實 box 稽核 v1**（make_root(..., real_audit=True)），不使用測試的宣告稽核。
T42 唯一有效比賽入口 get_valid_f1_games：F1 累計、league_games_asof、league_games_asof_excl_team、100 場門檻、
    f1_prior_source 全部得到相同結果；ERROR／缺 box／回合數無效的排除一致；LOTO 一致；99 場不過、100 場過。
"""
import csv
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from nba_quant import audit_coverage, box_audit, config, data_access as DA, store
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


def edit_manifest(d, fn, s=2020, recompute=True):
    """竄改清單。recompute=True（預設）：同時重算 content_sha256，模擬「知道指紋算法的人」改清單。"""
    p = manifest_path(d, s)
    m = store.read_json(p)
    fn(m)
    if recompute and 'content_sha256' in m:
        m['content_sha256'] = audit_coverage.content_sha(m)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(m, fh)


def code_copy(d, mutate=None, crlf=False, drop=None):
    """把三個稽核程式檔複製到暫存目錄（不動 repo 內的檔案），可修改其中一個、轉成 CRLF 或刪掉一個。"""
    root = os.path.join(d, 'code')
    for rel in audit_coverage.AUDIT_CODE_FILES:
        dst = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if rel == drop:
            continue
        data = open(os.path.join(audit_coverage.CODE_ROOT, *rel.split('/')), 'rb').read()
        if rel == mutate:
            data += b'\n# changed\n'
        if crlf:
            data = data.replace(b'\n', b'\r\n')
        open(dst, 'wb').write(data)
    return root


class AuditFailClosed(unittest.TestCase):
    """T41：任何完整性檢查不通過 → AuditIntegrityError，F1 不得計算。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        make_root(self.d, G, real_audit=True)                          # flag 檔 = 真實稽核結果
        self.p = audit_coverage.paths(2020, self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def refused(self, code):
        with self.assertRaises(AuditIntegrityError) as cm:
            audit_coverage.verify(2020, self.d)
        self.assertEqual(cm.exception.code, code, str(cm.exception))
        for call in (lambda: DA.DataAccess('feature_computation', root=self.d).box_audit_flags(2020),
                     lambda: f1.get_valid_f1_games(DA.DataAccess('feature_computation', root=self.d), 2020),
                     lambda: f1.compute(2020, root=self.d)):
            with self.assertRaises(AuditIntegrityError) as cm:
                call()
            self.assertEqual(cm.exception.code, code)

    # ---- 正常 ----
    def test_09_reaudit_matches_flags_passes(self):
        """正常：重新稽核與 flag 檔完全一致 → 通過；回傳的 flag 就是真實稽核結果。"""
        m, flags = audit_coverage.verify_and_load(2020, self.d)
        self.assertEqual(flags, box_audit.audit_season(2020, self.d)[0])
        self.assertEqual(m['audit_code_sha256'], audit_coverage._code_sha())
        self.assertEqual(m['expected_game_ids'], ['g1', 'g2', 'g3'])
        self.assertTrue(f1.compute(2020, root=self.d).rows)

    # ---- 檔案缺失與格式 ----
    def test_01_flag_file_missing_refused(self):
        os.remove(self.p['flags'])
        self.refused('flags_missing')

    def test_02_empty_flag_file_without_manifest_refused(self):
        store.write_jsonl_gz(self.p['flags'], [])
        os.remove(self.p['manifest'])
        self.refused('manifest_missing')

    def test_10a_manifest_malformed_json(self):
        open(self.p['manifest'], 'w').write('{"season": 2020,')
        self.refused('manifest_unreadable')

    def test_10b_manifest_empty_file(self):
        open(self.p['manifest'], 'w').write('')
        self.refused('manifest_unreadable')

    def test_10c_manifest_not_object(self):
        open(self.p['manifest'], 'w').write('[1, 2]')
        self.refused('manifest_invalid')

    def test_10d_raw_teambox_missing(self):
        os.remove(self.p['teambox'])
        self.refused('raw_missing')

    def test_10e_raw_games_missing(self):
        os.remove(self.p['games'])
        self.refused('raw_missing')

    def test_10f_raw_corrupted(self):
        open(self.p['teambox'], 'wb').write(b'not gzip')
        with self.assertRaises(AuditIntegrityError) as cm:
            audit_coverage.verify(2020, self.d)
        self.assertEqual(cm.exception.code, 'raw_unreadable')

    def test_10g_unknown_or_mistyped_field_with_recomputed_content(self):
        edit_manifest(self.d, lambda m: m.update(note='x'))
        self.refused('manifest_invalid')
        seal(self.d, real_audit=True)
        edit_manifest(self.d, lambda m: m.update(audited_game_count='3'))
        self.refused('manifest_invalid')

    # ---- 稽核版本 ----
    def test_08_manifest_version_changed_refused(self):
        edit_manifest(self.d, lambda m: m.update(audit_version='box_quality_v0'))
        self.refused('version')

    def test_08e_required_version_bumped_old_manifest_refused(self):
        with mock.patch.object(audit_coverage, 'REQUIRED_AUDIT_VERSION', 'box_quality_v2'):
            self.refused('version')

    # ---- 稽核程式指紋 ----
    def test_code_fingerprint_covers_all_audit_files(self):
        m = store.read_json(self.p['manifest'])
        self.assertEqual(sorted(m['audit_code_files']),
                         ['nba_quant/audit_coverage.py', 'nba_quant/box_audit.py', 'nba_quant/game_class.py',
                          'nba_quant/integrity.py', 'nba_quant/store.py'])
        self.assertEqual(m['audit_code_sha256'], audit_coverage.combine_code_sha(m['audit_code_files']))

    def test_code_01_03_any_code_file_changed_refused(self):
        """box_audit.py、audit_coverage.py、store.py、integrity.py 任何一個實際內容改變（版本字串不變）→ 舊清單拒絕。"""
        for rel in audit_coverage.AUDIT_CODE_FILES:
            with self.subTest(rel), tempfile.TemporaryDirectory() as c:
                with mock.patch.object(audit_coverage, 'CODE_ROOT', code_copy(c, mutate=rel)):
                    self.refused('audit_code_mismatch')

    def test_code_04_crlf_and_lf_checkout_same_fingerprint(self):
        with tempfile.TemporaryDirectory() as c:
            root = code_copy(c, crlf=True)
            self.assertTrue(b'\r\n' in open(os.path.join(root, 'nba_quant', 'store.py'), 'rb').read())
            self.assertEqual(audit_coverage.code_files(root), audit_coverage.code_files())
            with mock.patch.object(audit_coverage, 'CODE_ROOT', root):
                audit_coverage.verify(2020, self.d)                          # CRLF checkout 不誤拒

    def test_code_05_missing_audit_code_sha256_refused(self):
        edit_manifest(self.d, lambda m: m.pop('audit_code_sha256'))
        self.refused('audit_code_mismatch')

    def test_code_06_missing_single_file_fingerprint_refused(self):
        def drop(m):
            del m['audit_code_files']['nba_quant/store.py']
            m['audit_code_sha256'] = audit_coverage.combine_code_sha(m['audit_code_files'])   # 組合指紋也重算
        edit_manifest(self.d, drop)
        self.refused('audit_code_mismatch')

    def test_code_06b_forged_file_fingerprint_refused(self):
        def forge(m):
            m['audit_code_files']['nba_quant/box_audit.py'] = '0' * 64
            m['audit_code_sha256'] = audit_coverage.combine_code_sha(m['audit_code_files'])
        edit_manifest(self.d, forge)
        self.refused('audit_code_mismatch')

    def test_code_06c_combined_fingerprint_inconsistent_refused(self):
        edit_manifest(self.d, lambda m: m.update(audit_code_sha256='0' * 64))
        self.refused('audit_code_mismatch')

    def test_code_06d_code_file_missing_on_disk_refused(self):
        with tempfile.TemporaryDirectory() as c:
            with mock.patch.object(audit_coverage, 'CODE_ROOT', code_copy(c, drop='nba_quant/store.py')):
                self.refused('audit_code_mismatch')

    # ---- 內容指紋 ----
    def test_content_hash_not_updated_refused(self):
        edit_manifest(self.d, lambda m: m.update(audited_team_box_count=99), recompute=False)
        self.refused('content_hash')

    def test_content_hash_missing_refused(self):
        edit_manifest(self.d, lambda m: m.pop('content_sha256'), recompute=False)
        self.refused('content_hash')

    def test_content_fingerprint_independent_of_timestamp(self):
        """相同原始資料、flag、稽核程式：不同時間重建 → 內容指紋相同；只有 audit_timestamp 不同。"""
        a = audit_coverage.build_manifest(2020, self.d, now='2026-01-01T00:00:00+00:00')
        b = audit_coverage.build_manifest(2020, self.d, now='2026-02-01T00:00:00+00:00')
        self.assertEqual(a['content_sha256'], b['content_sha256'])
        self.assertEqual({k for k in a if a[k] != b[k]}, {'audit_timestamp'})
        audit_coverage.verify(2020, self.d)

    def test_manifest_file_is_deterministic(self):
        a = open(self.p['manifest'], 'rb').read()
        audit_coverage.build_manifest(2020, self.d, now='synthetic')
        self.assertEqual(open(self.p['manifest'], 'rb').read(), a)

    # ---- 7. 重算內容指紋仍被原始資料交叉驗證擋下 ----
    def test_07_important_fields_with_recomputed_content_refused(self):
        def drop_both(m):
            for k in ('expected', 'audited'):
                m[f'{k}_game_ids'] = m[f'{k}_game_ids'][1:]
                m[f'{k}_game_count'] -= 1
        cases = [
            ('raw_boxscore_file_hash', lambda m: m.update(raw_boxscore_file_hash='0' * 64), 'raw_boxscore_hash'),
            ('raw_games_file_hash', lambda m: m.update(raw_games_file_hash='0' * 64), 'raw_games_hash'),
            ('flags_file_hash', lambda m: m.update(flags_file_hash='0' * 64), 'flags_hash'),
            ('audited_team_box_count', lambda m: m.update(audited_team_box_count=m['audited_team_box_count'] - 1),
             'scope_mismatch'),
            ('raw_boxscore_file', lambda m: m.update(raw_boxscore_file='data/raw/espn/2019/teambox.jsonl.gz'),
             'raw_file_mismatch'),
            ('season', lambda m: m.update(season=2019), 'season'),
            ('ids both lists', drop_both, 'scope_mismatch'),
        ]
        for name, fn, code in cases:
            with self.subTest(name):
                seal(self.d, real_audit=True)
                edit_manifest(self.d, fn)
                self.refused(code)

    # ---- ID 清單 ----
    def test_03_one_audited_id_missing_refused(self):
        def drop(m):
            m['audited_game_ids'] = m['audited_game_ids'][1:]
            m['audited_game_count'] -= 1
        edit_manifest(self.d, drop)
        self.refused('not_all_audited')

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

    # ---- 原始資料變動 ----
    def test_06_one_raw_box_field_changed_refused(self):
        bx = list(store.read_jsonl_gz(self.p['teambox']))
        bx[0]['tov'] += 1
        store.write_jsonl_gz(self.p['teambox'], bx)
        self.refused('raw_boxscore_hash')

    def test_07_new_game_invalidates_old_manifest(self):
        bx = list(store.read_jsonl_gz(self.p['teambox']))
        gs = list(store.read_jsonl_gz(self.p['games']))
        bx += [dict(bx[0], game_id='g9'), dict(bx[1], game_id='g9')]
        gs.append(dict(gs[0], game_id='g9', start_utc='2020-01-08T00:30:00Z'))
        store.write_jsonl_gz(self.p['teambox'], bx)
        store.write_jsonl_gz(self.p['games'], gs)
        cls = os.path.join(self.d, 'data', 'reference', 'game_classification.csv')   # 回補時分類表也會跟著重建
        with open(cls, encoding='utf-8', newline='') as fh:
            rows = list(csv.DictReader(fh))
        rows.append(dict(rows[0], game_id='g9', start_utc='2020-01-08T00:30:00Z'))
        with open(cls, 'w', encoding='utf-8', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        self.refused('raw_boxscore_hash')
        # 只把指紋改成新檔的（並重算內容指紋），不重新稽核：新比賽不在清單內 → 拒絕
        edit_manifest(self.d, lambda m: m.update(raw_boxscore_file_hash=store.sha256_file(self.p['teambox']),
                                                 raw_games_file_hash=store.sha256_file(self.p['games'])))
        self.refused('scope_mismatch')

    # ---- flag 與重新稽核 ----
    def test_08_verify_flags_false_inconsistent_flags_refused(self):
        """8. verify_flags=False 可以寫出清單，但 flag 與實際稽核不一致 → 正式 verify 拒絕（stale_audit）。"""
        fake = box_audit.audit_season(2020, self.d)[0] + [
            {'game_id': 'g1', 'team': 'A', 'source': 'espn', 'level': 'record', 'check': 'zero_value',
             'severity': 'error', 'detail': 'tov'}]
        store.write_jsonl_gz(self.p['flags'], fake)
        audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='t')
        self.refused('stale_audit')

    def test_08b_flags_missing_a_record_or_field_changed_refused(self):
        real = box_audit.audit_season(2020, self.d)[0]
        self.assertTrue(real, '測試資料需要至少一筆真實稽核 flag')
        variants = {'drop_record': real[1:],
                    'severity': [dict(real[0], severity='warning' if real[0]['severity'] == 'error' else 'error')] + real[1:],
                    'team': [dict(real[0], team='Z')] + real[1:],
                    'check': [dict(real[0], check='other')] + real[1:],
                    'detail': [dict(real[0], detail='x')] + real[1:]}
        for name, flags in variants.items():
            with self.subTest(name):
                store.write_jsonl_gz(self.p['flags'], flags)
                audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='t')
                with self.assertRaises(AuditIntegrityError) as cm:
                    audit_coverage.verify(2020, self.d)
                self.assertIn(cm.exception.code, ('stale_audit', 'flag_outside_scope'))

    def test_08c_flag_outside_audited_scope_refused(self):
        store.write_jsonl_gz(self.p['flags'], [{'game_id': 'nope', 'team': 'B', 'check': 'x', 'detail': '',
                                                'severity': 'error'}])
        audit_coverage.build_manifest(2020, self.d, verify_flags=False, now='t')
        self.refused('flag_outside_scope')

    def test_08d_flag_file_changed_after_manifest_refused(self):
        store.write_jsonl_gz(self.p['flags'], [])
        self.refused('flags_hash')

    def test_stale_audit_refused_when_building(self):
        bx = list(store.read_jsonl_gz(self.p['teambox']))
        bx[0]['tov'] = 0                                                # 會被 box 稽核 v1 標記的值
        store.write_jsonl_gz(self.p['teambox'], bx)
        with self.assertRaises(AuditIntegrityError) as cm:
            audit_coverage.build_manifest(2020, self.d)
        self.assertEqual(cm.exception.code, 'stale_audit')

    def test_reaudit_uses_same_bytes_no_second_raw_read(self):
        """重新稽核使用計算指紋的同一份已讀取位元組：verify 期間不呼叫從檔案讀範圍的 audit_scope。"""
        with mock.patch.object(box_audit, 'audit_scope', side_effect=AssertionError('不應重讀原始檔')):
            audit_coverage.verify(2020, self.d)


class NoRawDataException(unittest.TestCase):
    """11. 2013-14 空資料例外：只有「賽程為空」且「原始 games、teambox 檔都不存在」才成立。"""

    def test_positive_season_without_any_raw_data(self):
        """只有 allowlist 的 2013-14（season key 2014）可以完全沒有資料；其餘見 test_source_isolation.NoDataAllowlist。"""
        with tempfile.TemporaryDirectory() as d:
            make_root(d, [(x[0], 2015, x[2].replace('2020', '2015'), *x[3:]) for x in G], real_audit=True, empty_prev=False)
            da = DA.DataAccess('feature_computation', root=d)
            h = f1.get_valid_f1_games(da, 2014)
            self.assertEqual((h.status, h.game_ids), ('no_raw_data', []))
            self.assertFalse([x for x in da.log if x['call'] == 'box_audit_flags'])
            with self.assertRaises(AuditIntegrityError) as cm:
                f1.get_valid_f1_games(da, 2013)
            self.assertEqual(cm.exception.code, 'season_no_data')

    def test_negative_raw_exists_schedule_empty_still_audited(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, G, real_audit=True)
            da = DA.DataAccess('feature_computation', root=d)
            h = f1.get_valid_f1_games(da, 2020, as_of='2020-01-01T00:00:00Z')    # 賽程為空，但原始檔存在
            self.assertEqual((h.status, h.game_ids), ('available', []))
            self.assertTrue([x for x in da.log if x['call'] == 'box_audit_flags' and x['coverage_verified']])
            os.remove(audit_coverage.paths(2020, d)['manifest'])
            with self.assertRaises(AuditIntegrityError) as cm:
                f1.get_valid_f1_games(DA.DataAccess('feature_computation', root=d), 2020, as_of='2020-01-01T00:00:00Z')
            self.assertEqual(cm.exception.code, 'manifest_missing')

    def test_negative_only_one_raw_file_missing(self):
        for missing in ('teambox', 'games'):
            with self.subTest(missing), tempfile.TemporaryDirectory() as d:
                make_root(d, G, real_audit=True)
                os.remove(audit_coverage.paths(2020, d)[missing])
                for as_of in (None, '2020-01-01T00:00:00Z'):            # 有賽程／賽程為空都不得走例外
                    with self.assertRaises(AuditIntegrityError) as cm:
                        f1.get_valid_f1_games(DA.DataAccess('feature_computation', root=d), 2020, as_of)
                    self.assertEqual(cm.exception.code, 'raw_missing')

    def test_negative_both_raw_missing_but_schedule_present(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, G, real_audit=True)
            for k in ('teambox', 'games'):
                os.remove(audit_coverage.paths(2020, d)[k])
            with self.assertRaises(AuditIntegrityError) as cm:
                f1.get_valid_f1_games(DA.DataAccess('feature_computation', root=d), 2020)
            self.assertEqual(cm.exception.code, 'raw_missing')


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


class NoTestHooksInProduction(unittest.TestCase):
    def test_declared_audit_exists_only_in_tests(self):
        """宣告稽核（tests/conftest.py）只存在於測試；正式程式沒有任何略過重新稽核的開關。"""
        pkg = os.path.join(ROOT, 'nba_quant')
        for dp, _, fs in os.walk(pkg):
            for f in fs:
                if f.endswith('.py'):
                    src = open(os.path.join(dp, f), encoding='utf-8').read()
                    self.assertNotIn('synthetic_audit', src, f)


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
            m, flags = audit_coverage.verify_and_load(s, ROOT)             # 含讀取時重新稽核
            self.assertEqual(m['audit_code_sha256'], audit_coverage._code_sha())
            self.assertEqual(sorted(m['audit_code_files']), sorted(audit_coverage.AUDIT_CODE_FILES))
            self.assertIsNone(__import__('conftest').declared(s, ROOT))   # 真實資料不使用宣告稽核
            self.assertEqual(flags, list(store.read_jsonl_gz(audit_coverage.paths(s, ROOT)['flags'])))
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
