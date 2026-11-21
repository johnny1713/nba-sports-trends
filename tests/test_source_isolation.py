"""資料來源隔離、唯一性、已驗證資料快照、2013-14 空資料 allowlist（使用者 2026-11-21 核准）。T43。

每一項都走實際資料流：DataAccess → audit_coverage.load_snapshot → F1（get_valid_f1_games／compute），
或 DataAccess.games／team_boxes（F5／Elo 的路徑），不只測單一函式的回傳值。
"""
import os
import tempfile
import unittest
from unittest import mock

from nba_quant import audit_coverage, box_audit, data_access as DA, store
from nba_quant.integrity import AuditIntegrityError
from nba_quant.features import f1

from test_f1 import make_root, seal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
G = [('g1', 2020, '2020-01-02T00:30:00Z', 'A', 'B', 110, 100, 'REGULAR_SEASON'),
     ('g2', 2020, '2020-01-04T00:30:00Z', 'C', 'D', 100, 90, 'REGULAR_SEASON'),
     ('g3', 2020, '2020-01-06T00:30:00Z', 'A', 'C', 104, 96, 'REGULAR_SEASON'),
     ('p1', 2020, '2020-01-08T00:30:00Z', 'B', 'D', 101, 99, 'PLAY_IN')]
G_REG = G[:3]                                                         # 只有例行賽（全部放在 espn）


def raw(d, kind, season=2020):
    """kind: games／teambox（espn）、pi_games／pi_box／pi_bbref（espn_playin）。"""
    base = {'games': ('espn', 'games.jsonl.gz'), 'teambox': ('espn', 'teambox.jsonl.gz'),
            'pi_games': ('espn_playin', 'games.jsonl.gz'), 'pi_box': ('espn_playin', 'teambox.jsonl.gz'),
            'pi_bbref': ('espn_playin', 'teambox_bbref.jsonl.gz')}[kind]
    return os.path.join(d, 'data', 'raw', base[0], str(season), base[1])


def read(p):
    return list(store.read_jsonl_gz(p)) if os.path.exists(p) else []


def build(d, **kw):
    """合成球季：三場例行賽在 espn，附加賽 p1 依規定放在 espn_playin（make_root 的佈局）。"""
    make_root(d, G, **kw)
    assert read(raw(d, 'pi_games')) and not [g for g in read(raw(d, 'games')) if g['game_id'] == 'p1']


def fc(d):
    return DA.DataAccess('feature_computation', root=d)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        build(self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def f1_refused(self, code):
        """F1 的兩個入口都拒絕，且錯誤代碼相同。"""
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.compute(2020, root=self.d)
        self.assertEqual(cm.exception.code, code, str(cm.exception))
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.get_valid_f1_games(fc(self.d), 2020)
        self.assertEqual(cm.exception.code, code)

    def elo_refused(self, code):
        """F5／Elo 走的一般 DataAccess 路徑也套用同一套隔離規則。"""
        for call in (lambda: fc(self.d).games(2020, 'use_elo'),
                     lambda: fc(self.d).team_boxes(2020, 'use_fatigue', ['pts'])):
            with self.assertRaises(AuditIntegrityError) as cm:
                call()
            self.assertEqual(cm.exception.code, code)


class PlayInStillServesAllowedUses(Base):
    def test_05_play_in_reaches_f5_elo_but_not_f1(self):
        da = fc(self.d)
        elo = {g['game_id'] for g in da.games(2020, 'use_elo')}
        fat = {g['game_id'] for g in da.games(2020, 'use_fatigue')}
        fat_boxes = {(b['game_id'], b['team']) for b in da.team_boxes(2020, 'use_fatigue', ['pts'])}
        self.assertEqual(elo, {'g1', 'g2', 'g3', 'p1'})
        self.assertEqual(fat, {'g1', 'g2', 'g3', 'p1'})
        self.assertIn(('p1', 'B'), fat_boxes)
        self.assertIn(('p1', 'D'), fat_boxes)
        h = f1.get_valid_f1_games(da, 2020)
        self.assertEqual(sorted(h.game_ids), ['g1', 'g2', 'g3'])                     # 用途矩陣不變：F1 不含附加賽
        snap = da.verified_snapshot(2020)
        self.assertIn(('p1', 'B'), snap.boxes)                                       # 快照含附加賽（來源 espn_playin）
        self.assertEqual(f1.compute(2020, da=da).excluded, [])


class InjectionRefused(Base):
    def test_01_regular_season_box_from_espn_playin_refused(self):
        """一般例行賽 box 從 espn_playin 進來（espn 那筆不存在，所以不是重複）→ source_mismatch。"""
        store.write_jsonl_gz(raw(self.d, 'teambox'), [b for b in read(raw(self.d, 'teambox'))
                                                      if (b['game_id'], b['team']) != ('g1', 'A')])
        seal(self.d)
        bx = read(raw(self.d, 'pi_box'))
        store.write_jsonl_gz(raw(self.d, 'pi_box'), bx + [dict(bx[0], game_id='g1', team='A', pts=150)])
        self.f1_refused('source_mismatch')
        self.elo_refused('source_mismatch')

    def test_02_espn_playin_box_duplicating_espn_box_refused(self):
        e = [b for b in read(raw(self.d, 'teambox')) if (b['game_id'], b['team']) == ('g1', 'A')][0]
        store.write_jsonl_gz(raw(self.d, 'pi_box'), read(raw(self.d, 'pi_box')) + [dict(e, pts=150)])
        self.f1_refused('duplicate_box')
        self.elo_refused('duplicate_box')

    def test_02b_bbref_and_espn_playin_box_overlap_refused(self):
        bx = read(raw(self.d, 'pi_box'))
        store.write_jsonl_gz(raw(self.d, 'pi_bbref'), [dict(bx[0], source='bbref')])
        self.f1_refused('duplicate_box')
        self.elo_refused('duplicate_box')

    def test_02c_regular_game_in_espn_playin_games_refused(self):
        g = [x for x in read(raw(self.d, 'games')) if x['game_id'] == 'g1'][0]
        store.write_jsonl_gz(raw(self.d, 'pi_games'), read(raw(self.d, 'pi_games')) + [g])
        self.f1_refused('duplicate_game')
        self.elo_refused('duplicate_game')

    def test_02d_play_in_game_served_from_espn_refused(self):
        """附加賽改放在 espn（不得由 espn 提供）→ source_mismatch。"""
        gs, bx = read(raw(self.d, 'pi_games')), read(raw(self.d, 'pi_box'))
        store.write_jsonl_gz(raw(self.d, 'games'), read(raw(self.d, 'games')) + gs)
        store.write_jsonl_gz(raw(self.d, 'teambox'), read(raw(self.d, 'teambox')) + bx)
        os.remove(raw(self.d, 'pi_games'))
        os.remove(raw(self.d, 'pi_box'))
        seal(self.d)                                                   # 清單照常可建（稽核本身沒有錯），合併時拒絕
        self.f1_refused('source_mismatch')
        self.elo_refused('source_mismatch')

    def test_02e_espn_playin_game_not_classified_play_in_refused(self):
        """espn_playin 出現分類表沒有或不是 PLAY_IN 的比賽 → source_mismatch。"""
        g = read(raw(self.d, 'pi_games'))[0]
        store.write_jsonl_gz(raw(self.d, 'pi_games'), read(raw(self.d, 'pi_games')) + [dict(g, game_id='zz')])
        self.f1_refused('source_mismatch')
        self.elo_refused('source_mismatch')


class Duplicates(Base):
    def test_03_duplicate_game_id_within_espn_refused(self):
        gs = read(raw(self.d, 'games'))
        store.write_jsonl_gz(raw(self.d, 'games'), gs + [dict(gs[0], home_pts=1)])
        self.f1_refused('duplicate_game')
        self.elo_refused('duplicate_game')
        with self.assertRaises(AuditIntegrityError) as cm:            # 稽核前就擋（產生清單、box 稽核本身）
            audit_coverage.build_manifest(2020, self.d)
        self.assertEqual(cm.exception.code, 'duplicate_game')
        with self.assertRaises(AuditIntegrityError):
            box_audit.audit_scope(2020, self.d)

    def test_03b_duplicate_game_id_within_espn_playin_refused(self):
        gs = read(raw(self.d, 'pi_games'))
        store.write_jsonl_gz(raw(self.d, 'pi_games'), gs + gs)
        self.f1_refused('duplicate_game')
        self.elo_refused('duplicate_game')

    def test_04_duplicate_team_box_within_espn_refused(self):
        bx = read(raw(self.d, 'teambox'))
        for order in ([bx[0], dict(bx[0], pts=1)], [dict(bx[0], pts=1), bx[0]]):   # 兩種順序都拒絕，不依順序取捨
            with self.subTest(first_pts=order[0]['pts']):
                store.write_jsonl_gz(raw(self.d, 'teambox'), bx + order[1:])
                self.f1_refused('duplicate_box')
                self.elo_refused('duplicate_box')
                with self.assertRaises(AuditIntegrityError) as cm:
                    audit_coverage.build_manifest(2020, self.d)
                self.assertEqual(cm.exception.code, 'duplicate_box')


class SnapshotIsTheOnlySource(Base):
    def test_06_snapshot_changed_after_verification_refused(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        with self.assertRaises(TypeError):                           # 快照深層不可變：無法原地竄改
            snap.boxes[('g1', 'A')]['pts'] = 999
        box = dict(snap.boxes[('g1', 'A')], pts=999)                 # 以底層手段整個替換欄位（繞過 frozen）
        object.__setattr__(snap, 'boxes', type(snap.boxes)({**snap.boxes, ('g1', 'A'): box}))
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.get_valid_f1_games(da, 2020)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')
        with self.assertRaises(AuditIntegrityError) as cm:
            f1.compute(2020, da=da)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')

    def test_06b_snapshot_of_other_season_refused(self):
        da = fc(self.d)
        snap = da.verified_snapshot(2020)
        with self.assertRaises(AuditIntegrityError) as cm:
            da.team_boxes(2019, 'use_team_stats', ['pts'], snapshot=snap)
        self.assertEqual(cm.exception.code, 'snapshot_mismatch')

    def test_06c_f1_boxes_equal_snapshot_boxes(self):
        """F1 實際使用的每一筆 box 都等於驗證快照裡的同一筆。"""
        da = fc(self.d)
        h = f1.get_valid_f1_games(da, 2020)
        snap = da.verified_snapshot(2020)
        for r in h.rows:
            b, o = snap.boxes[(r['game_id'], r['team'])], snap.boxes[(r['game_id'], r['opp'])]
            self.assertEqual((r['pf'], r['pa']), (b['pts'], o['pts']))
            self.assertAlmostEqual(r['poss'], (f1.team_poss(b) + f1.team_poss(o)) / 2)

    def test_07_no_reread_or_merge_after_verification(self):
        """F1 不呼叫一般讀檔／合併路徑；驗證後改動磁碟上的原始檔也換不掉已驗證的資料。"""
        boom = mock.Mock(side_effect=AssertionError('F1 不得重新讀取或合併原始檔'))
        with mock.patch.object(DA.DataAccess, '_merged', boom), \
                mock.patch.object(DA.DataAccess, '_raw_boxes', boom), mock.patch.object(DA.DataAccess, '_raw_games', boom):
            before = f1.compute(2020, root=self.d).rows
        da = fc(self.d)
        h1 = f1.get_valid_f1_games(da, 2020)
        store.write_jsonl_gz(raw(self.d, 'teambox'), [dict(b, pts=b['pts'] + 50) for b in read(raw(self.d, 'teambox'))])
        h2 = f1.get_valid_f1_games(da, 2020)                            # 同一個 DataAccess：仍是驗證過的快照
        self.assertEqual(h1.rows, h2.rows)
        self.assertEqual(f1.compute(2020, da=da).rows, before)
        with self.assertRaises(AuditIntegrityError) as cm:             # 新的 DataAccess 重新驗證 → 指紋不符
            f1.get_valid_f1_games(fc(self.d), 2020)
        self.assertEqual(cm.exception.code, 'raw_boxscore_hash')


class F1SourceStructure(unittest.TestCase):
    def test_every_f1_data_read_uses_the_verified_snapshot(self):
        """F1 只透過 DataAccess 的 F1 專用私有讀取（_f1_*）取資料，每個讀取都帶同一份快照；不呼叫公開讀取入口，
        也沒有其他讀檔路徑。"""
        import re
        src = open(f1.__file__, encoding='utf-8').read()
        self.assertFalse(re.findall(r'\bda\.(games|team_boxes|box_audit_flags|verified_snapshot)\(', src))
        lines = [l for l in src.splitlines() if re.search(r'\bda\._f1_(games|team_boxes|flags)\(', l)]
        self.assertGreaterEqual(len(lines), 7)
        for l in lines:
            self.assertRegex(l, r'_f1_\w+\(snap,', l)
        for banned in ('_raw_games', '_raw_boxes', '_merged', 'read_jsonl_gz', 'open('):
            self.assertNotIn(banned, src)


class NoDataAllowlist(unittest.TestCase):
    """2013-14（season key 2014）是唯一可以完全沒有資料的球季。"""

    def test_allowlist_value(self):
        self.assertEqual(audit_coverage.NO_DATA_SEASONS, (2014,))

    def test_08_2013_14_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, [(x[0], 2015, x[2].replace('2020', '2015'), *x[3:]) for x in G_REG], empty_prev=False)
            da = fc(d)
            self.assertFalse(os.path.exists(raw(d, 'games', 2014)))
            h = f1.get_valid_f1_games(da, 2014)
            self.assertEqual((h.status, h.game_ids), ('no_raw_data', []))
            rows = f1.compute(2015, da=da).rows                        # 2014-15：沒有上季，未滿 100 場為 missing
            self.assertTrue(rows)
            self.assertTrue(all(r['status'] == 'missing' for r in rows))

    def test_09_other_seasons_without_any_data_refused(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, G_REG, empty_prev=False)
            for s in (2019, 2013, 2010, 2030):
                with self.subTest(s):
                    with self.assertRaises(AuditIntegrityError) as cm:
                        f1.get_valid_f1_games(fc(d), s)
                    self.assertEqual(cm.exception.code, 'season_no_data')
            with self.assertRaises(AuditIntegrityError) as cm:          # 2019-20 的上一季整季不存在 → F1 不計算
                f1.compute(2020, root=d)
            self.assertEqual(cm.exception.code, 'season_no_data')

    def test_09b_whole_season_lost_including_classification_refused(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, G_REG + [(x[0] + 'n', 2021, x[2].replace('2020', '2021'), *x[3:]) for x in G_REG])
            os.remove(raw(d, 'games'))
            os.remove(raw(d, 'teambox'))
            os.remove(raw(d, 'pi_games')) if os.path.exists(raw(d, 'pi_games')) else None
            p = os.path.join(d, 'data', 'reference', 'game_classification.csv')
            lines = open(p, encoding='utf-8').read().splitlines()
            open(p, 'w', encoding='utf-8').write('\n'.join(l for l in lines if ',2020,' not in l) + '\n')
            with self.assertRaises(AuditIntegrityError) as cm:
                f1.compute(2021, root=d)                               # 上一季 2020 整季消失 → 拒絕，不當成「沒有上季」
            self.assertEqual(cm.exception.code, 'season_no_data')

    def test_10_raw_present_season_not_started_returns_verified_empty(self):
        with tempfile.TemporaryDirectory() as d:
            build(d)
            da = fc(d)
            h = f1.get_valid_f1_games(da, 2020, as_of='2020-01-01T00:00:00Z')
            self.assertEqual((h.status, h.game_ids), ('available', []))
            self.assertTrue([x for x in da.log if x['call'] == 'verified_snapshot' and x['coverage_verified']])

    def test_11_raw_missing_or_corrupted_refused(self):
        cases = [('teambox', 'missing', 'raw_missing'), ('games', 'missing', 'raw_missing'),
                 ('teambox', 'corrupt', 'raw_unreadable'), ('pi_box', 'corrupt', 'raw_unreadable'),
                 ('pi_games', 'corrupt', 'raw_unreadable')]
        for kind, how, code in cases:
            with self.subTest(kind=kind, how=how), tempfile.TemporaryDirectory() as d:
                build(d)
                if how == 'missing':
                    os.remove(raw(d, kind))
                else:
                    open(raw(d, kind), 'wb').write(b'not gzip')
                for as_of in (None, '2020-01-01T00:00:00Z'):
                    with self.assertRaises(AuditIntegrityError) as cm:
                        f1.get_valid_f1_games(fc(d), 2020, as_of)
                    self.assertEqual(cm.exception.code, code)

    def test_11b_2013_14_with_partial_data_is_fully_verified(self):
        """allowlist 球季只要有任何資料，就不再是例外，照常完整驗證。"""
        with tempfile.TemporaryDirectory() as d:
            make_root(d, [(x[0], 2015, x[2].replace('2020', '2015'), *x[3:]) for x in G_REG], empty_prev=False)
            store.write_jsonl_gz(raw(d, 'games', 2014), [])
            with self.assertRaises(AuditIntegrityError) as cm:
                f1.get_valid_f1_games(fc(d), 2014)
            self.assertIn(cm.exception.code, ('flags_missing', 'raw_missing'))


@unittest.skipUnless(HAS_DATA, 'no data')
class RealData(unittest.TestCase):
    def test_real_2013_14_allowed_others_refused(self):
        da = fc(ROOT)
        self.assertEqual(f1.get_valid_f1_games(da, 2014).status, 'no_raw_data')
        for s in (2013, 2010):
            with self.assertRaises(AuditIntegrityError) as cm:
                f1.get_valid_f1_games(da, s)
            self.assertEqual(cm.exception.code, 'season_no_data')
        first = min(int(x) for x in os.listdir(os.path.join(ROOT, 'data', 'raw', 'espn')) if x.isdigit())
        self.assertEqual(audit_coverage.NO_DATA_SEASONS, (first - 1,))      # 2013-14 = 第一個資料季的上一季

    def test_real_play_in_counts_unchanged_for_elo_and_f1_excludes(self):
        da = fc(ROOT)
        for s, n in ((2020, 1), (2021, 6), (2022, 6), (2023, 6)):
            pi = [g for g in da.games(s, 'use_elo') if g['game_type'] == 'PLAY_IN']
            self.assertEqual(len(pi), n, s)
            self.assertFalse(set(g['game_id'] for g in pi) & set(f1.get_valid_f1_games(da, s).game_ids))

    def test_real_snapshot_equals_general_path(self):
        """真實資料：快照路徑與一般 DataAccess 路徑（F5／Elo 使用）對同一季回傳相同的賽程與 box。"""
        for s in (2020, 2021, 2023):
            a, b = fc(ROOT), fc(ROOT)
            snap = a.verified_snapshot(s)
            for scope in ('use_team_stats', 'use_fatigue', 'use_elo'):
                self.assertEqual(a.games(s, scope, snapshot=snap), b.games(s, scope), (s, scope))
            self.assertEqual(a.team_boxes(s, 'use_fatigue', ['pts', 'fga'], snapshot=snap),
                             b.team_boxes(s, 'use_fatigue', ['pts', 'fga']))


if __name__ == '__main__':
    unittest.main()
