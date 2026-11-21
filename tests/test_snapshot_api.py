"""快照 API 權限（方案 B，使用者 2026-11-21 核准）。T45。

公開入口（verified_snapshot、check_snapshot、box_audit_flags、games(snapshot=…)、team_boxes(snapshot=…)）回傳前一律完整比對內容指紋；
F1 專用私有讀取（_f1_snapshot、_f1_games、_f1_team_boxes、_f1_flags）只做身分檢查，F1 每一條回傳路徑在回傳前完整比對。

「內容被改、身分不變」是身分檢查唯一抓不到的情況（快照深層不可變，一般操作做不到）。測試用
`tampered()` 在快照建立後讓內容指紋重算結果與預期值不同來模擬它：做了完整比對的入口必定拒絕，只做身分檢查的不會。
"""
import contextlib
import inspect
import os
import re
import tempfile
import unittest
from unittest import mock

from nba_quant import data_access as DA, integrity
from nba_quant.integrity import AuditIntegrityError
from nba_quant.features import f1

from test_f1 import make_root

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, 'nba_quant')
G = [('g1', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
     ('g2', 2020, '2020-01-04T00:30:00Z', 'C', 'D', 100, 90, 'REGULAR_SEASON'),
     ('g3', 2020, '2020-01-06T00:30:00Z', 'A', 'C', 104, 96, 'REGULAR_SEASON')]


def season_games(season):
    return [(x[0], season, x[2].replace('2020', str(season)), *x[3:]) for x in G]


@contextlib.contextmanager
def tampered():
    """模擬「快照內容在驗證後被改、物件身分不變」：重算的內容指紋不再等於預期值。"""
    with mock.patch.object(integrity.Snapshot, 'content_digest', lambda self: 'tampered'):
        yield


class Roots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = cls.tmp.name
        cls.r2020 = os.path.join(base, 'r2020')
        cls.r2015 = os.path.join(base, 'r2015')            # 2014-15：上一季 2013-14 為 allowlist 空資料
        cls.r2018 = os.path.join(base, 'r2018')            # 2017-18：F1 不可用
        make_root(cls.r2020, G)
        make_root(cls.r2015, season_games(2015), empty_prev=False)
        make_root(cls.r2018, season_games(2018))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def da(self, root, *warm):
        d = DA.DataAccess('feature_computation', root=root)
        for s in warm:                                      # 先建立快照（建立時計算預期指紋），之後才模擬竄改
            d._f1_snapshot(s)
        return d

    def refused(self, call):
        with self.assertRaises(AuditIntegrityError) as cm:
            call()
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')


class PublicApiFullCheck(Roots):
    """3～6：公開入口回傳前完整比對。"""

    def test_03_verified_snapshot(self):
        d = self.da(self.r2020, 2020)
        with tampered():
            self.refused(lambda: d.verified_snapshot(2020))

    def test_04_box_audit_flags(self):
        d = self.da(self.r2020, 2020)
        snap = d._f1_snapshot(2020)
        with tampered():
            self.refused(lambda: d.box_audit_flags(2020))
            self.refused(lambda: d.box_audit_flags(2020, snapshot=snap))

    def test_05_games_with_snapshot(self):
        d = self.da(self.r2020, 2020)
        snap = d._f1_snapshot(2020)
        with tampered():
            self.refused(lambda: d.games(2020, 'use_team_stats', snapshot=snap))
            d.games(2020, 'use_team_stats')                  # 不帶快照的一般路徑（F5／Elo）不受影響

    def test_06_team_boxes_with_snapshot(self):
        d = self.da(self.r2020, 2020)
        snap = d._f1_snapshot(2020)
        with tampered():
            self.refused(lambda: d.team_boxes(2020, 'use_team_stats', ['pts'], snapshot=snap))
            d.team_boxes(2020, 'use_team_stats', ['pts'])

    def test_check_snapshot_is_always_full(self):
        d = self.da(self.r2020, 2020)
        snap = d._f1_snapshot(2020)
        self.assertEqual(list(inspect.signature(d.check_snapshot).parameters), ['snapshot'])   # 沒有略過完整比對的參數
        with tampered():
            self.refused(lambda: d.check_snapshot(snap))

    def test_public_entries_have_no_skip_parameter(self):
        for name in ('verified_snapshot', 'check_snapshot', 'games', 'team_boxes', 'box_audit_flags', 'f1_prior_source'):
            params = inspect.signature(getattr(DA.DataAccess, name)).parameters
            self.assertFalse({'full', 'verify', 'check', 'skip_check', 'identity_only'} & set(params), name)

    def test_no_other_public_method_returns_snapshot_data(self):
        """其他公開方法都不接觸快照（除了 f1_prior_source，它轉給 F1，另有測試）。"""
        src = inspect.getsource(DA.DataAccess)
        public = [n for n in dir(DA.DataAccess) if not n.startswith('_')]
        touching = {n for n in public if callable(getattr(DA.DataAccess, n, None)) and
                    re.search(r'snapshot|_f1_|__verified', inspect.getsource(getattr(DA.DataAccess, n)))}
        self.assertEqual(touching, {'verified_snapshot', 'check_snapshot', 'games', 'team_boxes', 'box_audit_flags',
                                    'f1_prior_source'})
        self.assertIn('check_snapshot', src)


class PrivateF1ApiIdentityOnly(Roots):
    """7：F1 私有讀取只做身分檢查。"""

    def test_07_private_reads_skip_content_digest(self):
        d = self.da(self.r2020, 2020)
        snap = d._f1_snapshot(2020)
        with tampered():                                     # 內容指紋不符也照常回傳：只做身分檢查
            self.assertIs(d._f1_snapshot(2020), snap)
            self.assertTrue(d._f1_games(snap, 2020, 'use_team_stats'))
            self.assertTrue(d._f1_team_boxes(snap, 2020, 'use_team_stats', ['pts']))
            d._f1_flags(snap, 2020)

    def test_07b_private_reads_still_enforce_identity(self):
        d = self.da(self.r2020, 2020)
        snap = d._f1_snapshot(2020)
        other = DA.DataAccess('feature_computation', root=self.r2020)._f1_snapshot(2020)   # 別的實例驗證的快照
        for call in (lambda: d._f1_games(other, 2020, 'use_team_stats'),
                     lambda: d._f1_team_boxes(other, 2020, 'use_team_stats', ['pts']),
                     lambda: d._f1_flags(other, 2020),
                     lambda: d._f1_games(snap, 2019, 'use_team_stats')):
            self.refused(call)
        object.__setattr__(snap, 'games', tuple(list(snap.games)))
        self.refused(lambda: d._f1_snapshot(2020))

    def test_private_api_used_only_by_f1(self):
        for dp, _, fs in os.walk(PKG):
            for f in fs:
                p = os.path.join(dp, f)
                if not f.endswith('.py') or p.endswith(os.path.join('features', 'f1.py')) or f == 'data_access.py':
                    continue
                self.assertNotRegex(open(p, encoding='utf-8').read(), r'\._f1_(snapshot|games|team_boxes|flags)\(', p)


class F1ReturnPaths(Roots):
    """1、2、8：F1 每一條回傳路徑在回傳前完整比對；完整比對失敗就整個拒絕。"""

    def f1_entries(self):
        a20 = '2020-01-06T00:30:00Z'
        a15 = '2015-01-06T00:30:00Z'
        return [
            ('get_valid_f1_games 2020', self.r2020, (2020,), lambda d: f1.get_valid_f1_games(d, 2020)),
            ('get_valid_f1_games 2020 as_of+LOTO', self.r2020, (2020,), lambda d: f1.get_valid_f1_games(d, 2020, a20, 'A')),
            ('get_valid_f1_games 2014 (allowlist 空資料)', self.r2015, (2014,), lambda d: f1.get_valid_f1_games(d, 2014)),
            ('build_history 2020', self.r2020, (2020,), lambda d: f1.build_history(d, 2020)),
            ('season_totals 2020', self.r2020, (2020,), lambda d: f1.season_totals(d, 2020)),
            ('season_totals 2014', self.r2015, (2014,), lambda d: f1.season_totals(d, 2014)),
            ('prior_context 2020', self.r2020, (2019,), lambda d: f1.prior_context(d, 2020)),
            ('compute 2020', self.r2020, (2020, 2019), lambda d: f1.compute(2020, da=d)),
            ('compute 2015', self.r2015, (2015, 2014), lambda d: f1.compute(2015, da=d)),
            ('compute 2018 (F1 不可用)', self.r2018, (2018,), lambda d: f1.compute(2018, da=d)),
            ('compute_season 2020', self.r2020, (2020, 2019), lambda d: f1.compute_season(2020, da=d)),
            ('season_of 2020', self.r2020, (2020,), lambda d: f1.season_of(d, a20)),
            ('prior_source 2020', self.r2020, (2020, 2019), lambda d: f1.prior_source(d, 'A', a20)),
            ('prior_source 2015', self.r2015, (2015, 2014), lambda d: f1.prior_source(d, 'A', a15)),
            ('f1_reference 2020', self.r2020, (2020, 2019), lambda d: f1.f1_reference(d, 'A', a20)),
            ('DataAccess.f1_prior_source 2020', self.r2020, (2020, 2019), lambda d: d.f1_prior_source('A', a20)),
        ]

    def test_01_02_08_every_return_path_refuses_when_full_check_fails(self):
        for name, root, warm, call in self.f1_entries():
            with self.subTest(name):
                d = self.da(root, *warm)
                call(d)                                       # 正常情況可以回傳
                with tampered():
                    with self.assertRaises(AuditIntegrityError) as cm:
                        call(d)
                    self.assertEqual(cm.exception.code, 'snapshot_mismatch', name)

    def test_02_2017_18_isolated_path_loads_nothing(self):
        """get_valid_f1_games(2017-18) 依規則直接隔離：不載入快照、不讀任何 2017-18 資料，所以不需要比對。"""
        d = DA.DataAccess('feature_computation', root=self.r2018)
        with tampered():
            h = f1.get_valid_f1_games(d, 2018)
            self.assertEqual((h.status, h.rows), ('unavailable', []))
            self.assertEqual(f1.prior_source(d, 'A', '2018-01-06T00:30:00Z')['status'], 'unavailable')
        self.assertFalse([x for x in d.log if x.get('season') == 2018])

    def test_08_full_check_after_last_read_for_every_snapshot(self):
        """插樁記錄讀取與檢查順序：每個入口用到的每一季快照，最後一次讀取之後、回傳之前都有完整比對。"""
        events = []
        real = {n: getattr(DA.DataAccess, n) for n in ('check_snapshot', '_f1_snapshot', '_f1_games',
                                                         '_f1_team_boxes', '_f1_flags')}

        def spy(name):
            def f(self, *a, **k):
                r = real[name](self, *a, **k)
                season = a[0].season if name == 'check_snapshot' else (a[0] if name == '_f1_snapshot' else a[1])
                events.append(('full' if name == 'check_snapshot' else 'read', season))
                return r
            return f
        for name, root, warm, call in self.f1_entries():
            with self.subTest(name):
                d = self.da(root, *warm)
                events.clear()
                with mock.patch.multiple(DA.DataAccess, **{n: spy(n) for n in real}):
                    call(d)
                seasons = {s for kind, s in events if kind == 'read'}
                self.assertTrue(seasons, name)
                for s in seasons:
                    last = max(i for i, e in enumerate(events) if e == ('read', s))
                    self.assertIn(('full', s), events[last + 1:], f'{name}: {s} 最後一次讀取後沒有完整比對')

    def test_09_failure_mid_computation_returns_nothing(self):
        """計算中途（讀完 box 之後）內容被改 → 最後的完整比對失敗 → 整個計算拒絕，不回傳任何結果、不寫檔。"""
        d = self.da(self.r2020, 2020, 2019)
        real_tb = DA.DataAccess._f1_team_boxes
        patcher = mock.patch.object(integrity.Snapshot, 'content_digest', lambda self: 'tampered')

        def tb_then_tamper(self, *a, **k):
            out = real_tb(self, *a, **k)
            patcher.start()
            return out
        files_before = sorted(os.walk(self.r2020))
        result = None
        try:
            with mock.patch.object(DA.DataAccess, '_f1_team_boxes', tb_then_tamper):
                with self.assertRaises(AuditIntegrityError):
                    result = f1.compute(2020, da=d)
        finally:
            patcher.stop()
        self.assertIsNone(result)
        self.assertEqual(sorted(os.walk(self.r2020)), files_before)

    def test_10_full_check_count_is_bounded(self):
        """方案 B 的效能護欄：完整比對次數固定且少（每次約 0.1 秒），不隨讀取次數增加。"""
        counts = {}
        real = DA.DataAccess.check_snapshot

        def count(self, snapshot):
            counts[snapshot.season] = counts.get(snapshot.season, 0) + 1
            return real(self, snapshot)
        with mock.patch.object(DA.DataAccess, 'check_snapshot', count):
            for name, call, limit in (('get_valid', lambda d: f1.get_valid_f1_games(d, 2020), 1),
                                      ('compute', lambda d: f1.compute(2020, da=d), 4),
                                      ('prior_source', lambda d: f1.prior_source(d, 'A', '2020-01-06T00:30:00Z'), 2),
                                      ('f1_reference', lambda d: f1.f1_reference(d, 'A', '2020-01-06T00:30:00Z'), 2)):
                counts.clear()
                call(self.da(self.r2020, 2020, 2019))
                self.assertLessEqual(sum(counts.values()), limit, (name, counts))


if __name__ == '__main__':
    unittest.main()
