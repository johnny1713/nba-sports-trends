"""資料快照完整性：分類表一致性、快照不可變、預期指紋保存在快照外部（使用者 2026-11-21 核准）。T44。

每一項都走實際資料流（DataAccess.verified_snapshot → F1 get_valid_f1_games／compute），不只看指紋有沒有變。
"""
import csv
import os
import tempfile
import unittest
from types import MappingProxyType

from nba_quant import audit_coverage, data_access as DA, game_class, integrity
from nba_quant.integrity import AuditIntegrityError, Snapshot
from nba_quant.features import f1

from test_f1 import make_root

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
G = [('g1', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
     ('g2', 2020, '2020-01-04T00:30:00Z', 'C', 'D', 100, 90, 'CUP_GROUP'),
     ('g3', 2020, '2020-01-06T00:30:00Z', 'A', 'C', 104, 96, 'CUP_FINAL'),
     ('g4', 2020, '2020-01-08T00:30:00Z', 'B', 'D', 98, 97, 'POSTSEASON'),
     ('p1', 2020, '2020-01-07T00:30:00Z', 'B', 'D', 101, 99, 'PLAY_IN')]
CLS = ('data', 'reference', 'game_classification.csv')


def fc(d):
    return DA.DataAccess('feature_computation', root=d)


def edit_cls(d, fn):
    p = os.path.join(d, *CLS)
    with open(p, encoding='utf-8', newline='') as fh:
        rows = list(csv.DictReader(fh))
    rows = fn(rows)
    with open(p, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=game_class.FIELDS)
        w.writeheader()
        w.writerows(rows)


def setf(gid, **kw):
    return lambda rows: [dict(r, **kw) if r['game_id'] == gid else r for r in rows]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        make_root(self.d, G)

    def tearDown(self):
        self.tmp.cleanup()

    def refused(self, code):
        """F1 的資料流整個拒絕（批次計算、有效比賽、先驗來源）。"""
        for call in (lambda: f1.compute(2020, root=self.d),
                     lambda: f1.get_valid_f1_games(fc(self.d), 2020),
                     lambda: fc(self.d).f1_prior_source('A', '2020-01-06T00:30:00Z')):
            with self.assertRaises(AuditIntegrityError) as cm:
                call()
            self.assertEqual(cm.exception.code, code, str(cm.exception))


class ClassificationConsistency(Base):
    def test_04_consistent_classification_passes(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        self.assertEqual(sorted(snap.classifications), ['g1', 'g2', 'g3', 'g4', 'p1'])
        self.assertEqual(snap.classifications['g3']['game_type'], 'CUP_FINAL')
        self.assertEqual(sorted(f1.get_valid_f1_games(da, 2020).game_ids), ['g1', 'g2', 'g3'])   # 例行賽＋盃賽；不含季後賽、附加賽
        self.assertTrue(f1.compute(2020, da=da).rows)

    def test_01_use_team_stats_changed_refused(self):
        edit_cls(self.d, setf('g1', use_team_stats='False'))
        self.refused('classification_mismatch')
        edit_cls(self.d, setf('g1', use_team_stats='True'))
        edit_cls(self.d, setf('g4', use_team_stats='True'))           # 季後賽偷偷納入 F1
        self.refused('classification_mismatch')

    def test_02_game_type_or_other_fields_changed_refused(self):
        changes = {'game_type': 'REGULAR_SEASON', 'counts_for_standings': 'True', 'use_fatigue': 'False',
                   'use_elo': 'False', 'train_sample': 'True', 'eval_group': 'playoffs', 'espn_season_type': '2',
                   'start_utc': '2020-01-03T00:30:00Z', 'home': 'X', 'away': 'Y', 'status': 'scheduled',
                   'source_file': 'other', 'basis': 'x'}
        for k, v in changes.items():
            with self.subTest(field=k), tempfile.TemporaryDirectory() as d:
                make_root(d, G)
                self.assertNotEqual(fc(d)._classification()['g4'][k], v, k)      # 確實是一個改變
                edit_cls(d, setf('g4', **{k: v}))
                with self.assertRaises(AuditIntegrityError) as cm:
                    f1.compute(2020, root=d)
                self.assertEqual(cm.exception.code, 'classification_mismatch', k)

    def test_03_missing_extra_duplicate_rows_refused(self):
        edit_cls(self.d, lambda rows: [r for r in rows if r['game_id'] != 'g2'])
        self.refused('classification_missing')
        make_root(self.d, G)
        edit_cls(self.d, lambda rows: rows + [dict(rows[0], game_id='zz')])
        self.refused('classification_extra')
        make_root(self.d, G)
        edit_cls(self.d, lambda rows: rows + [dict(rows[0], use_team_stats='False')])   # 同一場兩列，順序不同結果不同
        self.refused('classification_duplicate')
        make_root(self.d, G)
        edit_cls(self.d, setf('g1', season='2019'))                    # 球季欄位錯：2020 缺、2019 多
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.compute(2020, root=self.d)
        self.assertEqual(cm.exception.code, 'classification_missing')

    def test_12_classification_change_is_rejected_by_consistency_check(self):
        """分類表改變：不是只讓指紋改變，而是在建立快照時就被一致性檢查拒絕；F1 拿不到任何結果。"""
        before = f1.compute(2020, root=self.d).rows
        edit_cls(self.d, setf('g2', game_type='CUP_QUARTERFINAL', basis='x'))
        with self.assertRaises(AuditIntegrityError):
            f1.compute(2020, root=self.d)
        make_root(self.d, G)
        self.assertEqual(f1.compute(2020, root=self.d).rows, before)

    def test_games_use_snapshot_classification_not_dataaccess_cache(self):
        """快照路徑用快照內的分類：即使 DataAccess 的分類快取在驗證後被換掉，F1 的結果不變。"""
        da = fc(self.d)
        before = f1.get_valid_f1_games(da, 2020).game_ids
        da._cls = {k: dict(v, use_team_stats='False') for k, v in da._classification().items()}
        self.assertEqual(f1.get_valid_f1_games(da, 2020).game_ids, before)

    def test_classification_rules_in_code_fingerprint(self):
        self.assertIn('nba_quant/game_class.py', audit_coverage.AUDIT_CODE_FILES)


class SnapshotImmutability(Base):
    def test_07_nested_data_cannot_be_modified(self):
        snap = fc(self.d).verified_snapshot(2020)
        attempts = [lambda: snap.games[0].__setitem__('home_pts', 1),
                    lambda: snap.boxes.__setitem__(('g1', 'A'), {}),
                    lambda: snap.boxes[('g1', 'A')].__setitem__('pts', 1),
                    lambda: snap.classifications['g1'].__setitem__('use_team_stats', 'False'),
                    lambda: snap.classifications.__setitem__('zz', {}),
                    lambda: snap.games.append({})]
        if snap.flags:
            attempts.append(lambda: snap.flags[0].__setitem__('severity', 'warning'))
        for a in attempts:
            with self.assertRaises((TypeError, AttributeError)):
                a()
        for name in ('season', 'status', 'games', 'boxes', 'flags', 'classifications', 'manifest'):
            with self.assertRaises(AttributeError):                       # frozen dataclass
                setattr(snap, name, None)
        self.assertIsInstance(snap.boxes, MappingProxyType)
        self.assertIsInstance(snap.games, tuple)

    def test_nested_lists_are_frozen(self):
        """真實 box 有巢狀 list（球員明細）、賽程有 notes：凍結後是 tuple。"""
        s = Snapshot.build(2020, 'verified', [{'game_id': 'x', 'notes': ['a', {'b': [1]}]}])
        self.assertIsInstance(s.games[0]['notes'], tuple)
        with self.assertRaises(TypeError):
            s.games[0]['notes'][1]['b'] = 2

    def test_08_no_public_reseal_method(self):
        for name in ('seal', 'reseal', 'digest', 'check'):
            self.assertFalse(hasattr(Snapshot, name), name)
        snap = fc(self.d).verified_snapshot(2020)
        self.assertNotIn('digest', vars(type(snap)).get('__dataclass_fields__', {}))

    def test_05_status_changed_refused(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2019)                               # 2019-20 的上一季（合成的已稽核空球季）
        object.__setattr__(snap, 'status', 'no_raw_data')
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.compute(2020, da=da)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')

    def test_05b_status_flip_on_real_previous_season_refused(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        object.__setattr__(snap, 'status', 'no_raw_data')
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.get_valid_f1_games(da, 2020)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')

    def test_06_season_changed_refused(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        object.__setattr__(snap, 'season', 2021)
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.get_valid_f1_games(da, 2020)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')

    def test_09_modify_then_reseal_cannot_pass(self):
        """以底層手段改資料、再自己算一次指紋：預期指紋保存在 DataAccess 內，無從更新 → 拒絕。"""
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        box = dict(snap.boxes[('g1', 'A')], pts=999)
        object.__setattr__(snap, 'boxes', MappingProxyType({**snap.boxes, ('g1', 'A'): MappingProxyType(box)}))
        snap.content_digest()                                           # 呼叫端能算新指紋，但沒有地方可以寫入
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.get_valid_f1_games(da, 2020)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')
        # 自己組一個「看起來一樣」的快照交給 DataAccess：不是驗證流程產生的 → 拒絕
        fake = Snapshot.build(2020, 'verified', snap.games, snap.boxes, snap.flags, snap.classifications, snap.manifest)
        with self.assertRaises(AuditIntegrityError) as cm:
            da.games(2020, 'use_team_stats', snapshot=fake)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')

    def test_09b_attribute_replaced_with_identical_content_still_checked(self):
        """欄位物件被換掉（即使內容相同）也拒絕：驗證時記錄的物件身分不同。"""
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        object.__setattr__(snap, 'games', tuple(list(snap.games)))          # 新的 tuple 物件、內容相同
        with self.assertRaises(AuditIntegrityError):
            f1.get_valid_f1_games(da, 2020)

    def test_10_box_audit_flags_return_is_independent_copy(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        da2 = fc(self.d)
        out = da2.box_audit_flags(2020)
        if not out:                                                      # 合成資料沒有 flag：注入一筆宣告的稽核結果
            from test_f1 import seal
            seal(self.d, {2020: [{'game_id': 'g1', 'team': 'A', 'check': 'x', 'severity': 'warning', 'detail': '',
                                  'level': 'record', 'source': 'espn'}]})
            da = fc(self.d)
            snap = da.verified_snapshot(2020)
            out = da.box_audit_flags(2020)
        before = f1.get_valid_f1_games(da, 2020).warnings
        for v in out.values():
            for f in v:
                f['severity'] = 'error'                                  # 呼叫端改自己的複本
        self.assertEqual(f1.get_valid_f1_games(da, 2020).warnings, before)   # 快照與 F1 結果不受影響
        self.assertTrue(all(f['severity'] != 'error' for f in snap.flags))
        da.check_snapshot(snap)

    def test_returned_games_boxes_are_copies(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        gs = da.games(2020, 'use_team_stats', snapshot=snap)
        bx = da.team_boxes(2020, 'use_team_stats', ['pts'], snapshot=snap)
        gs[0]['home'] = 'ZZ'
        bx[0]['pts'] = 0
        da.check_snapshot(snap)
        self.assertNotEqual(da.games(2020, 'use_team_stats', snapshot=snap)[0]['home'], 'ZZ')

    def test_11_digest_deterministic(self):
        a, b = fc(self.d).verified_snapshot(2020), fc(self.d).verified_snapshot(2020)
        self.assertIsNot(a, b)
        self.assertEqual(a.content_digest(), b.content_digest())
        self.assertEqual(f1.compute(2020, root=self.d).rows, f1.compute(2020, root=self.d).rows)

    def test_digest_covers_all_numeric_inputs(self):
        """season、status、games、boxes、flags、classifications 任一改變 → 指紋改變；manifest 不在指紋內（metadata）。"""
        s = fc(self.d).verified_snapshot(2020)
        base = s.content_digest()
        kw = dict(season=s.season, status=s.status, games=s.games, boxes=s.boxes, flags=s.flags,
                  classifications=s.classifications, manifest=s.manifest)
        variants = {'season': 2021, 'status': 'no_raw_data', 'games': s.games[1:],
                    'boxes': {k: v for k, v in list(s.boxes.items())[1:]},
                    'flags': list(s.flags) + [{'game_id': 'g1'}],
                    'classifications': {k: v for k, v in list(s.classifications.items())[1:]}}
        for k, v in variants.items():
            self.assertNotEqual(Snapshot.build(**dict(kw, **{k: v})).content_digest(), base, k)
        self.assertEqual(Snapshot.build(**dict(kw, manifest={'x': 1})).content_digest(), base)


@unittest.skipUnless(HAS_DATA, 'no data')
class RealData(unittest.TestCase):
    def test_real_classification_matches_reclassification_all_seasons(self):
        """真實資料：2014-15～2022-23 的分類表與用同一份原始賽程重新分類的結果逐筆逐欄位相同。"""
        da = fc(ROOT)
        for s in range(2015, 2024):
            snap = da.verified_snapshot(s)
            self.assertEqual(len(snap.classifications), len(snap.games), s)
            self.assertEqual({k: dict(v) for k, v in snap.classifications.items()},
                             {k: dict(v) for k, v in da._classification().items() if v['season'] == str(s)}, s)

    def test_real_snapshot_is_immutable(self):
        snap = fc(ROOT).verified_snapshot(2021)
        b = next(iter(snap.boxes.values()))
        self.assertIsInstance(b.get('players', ()), tuple)
        with self.assertRaises(TypeError):
            b['pts'] = 0


if __name__ == '__main__':
    unittest.main()
