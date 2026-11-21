"""F1 最終唯讀審查的補充測試（2026-11-21，T40）。不修改程式。"""
import json
import os
import shutil
import tempfile
import unittest

from nba_quant import audit_coverage, store
from nba_quant.features import f1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_DATA = os.path.exists(os.path.join(ROOT, 'data', 'reference', 'game_classification.csv'))
ERR = {'401161297', '401468217', '401468616'}


@unittest.skipUnless(HAS_DATA, 'no data')
class ThreeErrorGames(unittest.TestCase):
    def test_extreme_values_in_error_games_change_nothing(self):
        """三場 ERROR 比賽的 box 改成極端值：2019-20、2020-21（上季先驗）、2022-23 的 F1 完全不變；repo 原始檔不變。"""
        base = {s: f1.compute(s) for s in (2020, 2021, 2023)}
        raw_before = {s: store.sha256_file(os.path.join(ROOT, 'data', 'raw', 'espn', str(s), 'teambox.jsonl.gz')) for s in (2020, 2023)}
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(os.path.join(ROOT, 'data', 'reference'), os.path.join(d, 'data', 'reference'))
            shutil.copytree(os.path.join(ROOT, 'data', 'audit', 'box_quality'), os.path.join(d, 'data', 'audit', 'box_quality'))
            for s in (2019, 2020, 2021, 2022, 2023):
                shutil.copytree(os.path.join(ROOT, 'data', 'raw', 'espn', str(s)), os.path.join(d, 'data', 'raw', 'espn', str(s)))
            n = 0
            for s in (2020, 2023):
                p = os.path.join(d, 'data', 'raw', 'espn', str(s), 'teambox.jsonl.gz')
                bx = list(store.read_jsonl_gz(p))
                for b in bx:
                    if b['game_id'] in ERR:
                        b.update({'pts': 999, 'fga': 1, 'fta': 400, 'oreb': 0, 'tov': 99, 'overtimes': 7})
                        n += 1
                store.write_jsonl_gz(p, bx)
            self.assertEqual(n, 6)
            for s in (2020, 2023):                                     # fail closed：原始檔變了 → 舊清單失效、拒絕計算
                with self.assertRaises(audit_coverage.AuditIntegrityError) as cm:
                    f1.compute(s, root=d)
                self.assertEqual(cm.exception.code, 'raw_boxscore_hash')
                audit_coverage.build_manifest(s, d, verify_flags=False, now='test')   # 沿用原稽核判定（只為隔離數值影響）
            for s, res in base.items():
                alt = f1.compute(s, root=d)
                self.assertEqual(alt.rows, res.rows, s)
        for s, h in raw_before.items():
            self.assertEqual(store.sha256_file(os.path.join(ROOT, 'data', 'raw', 'espn', str(s), 'teambox.jsonl.gz')), h)
        self.assertEqual({e['game_id'] for s in (2020, 2023) for e in base[s].excluded}, ERR)


@unittest.skipUnless(HAS_DATA, 'no data')
class Rerun(unittest.TestCase):
    def test_full_output_identical_on_rerun(self):
        dump = lambda: json.dumps([[r.rows, r.excluded, r.warnings] for r in (f1.compute(s) for s in (2015, 2019, 2023))],
                                  sort_keys=True, default=str)
        self.assertEqual(dump(), dump())
