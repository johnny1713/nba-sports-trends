"""
Basketball-Reference box score：只在 ESPN box score 缺漏時當備援（2014-15 實測 ESPN 有 13.6% 的比賽統計全為 0）。

- 禮貌抓取：每次請求間隔 ≥ 3.5 秒（對方公告上限每分鐘 20 次）。
- 採用條件：兩隊得分必須與 ESPN 比分完全一致，否則不採用。
- 球員 id 以 'bbref:' 前綴標示（與 ESPN id 不同體系）；依賴球員 id 的特徵需處理混用。
"""
from __future__ import annotations

import re
from datetime import timedelta, timezone

from ..schema import PlayerLine, TeamBox, parse_utc

BASE = 'https://www.basketball-reference.com/boxscores/{date}0{home}.html'
# ESPN team id → Basketball-Reference 代號（2014-15 起：NOP、CHO、BRK）
ESPN_TO_BBREF = {
    '1': 'ATL', '2': 'BOS', '3': 'NOP', '4': 'CHI', '5': 'CLE', '6': 'DAL', '7': 'DEN', '8': 'DET', '9': 'GSW',
    '10': 'HOU', '11': 'IND', '12': 'LAC', '13': 'LAL', '14': 'MIA', '15': 'MIL', '16': 'MIN', '17': 'BRK',
    '18': 'NYK', '19': 'ORL', '20': 'PHI', '21': 'PHO', '22': 'POR', '23': 'SAC', '24': 'SAS', '25': 'OKC',
    '26': 'UTA', '27': 'WAS', '28': 'TOR', '29': 'MEM', '30': 'CHO',
}
_ET = timezone(timedelta(hours=-5))


def box_url(game: dict) -> str:
    d = parse_utc(game['start_utc']).astimezone(_ET).strftime('%Y%m%d')
    return BASE.format(date=d, home=ESPN_TO_BBREF[game['home']])


def _int(cell):
    cell = (cell or '').strip()
    return int(cell) if cell else 0


def _stat(row, key):
    m = re.search(r'data-stat="%s"[^>]*>([^<]*)<' % key, row)
    return m.group(1) if m else None


def parse_box(html: str, game: dict, fetched_at: str):
    boxes = []
    for tid in (game['away'], game['home']):
        ab = ESPN_TO_BBREF[tid]
        m = re.search(r'<table[^>]*id="box-%s-game-basic".*?</table>' % ab, html, re.S)
        if not m:
            raise ValueError(f'bbref: table box-{ab}-game-basic not found')
        tbl = m.group(0)
        foot = re.search(r'<tfoot>(.*?)</tfoot>', tbl, re.S).group(1)
        g = lambda k: _int(_stat(foot, k))
        players, starter = [], True
        body = re.search(r'<tbody>(.*?)</tbody>', tbl, re.S).group(1)
        for attrs, row in re.findall(r'<tr([^>]*)>(.*?)</tr>', body, re.S):
            if 'thead' in attrs:                      # 「Reserves」標題列：之後都是替補
                starter = False
                continue
            pid = re.search(r'data-append-csv="([^"]+)"', row)
            if not pid:
                starter = False
                continue
            name = re.sub(r'<[^>]+>', '', re.search(r'data-stat="player"[^>]*>(.*?)</th>', row, re.S).group(1)).strip()
            reason = re.search(r'data-stat="reason"[^>]*>([^<]*)<', row)
            mp = _stat(row, 'mp')
            mins = None
            if mp and ':' in mp:
                mm, ss = mp.split(':')
                mins = round(int(mm) + int(ss) / 60, 2)
            pts = _stat(row, 'pts')
            players.append(PlayerLine(player_id='bbref:' + pid.group(1), name=name, minutes=mins,
                                      pts=int(pts) if pts not in (None, '') else None, starter=starter,
                                      dnp_reason=reason.group(1).strip() if reason else None).__dict__)
        tb = TeamBox(game_id=game['game_id'], team=tid, fgm=g('fg'), fga=g('fga'), fg3m=g('fg3'), fg3a=g('fg3a'),
                     ftm=g('ft'), fta=g('fta'), oreb=g('orb'), dreb=g('drb'), tov=g('tov'), pts=g('pts'),
                     overtimes=max(0, (g('mp') - 240) // 25), source='bbref:boxscore', fetched_at=fetched_at,
                     players=players)
        boxes.append(tb.validate().__dict__)
    return boxes
