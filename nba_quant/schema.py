"""
V2 資料模型與驗證。

原則：缺資料就是 None，**絕不補值**；驗證失敗直接丟例外，不默默修正。
所有紀錄都要有 source 與 fetched_at，事後才查得到資料從哪來、何時拿到的。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

SEASON_TYPES = {2: 'regular', 3: 'postseason', 5: 'play_in'}   # 季前賽不收；play-in 只由獨立抓取使用（正式回補仍只收 2、3）
GAME_STATUS = {'scheduled', 'final', 'postponed', 'canceled'}
ODDS_STAGES = {'open', 'close', 'snapshot', 'current_postgame'}
PREDICTIVE_STAGES = {'open', 'snapshot'}                 # 可用於預測（snapshot 另需時間檢查）
CLOSING_STAGES = {'close'}                               # 真正的收盤：只能用於 CLV／賽前市場基準的評估
POSTGAME_STAGES = {'current_postgame'}                   # 賽後才抓到的快照：不是收盤（可能混入比賽中盤口）
EVAL_ONLY_STAGES = CLOSING_STAGES | POSTGAME_STAGES      # 兩者都不能進預測
# 時間性質標籤（2026-11-20 使用者決定）：current_postgame 一律稱 POSTGAME_SNAPSHOT，不得稱為 CLOSING。
# POSTGAME_SNAPSHOT 不得用於賽前模型訓練、賽前市場基準、CLV 或任何需要賽前資訊的回測評估。
# 沒有時間戳時的預設類別；有時間戳時由 price_time.classify() 升級為 TIMESTAMP_VERIFIED_* 或判為 INVALID_AFTER_START
STAGE_TIME_CLASS = {'open': 'PROVIDER_LABELED_OPEN', 'snapshot': 'PREGAME_SNAPSHOT', 'close': 'PROVIDER_LABELED_CLOSE',
                    'current_postgame': 'POSTGAME_SNAPSHOT'}
MARKETS = {'ml', 'spread', 'total'}
SIDES = {'ml': {'home', 'away'}, 'spread': {'home', 'away'}, 'total': {'over', 'under'}}
INJURY_STATUS = {'Out', 'Doubtful', 'Questionable', 'Probable', 'Day-To-Day', 'Available'}
TAIWAN_SOURCES = {'manual', 'playsport'}


class SchemaError(ValueError):
    pass


def parse_utc(s: Optional[str]) -> Optional[datetime]:
    """ISO 8601（可帶 Z）→ aware datetime。None 原樣回傳；沒有時區直接報錯，避免把當地時間當 UTC。"""
    if s is None:
        return None
    d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise SchemaError(f'timestamp without timezone: {s!r}')
    return d


def _req(cond, msg):
    if not cond:
        raise SchemaError(msg)


@dataclass
class Game:
    game_id: str
    season: int
    season_type: int
    start_utc: str
    home: str
    away: str
    status: str
    source: str
    fetched_at: str
    home_pts: Optional[int] = None
    away_pts: Optional[int] = None
    neutral: bool = False

    def validate(self):
        _req(self.season_type in SEASON_TYPES, f'{self.game_id}: season_type {self.season_type}')
        _req(self.status in GAME_STATUS, f'{self.game_id}: status {self.status}')
        _req(self.home != self.away, f'{self.game_id}: home == away')
        parse_utc(self.start_utc), parse_utc(self.fetched_at)
        if self.status == 'final':
            _req(self.home_pts is not None and self.away_pts is not None, f'{self.game_id}: final without score')
            _req(self.home_pts != self.away_pts, f'{self.game_id}: NBA game cannot end tied')
        else:
            _req(self.home_pts is None and self.away_pts is None, f'{self.game_id}: score on non-final game')
        return self


@dataclass
class PlayerLine:
    player_id: str
    name: str
    minutes: Optional[float]
    pts: Optional[int]
    starter: bool
    dnp_reason: Optional[str] = None


@dataclass
class TeamBox:
    game_id: str
    team: str
    fgm: int
    fga: int
    fg3m: int
    fg3a: int
    ftm: int
    fta: int
    oreb: int
    dreb: int
    tov: int
    pts: int
    overtimes: int
    source: str
    fetched_at: str
    players: list = field(default_factory=list)

    def validate(self):
        _req(0 <= self.fgm <= self.fga, f'{self.game_id}/{self.team}: fgm/fga')
        _req(0 <= self.fg3m <= self.fg3a <= self.fga, f'{self.game_id}/{self.team}: 3pt')
        _req(self.fg3m <= self.fgm, f'{self.game_id}/{self.team}: fg3m > fgm')
        _req(0 <= self.ftm <= self.fta, f'{self.game_id}/{self.team}: ft')
        _req(self.pts == 2 * self.fgm + self.fg3m + self.ftm, f'{self.game_id}/{self.team}: pts mismatch')
        return self

    def possessions(self) -> float:
        """單隊回合數估計；正式計算取兩隊平均（features 模組）。"""
        return self.fga - self.oreb + self.tov + 0.44 * self.fta


@dataclass
class OddsQuote:
    game_id: str
    provider: str
    stage: str
    market: str
    side: str
    line: Optional[float]
    price_decimal: Optional[float]
    source: str
    fetched_at: str
    observed_at: Optional[str] = None          # 我們自己看到這個價格的時間（只有 snapshot 有）
    provider_timestamp: Optional[str] = None   # 供應商提供的價格時間戳；ESPN 沒有 → 一律 None，絕不推測

    def validate(self):
        _req(self.stage in ODDS_STAGES, f'{self.game_id}: stage {self.stage}')
        _req(self.market in MARKETS, f'{self.game_id}: market {self.market}')
        _req(self.side in SIDES[self.market], f'{self.game_id}: side {self.side} for {self.market}')
        if self.market == 'ml':
            _req(self.line is None, f'{self.game_id}: moneyline with line')
        else:
            _req(self.line is not None, f'{self.game_id}: {self.market} without line')
        if self.price_decimal is not None:
            _req(self.price_decimal > 1.0, f'{self.game_id}: decimal price {self.price_decimal} <= 1')
        if self.stage == 'snapshot':
            _req(self.observed_at is not None, f'{self.game_id}: snapshot without observed_at')
        parse_utc(self.observed_at), parse_utc(self.fetched_at), parse_utc(self.provider_timestamp)
        return self


@dataclass
class InjuryReport:
    team: str
    player_id: str
    player: str
    status: str
    comment: str
    reported_at: Optional[str]
    source: str
    fetched_at: str

    def validate(self):
        _req(self.status in INJURY_STATUS, f'{self.player}: injury status {self.status}')
        parse_utc(self.reported_at), parse_utc(self.fetched_at)
        return self


@dataclass
class TaiwanQuote:
    date_tw: str
    home: str
    away: str
    market: str
    side: str
    line: Optional[float]
    price_decimal: float
    source: str
    observed_at: str
    note: str = ''

    def validate(self):
        _req(self.source in TAIWAN_SOURCES, f'taiwan source {self.source}: 美國盤口不可冒充台灣盤口')
        _req(self.market in MARKETS and self.side in SIDES[self.market], f'taiwan {self.market}/{self.side}')
        _req(self.price_decimal > 1.0, f'taiwan price {self.price_decimal}')
        if self.market != 'ml':
            _req(self.line is not None, f'taiwan {self.market} without line')
        parse_utc(self.observed_at)
        return self


def to_dict(obj) -> dict:
    return asdict(obj)
