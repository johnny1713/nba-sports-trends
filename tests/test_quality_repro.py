"""T24：盤口品質報告的可重現性回歸測試（不寫入既有檔案）。

在暫存目錄重跑 season_report()：quality.json 與 odds_flags.jsonl.gz 必須與既有檔案位元組相同；
測試前後既有檔案的 sha256 不變。逐家表格的 .md 同分列順序目前不可重現（見設計文件 3.3），這裡只比對數字內容。
"""
import hashlib
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = 2016


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


class QualityReproducible(unittest.TestCase):
    def test_season_report_reproduces_existing_outputs(self):
        src = os.path.join(ROOT, 'data', 'raw', 'espn', str(SEASON))
        if not os.path.exists(os.path.join(src, 'quality.json')):
            self.skipTest('no data')
        originals = {f: sha(os.path.join(src, f)) for f in os.listdir(src)}
        md = os.path.join(ROOT, 'docs', 'reports', 'data_quality', f'{SEASON}.md')
        md_sha = sha(md)
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as t:
            shutil.copytree(src, os.path.join(t, 'data', 'raw', 'espn', str(SEASON)))
            os.makedirs(os.path.join(t, 'docs', 'reports', 'data_quality'))
            try:
                os.chdir(t)
                from nba_quant import quality
                quality.season_report(SEASON)
            finally:
                os.chdir(cwd)
            for f in ('quality.json', 'odds_flags.jsonl.gz'):
                self.assertEqual(sha(os.path.join(t, 'data', 'raw', 'espn', str(SEASON), f)), originals[f], f)
            new_md = open(os.path.join(t, 'docs', 'reports', 'data_quality', f'{SEASON}.md'), encoding='utf-8').read().splitlines()
            old_md = open(md, encoding='utf-8').read().splitlines()
            self.assertEqual(sorted(new_md), sorted(old_md))      # 同樣的列，只容許順序不同
        self.assertEqual({f: sha(os.path.join(src, f)) for f in os.listdir(src)}, originals)
        self.assertEqual(sha(md), md_sha)
