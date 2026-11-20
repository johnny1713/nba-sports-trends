"""
ESPN 資料：賽程／比分、box score、盤口。只負責抓取與正規化，不做任何預測。

盤口的關鍵事實（2026-11-20 實測，見 docs/reports）：
- ESPN **沒有**提供開盤／收盤的時間戳 → open_time / close_time 一律 None，並標 timestamp_available=False。
- 2023-24 起每家莊家有 open / close / current 三段；更早只有 current（賽後抓 = 收盤）＋ initialSpread / initialOverUnder（開盤線，無價格）。
- **未開打的比賽也有 "close" 欄位，但內容就是當下的即時盤**，不是真正的收盤。
  → 比賽未完賽時：close 一律丟棄，current 存成 snapshot（帶 observed_at）。完賽後再抓才存 close。
- consensus / numberfire / teamrankings / accuscore 是預測或共識，不是莊家；"Opening" 是開盤線彙整。
  全部保留，但以 provider_type 區分，模型只用 book。
- 價格以 american 換算小數（ESPN 的 decimal 欄位有四捨五入，-111 給 1.9）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..schema import Game, OddsQuote, TeamBox, PlayerLine

SITE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba'
NBA_TEAM_IDS = {str(i) for i in range(1, 31)}            # ESPN 的 30 支 NBA 球隊 id；明星賽等隊伍不在此列
NON_BOOK = {'consensus', 'numberfire', 'teamrankings', 'accuscore'}
OPENING_FEED = {'opening'}
SEASON_TYPE_KEEP = {2, 3}                                 # 例行賽、季後賽；季前賽(1)、play-in(5) 另計不收


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def provider_type(name: str) -> str:
    n = (name or '').strip().lower()
    if n in NON_BOOK:
        return 'non_book'
    if n in OPENING_FEED:
        return 'opening_feed'
    if 'live odds' in n:
        return 'live'
    return 'book'


def american_to_decimal(a):
    if a is None or a == '':
        return None
    try:
        a = float(str(a).replace('+', ''))
    except ValueError:
        return None
    if a == 0 or -100 < a < 100:
        return None                        # 美式賠率不會落在 (-100, 100)，出現就是資料錯誤
    return round(1 + a / 100, 6) if a > 0 else round(1 + 100 / -a, 6)


def _price(node):
    """{'american': '-110', 'decimal': 1.909} → 小數賠率；以 american 為準。"""
    if not isinstance(node, dict):
        return None
    d = american_to_decimal(node.get('american') or node.get('alternateDisplayValue'))
    if d is None and node.get('decimal'):
        try:
            d = float(node['decimal']) if float(node['decimal']) > 1 else None
        except (TypeError, ValueError):
            d = None
    return d


def _line(node):
    if not isinstance(node, dict):
        return None
    v = node.get('american') or node.get('alternateDisplayValue')
    if v in (None, ''):
        return None
    s = str(v).strip().upper()
    if s in ('PK', 'EVEN', 'PICK'):
        return 0.0
    try:
        return float(s.replace('+', '').lstrip('OU'))
    except ValueError:
        return None


# ---------------------------------------------------------------- scoreboard
def scoreboard_url(d0: date, d1: date = None, limit=1000):
    d1 = d1 or d0
    rng = f'{d0:%Y%m%d}' if d0 == d1 else f'{d0:%Y%m%d}-{d1:%Y%m%d}'
    return f'{SITE}/scoreboard?dates={rng}&limit={limit}'


def parse_scoreboard_event(ev: dict, fetched_at: str):
    """回傳 (Game 或 None, 略過原因)。"""
    st = (ev.get('season') or {}).get('type')
    comp = ev['competitions'][0]
    teams = {c['homeAway']: c for c in comp['competitors']}
    home, away = teams.get('home'), teams.get('away')
    if not home or not away:
        return None, 'no home/away'
    if home['team']['id'] not in NBA_TEAM_IDS or away['team']['id'] not in NBA_TEAM_IDS:
        return None, 'non-NBA teams (all-star etc.)'
    if st not in SEASON_TYPE_KEEP:
        return None, f'season type {st}'
    stype = comp.get('status', {}).get('type', {})
    name = stype.get('name', '')
    if stype.get('completed') and name in ('STATUS_FINAL', 'STATUS_FINAL_OT'):
        status = 'final'
    elif 'POSTPONED' in name:
        status = 'postponed'
    elif 'CANCELED' in name or 'CANCELLED' in name:
        status = 'canceled'
    elif stype.get('state') == 'pre':
        status = 'scheduled'
    else:
        return None, f'in progress / unknown status {name}'
    hp = int(home['score']) if status == 'final' else None
    ap = int(away['score']) if status == 'final' else None
    g = Game(game_id=ev['id'], season=int(ev['season']['year']), season_type=st,
             start_utc=_norm_ts(ev['date']), home=home['team']['id'], away=away['team']['id'],
             status=status, source='espn:scoreboard', fetched_at=fetched_at,
             home_pts=hp, away_pts=ap, neutral=bool(comp.get('neutralSite')))
    d = g.__dict__.copy()
    d['home_abbr'], d['away_abbr'] = home['team'].get('abbreviation'), away['team'].get('abbreviation')
    d['notes'] = [n.get('headline') for n in comp.get('notes', []) if n.get('headline')]
    return g.validate() and d, None


def _norm_ts(s):
    # ESPN 給 "2024-01-15T18:00Z"（沒有秒）
    d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    return d.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


# ---------------------------------------------------------------- box score
def summary_url(game_id):
    return f'{SITE}/summary?event={game_id}'


def _split(v):
    a, b = v.split('-')
    return int(a), int(b)


def parse_boxscore(summary: dict, game_id: str, fetched_at: str):
    """回傳兩隊的 TeamBox dict（含球員）。資料缺就丟 ValueError，由呼叫端記錄為錯誤。"""
    bx = summary.get('boxscore') or {}
    header = summary['header']['competitions'][0]
    ot_by_team = {}
    for c in header['competitors']:
        ls = c.get('linescores') or []
        ot_by_team[c['team']['id']] = max(0, len(ls) - 4)
    players_by_team = {}
    for p in bx.get('players') or []:
        tid = p['team']['id']
        st = p['statistics'][0] if p.get('statistics') else {}
        keys = st.get('names') or st.get('keys') or []
        idx = {k: i for i, k in enumerate(keys)}
        out = []
        for a in st.get('athletes', []):
            stats = a.get('stats') or []
            mins = pts = None
            if stats and 'MIN' in idx and idx['MIN'] < len(stats):
                try:
                    mins = float(stats[idx['MIN']])
                except ValueError:
                    mins = None
            if stats and 'PTS' in idx and idx['PTS'] < len(stats):
                try:
                    pts = int(stats[idx['PTS']])
                except ValueError:
                    pts = None
            out.append(PlayerLine(player_id=a['athlete']['id'], name=a['athlete'].get('displayName', ''),
                                  minutes=mins, pts=pts, starter=bool(a.get('starter')),
                                  dnp_reason=(a.get('reason') or None) if a.get('didNotPlay') else None).__dict__)
        players_by_team[tid] = out
    boxes = []
    for t in bx.get('teams') or []:
        tid = t['team']['id']
        s = {x['name']: x.get('displayValue') for x in t.get('statistics', [])}
        fgm, fga = _split(s['fieldGoalsMade-fieldGoalsAttempted'])
        f3m, f3a = _split(s['threePointFieldGoalsMade-threePointFieldGoalsAttempted'])
        ftm, fta = _split(s['freeThrowsMade-freeThrowsAttempted'])
        tov = int(s.get('totalTurnovers') or s.get('turnovers'))
        tb = TeamBox(game_id=game_id, team=tid, fgm=fgm, fga=fga, fg3m=f3m, fg3a=f3a, ftm=ftm, fta=fta,
                     oreb=int(s['offensiveRebounds']), dreb=int(s['defensiveRebounds']), tov=tov,
                     pts=2 * fgm + f3m + ftm, overtimes=ot_by_team.get(tid, 0),
                     source='espn:summary', fetched_at=fetched_at, players=players_by_team.get(tid, []))
        boxes.append(tb.validate().__dict__)
    if len(boxes) != 2:
        raise ValueError(f'{game_id}: expected 2 team boxes, got {len(boxes)}')
    return boxes


# ---------------------------------------------------------------- odds
def odds_url(game_id):
    return f'{CORE}/events/{game_id}/competitions/{game_id}/odds?limit=100'


def strip_raw(o):
    if isinstance(o, dict):
        return {k: strip_raw(v) for k, v in o.items() if k not in ('links', 'logos', '$ref', 'team')}
    if isinstance(o, list):
        return [strip_raw(x) for x in o]
    return o


def parse_odds(payload: dict, game_id: str, game_final: bool, fetched_at: str):
    """
    回傳 (quotes, raw_items, notes)。quotes 是 OddsQuote dict（多了 provider_id / provider_type /
    timestamp_available）。game_final=False 時：不存 close、current 存為 snapshot。
    """
    quotes, notes = [], []
    raw = []
    for it in payload.get('items', []):
        prov = it.get('provider') or {}
        pname, pid = prov.get('name', ''), str(prov.get('id', ''))
        ptype = provider_type(pname)
        raw.append(strip_raw(it))
        if ptype == 'live':
            continue                              # 賽中滾球盤，不收
        h, a = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
        has_stages = any(isinstance(h.get(k), dict) for k in ('open', 'close'))

        def add(stage, market, side, line, price, observed=None):
            if market != 'ml' and line is None:
                return
            if market == 'ml' and price is None:
                return
            q = OddsQuote(game_id=game_id, provider=pname, stage=stage, market=market, side=side,
                          line=line, price_decimal=price, source='espn:core-odds', fetched_at=fetched_at,
                          observed_at=observed).validate().__dict__
            q.update(provider_id=pid, provider_type=ptype, timestamp_available=False)
            quotes.append(q)

        def add_stage(stage, hs, as_, tot, observed=None):
            hl, al = _line((hs or {}).get('pointSpread')), _line((as_ or {}).get('pointSpread'))
            if hl is not None and al is not None and abs(hl + al) > 1e-9:
                notes.append(f'{game_id}/{pname}/{stage}: spread home {hl} away {al} not opposite')
            add(stage, 'spread', 'home', hl, _price((hs or {}).get('spread')), observed)
            add(stage, 'spread', 'away', al, _price((as_ or {}).get('spread')), observed)
            add(stage, 'ml', 'home', None, _price((hs or {}).get('moneyLine')), observed)
            add(stage, 'ml', 'away', None, _price((as_ or {}).get('moneyLine')), observed)
            tl = _line((tot or {}).get('total'))
            add(stage, 'total', 'over', tl, _price((tot or {}).get('over')), observed)
            add(stage, 'total', 'under', tl, _price((tot or {}).get('under')), observed)

        if has_stages:
            add_stage('open', h.get('open'), a.get('open'), it.get('open'))
            if game_final:
                add_stage('close', h.get('close'), a.get('close'), it.get('close'))
            else:
                add_stage('snapshot', h.get('current'), a.get('current'), it.get('current'), observed=fetched_at)
        else:
            # 舊年代：只有 current（賽後抓到 = 收盤）＋ initial* 開盤線（無價格）
            cur_stage = 'current_postgame' if game_final else 'snapshot'
            obs = None if game_final else fetched_at
            sp = it.get('spread')
            hs = {'pointSpread': {'american': sp}, 'spread': {'american': h.get('spreadOdds')},
                  'moneyLine': {'american': h.get('moneyLine')}} if True else None
            as_ = {'pointSpread': {'american': -sp if sp is not None else None},
                   'spread': {'american': a.get('spreadOdds')}, 'moneyLine': {'american': a.get('moneyLine')}}
            tot = {'total': {'american': it.get('overUnder')}, 'over': {'american': it.get('overOdds')},
                   'under': {'american': it.get('underOdds')}}
            add_stage(cur_stage, hs, as_, tot, observed=obs)
            if it.get('initialSpread') is not None:
                add('open', 'spread', 'home', float(it['initialSpread']), None)
                add('open', 'spread', 'away', -float(it['initialSpread']), None)
            if it.get('initialOverUnder') is not None:
                add('open', 'total', 'over', float(it['initialOverUnder']), None)
                add('open', 'total', 'under', float(it['initialOverUnder']), None)
            # 交叉檢查：item.spread 應等於主隊 current pointSpread
            cps = _line(((h.get('current') or {}).get('pointSpread')))
            if sp is not None and cps is not None and abs(float(sp) - cps) > 1e-9:
                notes.append(f'{game_id}/{pname}: item.spread {sp} != home current {cps}')
    return quotes, raw, notes
