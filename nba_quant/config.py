"""V2 全域設定。期間劃分依據見 docs/reports/2026-11-20_espn_odds_coverage.md。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

WARMUP_SEASONS = (2015,)                                   # 2014-15：只累積數據
DEV_SEASONS = tuple(range(2016, 2024))                     # 2015-16～2022-23：只有收盤
TUNE_SEASONS = (2024,)                                     # 2023-24：開盤＋收盤，多家莊家
HOLDOUT_SEASONS = (2025, 2026)                             # 2024-25、2025-26：鎖定
LIVE_SEASON = 2027                                         # 2026-27

HOLDOUT_LOG = os.path.join('data', 'ops', 'holdout_log.jsonl')

# 鎖定測試期的評估流程（要求 D + Phase 3 前補充要求 1）：
#   run_id = holdout_begin(...)   → 寫入一筆 begin（時間、程式 git sha、模型版本、資料版本）
#   check_seasons(seasons, run_id) → 只有已登記的 run 才能碰鎖定球季
#   holdout_finish(run_id, results)→ 寫入一筆 result（測試結果摘要）
# 紀錄檔是 append-only 的雜湊鏈：每筆帶前一筆的 sha256，改動或刪除任何一筆，
# verify_holdout_log() 都會失敗（測試與 workflow 每次都會驗證）。
# 限制要講清楚：git 歷史理論上可被強制改寫，雜湊鏈讓「偷偷改」一定留下痕跡，但無法阻止「整檔重建」；
# 所以每筆 result 的 hash 也會印在 Actions 日誌，日誌由 GitHub 保存、我們改不到。


class HoldoutLocked(PermissionError):
    pass


class HoldoutLogCorrupted(RuntimeError):
    pass


GENESIS = '0' * 64


def _canon(rec):
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _read_log():
    if not os.path.exists(HOLDOUT_LOG):
        return []
    with open(HOLDOUT_LOG, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def verify_holdout_log():
    """逐筆重算雜湊鏈；任何一筆被改、被刪、順序被動都會丟 HoldoutLogCorrupted。回傳紀錄清單。"""
    recs = _read_log()
    prev = GENESIS
    for i, r in enumerate(recs):
        body = {k: v for k, v in r.items() if k != 'hash'}
        if body.get('prev_hash') != prev:
            raise HoldoutLogCorrupted(f'record {i}: prev_hash mismatch')
        h = hashlib.sha256(_canon(body).encode('utf-8')).hexdigest()
        if h != r.get('hash'):
            raise HoldoutLogCorrupted(f'record {i}: hash mismatch (edited?)')
        prev = h
    return recs


def _append(rec):
    recs = verify_holdout_log()
    rec = dict(rec, prev_hash=recs[-1]['hash'] if recs else GENESIS)
    rec['hash'] = hashlib.sha256(_canon(rec).encode('utf-8')).hexdigest()
    os.makedirs(os.path.dirname(HOLDOUT_LOG), exist_ok=True)
    with open(HOLDOUT_LOG, 'a', encoding='utf-8') as f:
        f.write(_canon(rec) + '\n')
    print(f'[holdout-log] {rec["type"]} {rec["run_id"]} hash={rec["hash"]}')
    return rec


def git_state():
    """(commit sha, 工作區是否乾淨)。鎖定期評估要求工作區乾淨，否則程式版本無法重現。"""
    try:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                                    capture_output=True, text=True, check=True).stdout.strip())
        return sha, not dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False


def holdout_begin(seasons, purpose, model_version, data_version, require_clean=True):
    touched = sorted(set(seasons) & set(HOLDOUT_SEASONS))
    if not touched:
        raise ValueError('holdout_begin called without any holdout season')
    sha, clean = git_state()
    if require_clean and (not sha or not clean):
        raise HoldoutLocked('locked holdout requires a committed, clean working tree (code version must be reproducible)')
    run_id = hashlib.sha256(f'{datetime.now(timezone.utc).isoformat()}{sha}{purpose}'.encode()).hexdigest()[:16]
    _append({'type': 'begin', 'run_id': run_id, 'at': _now(), 'seasons': touched, 'purpose': purpose,
             'code_sha': sha, 'model_version': model_version, 'data_version': data_version})
    return run_id


def holdout_finish(run_id, results):
    recs = verify_holdout_log()
    if not any(r['type'] == 'begin' and r['run_id'] == run_id for r in recs):
        raise HoldoutLocked(f'unknown holdout run {run_id}')
    if any(r['type'] == 'result' and r['run_id'] == run_id for r in recs):
        raise HoldoutLocked(f'holdout run {run_id} already has a result (results are write-once)')
    return _append({'type': 'result', 'run_id': run_id, 'at': _now(), 'results': results})


def check_seasons(seasons, run_id=None):
    """回測／調參入口都要呼叫：碰到鎖定球季時，必須帶著已登記且尚未出結果的 run_id。"""
    touched = sorted(set(seasons) & set(HOLDOUT_SEASONS))
    if not touched:
        return
    if run_id is None:
        raise HoldoutLocked(f'seasons {touched} are the locked holdout; use --final (logged via holdout_begin)')
    recs = verify_holdout_log()
    begins = [r for r in recs if r['type'] == 'begin' and r['run_id'] == run_id]
    if not begins or not set(touched) <= set(begins[0]['seasons']):
        raise HoldoutLocked(f'run {run_id} was not registered for seasons {touched}')
    if any(r['type'] == 'result' and r['run_id'] == run_id for r in recs):
        raise HoldoutLocked(f'run {run_id} already finished; start a new logged run')


def holdout_views():
    """鎖定期間被評估過幾次——次數越多，越不算真正的樣本外。"""
    return sum(1 for r in verify_holdout_log() if r['type'] == 'begin')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
