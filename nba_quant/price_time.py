"""
價格的時間性質分類（2026-11-20 使用者決定）。

ESPN 沒有提供開盤、收盤或最後更新的實際時間戳（探路與全量回補都確認），因此必須區分：

| 類別 | 意義 |
|---|---|
| PROVIDER_LABELED_OPEN / PROVIDER_LABELED_CLOSE | 供應商（ESPN）欄位明確標示為開盤／收盤，**沒有時間戳**——可依標記使用，但不能宣稱已獨立驗證取得時間 |
| TIMESTAMP_VERIFIED_OPEN / TIMESTAMP_VERIFIED_CLOSE | 有供應商提供的實際時間戳（provider_timestamp），且早於開賽 |
| PREGAME_SNAPSHOT | 我們自己在開賽前抓到的即時盤（observed_at 是我們的抓取時間，早於開賽） |
| POSTGAME_SNAPSHOT | 賽後才抓到的 current——**不是收盤** |
| INVALID_AFTER_START | 標示為開盤／收盤或快照，但時間戳／抓取時間晚於（或等於）開賽——不可當賽前價格 |

原則：
- **只用資料裡真的存在的時間**。開盤／收盤只看 `provider_timestamp`（供應商給的）；
  `fetched_at` 是我們抓取的時間，**不是**價格發生的時間，絕不拿來推測開盤／收盤時間。
- 缺時間戳就是 PROVIDER_LABELED_*，不推測、不補造。
- CLV 的收盤只能是 PROVIDER_LABELED_CLOSE 或 TIMESTAMP_VERIFIED_CLOSE；POSTGAME_SNAPSHOT 與 INVALID_AFTER_START 一律拒絕。
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from .schema import parse_utc

PROVIDER_LABELED_OPEN = 'PROVIDER_LABELED_OPEN'
PROVIDER_LABELED_CLOSE = 'PROVIDER_LABELED_CLOSE'
TIMESTAMP_VERIFIED_OPEN = 'TIMESTAMP_VERIFIED_OPEN'
TIMESTAMP_VERIFIED_CLOSE = 'TIMESTAMP_VERIFIED_CLOSE'
PREGAME_SNAPSHOT = 'PREGAME_SNAPSHOT'
POSTGAME_SNAPSHOT = 'POSTGAME_SNAPSHOT'
INVALID_AFTER_START = 'INVALID_AFTER_START'

CLV_ALLOWED = {PROVIDER_LABELED_CLOSE, TIMESTAMP_VERIFIED_CLOSE}
PREGAME_PRICE_CLASSES = {PROVIDER_LABELED_OPEN, TIMESTAMP_VERIFIED_OPEN, PREGAME_SNAPSHOT}


class PriceTimeError(RuntimeError):
    pass


def classify(quote: dict, game_start_utc: Optional[str]) -> str:
    """依資料中**實際存在**的欄位分類；不推測任何時間。"""
    stage = quote['stage']
    start = parse_utc(game_start_utc) if game_start_utc else None
    if stage == 'current_postgame':
        return POSTGAME_SNAPSHOT
    if stage == 'snapshot':
        obs = parse_utc(quote.get('observed_at'))
        if obs is None or start is None:
            raise PriceTimeError('snapshot needs observed_at and game start')
        return PREGAME_SNAPSHOT if obs < start else INVALID_AFTER_START
    if stage in ('open', 'close'):
        ts = parse_utc(quote.get('provider_timestamp'))     # 只有供應商給的時間才算；fetched_at 不算
        if ts is None:
            return PROVIDER_LABELED_OPEN if stage == 'open' else PROVIDER_LABELED_CLOSE
        if start is None:
            raise PriceTimeError('cannot verify a provider timestamp without the game start time')
        if ts >= start:
            return INVALID_AFTER_START
        return TIMESTAMP_VERIFIED_OPEN if stage == 'open' else TIMESTAMP_VERIFIED_CLOSE
    raise PriceTimeError(f'unknown stage {stage!r}')


def clv_closing_quotes(quotes: Iterable[dict], game_start_utc: Optional[str]) -> List[dict]:
    """
    CLV 用的收盤：只接受供應商明確標記的 close（有無時間戳皆可，但有時間戳時必須早於開賽）。
    每筆回傳附上 time_class，報告才能揭露「收盤是否經時間戳驗證」。
    """
    out = []
    for q in quotes:
        if q['stage'] != 'close':
            continue
        tc = classify(q, game_start_utc)
        if tc in CLV_ALLOWED:
            out.append(dict(q, time_class=tc))
    return out


def assert_clv_close(quotes: Iterable[dict], game_start_utc: Optional[str]):
    """CLV 計算入口：任何不是合格收盤的價格（賽後快照、開賽後時間戳、開盤、快照）都直接報錯。"""
    for q in quotes:
        tc = q.get('time_class') or classify(q, game_start_utc)
        if tc not in CLV_ALLOWED:
            raise PriceTimeError(f'{q.get("game_id")}/{q.get("provider")}: {tc} cannot be used as a CLV closing price')


def verification_summary(quotes: Iterable[dict], start_by_game: dict) -> dict:
    """報告用：各階段有多少是「供應商標記」、多少是「時間戳驗證」。"""
    from collections import Counter
    c = Counter()
    for q in quotes:
        if q.get('provider_type') not in (None, 'book'):
            continue
        try:
            c[classify(q, start_by_game.get(q['game_id']))] += 1
        except PriceTimeError:
            c['UNCLASSIFIABLE'] += 1
    return dict(c)
