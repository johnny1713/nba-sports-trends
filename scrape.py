#!/usr/bin/env python3
"""
NBA 每日賽事趨勢爬蟲 + 儀表板產生器（mlb-sports-trends 的姊妹專案）。

抓 covers.com 的賽前趨勢，以「過盤命中率」排序推薦，輸出單一 index.html 給 GitHub Pages。
零外部依賴（純標準庫），設計理由與踩過的坑見 CLAUDE.md，以及 MLB 專案的 CLAUDE.md。

用法：
    python scrape.py                     # 抓美東今天
    python scrape.py --date 2026-10-21   # 指定美東日期
    python scrape.py --replay            # 不連網，用 index.html 內嵌資料重新產生頁面
    python scrape.py --offline samples --date 2026-10-13 --include-preseason
                                         # 用 samples/ 的離線頁面測試（不寫 history）
"""
import argparse
import glob
import html
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

APP_VERSION = "1.5"

# 不設樣本下限（使用者 2026-10-20）：情境趨勢 4-0 都算，全場趨勢 7-0 卻不算並不一致；
# 小樣本由 Wilson 下界自行打折（7-0 → 81.0）。MLB 仍維持 8 場。
MIN_TREND_SAMPLE = 1
TOP_PICK_MIN_SCORE = 50    # 低於 50 分不進任何精選清單（與 MLB 相同）
SCOREBOARD_LOOKBACK = 7    # 往回抓幾天的計分板（算休息天數、前一場勝負、回填賽果）
TRACK_RECENT_DAYS = 30
HISTORY_PATH = "history.json"
SCORES_PATH = "scores.json"

COVERS = "https://www.covers.com"

# 離線測試用：設定後 fetch_url 改讀這個資料夾裡的檔案（見 _offline_file）
OFFLINE_DIR = None


# ==========================================
# 統計
# ==========================================
def wilson_lower_bound(wins, n, z=1.28):
    """命中率的 Wilson 90% 信賴下界。小樣本的高命中率會被自然壓低。"""
    if not n:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - margin) / denom


def pct(x):
    return round(x * 100, 1)


# ==========================================
# 球隊資料（以 covers 的 nickname 為 key，最穩定）
# ==========================================
# nickname: (簡稱, 全名, 主場城市中文, 主場時區)
TEAMS = {
    'hawks': ('老鷹', '亞特蘭大老鷹', '亞特蘭大', 'America/New_York'),
    'celtics': ('塞爾提克', '波士頓塞爾提克', '波士頓', 'America/New_York'),
    'nets': ('籃網', '布魯克林籃網', '布魯克林', 'America/New_York'),
    'hornets': ('黃蜂', '夏洛特黃蜂', '夏洛特', 'America/New_York'),
    'bulls': ('公牛', '芝加哥公牛', '芝加哥', 'America/Chicago'),
    'cavaliers': ('騎士', '克里夫蘭騎士', '克里夫蘭', 'America/New_York'),
    'mavericks': ('獨行俠', '達拉斯獨行俠', '達拉斯', 'America/Chicago'),
    'nuggets': ('金塊', '丹佛金塊', '丹佛', 'America/Denver'),
    'pistons': ('活塞', '底特律活塞', '底特律', 'America/Detroit'),
    'warriors': ('勇士', '金州勇士', '舊金山', 'America/Los_Angeles'),
    'rockets': ('火箭', '休士頓火箭', '休士頓', 'America/Chicago'),
    'pacers': ('溜馬', '印第安納溜馬', '印第安納波利斯', 'America/Indiana/Indianapolis'),
    'clippers': ('快艇', '洛杉磯快艇', '洛杉磯', 'America/Los_Angeles'),
    'lakers': ('湖人', '洛杉磯湖人', '洛杉磯', 'America/Los_Angeles'),
    'grizzlies': ('灰熊', '曼菲斯灰熊', '曼菲斯', 'America/Chicago'),
    'heat': ('熱火', '邁阿密熱火', '邁阿密', 'America/New_York'),
    'bucks': ('公鹿', '密爾瓦基公鹿', '密爾瓦基', 'America/Chicago'),
    'timberwolves': ('灰狼', '明尼蘇達灰狼', '明尼亞波利斯', 'America/Chicago'),
    'pelicans': ('鵜鶘', '紐奧良鵜鶘', '紐奧良', 'America/Chicago'),
    'knicks': ('尼克', '紐約尼克', '紐約', 'America/New_York'),
    'thunder': ('雷霆', '奧克拉荷馬雷霆', '奧克拉荷馬市', 'America/Chicago'),
    'magic': ('魔術', '奧蘭多魔術', '奧蘭多', 'America/New_York'),
    '76ers': ('76人', '費城76人', '費城', 'America/New_York'),
    'suns': ('太陽', '鳳凰城太陽', '鳳凰城', 'America/Phoenix'),
    'trail blazers': ('拓荒者', '波特蘭拓荒者', '波特蘭', 'America/Los_Angeles'),
    'kings': ('國王', '沙加緬度國王', '沙加緬度', 'America/Los_Angeles'),
    'spurs': ('馬刺', '聖安東尼奧馬刺', '聖安東尼奧', 'America/Chicago'),
    'raptors': ('暴龍', '多倫多暴龍', '多倫多', 'America/Toronto'),
    'jazz': ('爵士', '猶他爵士', '鹽湖城', 'America/Denver'),
    'wizards': ('巫師', '華盛頓巫師', '華盛頓', 'America/New_York'),
}

# covers 「meetings in <City>」用的是英文城市名
CITY_ZH = {
    'atlanta': '亞特蘭大', 'boston': '波士頓', 'brooklyn': '布魯克林', 'charlotte': '夏洛特',
    'chicago': '芝加哥', 'cleveland': '克里夫蘭', 'dallas': '達拉斯', 'denver': '丹佛',
    'detroit': '底特律', 'golden state': '金州', 'san francisco': '舊金山', 'houston': '休士頓',
    'indiana': '印第安納', 'indianapolis': '印第安納波利斯', 'los angeles': '洛杉磯',
    'l.a.': '洛杉磯', 'la': '洛杉磯', 'memphis': '曼菲斯', 'miami': '邁阿密',
    'milwaukee': '密爾瓦基', 'minnesota': '明尼蘇達', 'minneapolis': '明尼亞波利斯',
    'new orleans': '紐奧良', 'new york': '紐約', 'oklahoma city': '奧克拉荷馬市',
    'orlando': '奧蘭多', 'philadelphia': '費城', 'phoenix': '鳳凰城', 'portland': '波特蘭',
    'sacramento': '沙加緬度', 'san antonio': '聖安東尼奧', 'toronto': '多倫多', 'utah': '猶他',
    'salt lake city': '鹽湖城', 'washington': '華盛頓',
}


def team_short(nick):
    return TEAMS.get(nick, (nick.title(),))[0]


def team_full(nick):
    t = TEAMS.get(nick)
    return t[1] if t else nick.title()


# ==========================================
# 時間
# ==========================================
def _tz(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


ET = _tz('America/New_York')
TW = timezone(timedelta(hours=8))


def eastern_today():
    now = datetime.now(timezone.utc)
    if ET:
        return now.astimezone(ET).date()
    return (now - timedelta(hours=4)).date()


def parse_start_utc(html_str):
    """
    單場頁 schema.org 的 startDate（UTC）。covers 有兩種寫法，兩種都要認：
    `10/14/2026 00:00:00 +00:00` 與 ISO `2026-10-13T23:00:00+00:00`。
    抓不到回 None——呼叫端要把 None 當「不知道」，不是「不符」。
    """
    hit = re.search(r'"startDate"\s*:\s*"([^"]+)"', html_str or '')
    if not hit:
        return None
    raw = html.unescape(hit.group(1)).strip()
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})', raw)
    try:
        if m:
            mo, d, y, hh, mm, ss = (int(x) for x in m.groups())
            return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})', raw)
        if m:
            y, mo, d, hh, mm, ss = (int(x) for x in m.groups())
            return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
    except ValueError:
        return None
    return None


def et_time_to_utc(date_str, et_label):
    """列表上的 "7:00 PM ET" + 美東日期 → UTC datetime。"""
    m = re.match(r'(\d{1,2}):(\d{2})\s*([AP]M)', et_label or '', re.I)
    if not m:
        return None
    hh, mm = int(m.group(1)) % 12, int(m.group(2))
    if m.group(3).upper() == 'PM':
        hh += 12
    y, mo, d = (int(x) for x in date_str.split('-'))
    if ET:
        local = datetime(y, mo, d, hh, mm, tzinfo=ET)
    else:
        local = datetime(y, mo, d, hh, mm, tzinfo=timezone(timedelta(hours=-4)))
    return local.astimezone(timezone.utc)


def fmt_local(utc_dt, tzname):
    tz = _tz(tzname)
    if not utc_dt or not tz:
        return None
    t = utc_dt.astimezone(tz)
    h12 = t.hour % 12 or 12
    return f"{h12}:{t.minute:02d} {'PM' if t.hour >= 12 else 'AM'}"


def fmt_taiwan(utc_dt):
    if not utc_dt:
        return None
    t = utc_dt.astimezone(TW)
    return f"{t.month}/{t.day} {t.hour:02d}:{t.minute:02d}"


# ==========================================
# 網路
# ==========================================
def _offline_file(url):
    """離線測試：把 covers 網址對應到 samples/ 裡的檔名。"""
    m = re.search(r'matchups\?selectedDate=(\d{4}-\d{2}-\d{2})', url)
    if m:
        path = os.path.join(OFFLINE_DIR, f'list_{m.group(1)}.html')
        return path if os.path.exists(path) else None
    m = re.search(r'/matchup/(\d+)/picks', url)
    if m:
        hits = glob.glob(os.path.join(OFFLINE_DIR, f'matchup_*_{m.group(1)}_picks.html'))
        return hits[0] if hits else None
    return None


def fetch_url(url, max_retries=3, backoff_factor=3.0):
    """
    抓網頁。退避 3s / 9s，優先聽 Retry-After（理由見 MLB CLAUDE.md「網路抓取的韌性」）。
    """
    if OFFLINE_DIR:
        path = _offline_file(url)
        if not path:
            return None
        with open(path, encoding='utf-8') as f:
            return f.read()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,zh-TW;q=0.8',
    }
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode('utf-8', errors='ignore')
            time.sleep(1)
            return body
        except Exception as e:
            if attempt >= max_retries - 1:
                print(f"  [錯誤] 嘗試 {max_retries} 次後仍無法抓取 {url}: {e}")
                return None
            wait = backoff_factor ** (attempt + 1)
            retry_after = getattr(e, 'headers', None) and e.headers.get('Retry-After')
            if retry_after:
                try:
                    wait = max(wait, min(float(retry_after), 60.0))
                except (TypeError, ValueError):
                    pass
            print(f"  [警告] 抓取 {url} 失敗 ({e})，{wait:.0f} 秒後重試")
            time.sleep(wait)


# ==========================================
# 賽事列表（同時也是計分板）
# ==========================================
_ARTICLE_RE = re.compile(r'<article\s+[^>]*class="[^"]*\bgamebox\b[^"]*"[^>]*>.*?</article>', re.S | re.I)
# 比分：要求原本所有語意 token（team-score + d-xl-inline-block=桌機版），只容許額外或重排。
# 拿掉 d-xl-inline-block 會把手機版重複的比分也抓進來（見 MLB CLAUDE.md 第 10 點）。
_SCORE_RE = re.compile(
    r'<strong[^>]*\bclass="(?=[^"]*\bteam-score\b)(?=[^"]*\bd-xl-inline-block\b)[^"]*"[^>]*>'
    r'\s*(\d+)\s*</strong>', re.I)
# 例行賽的共識盤口旁邊會多一個下注比例 <strong>38%</strong>（季前賽沒有），所以先取整個 span
# 再拿掉 <strong> 才解析數字。2026-10-20 開幕前發現：舊寫法要求 span 內沒有任何標籤，
# 例行賽每一場都會讀不到讓分 → 整個讓分市場被靜默跳過。
_SPREAD_RE = re.compile(
    r'<span[^>]*\bclass="(?=[^"]*\bteam-consensus\b)[^"]*"[^>]*>(.*?)</span>', re.I | re.S)
_OU_RE = re.compile(
    r'<span[^>]*\bclass="(?=[^"]*\bteam-overunder\b)[^"]*"[^>]*>\s*o/u\s*([\d.]+)', re.I)


def _attr(art, name):
    m = re.search(r'\bdata-%s=(?:"([^"]*)"|([^\s>]*(?:\s(?!data-)[^\s>=]+)*))' % re.escape(name), art)
    if not m:
        return ''
    return html.unescape((m.group(1) if m.group(1) is not None else m.group(2)) or '').strip().lower()


def _num(text):
    text = html.unescape(text or '').replace('+', '').strip()
    m = re.search(r'-?\d+(?:\.\d+)?|\bPK\b|\bPICK\b|\bEVEN\b', text, re.I)
    text = m.group(0) if m else text
    if text.upper() in ('PK', 'PICK', "PICK'EM", 'EVEN'):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def parse_gameboxes(html_str):
    """
    解析 covers 賽事列表的每一個 gamebox。賽前的 box 有開賽時間與共識盤口，
    已完賽的有比分與「誰過了讓分」的摘要。季前賽在標頭寫 "Pre Season"。
    """
    games = []
    for art in _ARTICLE_RE.findall(html_str or ''):
        gid = re.search(r'data-url=["\']?/sports/game/(\d+)', art)
        if not gid:
            continue
        g = {
            'gid': gid.group(1),
            'away_short': _attr(art, 'away-team-shortname'),
            'home_short': _attr(art, 'home-team-shortname'),
            'away': _attr(art, 'away-team-nickname'),
            'home': _attr(art, 'home-team-nickname'),
            'away_disp': _attr(art, 'away-team-displayname'),
            'home_disp': _attr(art, 'home-team-displayname'),
            'away_full': _attr(art, 'away-team-fullname'),
            'home_full': _attr(art, 'home-team-fullname'),
        }
        header = re.search(r'gamebox-header.*?</p>', art, re.S)
        g['preseason'] = bool(header and re.search(r'Pre\s*Season', header.group(0), re.I))

        t = re.search(r'(\d{1,2}:\d{2}\s*[AP]M)\s*ET', art, re.I)
        g['game_time'] = f"{t.group(1).upper()} ET" if t else None

        spreads = [_num(re.sub(r'<strong[^>]*>.*?</strong>|<[^>]+>', ' ', s, flags=re.S))
                   for s in _SPREAD_RE.findall(art)]
        if _SPREAD_RE.findall(art) and None in spreads:
            print(f"  [!] 警告：{g['gid']} 讀不到讓分數字: {[_text(x) for x in _SPREAD_RE.findall(art)]}")
        if len(spreads) == 2 and None not in spreads and abs(spreads[0] + spreads[1]) < 1e-9:
            g['spread_away'], g['spread_home'] = spreads
        else:
            g['spread_away'] = g['spread_home'] = None
        ou = _OU_RE.search(art)
        g['total'] = float(ou.group(1)) if ou else None

        g['final'] = bool(re.search(r'post-game-status[^>]*>\s*Final', art, re.I))
        g['away_score'] = g['home_score'] = None
        g['cover'] = None
        if g['final']:
            nums = _SCORE_RE.findall(art)
            if len(nums) == 2:
                g['away_score'], g['home_score'] = int(nums[0]), int(nums[1])
            elif len(nums) > 2:
                # 一場只該有兩個比分；多了代表 covers 改版，寧可不記也不要記錯
                print(f"  [!] 警告：{g['gid']} 抓到 {len(nums)} 個比分（應為 2），略過")
            summ = re.search(r'summary-box[^>]*>(.*?)</p>', art, re.S)
            if summ:
                s = re.sub(r'<[^>]+>', '', summ.group(1))
                s = html.unescape(re.sub(r'\s+', ' ', s)).strip()
                g['summary'] = s
                if re.search(r'\bpush', s, re.I):
                    g['cover'] = 'push'
                else:
                    cm = re.search(r'^(.+?) covered the spread', s, re.I)
                    if cm:
                        who = cm.group(1).strip().lower()
                        if who in (g['away_disp'], g['away']):
                            g['cover'] = 'away'
                        elif who in (g['home_disp'], g['home']):
                            g['cover'] = 'home'
        games.append(g)
    return games


def fetch_list(date_str):
    return fetch_url(f"{COVERS}/sports/nba/matchups?selectedDate={date_str}")


# ==========================================
# 計分板快取（scores.json）
# ==========================================
def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')


def update_scoreboard(scores, today_str):
    """
    補齊今天之前 SCOREBOARD_LOOKBACK 天的計分板。一天一次請求，已經全部打完的日子不再重抓。
    用途：(1) 算情境條件（休息天數、前一場勝負與得失分、前一場有沒有過盤）
          (2) 回填推薦的賽果
    """
    today = date.fromisoformat(today_str)
    for back in range(1, SCOREBOARD_LOOKBACK + 1):
        d = (today - timedelta(days=back)).isoformat()
        day = scores.get(d)
        if day and day.get('complete'):
            continue
        body = fetch_list(d)
        if body is None:
            continue
        games = parse_gameboxes(body)
        keep = ['gid', 'away', 'home', 'away_score', 'home_score', 'final', 'preseason', 'cover',
                'spread_away']
        rows = [{k: g.get(k) for k in keep} for g in games]
        n_final = sum(1 for g in rows if g['final'])
        n_scored = sum(1 for g in rows if g['away_score'] is not None)
        if n_final and not n_scored:
            print(f"  [!] 警告：{d} 有 {n_final} 場 Final 卻抓不到比分，covers 可能改了標記")
        scores[d] = {'complete': bool(rows) and all(g['final'] for g in rows) and n_scored == n_final,
                     'games': rows}
        print(f"  [計分板] {d}: {len(rows)} 場，完賽 {n_final}，有比分 {n_scored}")
    # 只留近 60 天，避免檔案無限長大（回填只需要 RESULT 那幾天）
    cutoff = (today - timedelta(days=60)).isoformat()
    for d in [d for d in scores if d < cutoff]:
        del scores[d]
    return scores


def previous_game(scores, nick, today_str):
    """
    該隊今天之前最近一場**例行賽**完賽紀錄。找不到、或最近一場是季前賽 → None（不知道）。
    """
    for d in sorted(scores, reverse=True):
        if d >= today_str:
            continue
        for g in scores[d].get('games', []):
            if nick not in (g.get('away'), g.get('home')):
                continue
            if g.get('preseason') or not g.get('final') or g.get('away_score') is None:
                return None
            home = g['home'] == nick
            pf = g['home_score'] if home else g['away_score']
            pa = g['away_score'] if home else g['home_score']
            cover = g.get('cover')
            if cover == 'push':
                covered = 'push'
            elif cover in ('away', 'home'):
                covered = (cover == 'home') == home
            else:
                covered = None
            rest = (date.fromisoformat(today_str) - date.fromisoformat(d)).days - 1
            return {'date': d, 'home': home, 'pf': pf, 'pa': pa, 'won': pf > pa,
                    'margin': pf - pa, 'covered': covered, 'rest': rest}
    return None


# ==========================================
# 單場頁面
# ==========================================
_ROI_PAREN_RE = re.compile(r'\s*\([^()]*\b(?:Units?|ROI)\b[^()]*\)')


def strip_roi_text(text):
    """Units/ROI 是美國賠率算的，對台灣運彩沒有意義，全站不顯示（見 MLB CLAUDE.md）。"""
    return _ROI_PAREN_RE.sub('', text).strip()


def _text(fragment):
    s = re.sub(r'<[^>]+>', ' ', fragment)
    return html.unescape(re.sub(r'\s+', ' ', s)).strip()


def parse_matchup_page(body, game):
    """
    解析單場 /picks 頁：ROI 趨勢、Recent Form（情境趨勢）、開賽時間、主場城市。
    回傳 None 代表頁面不是這一場（例如被導到通用頁），呼叫端當成抓取失敗。
    """
    # 確認頁面真的是這一場。賽前頁有 schema.org 的 homeTeam/awayTeam；已完賽頁沒有，
    # 改看 og:title（"Thunder vs Hawks Prediction..."）。實測有些網址會被導到 Odds Shark
    # 的通用頁，兩者都對不上 → 當成抓取失敗，不要拿別的頁面的趨勢來算。
    home_m = re.search(r'"homeTeam"\s*:\s*\{[^{}]*?"name"\s*:\s*"([^"]+)"', body)
    away_m = re.search(r'"awayTeam"\s*:\s*\{[^{}]*?"name"\s*:\s*"([^"]+)"', body)
    if home_m and away_m:
        home_name, away_name = html.unescape(home_m.group(1)), html.unescape(away_m.group(1))
        ok = game['home'] in home_name.lower() and game['away'] in away_name.lower()
    else:
        og = re.search(r'<meta property="og:title" content="([^"]*)"', body)
        title = html.unescape(og.group(1)).lower() if og else ''
        ok = game['home'] in title and game['away'] in title
        home_name, away_name = game['home_full'], game['away_full']
    if not ok:
        print(f"  [!] 頁面不是 {game['away']} @ {game['home']} 這一場，略過")
        return None

    city = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', body)
    sec = re.search(r'<section[^>]*\bid="trends"[^>]*>(.*?)</section>', body, re.S)
    trends_html = sec.group(1) if sec else ''
    heads = re.findall(r'<h4[^>]*\bclass="(?:[^"]*\s)?(High|Low)(?:\s[^"]*)?"[^>]*>(.*?)</h4>',
                       trends_html, re.S)
    roi = [{'class': c, 'text': strip_roi_text(_text(t))} for c, t in heads]
    if not roi and 'Units' in trends_html:
        # 解析壞掉與「尚未發佈」症狀一樣都是 0 條，必須喊出來（MLB CLAUDE.md 第 10 點）
        print(f"  [!] 警告：{game['gid']} 趨勢區有 Units 卻抓到 0 條，covers 可能改了標記")
        for tag in re.findall(r'<h4[^>]*>', trends_html)[:3]:
            print(f"      實際 h4: {tag}")
    rf = [_text(x) for x in re.findall(
        r'<p[^>]*\bclass="(?:[^"]*\s)?single-form-trend(?:\s[^"]*)?"[^>]*>(.*?)</p>', body, re.S)]
    return {
        'home_name': home_name, 'away_name': away_name,
        'city': city.group(1).strip() if city else None,
        'start_utc': parse_start_utc(body),
        'roi_raw': roi,
        'rf_raw': rf,
        'trends_published': 'Check back shortly' not in trends_html,
    }


# ==========================================
# ROI 趨勢（計分用）
# ==========================================
# 盤口名一律完全比對：`1Q Spread` 不可以被 `Spread` 吃掉。只做全場盤（使用者不下半場／單節）。
ROI_MARKETS = {
    'Moneyline': ('Moneyline', None),
    'Spread': ('Spread', None),
    'Game Total Over': ('Total', 'Over'),
    'Game Total Under': ('Total', 'Under'),
}
_ROI_RE = re.compile(
    r'^The (?P<team>.+?) have (?P<neg>not )?(?P<only>only )?(?:hit|covered) the (?P<market>.+?) '
    r'in (?:(?P<w>\d+) of |any of )?(?:their|the) last (?P<n>\d+) ?(?P<scope>.*?)\.?$')
ROI_SCOPE_ZH = {
    'games': '', '': '', 'away games': '客場', 'road games': '客場', 'home games': '主場',
    'games at home': '主場', 'games on the road': '客場', 'games away': '客場',
}
ROI_SCOPE_VENUE = {
    'games': None, '': None, 'away games': 'road', 'road games': 'road', 'games away': 'road',
    'games on the road': 'road', 'home games': 'home', 'games at home': 'home',
}
MARKET_ZH = {'Moneyline': '獨贏', 'Spread': '讓分', 'Game Total Over': '大分', 'Game Total Under': '小分'}


def parse_roi_trend(item, game, page):
    """
    回傳 None 代表不是全場盤（或句型認不得）。樣本四種寫法：
    `in N of their last M`、`in their last M`(全勝)、`not ... in any of their last M`(掛零)。
    ⚠️ 沒有分子不是「解析不到」而是全勝（MLB CLAUDE.md 第 3 點）。
    """
    m = _ROI_RE.match(item['text'])
    if not m or m.group('market') not in ROI_MARKETS:
        return None
    name = m.group('team').lower()
    if name == page['home_name'].lower() or game['home'] in name:
        side = 'home'
    elif name == page['away_name'].lower() or game['away'] in name:
        side = 'away'
    else:
        return None
    n = int(m.group('n'))
    if m.group('neg'):
        w = 0
    elif m.group('w'):
        w = int(m.group('w'))
    else:
        w = n
    if w > n:
        return None
    market, direction = ROI_MARKETS[m.group('market')]
    scope = m.group('scope').strip()
    scope_zh = ROI_SCOPE_ZH.get(scope)
    nick = game[side]
    zh = None
    if scope_zh is not None:
        zh = f"{team_short(nick)} 近 {n} 場{scope_zh}{MARKET_ZH[m.group('market')]}過盤 {w} 場"
    venue = ROI_SCOPE_VENUE.get(scope, 'unknown')
    if venue == 'unknown':
        applies = None
    else:
        applies = venue is None or (venue == 'home') == (side == 'home')
    return {'side': side, 'class': item['class'], 'market': market, 'direction': direction,
            'w': w, 'n': n, 'text': item['text'], 'text_zh': zh,
            'key': (venue, None, ''), 'applies': applies}


def roi_support(t, side_or_dir):
    """
    這條趨勢對「某隊過盤」或「某方向（Over/Under）」的支持紀錄 (k, n)。
    "only hit the Game Total Over in 12 of 40" 等於小分 28/40。
    """
    if t['market'] == 'Total':
        return (t['w'], t['n']) if t['direction'] == side_or_dir else (t['n'] - t['w'], t['n'])
    return (t['w'], t['n']) if t['side'] == side_or_dir else (t['n'] - t['w'], t['n'])


# ==========================================
# 情境趨勢（covers 的 Recent Form）
# ==========================================
_RF_TEAM_RE = re.compile(
    r'^(?P<team>.+?) are (?P<w>\d+)-(?P<l>\d+)(?:-(?P<p>\d+))? (?:(?P<ats>ATS) )?'
    r'in (?:their|the) last (?P<n>\d+) ?(?P<cond>.*?)\.?$')
_RF_TOTAL_RE = re.compile(
    r'^(?P<ou>Over|Under) is (?P<w>\d+)-(?P<l>\d+)(?:-(?P<p>\d+))? '
    r'in (?:the last|(?P<team>.+?) last) (?P<n>\d+) ?(?P<cond>.*?)\.?$')


def _nick_side(name, game):
    name = (name or '').strip().lower()
    if name == game['home'] or name.endswith(game['home']):
        return 'home'
    if name == game['away'] or name.endswith(game['away']):
        return 'away'
    return None


def _cond_text(cond):
    c = re.sub(r'\s+', ' ', cond.strip().lower())
    c = re.sub(r'^games\s*', '', c)
    c = re.sub(r'\s*games$', '', c)
    return c


_PTS_RE = re.compile(
    r'^(?P<who>after|when their opponent) (?P<verb>allowing|allows|scoring|scores) '
    r'(?:(?P<cmp1>more|less) than (?P<v1>\d+) points?|(?P<v2>\d+) points? or (?P<cmp2>more|less))'
    r'(?: in their previous game)?$')


def condition_applies(cond, side, game, ctx):
    """
    這個情境條件今天成立嗎？True / False / None(無法確認)。

    ⚠️ covers 會把**今天不成立**的條件也列出來（同一頁同時有公鹿「客場當熱門」與「客場當冷門」）。
    只有回傳 True 的才可以參與計分，否則等於拿別種比賽的紀錄下注。
    """
    c = _cond_text(cond)
    if c in ('', 'overall'):
        return True
    m = re.match(r'^meetings(?: in (.+))?$', c)
    if m:
        if not m.group(1):
            return True
        city = (ctx.get('city') or '').lower()
        if not city:
            return None
        return m.group(1).strip() == city
    if side is None:
        return None
    is_home = side == 'home'
    m = re.match(r'^(home|road|away)$', c) or re.match(r'^(?:games )?(at home|on the road)$', c)
    if m:
        want_home = m.group(1) in ('home', 'at home')
        return want_home == is_home
    m = re.match(r'^as an? (?:(home|road) )?(favorite|underdog)$', c)
    if m:
        if m.group(1) and (m.group(1) == 'home') != is_home:
            return False
        spread = game.get('spread_home' if is_home else 'spread_away')
        if spread is None:
            return None
        if spread == 0:
            return False
        return (spread < 0) == (m.group(2) == 'favorite')
    m = re.match(r'^(?:games )?(?:on |played on )?an? ?(%s)s?$' % '|'.join(WEEKDAYS), c) or \
        re.match(r'^(?:on )?(%s)s?$' % '|'.join(WEEKDAYS), c)
    if m:
        wd = ctx.get('weekday')
        return None if wd is None else WEEKDAYS.index(m.group(1)) == wd
    prev = ctx.get('prev', {}).get(side)
    opp_prev = ctx.get('prev', {}).get('away' if is_home else 'home')
    m = re.match(r'^playing on (\d+) days? rest$', c)
    if m:
        return None if prev is None else prev['rest'] == int(m.group(1))
    m = re.match(r'^(?:following|after) an? (straight up|ats) (loss|win)(?: of more than (\d+) points?)?$', c)
    if m:
        if prev is None:
            return None
        if m.group(1) == 'ats':
            if prev['covered'] in (None, 'push'):
                return None if prev['covered'] is None else False
            ok = prev['covered'] == (m.group(2) == 'win')
        else:
            ok = prev['won'] == (m.group(2) == 'win')
        if ok and m.group(3):
            ok = abs(prev['margin']) > int(m.group(3))
        return ok
    m = re.match(r'^(?:following|after) an? double-digit (loss|win)(?: (at home|on the road))?$', c)
    if m:
        if prev is None:
            return None
        ok = prev['won'] == (m.group(1) == 'win') and abs(prev['margin']) >= 10
        if ok and m.group(2):
            ok = prev['home'] == (m.group(2) == 'at home')
        return ok
    m = _PTS_RE.match(c)
    if m:
        p = prev if m.group('who') == 'after' else opp_prev
        if p is None:
            return None
        pts = p['pa'] if m.group('verb').startswith('allow') else p['pf']
        if m.group('v1'):
            v = int(m.group('v1'))
            return pts > v if m.group('cmp1') == 'more' else pts < v
        v = int(m.group('v2'))
        return pts >= v if m.group('cmp2') == 'more' else pts <= v
    return None


def condition_zh(cond, ctx_city=None):
    """情境條件中譯；翻不出來回 None（前端顯示英文原文，寧可沒翻也不要翻錯）。"""
    c = _cond_text(cond)
    if c in ('', 'overall'):
        return ''
    if c == 'meetings':
        return '交手'
    m = re.match(r'^meetings in (.+)$', c)
    if m:
        return f"在{CITY_ZH.get(m.group(1).strip(), m.group(1).title())}交手"
    if c in ('home', 'at home', 'games at home'):
        return '主場'
    if c in ('road', 'away', 'on the road', 'games on the road'):
        return '客場'
    m = re.match(r'^as an? (?:(home|road) )?(favorite|underdog)$', c)
    if m:
        venue = {'home': '主場', 'road': '客場', None: ''}[m.group(1)]
        return f"{venue}當{'熱門（讓分方）' if m.group(2) == 'favorite' else '冷門（受讓方）'}"
    m = re.match(r'^(?:games )?(?:on |played on )?an? ?(%s)s?$' % '|'.join(WEEKDAYS), c) or \
        re.match(r'^(?:on )?(%s)s?$' % '|'.join(WEEKDAYS), c)
    if m:
        return WEEKDAY_ZH[WEEKDAYS.index(m.group(1))]
    m = re.match(r'^playing on (\d+) days? rest$', c)
    if m:
        return '背靠背（連兩天出賽）' if m.group(1) == '0' else f"休息 {m.group(1)} 天"
    m = re.match(r'^(?:following|after) an? (straight up|ats) (loss|win)(?: of more than (\d+) points?)?$', c)
    if m:
        what = ('過盤' if m.group(2) == 'win' else '沒過盤') if m.group(1) == 'ats' else \
               ('贏球' if m.group(2) == 'win' else '輸球')
        more = f"（{'贏' if m.group(2) == 'win' else '輸'}超過 {m.group(3)} 分）" if m.group(3) else ''
        return f"前一場{what}{more}後"
    m = re.match(r'^(?:following|after) an? double-digit (loss|win)(?: (at home|on the road))?$', c)
    if m:
        venue = {'at home': '主場', 'on the road': '客場', None: ''}[m.group(2)]
        return f"前一場{venue}{'贏' if m.group(1) == 'win' else '輸'} 10 分以上後"
    m = _PTS_RE.match(c)
    if m:
        who = '' if m.group('who') == 'after' else '對手'
        what = '失分' if m.group('verb').startswith('allow') else '得分'
        if m.group('v1'):
            rule = f"{'>' if m.group('cmp1') == 'more' else '<'} {m.group('v1')}"
        else:
            rule = f"{'≥' if m.group('cmp2') == 'more' else '≤'} {m.group('v2')}"
        return f"{who}前一場{what} {rule} 後"
    return None


WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
WEEKDAY_ZH = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']
_WEEKDAY_RE = re.compile(r'\b(%s)s?\b' % '|'.join(WEEKDAYS))


def cond_key(cond):
    """
    條件的配對鍵 (主客, 熱門冷門, 其他條件)。兩隊紀錄要條件互相對應才能配成一對：
    主↔客、熱門↔冷門對調，其他條件（休息天數、前一場輸贏…）要相同。兩隊交手回傳 'MEET'。
    """
    c = _cond_text(cond)
    if c.startswith('meetings'):
        return 'MEET'
    if c in ('', 'overall'):
        return (None, None, '')
    if c in ('home', 'at home'):
        return ('home', None, '')
    if c in ('road', 'away', 'on the road'):
        return ('road', None, '')
    m = re.match(r'^as an? (?:(home|road) )?(favorite|underdog)$', c)
    if m:
        return (m.group(1), m.group(2), '')
    # 休息天數不論幾天都算「休息」這一類（使用者 2026-10-20：A 休 1 天、B 休 2 天也算對應）
    if re.match(r'^playing on \d+ days? rest$', c):
        return (None, None, 'rest')
    if _WEEKDAY_RE.search(c):
        return (None, None, 'weekday')
    return (None, None, c)


_FLIP = {'home': 'road', 'road': 'home', 'favorite': 'underdog', 'underdog': 'favorite', None: None}


def mirror_key(key):
    return (_FLIP[key[0]], _FLIP[key[1]], key[2])


def parse_recent_form(raw, game, ctx):
    """
    情境趨勢逐條解析：主詞（哪一隊／兩隊交手）、市場（讓分 ATS／勝負 SU／大小分）、
    戰績、條件，以及**今天是否成立**。認不得的句子保留原文、只顯示不計分。
    """
    items = []
    for text in raw:
        item = {'text': text, 'text_zh': None, 'kind': None, 'side': None,
                'w': None, 'l': None, 'applies': None}
        m = _RF_TOTAL_RE.match(text)
        if m:
            item['kind'] = 'Total'
            item['direction'] = m.group('ou')
            item['side'] = _nick_side(m.group('team'), game) if m.group('team') else None
            if m.group('team') and item['side'] is None:
                item['kind'] = None
        else:
            m = _RF_TEAM_RE.match(text)
            if m:
                item['side'] = _nick_side(m.group('team'), game)
                item['kind'] = ('ATS' if m.group('ats') else 'SU') if item['side'] else None
        if not m or item['kind'] is None:
            items.append(item)
            continue
        item['w'], item['l'] = int(m.group('w')), int(m.group('l'))
        cond = m.group('cond')
        item['cond'] = cond
        item['applies'] = condition_applies(cond, item['side'], game, ctx)
        item['key'] = cond_key(cond)
        cz = condition_zh(cond)
        if cz is not None:
            who = team_short(game[item['side']]) if item['side'] else '兩隊'
            rec = f"{item['w']}勝{item['l']}負"
            n = item['w'] + item['l']
            if item['kind'] == 'Total':
                rec = f"{'大分' if item['direction'] == 'Over' else '小分'} {item['w']}-{item['l']}"
                label = f"{who}近 {n} 場{cz}" if item['side'] else (
                    f"兩隊近 {n} 次{cz}" if '交手' in cz else f"近 {n} 場{cz}")
            else:
                market = '讓分' if item['kind'] == 'ATS' else '勝負'
                label = f"{who}近 {n} 場{cz}" if '交手' not in cz else f"{who}近 {n} 次{cz}"
                rec = f"{market} {rec}"
            item['text_zh'] = f"{label}：{rec}"
        items.append(item)
    return items


def rf_support(item, target):
    """情境趨勢對 target（'home'/'away'/'Over'/'Under'）的支持紀錄 (k, n)。"""
    w, l = item['w'], item['l']
    if item['kind'] == 'Total':
        return (w, w + l) if item['direction'] == target else (l, w + l)
    return (w, w + l) if item['side'] == target else (l, w + l)


# ==========================================
# 推薦
# ==========================================
def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def paired_scores(records, support, target):
    """
    「條件相對應」的配對（使用者 2026-10-20）：A 隊的紀錄要配上 B 隊**對應條件**的紀錄才算數，
    例如 A「主場 8/10」配 B「客場 1/10」、A「休息 1 天 9/10」配 B「休息 1 天 1/10」。
    主↔客、熱門↔冷門對調，其他條件相同；休息天數不論幾天都算同一類、星期幾也算同一類（見 cond_key）。
    兩隊交手紀錄只顯示、不計分。

    每一對的分數 = (A 那組平均 + B 那組平均) / 2，每條換算成「對 target 有利」的下界。
    只用今天**確定成立**的紀錄（applies is True）。回傳 (每對分數清單, 用到的紀錄)。
    """
    rows = [r for r in records if r.get('applies') is True]
    groups, pairs, used = {}, [], []
    for r in rows:
        k = r.get('key')
        lb = wilson_lower_bound(*support(r, target))
        if k == 'MEET':
            continue   # 兩隊交手紀錄不計分（使用者 2026-10-20：要兩邊各自都有紀錄才算）
        groups.setdefault((r['side'], k), []).append((lb, r))
    for (side, k), a in groups.items():
        if side != 'away':
            continue
        b = groups.get(('home', mirror_key(k)))
        if not b:
            continue
        pairs.append((_mean([x for x, _ in a]) + _mean([x for x, _ in b])) / 2)
        used.extend(r for _, r in a + b)
    return pairs, used


def _rf_support(i, target):
    return rf_support(i, target)


def trend_score(roi, market, target):
    """只看全場趨勢的配對分數（記戰績比較用）。"""
    recs = [t for t in roi if t['market'] == market and t['n'] >= MIN_TREND_SAMPLE]
    pairs, used = paired_scores(recs, roi_support, target)
    return (pct(_mean(pairs)) if pairs else None), used


def situational_score(rf, kind, target):
    """只看情境趨勢的配對分數（記戰績比較用）。"""
    recs = [i for i in rf if i['kind'] == kind and (i['w'] or 0) + (i['l'] or 0) > 0]
    pairs, used = paired_scores(recs, _rf_support, target)
    return (pct(_mean(pairs)) if pairs else None), used


def pooled_score(roi, rf, market, kind, target):
    """
    推薦分數（網站實際用的）：全場趨勢的配對與情境趨勢的配對**權重相同**，所有配對取平均。
    不跨來源配對——全場只配全場、情境只配情境。沒有任何一對就不出推薦。
    """
    recs_t = [t for t in roi if t['market'] == market and t['n'] >= MIN_TREND_SAMPLE]
    recs_s = [i for i in rf if i['kind'] == kind and (i['w'] or 0) + (i['l'] or 0) > 0]
    p1, _ = paired_scores(recs_t, roi_support, target)
    p2, _ = paired_scores(recs_s, _rf_support, target)
    allp = p1 + p2
    return pct(_mean(allp)) if allp else None


def side_label(spread):
    if spread is None:
        return None
    if spread == 0:
        return '讓 0（PK）'
    v = f"{abs(spread):g}"
    return f"讓 {v}" if spread < 0 else f"受讓 {v}"


def margin_needed(rec):
    """押注隊至少要贏幾分才算過（受讓 ⊇ 獨贏 ⊇ 讓分，數字越小越容易中）。"""
    if rec['market'] == 'Moneyline':
        return 1
    return math.floor(-rec['line']) + 1


def build_recommendations(game, roi, rf):
    """
    每個市場算三種分數，各自選邊：
      combined（網站實際推薦）、trend（只看 ROI 趨勢）、sit（只看情境趨勢）
    後兩者只用來記戰績、比較兩種算法，畫面上的推薦一律是 combined。
    """
    out = []
    markets = [('Moneyline', 'SU', ('away', 'home')),
               ('Spread', 'ATS', ('away', 'home')),
               ('Total', 'Total', ('Over', 'Under'))]
    for market, kind, targets in markets:
        if market == 'Spread' and game.get('spread_home') is None:
            continue   # 沒有盤口數字就不出讓分推薦——少一筆，好過給一筆下不了的
        if market == 'Total' and game.get('total') is None:
            continue
        cands = []
        for target in targets:
            ts, t_rows = trend_score(roi, market, target)
            ss, s_rows = situational_score(rf, kind, target)
            cands.append({'target': target, 'trend': ts, 'sit': ss,
                          'combined': pooled_score(roi, rf, market, kind, target),
                          't_rows': t_rows, 's_rows': s_rows})
        for algo in ('combined', 'trend', 'sit'):
            scored = [c for c in cands if c[algo] is not None]
            if not scored:
                continue
            best = max(scored, key=lambda c: c[algo])
            rec = _make_rec(game, market, best, algo)
            out.append(rec)
    return out


def _make_rec(game, market, cand, algo):
    target = cand['target']
    rec = {'gid': game['gid'], 'market': market, 'algo': algo,
           'score': cand[algo], 'score_trend': cand['trend'], 'score_sit': cand['sit']}
    if market == 'Total':
        rec['direction'] = target
        rec['line'] = game['total']
        rec['bet_on'] = None
        rec['label'] = f"{'大' if target == 'Over' else '小'} {game['total']:g}"
        rec['text'] = f"買 全場{'大分' if target == 'Over' else '小分'}（{rec['label']}）"
    else:
        nick = game[target]
        rec['bet_on'] = target
        rec['bet_nick'] = nick
        if market == 'Moneyline':
            rec['line'] = None
            rec['label'] = '獨贏'
        else:
            rec['line'] = game['spread_home' if target == 'home' else 'spread_away']
            rec['label'] = side_label(rec['line'])
        rec['text'] = f"買 {team_short(nick)} {rec['label']}"
    rec['trend_rows'] = [t['text_zh'] or t['text'] for t in cand['t_rows']][:6]
    rec['sit_rows'] = [i['text_zh'] or i['text'] for i in cand['s_rows']][:8]
    return rec


def dedupe_same_team(recs):
    """
    同場同隊只留**最容易中**的那筆：受讓 ⊇ 獨贏 ⊇ 讓分 是邏輯上的包含關係。
    分數跨市場不可比，不能拿來做同隊取捨（MLB 實測比分數會選錯邊 25/103 次）。
    """
    best = {}
    for r in recs:
        key = (r['gid'], r['bet_on'])
        rank = (margin_needed(r), -(r['score'] or 0))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, r)
    return [r for _rank, r in best.values()]


def build_top_lists(recs):
    picks = [r for r in recs if r['algo'] == 'combined' and (r['score'] or 0) >= TOP_PICK_MIN_SCORE]
    sides = dedupe_same_team([r for r in picks if r['market'] != 'Total'])
    totals = [r for r in picks if r['market'] == 'Total']
    key = lambda r: (-r['score'], r['gid'], r['market'])
    top_sides = sorted(sides, key=key)[:5]
    top_totals = sorted(totals, key=key)[:5]
    # AI Top 5：同一場的勝負推薦最多一筆（MLB 2026-09-08 使用者要求），大小分是不同市場另計
    ai, seen = [], set()
    for r in sorted(sides + totals, key=key):
        k = (r['gid'], r['market'] == 'Total')
        if k in seen:
            continue
        seen.add(k)
        ai.append(r)
        if len(ai) == 5:
            break
    return ai, top_sides, top_totals


def _rec_id(r):
    return (r['gid'], r['market'], r.get('bet_on'), r.get('direction'))


# ==========================================
# 戰績（history.json）
# ==========================================
def record_day(history, date_str, games, recs, ai, top_sides, top_totals):
    """同一天會被後面幾輪覆蓋：使用者晚上看到的是最後一輪，戰績就以那份為準。"""
    ids = {name: {_rec_id(r) for r in lst}
           for name, lst in (('ai', ai), ('sides', top_sides), ('totals', top_totals))}
    rows = []
    for r in recs:
        row = {k: r.get(k) for k in ('gid', 'market', 'algo', 'bet_on', 'direction', 'line',
                                      'score', 'score_trend', 'score_sit')}
        if r['algo'] == 'combined':
            rid = _rec_id(r)
            row['top_ai'] = rid in ids['ai']
            row['top_sides'] = rid in ids['sides']
            row['top_totals'] = rid in ids['totals']
        rows.append(row)
    old = history.get(date_str, {})
    history[date_str] = {
        'games': {g['gid']: {'away': g['away'], 'home': g['home']} for g in games},
        'picks': rows,
        'results': old.get('results', {}),
    }


def backfill_results(history, scores, today_str):
    for d, day in history.items():
        if d >= today_str:
            continue
        sb = {g['gid']: g for g in scores.get(d, {}).get('games', [])}
        for gid in day.get('games', {}):
            g = sb.get(gid)
            if g and g.get('final') and g.get('away_score') is not None:
                day.setdefault('results', {})[gid] = {'away': g['away_score'], 'home': g['home_score']}


def judge(pick, result):
    if not result:
        return None
    a, h = result['away'], result['home']
    if pick['market'] == 'Total':
        if pick.get('line') is None:
            return None
        tot = a + h
        if tot == pick['line']:
            return None
        return (tot > pick['line']) == (pick['direction'] == 'Over')
    margin = (h - a) if pick['bet_on'] == 'home' else (a - h)
    if pick['market'] == 'Moneyline':
        return margin > 0
    if pick.get('line') is None:
        return None
    v = margin + pick['line']
    return None if v == 0 else v > 0


def market_bucket(p):
    if p['market'] == 'Total':
        return '大分' if p['direction'] == 'Over' else '小分'
    if p['market'] == 'Moneyline':
        return '獨贏'
    return '讓分' if (p.get('line') or 0) < 0 else '受讓'


def compute_track_record(history, today_str):
    recent_cut = (date.fromisoformat(today_str) - timedelta(days=TRACK_RECENT_DAYS)).isoformat()

    def blank():
        return {'all': [0, 0], 'recent': [0, 0]}

    def add(bucket, ok, d):
        bucket['all'][1] += 1
        bucket['all'][0] += ok
        if d >= recent_cut:
            bucket['recent'][1] += 1
            bucket['recent'][0] += ok

    ai = blank()
    by_market = {k: blank() for k in ('獨贏', '受讓', '讓分', '大分', '小分')}
    algos = {'combined': blank(), 'trend': blank(), 'sit': blank()}
    days = 0
    for d in sorted(history):
        if d >= today_str:
            continue
        day = history[d]
        res = day.get('results', {})
        if res:
            days += 1
        for p in day.get('picks', []):
            ok = judge(p, res.get(p['gid']))
            if ok is None:
                continue
            if (p.get('score') or 0) >= TOP_PICK_MIN_SCORE:
                add(algos[p['algo']], ok, d)
            if p['algo'] == 'combined' and p.get('top_ai'):
                add(ai, ok, d)
                add(by_market[market_bucket(p)], ok, d)
    return {'ai': ai, 'by_market': by_market, 'algos': algos, 'days': days}


# ==========================================
# HTML
# ==========================================
CSS = """
:root{--bg:#0f1420;--card:#171e2e;--card2:#1e2638;--line:#2a3448;--text:#e8ecf3;--dim:#94a0b8;
--accent:#ff7a1a;--green:#2fbf71;--yellow:#e6b422;--gray:#6b7489;--red:#e5534b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:"Noto Sans TC",-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif;line-height:1.5}
.wrap{max-width:960px;margin:0 auto;padding:16px}
header{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin-bottom:12px}
h1{font-size:22px;margin:0}
h1 small{font-size:12px;color:var(--accent);margin-left:6px;font-weight:600}
.badge{background:var(--card2);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:13px}
.badge b{color:var(--accent)}
.notice{background:#2b2410;border:1px solid #6b5514;color:#ffd98a;border-radius:10px;padding:10px 12px;margin:10px 0;font-size:14px}
.legend{font-size:12.5px;color:var(--dim);margin:8px 0 16px}
.legend span{white-space:nowrap;margin-right:10px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px;vertical-align:middle}
.g{background:var(--green)}.y{background:var(--yellow)}.n{background:var(--gray)}
section.box{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}
section.box h2{font-size:16px;margin:0 0 10px}
.tops{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.tops>section{min-width:0;margin:0}
ol.picks{list-style:none;margin:0;padding:0}
ol.picks li{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line);min-width:0}
ol.picks li:first-child{border-top:0}
.rank{color:var(--dim);font-weight:700;width:18px;flex:none}
.pinfo{flex:1;min-width:0}
.pmatch{font-size:12px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pbet{font-weight:700}
.score{flex:none;font-weight:800;font-size:15px;padding:2px 8px;border-radius:8px;background:var(--card2)}
.score.g{color:var(--green);background:#13301f}.score.y{color:var(--yellow);background:#33290f}.score.n{color:var(--dim)}
.sub{font-size:11.5px;color:var(--dim)}
.empty{color:var(--dim);font-size:14px;padding:6px 0}
.game{background:var(--card);border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden}
.ghead{padding:12px 14px;display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px 12px;cursor:pointer}
.teams{font-weight:800;font-size:16px}
.teams .at{color:var(--dim);font-weight:400;margin:0 6px}
.meta{font-size:12.5px;color:var(--dim)}
.lines{font-size:12.5px;color:var(--dim);width:100%}
.recs{padding:0 14px 12px}
.rec{background:var(--card2);border-radius:10px;padding:9px 11px;margin-top:8px;display:flex;gap:10px;align-items:center}
.rec .pinfo{min-width:0}
.detail{display:none;border-top:1px solid var(--line);padding:12px 14px}
.game.open .detail{display:block}
.detail h3{font-size:14px;margin:4px 0 6px}
.detail ul{margin:0 0 10px;padding-left:18px;font-size:13.5px}
.detail li{margin:3px 0}
.ap{font-size:11px;padding:1px 6px;border-radius:6px;margin-right:5px;white-space:nowrap}
.ap.yes{background:#13301f;color:var(--green)}.ap.no{background:#3a1d1d;color:#f09a95}.ap.unk{background:#262d3d;color:var(--dim)}
.en{color:var(--dim);font-size:12px}
.toggle{float:right;color:var(--dim);font-size:12px}
details.track{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin:14px 0}
details.track summary{cursor:pointer;font-weight:700}
.tw{overflow-x:auto}
table.tr{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0}
table.tr th,table.tr td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;white-space:nowrap}
table.tr td.num{text-align:right}
.big{font-weight:800}
footer{color:var(--dim);font-size:12px;text-align:center;margin:24px 0 8px}
@media(max-width:700px){.tops{grid-template-columns:1fr}.wrap{padding:12px}h1{font-size:19px}}
"""

JS = """
function tg(el){el.closest('.game').classList.toggle('open')}
function go(id){var g=document.getElementById('g'+id);if(!g)return;g.classList.add('open');g.scrollIntoView({behavior:'smooth',block:'start'})}
"""


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def score_class(s):
    if s is None:
        return 'n'
    return 'g' if s >= 55 else ('y' if s >= 50 else 'n')


def _score_sub(r):
    parts = []
    if r.get('score_trend') is not None:
        parts.append(f"趨勢 {r['score_trend']:.1f}")
    if r.get('score_sit') is not None:
        parts.append(f"情境 {r['score_sit']:.1f}")
    return '｜'.join(parts)


def render_top(title, recs, games_by_id, empty):
    rows = []
    for i, r in enumerate(recs, 1):
        g = games_by_id[r['gid']]
        rows.append(
            f'<li onclick="go(\'{esc(r["gid"])}\')"><span class="rank">{i}</span><div class="pinfo">'
            f'<div class="pmatch">{esc(team_short(g["away"]))} @ {esc(team_short(g["home"]))}</div>'
            f'<div class="pbet">{esc(r["text"])}</div><div class="sub">{esc(_score_sub(r))}</div></div>'
            f'<span class="score {score_class(r["score"])}">{r["score"]:.1f}</span></li>')
    body = f'<ol class="picks">{"".join(rows)}</ol>' if rows else f'<div class="empty">{esc(empty)}</div>'
    return f'<section class="box"><h2>{esc(title)}</h2>{body}</section>'


def _ap(applies):
    if applies is True:
        return '<span class="ap yes">今天適用</span>'
    if applies is False:
        return '<span class="ap no">今天不適用</span>'
    return '<span class="ap unk">無法確認</span>'


def render_game(g):
    away, home = g['away'], g['home']
    times = []
    if g.get('local_time'):
        times.append(f"當地 {g['local_time']}")
    if g.get('taiwan_time'):
        times.append(f"台灣 {g['taiwan_time']}")
    when = ' ｜ '.join(times) if times else '開賽時間未提供'
    lines = []
    if g.get('spread_home') is not None:
        lines.append(f"讓分：{team_short(home)} {side_label(g['spread_home'])}")
    if g.get('total') is not None:
        lines.append(f"大小分：{g['total']:g}")
    recs_html = ''.join(
        f'<div class="rec"><div class="pinfo"><div class="pbet">{esc(r["text"])}</div>'
        f'<div class="sub">{esc(_score_sub(r))}</div></div>'
        f'<span class="score {score_class(r["score"])}">{r["score"]:.1f}</span></div>'
        for r in g['recs'])
    if not recs_html:
        recs_html = ('<div class="empty">covers 尚未發佈這場的趨勢，稍後的自動更新會補上。</div>'
                     if not g.get('trends_published') else '<div class="empty">這場沒有符合條件的推薦。</div>')
    roi = ''.join(f'<li>{esc(t["text_zh"]) if t.get("text_zh") else ""}'
                  f'{"<br>" if t.get("text_zh") else ""}<span class="en">{esc(t["text"])}</span></li>'
                  for t in g['roi'])
    rf = ''.join(f'<li>{_ap(i.get("applies")) if i.get("kind") else ""}'
                 f'{esc(i["text_zh"]) if i.get("text_zh") else ""}{"<br>" if i.get("text_zh") else ""}'
                 f'<span class="en">{esc(i["text"])}</span></li>' for i in g['rf'])
    detail = ''
    if roi:
        detail += f'<h3>📊 全場趨勢（計分用）</h3><ul>{roi}</ul>'
    if rf:
        detail += ('<h3>📈 情境趨勢</h3><div class="sub" style="margin-bottom:4px">'
                   '只有標「今天適用」的才計入情境分</div>' f'<ul>{rf}</ul>')
    if not detail:
        detail = '<div class="empty">沒有趨勢資料。</div>'
    return (f'<div class="game" id="g{esc(g["gid"])}"><div class="ghead" onclick="tg(this)">'
            f'<div class="teams">{esc(team_full(away))}<span class="at">@</span>{esc(team_full(home))}</div>'
            f'<div class="meta">{esc(when)} <span class="toggle">詳細 ▾</span></div>'
            f'<div class="lines">{esc("　".join(lines))}</div></div>'
            f'<div class="recs">{recs_html}</div><div class="detail">{detail}</div></div>')


def _fmt_rate(pair):
    hit, n = pair
    if not n:
        return '<td class="num">—</td>'
    return f'<td class="num"><span class="big">{hit}/{n}</span> ({hit / n * 100:.1f}%)</td>'


def render_track(track):
    if not track or not track.get('ai', {}).get('all', [0, 0])[1] and not any(
            v['all'][1] for v in track.get('algos', {}).values()):
        return ('<details class="track"><summary>📒 推薦戰績</summary>'
                '<div class="empty">還沒有已完賽的推薦紀錄，例行賽開打後隔天開始累積。</div></details>')
    rows = [f'<tr><td>AI Top 5 合計</td>{_fmt_rate(track["ai"]["all"])}{_fmt_rate(track["ai"]["recent"])}</tr>']
    for k, v in track['by_market'].items():
        rows.append(f'<tr><td>　{k}</td>{_fmt_rate(v["all"])}{_fmt_rate(v["recent"])}</tr>')
    names = {'combined': '綜合分（網站推薦）', 'trend': '只看全場趨勢', 'sit': '只看情境趨勢'}
    rows2 = ''.join(f'<tr><td>{names[k]}</td>{_fmt_rate(v["all"])}{_fmt_rate(v["recent"])}</tr>'
                    for k, v in track['algos'].items())
    head = f'<tr><th></th><th>全期間</th><th>近 {TRACK_RECENT_DAYS} 天</th></tr>'
    return ('<details class="track"><summary>📒 推薦戰績</summary>'
            f'<div class="tw"><table class="tr">{head}{"".join(rows)}</table></div>'
            '<h3 style="font-size:14px;margin:12px 0 2px">兩種算法比較（所有 ≥50 分的推薦，不限 Top 5）</h3>'
            '<div class="sub">情境趨勢是否真的有用，看這張表：同一批比賽，三種算法各自選邊、各自計分。</div>'
            f'<div class="tw"><table class="tr">{head}{rows2}</table></div></details>')


def render_page(data):
    games = data['games']
    by_id = {g['gid']: g for g in games}
    notices = ''.join(f'<div class="notice">{n}</div>' for n in data.get('notices', []))
    tw = data.get('taiwan_dates')
    tw_badge = f'<span class="badge">台灣 <b>{esc(tw)}</b> 開打</span>' if tw else ''
    tops = ''
    if games:
        tops = (render_top('🤖 AI Top 5', data['ai'], by_id, '今天沒有 50 分以上的推薦。')
                + '<div class="tops">'
                + render_top('🏀 勝負 Top 5（獨贏／讓分）', data['top_sides'], by_id, '沒有符合條件的推薦。')
                + render_top('📏 大小分 Top 5', data['top_totals'], by_id, '沒有符合條件的推薦。')
                + '</div>')
    cards = ''.join(render_game(g) for g in games)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).replace('</', '<\\/')
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NBA 趨勢 PRO</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header><h1>🏀 NBA 趨勢<small>PRO v{esc(data['version'])}</small></h1>
<span class="badge">美東 <b>{esc(data['date'])}</b></span>{tw_badge}
<span class="badge">{len(games)} 場</span></header>
{notices}
<div class="legend"><span><i class="dot g"></i>≥55 強</span><span><i class="dot y"></i>50~55 普通</span><span><i class="dot n"></i>&lt;50 僅供參考</span><br>分數＝過盤命中率的保守估計。兩隊的紀錄要條件相對應才配成一對（例：A 主場 8/10 配 B 客場 1/10、A 休息後 9/10 配 B 休息後 1/10），全場趨勢與情境趨勢的所有配對權重相同、取平均。兩隊交手紀錄只顯示不計分。「趨勢」「情境」是兩者各自單獨算的分數，僅供參考。</div>
{tops}
{cards}
{render_track(data.get('track'))}
<footer>資料來源 covers.com・更新於 {esc(data['updated'])}（台灣時間）・僅供分析參考，請理性投注</footer>
</div>
<script>{JS}</script>
<script type="application/json" id="page-data">{payload}</script>
</body>
</html>
"""


# ==========================================
# 主流程
# ==========================================
def taiwan_dates(games):
    ds = sorted({g['tw_date'] for g in games if g.get('tw_date')})
    if not ds:
        return None
    return ds[0] if len(ds) == 1 else f"{ds[0]}~{ds[-1]}"


def analyze(date_str, include_preseason=False):
    """抓一天、分析、回傳 (頁面資料, 所有推薦, 原始賽事)。"""
    print(f"[*] 抓取 {date_str}（美東）的賽事列表…")
    body = fetch_list(date_str)
    notices = []
    if body is None:
        return None
    listed = parse_gameboxes(body)
    games_all = listed
    preseason = [g for g in games_all if g['preseason']]
    games = [g for g in games_all if include_preseason or not g['preseason']]
    print(f"  列表 {len(listed)} 場，季前賽 {len(preseason)} 場")
    if preseason and not games:
        notices.append('🗓️ <strong>目前是季前賽</strong>，季前賽的趨勢不準，例行賽開打後才提供推薦。')
    return {'listed': listed, 'games': games, 'notices': notices}


def run(date_str, include_preseason=False, scores=None, history=None, write_history=True):
    scores = scores if scores is not None else {}
    got = analyze(date_str, include_preseason)
    if got is None:
        print("[錯誤] 抓不到賽事列表")
        return None
    notices = got['notices']
    if not OFFLINE_DIR:
        update_scoreboard(scores, date_str)

    # 比賽一開打，列表上的共識盤口就會消失。同一天稍早那一輪抓到的盤口沿用下來，
    # 否則較晚的輪次會讓讓分／大小分推薦整筆消失（戰績也跟著少記）。
    known = known_lines(date_str)
    for g in got['games']:
        prev = known.get(g['gid'])
        if prev:
            for k in ('spread_home', 'spread_away', 'total'):
                if g.get(k) is None and prev.get(k) is not None:
                    g[k] = prev[k]

    out_games, all_recs, failed, off_day = [], [], [], []
    for g in got['games']:
        print(f"  → {g['away']} @ {g['home']} ({g['gid']})")
        body = fetch_url(f"{COVERS}/sport/basketball/nba/matchup/{g['gid']}/picks")
        page = parse_matchup_page(body, g) if body else None
        if not page:
            failed.append(g['gid'])
            continue
        start = page['start_utc'] or et_time_to_utc(date_str, g['game_time'])
        if page['start_utc'] and ET:
            actual = page['start_utc'].astimezone(ET).date().isoformat()
            # 休息日時 covers 會回下一個有比賽的日子（MLB CLAUDE.md 第 11 點）。
            # 只在「確定不符」時跳過；startDate 只有賽前才有，抓不到不代表不符。
            if actual != date_str:
                print(f"    [跳過] 實際是 {actual} 的比賽")
                off_day.append(g['gid'])
                continue
        ctx = {'city': page['city'], 'weekday': date.fromisoformat(date_str).weekday(),
               'prev': {s: previous_game(scores, g[s], date_str) for s in ('away', 'home')}}
        roi = [t for t in (parse_roi_trend(i, g, page) for i in page['roi_raw']) if t]
        rf = parse_recent_form(page['rf_raw'], g, ctx)
        recs = build_recommendations(g, roi, rf)
        all_recs.extend(recs)
        home_tz = TEAMS.get(g['home'], (None, None, None, 'America/New_York'))[3]
        tw_dt = start.astimezone(TW) if start else None
        out_games.append({
            'gid': g['gid'], 'away': g['away'], 'home': g['home'],
            'spread_home': g['spread_home'], 'spread_away': g['spread_away'], 'total': g['total'],
            'game_time': g['game_time'],
            'local_time': fmt_local(start, home_tz), 'taiwan_time': fmt_taiwan(start),
            'tw_date': f"{tw_dt.month}/{tw_dt.day}" if tw_dt else None,
            'sort': start.isoformat() if start else '9',
            'trends_published': page['trends_published'],
            'roi': roi,
            'rf': [{k: i.get(k) for k in ('text', 'text_zh', 'kind', 'applies')} for i in rf],
            'recs': sorted([r for r in recs if r['algo'] == 'combined'], key=lambda r: -r['score']),
        })
        print(f"    全場趨勢 {len(roi)} 條、情境 {len(rf)} 條（今天適用 "
              f"{sum(1 for i in rf if i['applies'] is True)}）、推薦 "
              f"{sum(1 for r in recs if r['algo'] == 'combined')} 筆")

    out_games.sort(key=lambda g: (g['sort'], g['gid']))
    ai, top_sides, top_totals = build_top_lists(all_recs)
    if failed:
        notices.append(f'⚠️ 有 {len(failed)} 場沒抓到（通常是 covers 暫時無回應），'
                       '不是當天沒有這些比賽。下一輪自動更新會重試。')
    if off_day and not out_games:
        notices.append(f'🗓️ <strong>今天沒有比賽</strong>（covers 回的是後面幾天的 {len(off_day)} 場賽程，已排除）。')
    if not got['games'] and not notices:
        notices.append('🗓️ 今天沒有 NBA 比賽。')

    track = None
    if history is not None and write_history and out_games:
        record_day(history, date_str, out_games, all_recs, ai, top_sides, top_totals)
    if history is not None:
        backfill_results(history, scores, date_str)
        track = compute_track_record(history, date_str)

    strip = lambda r: {k: v for k, v in r.items() if k not in ('trend_rows', 'sit_rows')}
    data = {
        'version': APP_VERSION, 'date': date_str,
        'updated': datetime.now(TW).strftime('%Y-%m-%d %H:%M'),
        'taiwan_dates': taiwan_dates(out_games),
        'notices': notices,
        'games': [{k: v for k, v in g.items() if k != 'sort'} for g in out_games],
        'ai': ai, 'top_sides': top_sides, 'top_totals': top_totals,
        'track': track,
    }
    print(f"[完成] {len(out_games)} 場，AI Top 5 {len(ai)} 筆、勝負 {len(top_sides)}、大小分 {len(top_totals)}")
    return data


def load_page_data(path='index.html'):
    try:
        with open(path, encoding='utf-8') as f:
            body = f.read()
    except OSError:
        return None
    m = re.search(r'<script type="application/json" id="page-data">(.*?)</script>', body, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace('<\\/', '</'))
    except ValueError:
        return None


def known_lines(date_str, path='index.html'):
    """上一輪 index.html 已抓到的盤口（只在賽事日期相同時沿用，避免把昨天的帶到今天）。"""
    if OFFLINE_DIR:
        return {}
    data = load_page_data(path)
    if not data or data.get('date') != date_str:
        return {}
    return {g['gid']: g for g in data.get('games', [])}


def replay(path='index.html'):
    data = load_page_data(path)
    if not data:
        sys.exit('index.html 裡找不到 page-data')
    data['version'] = APP_VERSION
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_page(data))
    print('[replay] 已重新產生', path)


def main():
    global OFFLINE_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument('--date')
    ap.add_argument('--replay', action='store_true')
    ap.add_argument('--offline')
    ap.add_argument('--include-preseason', action='store_true',
                    help='測試用：季前賽也計算推薦（正式執行不要開）')
    ap.add_argument('--out', default='index.html')
    args = ap.parse_args()
    if args.replay:
        return replay(args.out)
    date_str = args.date or eastern_today().isoformat()
    if args.offline:
        OFFLINE_DIR = args.offline
        scores = {}
        for p in sorted(glob.glob(os.path.join(OFFLINE_DIR, 'list_*.html'))):
            d = re.search(r'list_(\d{4}-\d{2}-\d{2})', p).group(1)
            if d < date_str:
                with open(p, encoding='utf-8') as f:
                    scores[d] = {'complete': True, 'games': parse_gameboxes(f.read())}
        data = run(date_str, args.include_preseason, scores=scores, history={}, write_history=False)
    else:
        scores = load_json(SCORES_PATH, {})
        history = load_json(HISTORY_PATH, {})
        # 季前賽不寫進戰績（使用者 2026-10-13 決定）
        data = run(date_str, args.include_preseason, scores=scores, history=history,
                   write_history=not args.include_preseason)
        save_json(SCORES_PATH, scores)
        save_json(HISTORY_PATH, history)
    if data is None:
        return 1
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(render_page(data))
    print('[輸出]', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
