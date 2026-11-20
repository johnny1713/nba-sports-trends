"""V2 全域設定。期間劃分依據見 docs/reports/2026-11-20_espn_odds_coverage.md。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

WARMUP_SEASONS = (2015,)                                   # 2014-15：只累積數據（盤口只有賽後快照）
DEV_SEASONS = tuple(range(2016, 2024))                     # 2015-16～2022-23：沒有可用的賽前市場價格（只有賽後快照＋無價格開盤線）
TUNE_SEASONS = (2024,)                                     # 2023-24：開盤＋收盤，多家莊家
HOLDOUT_SEASONS = (2025, 2026)                             # 2024-25、2025-26：鎖定
LIVE_SEASON = 2027                                         # 2026-27

HOLDOUT_LOG = os.path.join('data', 'ops', 'holdout_log.jsonl')

# 鎖定測試期的評估流程（要求 D + Phase 3 前補充要求 1；2026-11-20 第七輪修訂）：
#   freeze_model(model_version)    → 寫入一筆 freeze（模型凍結；之後才能登記正式測試）
#   run_id = holdout_begin([季], 'final_evaluation', model_version, data_version)
#                                  → 每季分別登記；每季一生只能登記一次；必須是已凍結的模型版本
#   check_seasons([季], run_id)    → 只有已登記、尚未出結果的 run 才能碰該季
#   holdout_finish(run_id, results)→ 寫入一筆 result（結果自動標上該季，兩季分開保存，不提供合併平均）
#   holdout_independence()         → 看過任何一季結果後若再凍結新模型（或另一季用不同模型版本），
#                                    兩季都不再是獨立測試，永久標記
# 模型凍結前：2024-25 只能做資料品質檢查、2025-26 完全禁止讀取（data_access.py 強制）。
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


FINAL_PURPOSE = 'final_evaluation'


def freeze_model(model_version, manifest_sha, require_clean=True):
    """登記模型凍結。之後才能登記正式最終測試；看過結果後再凍結任何模型 → 鎖定測試期失去獨立性。"""
    sha, clean = git_state()
    if require_clean and (not sha or not clean):
        raise HoldoutLocked('model freeze requires a committed, clean working tree')
    return _append({'type': 'freeze', 'run_id': f'freeze:{model_version}', 'at': _now(), 'model_version': model_version,
                    'manifest_sha': manifest_sha, 'code_sha': sha})


def frozen_versions():
    return {r['model_version'] for r in verify_holdout_log() if r['type'] == 'freeze'}


def holdout_begin(seasons, purpose, model_version, data_version, require_clean=True):
    touched = sorted(set(seasons) & set(HOLDOUT_SEASONS))
    if not touched:
        raise ValueError('holdout_begin called without any holdout season')
    if len(set(seasons)) != 1 or len(touched) != 1:
        raise HoldoutLocked('每一季必須分別登記正式最終測試（一次只能登記一季）')
    if purpose != FINAL_PURPOSE:
        raise HoldoutLocked(f'鎖定測試期只允許 {FINAL_PURPOSE}；不允許訓練、特徵選擇、調參、選模或回測')
    recs = verify_holdout_log()
    if model_version not in {r['model_version'] for r in recs if r['type'] == 'freeze'}:
        raise HoldoutLocked(f'模型 {model_version} 尚未凍結（freeze_model），不能登記正式最終測試')
    if any(r['type'] == 'begin' and touched[0] in r['seasons'] for r in recs):
        raise HoldoutLocked(f'{touched[0]} 已登記過正式最終測試；每季只能評估一次')
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
    if not isinstance(results, dict) or any(k in results for k in ('combined', 'pooled', 'average_over_seasons')):
        raise HoldoutLocked('結果必須是單季的 dict；兩季結果分開保存，不可合併平均')
    season = next(r for r in recs if r['type'] == 'begin' and r['run_id'] == run_id)['seasons']
    return _append({'type': 'result', 'run_id': run_id, 'at': _now(), 'seasons': season, 'results': results})


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


def holdout_results():
    """每季的正式結果，分開回傳 {season: [results]}；刻意不提供合併平均。"""
    out = {}
    for r in verify_holdout_log():
        if r['type'] == 'result':
            for s in r['seasons']:
                out.setdefault(s, []).append(r['results'])
    return out


def holdout_independence():
    """看過任何一季的正式結果之後，若再凍結任何模型，或另一季的正式測試用了不同的模型版本，
    鎖定測試期就不再是獨立測試（永久，因為紀錄是 append-only）。"""
    recs = verify_holdout_log()
    seen, first_version, why = False, None, []
    for r in recs:
        if r['type'] == 'result':
            seen = True
        elif r['type'] == 'begin':
            if first_version is None:
                first_version = r['model_version']
            elif seen and r['model_version'] != first_version:
                why.append(f"看過結果後以不同模型版本 {r['model_version']} 登記 {r['seasons']}")
        elif r['type'] == 'freeze' and seen:
            why.append(f"看過結果後又凍結模型 {r['model_version']}")
    return {'independent': not why, 'reasons': why}


def holdout_views():
    """鎖定期間被評估過幾次——次數越多，越不算真正的樣本外。"""
    return sum(1 for r in verify_holdout_log() if r['type'] == 'begin')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
