"""
分季回補 ESPN 歷史資料（Phase 3）。一次只跑一季，跑完立刻產生資料品質報告。

    python -m nba_quant.jobs backfill --season 2016          # 2015-16 季
    python -m nba_quant.jobs backfill --taiwan               # 抓一次玩運彩運彩盤（存原始 HTML + 解析結果）

輸出（data/raw/espn/<季>/）：
  games.jsonl.gz      每場一筆（含 complete 判定與原因）
  teambox.jsonl.gz    每場每隊一筆（含球員）
  odds.jsonl.gz       正規化盤口：每家莊家 × 階段 × 市場 × 邊，保留莊家、盤口、賠率；
                      ESPN 沒給開收盤時間 → timestamp_available=False（不假裝有）
  odds_raw.jsonl.gz   ESPN 原始盤口（去掉連結與 logo），供日後追查
  fetch_log.json      請求數、錯誤清單、抓取時間
  quality.json        資料品質指標（同時輸出 docs/reports/data_quality/<季>.md）

可中斷續跑：已存在且 complete 的比賽不重抓（當季每天只補新完賽的比賽與收盤）。
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from . import store
from .sources import espn
from .sources.http import Fetcher, FetchError

RAW = os.path.join('data', 'raw', 'espn')


def season_dir(season):
    return os.path.join(RAW, str(season))


def _months(season):
    """Aug 1 (前一年) ～ Oct 31（當年）每月一段：涵蓋 2019-20 泡泡、2020-21 延後開季。再以 season.year 過濾。"""
    d = date(season - 1, 8, 1)
    end = date(season, 10, 31)
    while d <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield d, min(nxt - timedelta(days=1), end)
        d = nxt


def list_games(f: Fetcher, season: int, today: date = None, log=print):
    games, skipped = {}, {}
    for d0, d1 in _months(season):
        if today and d0 > today:
            break
        d1 = min(d1, today) if today else d1
        evs = _range_events(f, d0, d1, log)
        for ev in evs:
            if int((ev.get('season') or {}).get('year', 0)) != season:
                continue
            g, why = espn.parse_scoreboard_event(ev, espn.now_utc())
            if g is None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            games[g['game_id']] = g
    return games, skipped


def _range_events(f, d0, d1, log, limit=1000):
    """區間查詢；回傳數量碰到上限就切半重抓，避免被截斷而不自知。"""
    data = f.get_json(espn.scoreboard_url(d0, d1, limit))
    evs = data.get('events', [])
    if len(evs) >= limit and d0 < d1:
        mid = d0 + (d1 - d0) // 2
        log(f'  range {d0}~{d1} hit limit {limit}, splitting')
        return _range_events(f, d0, mid, log) + _range_events(f, mid + timedelta(days=1), d1, log)
    return evs


def _load(path):
    return list(store.read_jsonl_gz(path)) if os.path.exists(path) else []


def run_season(season: int, live: bool = False, log=print):
    f = Fetcher()
    out = season_dir(season)
    old_games = {g['game_id']: g for g in _load(os.path.join(out, 'games.jsonl.gz'))}
    old_boxes = {}
    for b in _load(os.path.join(out, 'teambox.jsonl.gz')):
        old_boxes.setdefault(b['game_id'], []).append(b)
    old_odds, old_raw = {}, {}
    for q in _load(os.path.join(out, 'odds.jsonl.gz')):
        old_odds.setdefault(q['game_id'], []).append(q)
    for r in _load(os.path.join(out, 'odds_raw.jsonl.gz')):
        old_raw[r['game_id']] = r

    today = date.today() if live else None
    log(f'== season {season} ({season - 1}-{str(season)[2:]}) listing games…')
    games, skipped = list_games(f, season, today, log)
    log(f'   {len(games)} games kept, skipped: {skipped}')

    boxes, odds, raws, errors, notes = {}, {}, {}, [], []
    for i, (gid, g) in enumerate(sorted(games.items(), key=lambda kv: kv[1]['start_utc'])):
        prev = old_games.get(gid)
        final = g['status'] == 'final'
        reuse = (prev and prev.get('complete') and prev.get('odds_final') and final)
        if reuse:
            g.update({k: prev[k] for k in ('complete', 'complete_reason', 'odds_final', 'odds_books') if k in prev})
            boxes[gid] = old_boxes.get(gid, [])
            odds[gid] = old_odds.get(gid, [])
            if gid in old_raw:
                raws[gid] = old_raw[gid]
            continue
        g['complete'], g['complete_reason'] = False, None
        if final:
            try:
                bx = espn.parse_boxscore(f.get_json(espn.summary_url(gid)), gid, espn.now_utc())
                pts = {b['team']: b['pts'] for b in bx}
                if pts.get(g['home']) != g['home_pts'] or pts.get(g['away']) != g['away_pts']:
                    g['complete_reason'] = f'box points {pts} != scoreboard {g["home_pts"]}-{g["away_pts"]}'
                else:
                    g['complete'] = True
                boxes[gid] = bx
            except (FetchError, ValueError, KeyError, TypeError) as e:
                g['complete_reason'] = f'boxscore error: {type(e).__name__}: {str(e)[:160]}'
                errors.append({'game_id': gid, 'stage': 'boxscore', 'error': g['complete_reason']})
        else:
            g['complete_reason'] = f'status {g["status"]}'
        if not final:
            # 未完賽的盤口快照由每日流程另存（data/snapshots），回補不碰，避免覆寫掉賽前快照
            g['odds_final'], g['odds_books'] = False, []
            continue
        try:
            fetched = espn.now_utc()
            q, raw, nt = espn.parse_odds(f.get_json(espn.odds_url(gid)), gid, final, fetched)
            odds[gid] = q
            raws[gid] = {'game_id': gid, 'fetched_at': fetched, 'game_final_at_fetch': final, 'items': raw}
            notes.extend(nt)
            g['odds_final'] = final
            g['odds_books'] = sorted({x['provider'] for x in q if x['provider_type'] == 'book'})
        except (FetchError, ValueError, KeyError, TypeError) as e:
            errors.append({'game_id': gid, 'stage': 'odds', 'error': f'{type(e).__name__}: {str(e)[:160]}'})
            g['odds_final'] = False
            g['odds_books'] = []
        if (i + 1) % 100 == 0:
            log(f'   {i + 1}/{len(games)} games, {f.calls} requests, {len(errors)} errors')

    os.makedirs(out, exist_ok=True)
    order = sorted(games, key=lambda k: (games[k]['start_utc'], k))
    store.write_jsonl_gz(os.path.join(out, 'games.jsonl.gz'), [games[k] for k in order])
    store.write_jsonl_gz(os.path.join(out, 'teambox.jsonl.gz'), [b for k in order for b in sorted(boxes.get(k, []), key=lambda b: b['team'])])
    store.write_jsonl_gz(os.path.join(out, 'odds.jsonl.gz'), [q for k in order for q in odds.get(k, [])])
    store.write_jsonl_gz(os.path.join(out, 'odds_raw.jsonl.gz'), [raws[k] for k in order if k in raws])
    store.write_json(os.path.join(out, 'fetch_log.json'), {
        'season': season, 'requests': f.calls, 'http_errors': [list(e) for e in f.errors],
        'parse_errors': errors, 'notes': notes[:500], 'notes_total': len(notes), 'skipped': skipped})
    from . import quality
    q = quality.season_report(season)
    log(f'   quality: {q["verdict"]}')
    return 0 if q['verdict_ok'] else 1


def run_taiwan(log=print):
    """抓玩運彩今天與明天的運彩盤：原始 HTML（gzip）與解析結果分開存。"""
    from .sources import taiwan
    from datetime import datetime
    f = Fetcher(min_interval=2.0)
    now_tw = datetime.now(taiwan.TW)
    rc = 0
    for d in (now_tw.date(), now_tw.date() + timedelta(days=1)):
        ds = d.isoformat()
        fetched = espn.now_utc()
        try:
            html = f.get_bytes(taiwan.url_for(ds), headers={'Accept-Language': 'zh-TW,zh;q=0.9'}).decode('utf-8', 'replace')
        except FetchError as e:
            log(f'  playsport {ds} fetch failed: {e}')
            rc = 1
            continue
        stamp = fetched.replace(':', '').replace('-', '')
        raw_path = os.path.join('data', 'taiwan', 'raw', ds, f'{stamp}.html.gz')
        import gzip as _gz
        import io
        buf = io.BytesIO()
        with _gz.GzipFile(fileobj=buf, mode='wb', mtime=0) as gz:
            gz.write(html.encode('utf-8'))
        store._atomic_write(raw_path, buf.getvalue())
        try:
            games, problems = taiwan.parse(html, fetched)
        except taiwan.ParseRejected as e:
            log(f'  playsport {ds} REJECTED: {e}')
            store.write_json(os.path.join('data', 'taiwan', 'scraped', ds, f'{stamp}.json'),
                             {'date_tw': ds, 'fetched_at': fetched, 'raw_html': raw_path, 'rejected': str(e), 'games': []})
            rc = 1
            continue
        store.write_json(os.path.join('data', 'taiwan', 'scraped', ds, f'{stamp}.json'),
                         {'date_tw': ds, 'fetched_at': fetched, 'raw_html': raw_path,
                          'raw_sha256': store.sha256_file(raw_path), 'games': games, 'problems': problems})
        log(f'  playsport {ds}: {len(games)} games, {len(problems)} problems → {raw_path}')
    return rc


def main(season, rest):
    if '--taiwan' in rest:
        return run_taiwan()
    if season is None:
        print('need --season or --taiwan', file=sys.stderr)
        return 2
    from .config import LIVE_SEASON
    return run_season(season, live=(season == LIVE_SEASON))
