"""
盤口方向與正負號的唯一定義（要求：統一主客方向，防止讓分顛倒）。

讓分（spread）一律以「被押注的那一隊」的角度記錄：
  - line < 0：該隊讓分（熱門），例如主隊 -7.5 = 主隊要贏 8 分以上才過盤
  - line > 0：該隊受讓（冷門），例如客隊 +7.5 = 客隊輸 7 分以內或贏球就過盤
  - 同一家、同一階段：home.line == -away.line（一定相反）
過盤判定：(該隊得分 − 對手得分) + line  > 0 贏、= 0 走盤（退本金）、< 0 輸。

大小分：line = 總分；over 過盤 ⇔ 總分 > line。
獨贏：line 為 None。

ESPN 的 item.spread 與 homeTeamOdds.pointSpread 都是主隊角度；
玩運彩的「客 +5.5／主 −5.5」也是各隊自己的角度——兩邊直接相容，不需要再翻號。
"""
from __future__ import annotations


def settle(market: str, side: str, line, home_pts: int, away_pts: int) -> str:
    """回傳 'win' / 'loss' / 'push'。"""
    if market == 'total':
        total = home_pts + away_pts
        diff = (total - line) if side == 'over' else (line - total)
    else:
        margin = (home_pts - away_pts) if side == 'home' else (away_pts - home_pts)
        diff = margin + (line if market == 'spread' else 0.0)
        if market == 'ml' and diff == 0:
            raise ValueError('NBA games cannot end tied')
    if diff > 0:
        return 'win'
    if diff < 0:
        return 'loss'
    return 'push'


def favorite_side(home_line: float):
    """依主隊讓分判斷熱門方：'home' / 'away' / None（PK）。"""
    if home_line < 0:
        return 'home'
    if home_line > 0:
        return 'away'
    return None
