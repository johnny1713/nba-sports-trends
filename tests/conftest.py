"""測試專用：合成資料根目錄的「宣告稽核結果」（2026-11-21）。

正式程式的 audit_coverage.verify 每次都以真實 box_audit.audit_season 重新稽核。F1 的合成測試需要指定稽核結果
（例如同場層級 ERROR，v1 規則本身不會產生），所以測試期間把 audit_season 包一層：
- 根目錄下有 synthetic_audit/<季>.json（由 tests/test_f1.seal 寫入）→ 該季的稽核結果就是宣告的內容；
- 沒有宣告檔（真實資料、稽核完整性測試的根目錄）→ 呼叫真實稽核。
flag 檔仍必須與（宣告的）重新稽核結果逐筆相同，否則照樣 stale_audit。正式程式裡沒有任何這種開關。
"""
import json
import os

import pytest

from nba_quant import box_audit

_REAL_AUDIT = box_audit.audit_season
MARKER_DIR = 'synthetic_audit'


def declared(season, root):
    p = os.path.join(root, MARKER_DIR, f'{season}.json')
    if os.path.isfile(p):
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    return None


def _audit_season(season, root='.', scope=None):
    d = declared(season, root)
    if d is not None:
        return d, {}
    return _REAL_AUDIT(season, root, scope)


@pytest.fixture(autouse=True, scope='session')
def _synthetic_audit():
    # session 層級：unittest 的 setUpClass 也在範圍內
    mp = pytest.MonkeyPatch()
    mp.setattr(box_audit, 'audit_season', _audit_season)
    yield
    mp.undo()
