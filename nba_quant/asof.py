"""
防資料洩漏的唯一關卡（要求 A）。

特徵工程與模型**只能**透過這裡拿資料。規則：
- 球隊比賽紀錄：只放行比賽日（美東）早於預測比賽日的場次。
- 盤口：預測用途只放行 open 與 observed_at < T 的 snapshot。
- 真正的收盤（CLOSING）只能走 closing_quotes()，用於 CLV 與賽前市場基準的評估。
- 賽後快照（POSTGAME_SNAPSHOT，stage=current_postgame）**不是收盤**：不得用於賽前模型訓練、賽前市場基準、
  CLV 或任何需要賽前資訊的回測評估。只能透過 postgame_snapshots_for_audit() 取得，用途限資料品質稽核。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from .schema import CLOSING_STAGES, EVAL_ONLY_STAGES, POSTGAME_STAGES, parse_utc


class LeakageError(RuntimeError):
    pass


# 美東日期：NBA 例行賽最晚開打約美東 22:30，以 UTC−5 判定日期即可（夏令時間差 1 小時不會跨日）
_ET = timezone(timedelta(hours=-5))


def et_date(start_utc: str):
    return parse_utc(start_utc).astimezone(_ET).date()


def games_before(games: Iterable[dict], game_start_utc: str) -> List[dict]:
    """
    只回傳**前一個美東日期（含）以前**、已完賽**且資料完整**的比賽。同一天較早的場次也排除。
    資料完整（complete=True）由 backfill 判定：完賽、兩隊 box score 通過驗證、box 得分與比分一致。
    當季（2026-27）進行中、延賽、box score 缺漏的比賽一律不進特徵。
    """
    cutoff = et_date(game_start_utc)
    return [g for g in games
            if g.get('status') == 'final' and g.get('complete') is True and et_date(g['start_utc']) < cutoff]


def quotes_for_prediction(quotes: Iterable[dict], as_of: datetime) -> List[dict]:
    if as_of.tzinfo is None:
        raise LeakageError('as_of must be timezone-aware')
    out = []
    for q in quotes:
        st = q['stage']
        if st == 'open':
            out.append(q)
        elif st == 'snapshot':
            obs = parse_utc(q.get('observed_at'))
            if obs is not None and obs < as_of:
                out.append(q)
        elif st in EVAL_ONLY_STAGES:
            continue
        else:
            raise LeakageError(f'unknown stage {st!r}')
    return out


def closing_quotes(quotes: Iterable[dict]) -> List[dict]:
    """真正的收盤（ESPN 明確標記的 close）：只給 CLV 與賽前市場基準的評估用。不含賽後快照。"""
    return [q for q in quotes if q['stage'] in CLOSING_STAGES]


def postgame_snapshots_for_audit(quotes: Iterable[dict]) -> List[dict]:
    """賽後快照（POSTGAME_SNAPSHOT）：只供資料品質稽核。不得當收盤、不得算 CLV、不得當市場基準。"""
    return [q for q in quotes if q['stage'] in POSTGAME_STAGES]


def assert_no_postgame(quotes: Iterable[dict]):
    """放在 CLV／市場基準／回測評估函式入口：混進賽後快照就直接報錯。"""
    bad = [q for q in quotes if q.get('stage') in POSTGAME_STAGES]
    if bad:
        raise LeakageError(f'{len(bad)} POSTGAME_SNAPSHOT quotes passed to a pre-game evaluation (not closing lines)')


def assert_no_eval_stage(quotes: Iterable[dict]):
    """放在特徵函式入口的保險：只要混進 close 就直接報錯。"""
    bad = [q for q in quotes if q.get('stage') in EVAL_ONLY_STAGES]
    if bad:
        raise LeakageError(f'{len(bad)} closing quotes passed to a predictive function')
