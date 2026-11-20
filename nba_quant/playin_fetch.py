"""
2019-20 泡泡區附加賽（Play-In）獨立抓取（使用者 2026-11-20 核准）。

    python -m nba_quant.jobs backfill --playin-2020
    python -m nba_quant.jobs backfill --playin 2021,2022,2023,2024,2025

- 只抓 2020-08-15（美東）ESPN 賽事類型 5 的比賽（POR vs MEM）。
- 獨立存放在 data/raw/espn_playin/2020/，不寫入 data/raw/espn/2020/，不混入例行賽或季後賽資料。
- 保留原始回應：ESPN scoreboard JSON、ESPN summary JSON（完整）、BBRef box score HTML（gzip），附 URL、抓取時間、sha256。
- 解析結果標記 game_type = PLAY_IN、counts_for_standings = False。
- 驗證：ESPN box 得分恆等式、ESPN box 得分 = 計分板比分、ESPN vs BBRef 同場逐欄位比對。
"""
from __future__ import annotations

import gzip
import io
import json
import os
from datetime import date

from . import store
from .sources import bbref, espn
from .sources.http import Fetcher

OUT = os.path.join('data', 'raw', 'espn_playin', '2020')
DAY = date(2020, 8, 15)
PLAY_IN_TYPE = 5


def _write_raw(path, data: bytes):
    """原始位元組以 gzip（mtime=0）保存，可重現。已存在則不覆寫。"""
    if os.path.exists(path):
        raise FileExistsError(f'{path} 已存在，不覆寫原始資料')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0) as gz:
        gz.write(data)
    with open(path, 'wb') as fh:
        fh.write(buf.getvalue())
    return path


def _sha(b: bytes):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def out_dir(season):
    return os.path.join('data', 'raw', 'espn_playin', str(season))


def candidate_dates(season):
    """附加賽的候選美東日期：該季最後一個例行賽日 ~ 第一個季後賽日（含兩端），從既有 games.jsonl.gz 推得，不寫死日期。"""
    from datetime import timedelta
    from . import asof
    g = [x for x in store.read_jsonl_gz(os.path.join('data', 'raw', 'espn', str(season), 'games.jsonl.gz')) if x['status'] == 'final']
    lo = max(asof.et_date(x['start_utc']) for x in g if x['season_type'] == 2)
    hi = min(asof.et_date(x['start_utc']) for x in g if x['season_type'] == 3)
    return [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]


EXPECTED = {2020: 1}            # 2019-20 泡泡區只有 1 場；2020-21 起每季 6 場（東西區各 3 場）
EXPECTED_DEFAULT = 6
LOCKED = (2026,)                # 2025-26 鎖定測試期：模型凍結前不抓、不讀


def run(seasons=(2020,), log=print):
    for season in seasons:
        if season in LOCKED:
            raise PermissionError(f'{season} 為鎖定測試期，模型凍結前不抓取')
        run_season(season, log)
    return 0


def run_season(season, log=print):
    out = out_dir(season)
    if os.path.exists(os.path.join(out, 'provenance.json')):
        log(f'{out} 已存在，不重抓、不覆寫')
        return
    f_espn, f_bb = Fetcher(min_interval=0.4), Fetcher(min_interval=3.5)
    prov = {'purpose': f'{season - 1}-{str(season)[2:]} Play-In（使用者 2026-11-20 核准獨立補抓）', 'season': season, 'files': {}}
    days = [DAY] if season == 2020 else candidate_dates(season)
    prov['scanned_et_dates'] = [d.isoformat() for d in days]
    games, skipped = [], []
    for d in days:
        sb_url = espn.scoreboard_url(d)
        sb_raw = f_espn.get_bytes(sb_url)
        fetched = espn.now_utc()
        name = f'raw/espn_scoreboard_{d:%Y%m%d}.json.gz'
        _write_raw(os.path.join(out, name), sb_raw)
        prov['files'][name] = {'url': sb_url, 'fetched_at': fetched, 'sha256_uncompressed': _sha(sb_raw)}
        for ev in json.loads(sb_raw).get('events', []):
            g, why = espn.parse_scoreboard_event(ev, fetched, keep={PLAY_IN_TYPE})
            if g is None:
                skipped.append({'date': d.isoformat(), 'event_id': ev.get('id'), 'reason': why})
                continue
            if g['season'] != season:
                skipped.append({'date': d.isoformat(), 'event_id': ev.get('id'), 'reason': f"season {g['season']}"})
                continue
            games.append(g)
    log(f'{season}: play-in games found {len(games)} (expected {EXPECTED.get(season, EXPECTED_DEFAULT)}); skipped {len(skipped)}')
    teamboxes, checks = [], []
    for g in games:
        g['game_type'] = 'PLAY_IN'
        g['counts_for_standings'] = False
        g['box_source'] = 'espn'
        sm_url = espn.summary_url(g['game_id'])
        sm_raw = f_espn.get_bytes(sm_url)
        t = espn.now_utc()
        name = f"raw/espn_summary_{g['game_id']}.json.gz"
        _write_raw(os.path.join(out, name), sm_raw)
        prov['files'][name] = {'url': sm_url, 'fetched_at': t, 'sha256_uncompressed': _sha(sm_raw), 'game_id': g['game_id']}
        try:
            bx = espn.parse_boxscore(json.loads(sm_raw), g['game_id'], t)
        except (ValueError, KeyError, TypeError) as e:
            checks.append({'game_id': g['game_id'], 'error': f'espn box: {type(e).__name__}: {e}'})
            continue
        teamboxes += bx
        bb_url = bbref.box_url(g)
        try:
            bb_raw = f_bb.get_bytes(bb_url)
        except Exception as e:  # noqa: BLE001 — 記錄後繼續，驗證結果會標示缺 BBRef
            checks.append(dict(verify(g, bx, {}), bbref_error=f'{type(e).__name__}: {str(e)[:120]}'))
            continue
        t = espn.now_utc()
        name = f"raw/bbref_box_{g['game_id']}.html.gz"
        _write_raw(os.path.join(out, name), bb_raw)
        prov['files'][name] = {'url': bb_url, 'fetched_at': t, 'sha256_uncompressed': _sha(bb_raw), 'game_id': g['game_id']}
        bbx = {b['team']: b for b in bbref.parse_box(bb_raw.decode('utf-8', 'replace'), g, t)}
        checks.append(verify(g, bx, bbx))
    store.write_jsonl_gz(os.path.join(out, 'games.jsonl.gz'), games)
    store.write_jsonl_gz(os.path.join(out, 'teambox.jsonl.gz'), teamboxes)
    store.write_json(os.path.join(out, 'verification.json'), {'season': season, 'expected_games': EXPECTED.get(season, EXPECTED_DEFAULT),
                                                              'games_found': len(games), 'games': checks, 'skipped_events': skipped})
    prov['parsed'] = {'games.jsonl.gz': 'espn.parse_scoreboard_event(keep={5})，加上 game_type=PLAY_IN、counts_for_standings=False',
                      'teambox.jsonl.gz': 'espn.parse_boxscore（與正式回補相同的解析器）'}
    store.write_json(os.path.join(out, 'provenance.json'), prov)


FIELDS = ('pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'tov')


def verify(g, espn_boxes, bbref_boxes):
    out = {'game_id': g['game_id'], 'season_type_espn': g['season_type'], 'matchup': f"{g['away_abbr']} @ {g['home_abbr']}",
           'score': [g['away_pts'], g['home_pts']], 'teams': {}}
    for b in espn_boxes:
        score = g['home_pts'] if b['team'] == g['home'] else g['away_pts']
        bb = bbref_boxes.get(b['team'], {})
        out['teams'][b['team']] = {
            'pts_identity_ok': 2 * b['fgm'] + b['fg3m'] + b['ftm'] == b['pts'],
            'pts_eq_scoreboard': b['pts'] == score,
            'espn_vs_bbref': {k: [b.get(k), bb.get(k)] for k in FIELDS},
            'all_fields_match_bbref': all(b.get(k) == bb.get(k) for k in FIELDS),
            'players': len(b.get('players') or [])}
    out['both_teams_present'] = len(out['teams']) == 2
    return out
