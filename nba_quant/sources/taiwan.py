"""
台灣運彩盤口：玩運彩（playsport.cc）抓取 + 手動 CSV 備援。

只讀「運彩盤」欄位（td-bank-*），國際盤（td-universal-*）一律不碰：
- 每次先確認表頭 `<th ... class="th-bank">運彩盤</th>` 存在且 colspan=3，
  且子欄位依序是 th-bank-bet01 讓分 / th-bank-bet03 不讓分 / th-bank-bet02 大小；不符就整頁拒收（ParseRejected）。
- 原始 HTML 一律 gzip 存檔（data/taiwan/raw/），解析結果另存，事後可追查。
- 解析結果在人工抽樣驗證之前一律 verified=False，網站顯示「未驗證」。

美國盤口絕對不會進到這裡：TaiwanQuote.validate() 只接受 source ∈ {manual, playsport}。
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta, timezone

from ..schema import TaiwanQuote

URL = 'https://www.playsport.cc/predict/games?allianceid=3'
TW = timezone(timedelta(hours=8))

# 玩運彩中文隊名 → ESPN team id
ZH_TO_ESPN = {
    '老鷹': '1', '塞爾提克': '2', '鵜鶘': '3', '公牛': '4', '騎士': '5', '獨行俠': '6', '金塊': '7',
    '活塞': '8', '勇士': '9', '火箭': '10', '溜馬': '11', '快艇': '12', '湖人': '13', '熱火': '14',
    '公鹿': '15', '灰狼': '16', '籃網': '17', '尼克': '18', '魔術': '19', '76人': '20', '太陽': '21',
    '拓荒者': '22', '國王': '23', '馬刺': '24', '雷霆': '25', '爵士': '26', '巫師': '27', '暴龍': '28',
    '灰熊': '29', '黃蜂': '30',
}


class ParseRejected(ValueError):
    pass


def url_for(date_tw: str = None):
    return URL if not date_tw else f'{URL}&gametime={date_tw.replace("-", "")}'


def _txt(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()


def check_header(html: str):
    m = re.search(r'<th[^>]*colspan="(\d)"[^>]*class="th-bank"[^>]*>\s*運彩盤\s*</th>', html)
    if not m or m.group(1) != '3':
        raise ParseRejected('運彩盤 表頭不存在或欄數不是 3——頁面結構變了，拒收')
    order = re.findall(r'<th class="(th-bank-bet0\d)">\s*([^<\s]+)\s*</th>', html)
    want = [('th-bank-bet01', '讓分'), ('th-bank-bet03', '不讓分'), ('th-bank-bet02', '大小')]
    if order != want:
        raise ParseRejected(f'運彩盤 子欄位順序不符：{order}')


_NUM = r'([+-]?\d+(?:\.\d+)?)'


def _cell(body, cls):
    m = re.search(r'<td class="%s"[^>]*>(.*?)</td>' % cls, body, re.S)
    return _txt(m.group(1)) if m else ''


def parse(html: str, fetched_at: str):
    """
    回傳 (games, problems)。games: 每場一筆 dict，含原始文字（raw_cells）方便人工比對。
    problems: 無法解析的列（不丟例外，但會寫進報告）。
    """
    check_header(html)
    rows = re.findall(r'<tr\s+gameid="(\d+)"\s*>(.*?)</tr>', html, re.S)
    by_gid = {}
    for gid, body in rows:
        by_gid.setdefault(gid, []).append(body)
    games, problems = [], []
    for gid, bodies in by_gid.items():
        if len(bodies) != 2:
            problems.append((gid, f'expected 2 rows, got {len(bodies)}'))
            continue
        info = bodies[0]
        game_no = (re.search(r'<td rowspan="2" class="td-gameinfo">.*?<h3>(\d+)</h3>', info, re.S) or [None, None])[1]
        tm = re.search(r'<h4>\s*(AM|PM)\s*(\d{1,2}):(\d{2})\s*</h4>', info)
        names, cells = [], []
        for b in bodies:
            names.append(_cell(b, r'td-teaminfo[^"]*'))
            cells.append({k: _cell(b, f'td-bank-{k}') for k in ('bet01', 'bet03', 'bet02')})
        try:
            g = _build(gid, game_no, tm, names, cells, fetched_at)
            games.append(g)
        except (ValueError, KeyError) as e:
            problems.append((gid, f'{e}; names={names}; cells={cells}'))
    return games, problems


def _build(gid, game_no, tm, names, cells, fetched_at):
    date_tw = f'{gid[0:4]}-{gid[4:6]}-{gid[6:8]}'
    start_tw = None
    if tm:
        h = int(tm.group(2)) % 12 + (12 if tm.group(1) == 'PM' else 0)
        start_tw = f'{date_tw}T{h:02d}:{tm.group(3)}:00+08:00'
    away_zh, home_zh = names
    if away_zh not in ZH_TO_ESPN or home_zh not in ZH_TO_ESPN:
        raise ValueError(f'unknown team name {names}')
    c_away, c_home = cells
    # 讓分：「客 +5.5 , 1.7」「主 -5.5 , 1.73」
    quotes = []

    def side_tag(text, want):
        if text and not text.startswith(want):
            raise ValueError(f'side tag mismatch: expected {want} in {text!r}')

    for text, side, tag in ((c_away['bet01'], 'away', '客'), (c_home['bet01'], 'home', '主')):
        if not text:
            continue
        side_tag(text, tag)
        m = re.search(_NUM + r'\s*,\s*' + _NUM, text)
        if not m:
            raise ValueError(f'spread cell {text!r}')
        quotes.append(('spread', side, float(m.group(1)), float(m.group(2))))
    for text, side, tag in ((c_away['bet03'], 'away', '客'), (c_home['bet03'], 'home', '主')):
        if not text:
            continue
        side_tag(text, tag)
        m = re.search(_NUM + r'\s*$', text)
        if not m:
            raise ValueError(f'ml cell {text!r}')
        quotes.append(('ml', side, None, float(m.group(1))))
    for text, side, tag in ((c_away['bet02'], 'over', '大'), (c_home['bet02'], 'under', '小')):
        if not text:
            continue
        side_tag(text, tag)
        m = re.search(_NUM + r'\s*,\s*' + _NUM, text)
        if not m:
            raise ValueError(f'total cell {text!r}')
        quotes.append(('total', side, float(m.group(1)), float(m.group(2))))
    sp = {s: l for mk, s, l, _ in quotes if mk == 'spread'}
    if len(sp) == 2 and abs(sp['home'] + sp['away']) > 1e-9:
        raise ValueError(f'spread lines not opposite: {sp}')
    tl = {s: l for mk, s, l, _ in quotes if mk == 'total'}
    if len(tl) == 2 and tl['over'] != tl['under']:
        raise ValueError(f'total lines differ: {tl}')
    out = []
    for mk, side, line, price in quotes:
        out.append(TaiwanQuote(date_tw=date_tw, home=ZH_TO_ESPN[home_zh], away=ZH_TO_ESPN[away_zh], market=mk,
                               side=side, line=line, price_decimal=price, source='playsport',
                               observed_at=fetched_at, note=f'game_no={game_no}').validate().__dict__)
    return {'playsport_gameid': gid, 'game_no': game_no, 'date_tw': date_tw, 'start_tw': start_tw,
            'away_zh': away_zh, 'home_zh': home_zh, 'away': ZH_TO_ESPN[away_zh], 'home': ZH_TO_ESPN[home_zh],
            'quotes': out, 'raw_cells': {'away': c_away, 'home': c_home}, 'verified': False}


MANUAL_FIELDS = ['date_tw', 'game_no', 'away_zh', 'home_zh', 'market', 'side', 'line', 'price_decimal', 'observed_at', 'note']


def read_manual_csv(path):
    """手動輸入：data/taiwan/manual/<日期>.csv。欄位見 MANUAL_FIELDS；observed_at 用台灣時間 ISO（含 +08:00）。"""
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if not r.get('market'):
                continue
            out.append(TaiwanQuote(date_tw=r['date_tw'], home=ZH_TO_ESPN[r['home_zh']], away=ZH_TO_ESPN[r['away_zh']],
                                   market=r['market'], side=r['side'],
                                   line=float(r['line']) if r.get('line') not in (None, '') else None,
                                   price_decimal=float(r['price_decimal']), source='manual',
                                   observed_at=r['observed_at'], note=f"game_no={r.get('game_no', '')} {r.get('note', '')}".strip()
                                   ).validate().__dict__)
    return out
