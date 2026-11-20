"""
來源探查（唯讀；只新增檔案到 data/audit/，不覆寫任何既有資料）。在 GitHub Actions 上執行：

    python -m nba_quant.jobs backfill --source-audit                # 全部球季（2017-18 整季，其他每季 30 場）
    python -m nba_quant.jobs backfill --source-audit --only 2018    # 只跑指定球季（逗號分隔）

每場比賽同時抓：
- ESPN summary 原始 box score：球隊統計所有欄位（含 turnovers / teamTurnovers / totalTurnovers）、
  球員 TO 欄位加總；原始 boxscore JSON（去掉連結、頭像）另存，供追查。
- BBRef box score：球隊合計（Team Totals）、球員 tov 加總、場館與日期（scorebox_meta）；只存解析值與頁面 sha256。
- ESPN gameInfo.venue（場館；注意：ESPN 顯示的是場館**現在**的名稱，可能不是比賽當時的名稱）。

抽樣：固定亂數種子；每季從「ESPN 原生 box score 的例行賽完賽比賽」中，依月份輪流、優先未涵蓋的球隊，抽約 30 場。
2017-18（ESPN 失誤欄位已知系統性異常）：該季所有 ESPN 原生例行賽比賽。
中立場候選（見 neutral_candidates()）：另抓 ESPN 場館與 BBRef 場館作為輔助證據。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from collections import defaultdict

from . import store
from .sources import bbref, espn
from .sources.http import Fetcher, FetchError

RAW = os.path.join('data', 'raw', 'espn')
OUT = os.path.join('data', 'audit', 'source_compare')
SEED = 20261120
PER_SEASON = 30
FULL_SEASONS = (2018,)


def _final_regular(season):
    gs = [g for g in store.read_jsonl_gz(os.path.join(RAW, str(season), 'games.jsonl.gz'))
          if g['status'] == 'final' and g['season_type'] == 2 and g.get('complete')]
    return gs


def sample_games(season, k=PER_SEASON, seed=SEED):
    """依月份輪流抽樣、優先未涵蓋的球隊；只抽 ESPN 原生 box score 的比賽。固定種子，可重現。"""
    gs = [g for g in _final_regular(season) if g.get('box_source', 'espn') == 'espn']
    if season in FULL_SEASONS:
        return sorted(gs, key=lambda g: (g['start_utc'], g['game_id']))
    rng = random.Random(f'{seed}-{season}')
    by_month = defaultdict(list)
    for g in gs:
        by_month[g['start_utc'][:7]].append(g)
    for v in by_month.values():
        rng.shuffle(v)
    months = sorted(by_month)
    picked, teams = [], set()
    while len(picked) < k and any(by_month.values()):
        for m in months:
            if len(picked) >= k or not by_month[m]:
                continue
            cand = by_month[m]
            idx = next((i for i, g in enumerate(cand) if g['home'] not in teams or g['away'] not in teams), 0)
            g = cand.pop(idx)
            picked.append(g)
            teams |= {g['home'], g['away']}
    return sorted(picked, key=lambda g: (g['start_utc'], g['game_id']))


def neutral_candidates(season):
    """中立場候選：ESPN neutral 標記、季中賽／盃賽淘汰賽備註、2019-20 泡泡區期間。"""
    out = []
    for g in store.read_jsonl_gz(os.path.join(RAW, str(season), 'games.jsonl.gz')):
        if g['status'] != 'final':
            continue
        notes = ' '.join(g.get('notes') or [])
        bubble = season == 2020 and g['start_utc'] >= '2020-07-30'
        knockout = any(w in notes for w in ('Semifinal', 'Championship')) and ('Tournament' in notes or 'Cup' in notes)
        if g.get('neutral') or knockout or bubble:
            out.append(g)
    return out


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in ('links', 'headshot', 'logo', 'logos', '$ref', 'uid', 'guid')}
    if isinstance(o, list):
        return [_strip(x) for x in o]
    return o


def espn_raw_fields(summary):
    """回傳 ({team_id: {欄位: 值}}, {team_id: 球員 TO 加總}, venue, 原始 boxscore)。"""
    bx = summary.get('boxscore') or {}
    team_stats = {}
    for t in bx.get('teams') or []:
        team_stats[t['team']['id']] = {x['name']: x.get('displayValue') for x in t.get('statistics', [])}
    player_to = {}
    for p in bx.get('players') or []:
        st = (p.get('statistics') or [{}])[0]
        keys = st.get('keys') or []
        names = st.get('names') or []
        idx = keys.index('turnovers') if 'turnovers' in keys else (names.index('TO') if 'TO' in names else None)
        tot = 0
        ok = idx is not None
        for a in st.get('athletes', []):
            vals = a.get('stats') or []
            if idx is not None and idx < len(vals):
                try:
                    tot += int(vals[idx])
                except ValueError:
                    pass
        player_to[p['team']['id']] = tot if ok else None
    venue = ((summary.get('gameInfo') or {}).get('venue') or {})
    v = {'name': venue.get('fullName'), 'city': (venue.get('address') or {}).get('city'),
         'state': (venue.get('address') or {}).get('state'), 'note': 'ESPN 顯示場館現在的名稱，可能不是比賽當時的名稱'}
    return team_stats, player_to, v, _strip(bx)


def bbref_fields(html, game):
    """回傳 ({team_id: 球隊合計欄位}, {team_id: 球員 tov 加總}, scorebox 場館與時間)。"""
    out, ptov = {}, {}
    for tid in (game['away'], game['home']):
        ab = bbref.ESPN_TO_BBREF[tid]
        m = re.search(r'<table[^>]*id="box-%s-game-basic".*?</table>' % ab, html, re.S)
        if not m:
            raise ValueError(f'bbref table box-{ab}-game-basic not found')
        tbl = m.group(0)
        foot = re.search(r'<tfoot>(.*?)</tfoot>', tbl, re.S).group(1)

        def g(k, src=foot):
            mm = re.search(r'data-stat="%s"[^>]*>([^<]*)<' % k, src)
            return int(mm.group(1)) if mm and mm.group(1).strip() else None
        out[tid] = {k: g(k) for k in ('fg', 'fga', 'fg3', 'fg3a', 'ft', 'fta', 'orb', 'drb', 'trb', 'tov', 'pts', 'mp')}
        body = re.search(r'<tbody>(.*?)</tbody>', tbl, re.S).group(1)
        tot = 0
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S):
            mm = re.search(r'data-stat="tov"[^>]*>([^<]*)<', row)
            if mm and mm.group(1).strip().isdigit():   # tbody 中間會重複表頭（Reserves 列的 'TOV'）
                tot += int(mm.group(1))
        ptov[tid] = tot
    meta = re.search(r'<div class="scorebox_meta">(.*?)</div>\s*</div>', html, re.S)
    parts = [p.strip() for p in re.sub(r'<[^>]+>', '|', meta.group(1)).split('|') if p.strip()] if meta else []
    return out, ptov, {'raw_meta': parts[:3]}


def run(only=None, log=print):
    f_espn = Fetcher(min_interval=0.4)
    f_bb = Fetcher(min_interval=3.5)
    seasons = list(only) if only else [int(x) for x in sorted(os.listdir(RAW)) if os.path.exists(os.path.join(RAW, x, 'games.jsonl.gz'))]
    for season in seasons:
        games = {g['game_id']: g for g in sample_games(season)}
        neutral = {g['game_id']: g for g in neutral_candidates(season)}
        todo = sorted(set(games) | set(neutral), key=lambda k: ((games.get(k) or neutral.get(k))['start_utc'], k))
        log(f'== season {season}: compare {len(games)} games, neutral candidates {len(neutral)}')
        rows, raws, errors = [], [], []
        for i, gid in enumerate(todo):
            g = games.get(gid) or neutral.get(gid)
            row = {'game_id': gid, 'season': season, 'start_utc': g['start_utc'], 'home': g['home'], 'away': g['away'],
                   'home_abbr': g.get('home_abbr'), 'away_abbr': g.get('away_abbr'), 'season_type': g['season_type'],
                   'in_compare_sample': gid in games, 'neutral_candidate': gid in neutral,
                   'espn_neutral_flag': bool(g.get('neutral')), 'notes': g.get('notes') or []}
            try:
                s = f_espn.get_json(espn.summary_url(gid))
                ts, pto, venue, raw = espn_raw_fields(s)
                row.update(espn_team_fields=ts, espn_player_to_sum=pto, espn_venue=venue)
                raws.append({'game_id': gid, 'boxscore': raw})
            except (FetchError, KeyError, ValueError, TypeError) as e:
                errors.append({'game_id': gid, 'source': 'espn', 'error': f'{type(e).__name__}: {str(e)[:120]}'})
            try:
                html_b = f_bb.get_bytes(bbref.box_url(g))
                bt, bpto, meta = bbref_fields(html_b.decode('utf-8', 'replace'), g)
                row.update(bbref_team_totals=bt, bbref_player_tov_sum=bpto, bbref_meta=meta,
                           bbref_url=bbref.box_url(g), bbref_sha256=hashlib.sha256(html_b).hexdigest())
            except (FetchError, KeyError, ValueError, AttributeError, TypeError) as e:
                errors.append({'game_id': gid, 'source': 'bbref', 'error': f'{type(e).__name__}: {str(e)[:120]}'})
            rows.append(row)
            if (i + 1) % 100 == 0:
                log(f'   {i + 1}/{len(todo)}  errors {len(errors)}')
        d = os.path.join(OUT, str(season))
        store.write_jsonl_gz(os.path.join(d, 'compare.jsonl.gz'), rows)
        store.write_jsonl_gz(os.path.join(d, 'espn_raw_boxscore.jsonl.gz'), raws)
        store.write_json(os.path.join(d, 'fetch_log.json'), {'season': season, 'seed': SEED, 'games': len(todo),
                                                             'compare_sample': len(games), 'neutral_candidates': len(neutral),
                                                             'espn_requests': f_espn.calls, 'bbref_requests': f_bb.calls,
                                                             'errors': errors})
        log(f'   saved {len(rows)} rows, {len(errors)} errors')
    return 0
