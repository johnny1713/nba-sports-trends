"""V2 全域設定。期間劃分依據見 docs/reports/2026-11-20_espn_odds_coverage.md。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

WARMUP_SEASONS = (2015,)                                   # 2014-15：只累積數據
DEV_SEASONS = tuple(range(2016, 2024))                     # 2015-16～2022-23：只有收盤
TUNE_SEASONS = (2024,)                                     # 2023-24：開盤＋收盤，多家莊家
HOLDOUT_SEASONS = (2025, 2026)                             # 2024-25、2025-26：鎖定
LIVE_SEASON = 2027                                         # 2026-27

HOLDOUT_LOG = os.path.join('data', 'ops', 'holdout_log.jsonl')


class HoldoutLocked(PermissionError):
    pass


def check_seasons(seasons, final=False, purpose=''):
    """回測／調參的入口都要呼叫。碰到鎖定期間而沒有 final=True 就拒絕；有的話留下紀錄。"""
    touched = sorted(set(seasons) & set(HOLDOUT_SEASONS))
    if not touched:
        return
    if not final:
        raise HoldoutLocked(f'seasons {touched} are the locked holdout; pass --final to evaluate (logged)')
    os.makedirs(os.path.dirname(HOLDOUT_LOG), exist_ok=True)
    with open(HOLDOUT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                            'seasons': touched, 'purpose': purpose}, ensure_ascii=False) + '\n')


def holdout_views():
    """鎖定期間被評估過幾次——次數越多，越不算真正的樣本外。"""
    if not os.path.exists(HOLDOUT_LOG):
        return 0
    with open(HOLDOUT_LOG, encoding='utf-8') as f:
        return sum(1 for line in f if line.strip())
