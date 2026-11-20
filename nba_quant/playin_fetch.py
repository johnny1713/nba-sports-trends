"""
2019-20 泡泡區附加賽（Play-In）獨立抓取（使用者 2026-11-20 核准）。

    python -m nba_quant.jobs backfill --playin-2020

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


def run(log=print):
    if os.path.exists(os.path.join(OUT, 'provenance.json')):
        log(f'{OUT} 已存在，不重抓、不覆寫')
        return 0
    f_espn, f_bb = Fetcher(min_interval=0.4), Fetcher(min_interval=3.5)
    prov = {'purpose': '2019-20 Play-In（使用者 2026-11-20 核准獨立補抓）', 'files': {}}
    sb_url = espn.scoreboard_url(DAY)
    sb_raw = f_espn.get_bytes(sb_url)
    fetched = espn.now_utc()
    _write_raw(os.path.join(OUT, 'raw', 'espn_scoreboard_20200815.json.gz'), sb_raw)
    prov['files']['raw/espn_scoreboard_20200815.json.gz'] = {'url': sb_url, 'fetched_at': fetched, 'sha256_uncompressed': _sha(sb_raw)}
    games, skipped = [], []
    for ev in json.loads(sb_raw).get('events', []):
        g, why = espn.parse_scoreboard_event(ev, fetched, keep={PLAY_IN_TYPE})
        if g is None:
            skipped.append({'event_id': ev.get('id'), 'reason': why})
            continue
        games.append(g)
    log(f'play-in games found: {len(games)}; other events on that date skipped: {len(skipped)}')
    teamboxes, checks = [], []
    for g in games:
        g['game_type'] = 'PLAY_IN'
        g['counts_for_standings'] = False
        g['box_source'] = 'espn'
        sm_url = espn.summary_url(g['game_id'])
        sm_raw = f_espn.get_bytes(sm_url)
        t = espn.now_utc()
        name = f"raw/espn_summary_{g['game_id']}.json.gz"
        _write_raw(os.path.join(OUT, name), sm_raw)
        prov['files'][name] = {'url': sm_url, 'fetched_at': t, 'sha256_uncompressed': _sha(sm_raw)}
        bx = espn.parse_boxscore(json.loads(sm_raw), g['game_id'], t)
        bx = [b.__dict__ if hasattr(b, '__dict__') else b for b in bx]
        teamboxes += bx
        bb_url = bbref.box_url(g)
        bb_raw = f_bb.get_bytes(bb_url)
        t = espn.now_utc()
        name = f"raw/bbref_box_{g['game_id']}.html.gz"
        _write_raw(os.path.join(OUT, name), bb_raw)
        prov['files'][name] = {'url': bb_url, 'fetched_at': t, 'sha256_uncompressed': _sha(bb_raw)}
        bbx = bbref.parse_box(bb_raw.decode('utf-8', 'replace'), g, t)
        bbx = {(b.__dict__ if hasattr(b, '__dict__') else b)['team']: (b.__dict__ if hasattr(b, '__dict__') else b) for b in bbx}
        checks.append(verify(g, bx, bbx))
    store.write_jsonl_gz(os.path.join(OUT, 'games.jsonl.gz'), games)
    store.write_jsonl_gz(os.path.join(OUT, 'teambox.jsonl.gz'), teamboxes)
    store.write_json(os.path.join(OUT, 'verification.json'), {'games': checks, 'skipped_events': skipped})
    prov['parsed'] = {'games.jsonl.gz': 'espn.parse_scoreboard_event(keep={5})，加上 game_type=PLAY_IN、counts_for_standings=False',
                      'teambox.jsonl.gz': 'espn.parse_boxscore（與正式回補相同的解析器）'}
    store.write_json(os.path.join(OUT, 'provenance.json'), prov)
    log(json.dumps(checks, ensure_ascii=False)[:2000])
    return 0


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
