"""
Elo 球隊實力評分（第一階段模型實作 stage 1；使用者 2026-11-20 第七輪核准）。

資料：只透過 DataAccess 讀取 `use_elo` 範圍（所有比賽類型：一般例行賽、盃賽各階段與冠軍戰、附加賽、季後賽）。
只用比分（game_result），不用 box score、不用盤口。

時序（T23）：
- 更新順序：(開賽時間 UTC, game_id)。game_id 只是同時開賽時的固定排序鍵。
- 每個美東日期結束時存一份評分快照。預測美東日期 D 的任何一場，一律用「D 前一個美東日期結束時」的快照：
  同一天較早結束的比賽不會影響同一天較晚比賽的預測。
- 每筆更新紀錄 game_type（T20）。

Elo 更新清單與模型訓練樣本是兩份獨立清單（T20）：本模組不產生、也不讀取訓練樣本。

參數（T6）：
- DEFAULT_PARAMS 是文獻常用值（K=20、主場 100 分、季間保留 75%、比分差乘數），**不是用本專案資料調出來的**。
- 若要調參，只能呼叫 select_params()，它只接受開發期球季（config.DEV_SEASONS），其他球季（含 2023-24 驗證季、
  2024-25、2025-26）一律拒絕。本階段沒有執行任何調參。
"""
from __future__ import annotations

import math
from collections import OrderedDict

from .. import asof, config
from ..data_access import DataAccess

MEAN = 1505.0
DEFAULT_PARAMS = {'k': 20.0, 'home_adv': 100.0, 'carryover': 0.75, 'mov': True}


def expected(r_home, r_away, home_adv):
    return 1.0 / (1.0 + 10 ** (-(r_home + home_adv - r_away) / 400.0))


def mov_multiplier(margin, elo_diff_winner):
    """比分差乘數（Silver 2015 形式）：贏越多越多，但對原本就強的一方打折，避免自我強化。"""
    return ((abs(margin) + 3) ** 0.8) / (7.5 + 0.006 * elo_diff_winner)


class Elo:
    def __init__(self, params=None):
        self.params = dict(DEFAULT_PARAMS, **(params or {}))
        self.ratings = {}
        self.updates = []                    # 每場一筆：game_id、game_type、美東日期、賽前／賽後評分
        self.snapshots = OrderedDict()       # 美東日期 → (球季, 該日結束時的評分複本)
        self._season = None

    # ------------------------------------------------------------ 建立歷史
    def run(self, games, neutral=None):
        """games：DataAccess.games(..., 'use_elo') 的輸出（可跨多季串接）。依 (開賽時間, game_id) 排序後逐場更新。"""
        neutral = neutral or {}
        games = sorted(games, key=lambda g: (g['start_utc'], g['game_id']))
        day = None
        for g in games:
            d = asof.et_date(g['start_utc'])
            if day is not None and d != day:
                self.snapshots[day] = (self._season, dict(self.ratings))
            day = d
            if g['season'] != self._season:
                self._new_season(g['season'])
            self._update(g, d, neutral.get(g['game_id'], 'home'))
        if day is not None:
            self.snapshots[day] = (self._season, dict(self.ratings))
        return self

    def _new_season(self, season):
        c = self.params['carryover']
        self.ratings = {t: MEAN + c * (r - MEAN) for t, r in self.ratings.items()}
        self._season = season

    def _update(self, g, d, site):
        h, a = g['home'], g['away']
        rh, ra = self.ratings.get(h, MEAN), self.ratings.get(a, MEAN)
        adv = self.params['home_adv'] if site == 'home' else 0.0       # neutral、unknown 都不給主場效應
        e = expected(rh, ra, adv)
        margin = g['home_pts'] - g['away_pts']
        if margin == 0:
            raise ValueError(f"{g['game_id']}: NBA 比賽不應平手")
        s = 1.0 if margin > 0 else 0.0
        mult = 1.0
        if self.params['mov']:
            diff_winner = (rh + adv - ra) if margin > 0 else (ra - rh - adv)
            mult = mov_multiplier(margin, diff_winner)
        delta = self.params['k'] * mult * (s - e)
        self.ratings[h], self.ratings[a] = rh + delta, ra - delta
        self.updates.append({'game_id': g['game_id'], 'game_type': g['game_type'], 'season': g['season'],
                             'start_utc': g['start_utc'], 'et_date': d.isoformat(), 'home': h, 'away': a, 'site': site,
                             'pre_home': rh, 'pre_away': ra, 'post_home': rh + delta, 'post_away': ra - delta})

    # ------------------------------------------------------------ 預測時取用
    def ratings_before(self, start_utc, season):
        """預測一場在 start_utc 開賽、屬於 season 的比賽時可用的評分：前一個美東日期（含更早）結束時的快照。
        若快照停在上一季（新球季開幕前），套用與更新時相同的季間回歸——只用開季前已知的資料。"""
        d = asof.et_date(start_utc)
        snap_season, snap = None, {}
        for day, (s, r) in self.snapshots.items():
            if day < d:
                snap_season, snap = s, r
            else:
                break
        out = dict(snap)
        if snap_season is not None and snap_season != season:
            c = self.params['carryover']
            out = {t: MEAN + c * (r - MEAN) for t, r in out.items()}
        return out

    def predict(self, game, site='home'):
        """主隊獲勝機率（只用前一美東日期結束時的評分）。"""
        r = self.ratings_before(game['start_utc'], game['season'])
        rh, ra = r.get(game['home'], MEAN), r.get(game['away'], MEAN)
        return expected(rh, ra, self.params['home_adv'] if site == 'home' else 0.0)


def build(seasons, purpose='feature_computation', params=None, root='.'):
    """依序讀取多季 use_elo 比賽並建立 Elo 歷史。鎖定測試期由 DataAccess 依 purpose 拒絕。"""
    da = DataAccess(purpose, root=root)
    games = []
    for s in sorted(seasons):
        games += da.games(s, 'use_elo')
    neutral = da.neutral_status([g['game_id'] for g in games])
    return Elo(params).run(games, neutral), da


def select_params(seasons, candidates, score_fn):
    """Elo 參數選擇（T6）：只接受開發期球季。本階段不執行；評估階段才會呼叫。"""
    bad = sorted(set(seasons) - set(config.DEV_SEASONS))
    if bad:
        raise config.HoldoutLocked(f'Elo 參數只能用開發期球季 {config.DEV_SEASONS} 選擇；拒絕 {bad}')
    best = None
    for p in candidates:
        sc = score_fn(p, seasons)
        if best is None or sc < best[0]:
            best = (sc, p)
    return best[1] if best else None


def log_loss(p, y):
    p = min(max(p, 1e-12), 1 - 1e-12)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))
