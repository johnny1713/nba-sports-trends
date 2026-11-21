"""
Box score 欄位合理性稽核 v1（唯讀；獨立版本化，與盤口品質報告分開保存，不改任何既有檔案或 PASS 狀態）。

    PYTHONPATH=. python -m nba_quant.box_audit            # 全部球季
輸出：
    data/audit/box_quality/v1/<季>_flags.jsonl.gz   逐筆旗標（game_id, team, check, severity, detail）
    data/audit/box_quality/v1/summary.json          各季統計、系統性檢查結果
    docs/reports/box_quality/v1/README.md           報告

三個層級：
1. 單筆錯誤（record）：恆等式（命中 <= 出手、三分命中 <= 投籃命中、得分 = 2*FGM + 3PM + FTM、
   得分 = 計分板比分、球員得分加總 = 球隊得分）、非負、關鍵欄位為 0、
   相對於「同季同來源」分布的穩健離群值（中位數 ± 6 × 1.4826 × MAD），而不只靠固定範圍。
2. 同場關係（game）：兩隊皆有 box、回合數估計兩隊應接近、
   進攻籃板 A + 防守籃板 B 不可超過 A 的投籃不中 + 罰球不中（可搶的籃板上限）。
3. 整季系統性（season）：各欄位季平均與「前後各兩季」直線趨勢預測值比較（不用全期間或鄰近季中位數——
   三分出手逐年上升，邊界季只有單邊鄰居，用中位數會把真實趨勢誤判成錯誤）；以及欄位為 0 的比例。
   另比較同季 ESPN 原生與 BBRef 補抓的分布（不同場次，只是弱證據；定義是否一致要看同場比對）。
"""
from __future__ import annotations

import json
import os
import statistics
from collections import Counter, defaultdict

from . import store

VERSION = 'v1'
RAW = os.path.join('data', 'raw', 'espn')
OUT = os.path.join('data', 'audit', 'box_quality', VERSION)
REPORT = os.path.join('docs', 'reports', 'box_quality', VERSION, 'README.md')
FIELDS = ('pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'tov')
ZERO_SUSPECT = ('fgm', 'fga', 'dreb', 'tov', 'oreb')    # 一場 NBA 比賽實務上幾乎不可能為 0
MAD_K = 6.0
SEASON_REL = 0.10          # 季平均偏離鄰近季趨勢預測超過 10% → 系統性異常候選
SEASON_ZERO_SHARE = 0.02   # 該欄位為 0 的比例超過 2% → 系統性異常候選
POSS_REL = 0.08            # 兩隊回合數估計相差超過 8%


def _src(row):
    return 'bbref' if str(row.get('source', '')).startswith('bbref') else 'espn'


def possessions(b):
    if any(b.get(k) is None for k in ('fga', 'oreb', 'tov', 'fta')):
        return None
    return b['fga'] - b['oreb'] + b['tov'] + 0.44 * b['fta']


def record_checks(b, game):
    """單筆恆等式與基本檢查。回傳 [(check, severity, detail)]。"""
    out = []
    v = {k: b.get(k) for k in FIELDS}
    for k, x in v.items():
        if x is None:
            out.append(('field_missing', 'missing', k))
        elif x < 0:
            out.append(('negative_value', 'error', f'{k}={x}'))
    g = lambda k: v[k] if v[k] is not None else None
    pairs = (('fgm', 'fga'), ('fg3m', 'fg3a'), ('ftm', 'fta'), ('fg3m', 'fgm'), ('fg3a', 'fga'))
    for a, c in pairs:
        if g(a) is not None and g(c) is not None and g(a) > g(c):
            out.append((f'{a}_gt_{c}', 'error', f'{a}={g(a)} {c}={g(c)}'))
    if all(g(k) is not None for k in ('pts', 'fgm', 'fg3m', 'ftm')):
        calc = 2 * g('fgm') + g('fg3m') + g('ftm')
        if calc != g('pts'):
            out.append(('pts_identity', 'error', f'2*FGM+3PM+FTM={calc} pts={g("pts")}'))
    score = game['home_pts'] if b['team'] == game['home'] else (game['away_pts'] if b['team'] == game['away'] else None)
    if score is None:
        out.append(('team_not_in_game', 'error', b['team']))
    elif g('pts') is not None and g('pts') != score:
        out.append(('pts_vs_scoreboard', 'error', f'box={g("pts")} scoreboard={score}'))
    ps = [p.get('pts') for p in b.get('players') or [] if p.get('pts') is not None]
    if ps and g('pts') is not None and sum(ps) != g('pts'):
        out.append(('player_pts_sum', 'warning', f'sum={sum(ps)} team={g("pts")}'))
    for k in ZERO_SUSPECT:
        if v[k] == 0:
            out.append(('zero_value', 'error', k))
    return out


def robust_bounds(values):
    vs = [x for x in values if x is not None]
    if len(vs) < 30:
        return None
    med = statistics.median(vs)
    mad = statistics.median(abs(x - med) for x in vs) * 1.4826
    if mad == 0:
        return None
    return med - MAD_K * mad, med + MAD_K * mad, med, mad


def game_checks(game, boxes):
    """同場兩隊關係。boxes: {team: box}。"""
    out = []
    teams = (game['home'], game['away'])
    missing = [t for t in teams if t not in boxes]
    if missing:
        return [('box_missing_team', 'missing', ','.join(missing), None)]
    h, a = boxes[game['home']], boxes[game['away']]
    ph, pa = possessions(h), possessions(a)
    if ph and pa and abs(ph - pa) / ((ph + pa) / 2) > POSS_REL:
        out.append(('possessions_mismatch', 'warning', f'home={ph:.1f} away={pa:.1f}', None))
    for off, de, tid in ((h, a, game['home']), (a, h, game['away'])):
        need = ('fga', 'fgm', 'fta', 'ftm', 'oreb')
        if any(off.get(k) is None for k in need) or de.get('dreb') is None:
            continue
        cap = (off['fga'] - off['fgm']) + (off['fta'] - off['ftm'])
        reb = off['oreb'] + de['dreb']
        if reb > cap:
            out.append(('rebounds_exceed_misses', 'error', f'oreb+opp_dreb={reb} misses={cap}', tid))
    return out


def audit_scope(season, root='.'):
    """稽核範圍（唯一定義）：完賽比賽與其球隊 box。稽核涵蓋清單（audit_coverage.py）也用這個函式。"""
    d = os.path.join(root, RAW, str(season))
    games = {g['game_id']: g for g in store.read_jsonl_gz(os.path.join(d, 'games.jsonl.gz')) if g['status'] == 'final'}
    boxes = [b for b in store.read_jsonl_gz(os.path.join(d, 'teambox.jsonl.gz')) if b['game_id'] in games]
    return games, boxes


def audit_season(season, root='.'):
    games, boxes = audit_scope(season, root)
    flags = []
    by_game = defaultdict(dict)
    for b in boxes:
        by_game[b['game_id']][b['team']] = b
        for c, sev, det in record_checks(b, games[b['game_id']]):
            flags.append({'game_id': b['game_id'], 'team': b['team'], 'source': _src(b), 'level': 'record',
                          'check': c, 'severity': sev, 'detail': det})
    # 穩健離群值：同季、同來源、同賽段
    groups = defaultdict(list)
    for b in boxes:
        groups[(_src(b), games[b['game_id']]['season_type'])].append(b)
    bounds = {}
    for key, bs in groups.items():
        for k in FIELDS:
            rb = robust_bounds([b.get(k) for b in bs])
            bounds[(key, k)] = rb
            if not rb:
                continue
            lo, hi, med, mad = rb
            for b in bs:
                x = b.get(k)
                if x is not None and (x < lo or x > hi):
                    flags.append({'game_id': b['game_id'], 'team': b['team'], 'source': key[0], 'level': 'record',
                                  'check': 'robust_outlier', 'severity': 'warning',
                                  'detail': f'{k}={x} median={med:g} band=[{lo:.1f},{hi:.1f}]'})
    for gid, g in games.items():
        if not g.get('complete'):
            continue
        for c, sev, det, tid in game_checks(g, by_game.get(gid, {})):
            flags.append({'game_id': gid, 'team': tid, 'source': None, 'level': 'game', 'check': c,
                          'severity': sev, 'detail': det})
    # 季統計（例行賽，依來源）
    stats = {}
    for src in ('espn', 'bbref', 'all'):
        bs = [b for b in boxes if games[b['game_id']]['season_type'] == 2 and (src == 'all' or _src(b) == src)]
        if not bs:
            continue
        st = {'n': len(bs)}
        for k in FIELDS:
            vs = [b[k] for b in bs if b.get(k) is not None]
            if vs:
                st[k] = {'mean': round(statistics.mean(vs), 3), 'median': statistics.median(vs),
                         'zero_share': round(sum(1 for x in vs if x == 0) / len(vs), 4), 'max': max(vs), 'n': len(vs)}
        bsp = [possessions(b) for b in bs]
        bsp = [p for p in bsp if p]
        if bsp:
            st['possessions_mean'] = round(statistics.mean(bsp), 2)
        stats[src] = st
    flags.sort(key=lambda f: (f['game_id'], str(f['team']), f['check'], f['detail']))
    return flags, stats


def trend_predict(points, x0):
    """以前後兩季做最小平方直線，預測 x0 季的值（處理三分出手這類逐年趨勢；邊界季只有單邊鄰居時等於外插）。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx if sxx else 0.0
    return my + slope * (x0 - mx)


def _season_rows(all_stats, src, k, excluded):
    seasons = sorted(all_stats)
    rows = []
    for s in seasons:
        st = all_stats[s].get(src, {}).get(k)
        if not st:
            continue
        nb = [t for t in seasons if t != s and t not in excluded and all_stats[t].get(src, {}).get(k)]
        near = [t for t in nb if abs(t - s) <= 2]
        if len(near) < 2:                       # 鄰居被排除時放寬到 ±3 季
            near = [t for t in nb if abs(t - s) <= 3]
        if len(near) < 2:
            continue
        ref = trend_predict([(t, all_stats[t][src][k]['mean']) for t in near], s)
        rel = (st['mean'] - ref) / ref if ref else None
        zero = st['zero_share']
        nb_zero = statistics.median([all_stats[t][src][k]['zero_share'] for t in near])
        hit = (rel is not None and abs(rel) > SEASON_REL) or (zero > SEASON_ZERO_SHARE and zero > 5 * max(nb_zero, 0.001))
        rows.append({'season': s, 'source': src, 'field': k, 'mean': st['mean'], 'neighbor_trend': round(ref, 3),
                     'reference_seasons': near, 'rel_diff': round(rel, 4) if rel is not None else None,
                     'zero_share': zero, 'neighbor_zero_share': nb_zero, 'systematic_suspect': bool(hit)})
    return rows


def season_systematic(all_stats):
    """季平均 vs 前後兩季直線趨勢預測。異常季會汙染鄰居的參考值（2017-18 失誤 1.18 會把前後季的預測拉低），
    所以逐輪把「偏離最大的異常季」從參考季中剔除後重算，直到沒有新的異常季。被剔除的季仍照常列出自己的結果。"""
    out = []
    for src in ('espn', 'all'):
        for k in FIELDS:
            excluded = set()
            for _ in range(len(all_stats)):
                rows = _season_rows(all_stats, src, k, excluded)
                cand = [r for r in rows if r['systematic_suspect'] and r['season'] not in excluded]
                if not cand:
                    break
                worst = max(cand, key=lambda r: (abs(r['rel_diff'] or 0), r['zero_share']))
                excluded.add(worst['season'])
            for r in rows:
                r['excluded_from_reference'] = r['season'] in excluded
            out += rows
    return out


def source_mix(all_stats):
    """同季 ESPN 原生 vs BBRef 補抓的平均差（不同場次，僅弱證據）。"""
    out = []
    for s in sorted(all_stats):
        e, b = all_stats[s].get('espn'), all_stats[s].get('bbref')
        if not e or not b or b['n'] < 30:
            continue
        for k in FIELDS:
            if k in e and k in b:
                out.append({'season': s, 'field': k, 'espn_n': e[k]['n'], 'bbref_n': b[k]['n'],
                            'espn_mean': e[k]['mean'], 'bbref_mean': b[k]['mean'],
                            'diff': round(e[k]['mean'] - b[k]['mean'], 3)})
    return out


def season_label(s):
    return f'{s - 1}-{str(s)[2:]}'


def render(summary):
    L = [f'# Box score 欄位合理性稽核 {VERSION}', '',
         '唯讀稽核。只讀 `data/raw/espn/<季>/games.jsonl.gz`、`teambox.jsonl.gz`；與盤口品質報告分開保存，'
         '**不改任何既有報告、不改盤口 PASS 狀態、不覆寫原始資料**。', '',
         f'門檻：穩健離群值 = 同季同來源同賽段中位數 ± {MAD_K:g} × 1.4826 × MAD；季平均偏離「前後各兩季直線趨勢預測值」> {SEASON_REL:.0%}；'
         f'欄位為 0 比例 > {SEASON_ZERO_SHARE:.0%} 且 > 鄰近季 5 倍；兩隊回合數估計相差 > {POSS_REL:.0%}。', '',
         '## 1. 逐季旗標數（逐筆，error / warning / missing）', '',
         '| 球季 | 球隊 box 筆數 | ESPN | BBRef | error | warning | missing | 主要檢查 |', '|---|---|---|---|---|---|---|---|']
    for s, x in sorted(summary['seasons'].items(), key=lambda kv: int(kv[0])):
        top = ', '.join(f'{k} {v}' for k, v in sorted(x['by_check'].items(), key=lambda kv: -kv[1])[:4])
        L.append(f"| {season_label(int(s))} | {x['boxes']} | {x['espn_boxes']} | {x['bbref_boxes']} | "
                 f"{x['by_severity'].get('error', 0)} | {x['by_severity'].get('warning', 0)} | "
                 f"{x['by_severity'].get('missing', 0)} | {top} |")
    L += ['', '## 2. 整季系統性異常候選（ESPN 原生來源，例行賽）', '',
          '| 球季 | 欄位 | 季平均 | 前後兩季趨勢預測 | 相對差 | 0 值比例 | 鄰近季 0 值比例 |', '|---|---|---|---|---|---|---|']
    hits = [r for r in summary['systematic'] if r['systematic_suspect'] and r['source'] == 'espn']
    for r in hits:
        L.append(f"| {season_label(r['season'])} | {r['field']} | {r['mean']} | {r['neighbor_trend']} | "
                 f"{r['rel_diff']:+.1%} | {r['zero_share']:.1%} | {r['neighbor_zero_share']:.1%} |")
    if not hits:
        L.append('| — | 無 | | | | | |')
    L += ['', '## 3. 同季 ESPN 原生 vs BBRef 補抓（不同場次，弱證據）', '',
          '只有 BBRef 補抓 ≥ 30 筆的球季才列。兩者是**不同場次**，差異可能來自場次組成，不能單獨證明定義不同；'
          '定義是否一致以同場比對（`docs/reports/box_quality/v1/source_compare.md`）為準。', '',
          '| 球季 | 欄位 | ESPN n | BBRef n | ESPN 平均 | BBRef 平均 | 差 |', '|---|---|---|---|---|---|---|']
    for r in summary['source_mix']:
        L.append(f"| {season_label(r['season'])} | {r['field']} | {r['espn_n']} | {r['bbref_n']} | "
                 f"{r['espn_mean']} | {r['bbref_mean']} | {r['diff']:+.3f} |")
    L += ['', '## 4. 各季 ESPN 原生例行賽平均（參考）', '',
          '| 球季 | n | ' + ' | '.join(FIELDS) + ' | 回合數 |', '|' + '---|' * (len(FIELDS) + 3)]
    for s, x in sorted(summary['season_stats'].items(), key=lambda kv: int(kv[0])):
        e = x.get('espn')
        if not e:
            continue
        L.append(f"| {season_label(int(s))} | {e['n']} | " + ' | '.join(str(e[k]['mean']) if k in e else '' for k in FIELDS)
                 + f" | {e.get('possessions_mean', '')} |")
    L += ['', '## 5. error 旗標明細（最多每季 15 筆）', '']
    for s, x in sorted(summary['seasons'].items(), key=lambda kv: int(kv[0])):
        if x['error_samples']:
            L.append(f'**{season_label(int(s))}**')
            L.append('')
            for f in x['error_samples']:
                L.append(f"- {f['game_id']} team {f['team']} ({f['source']}): {f['check']} — {f['detail']}")
            L.append('')
    return '\n'.join(L) + '\n'


def main():
    seasons = [int(x) for x in sorted(os.listdir(RAW)) if os.path.exists(os.path.join(RAW, x, 'teambox.jsonl.gz'))]
    summary = {'version': VERSION, 'seasons': {}, 'season_stats': {}}
    all_stats = {}
    for s in seasons:
        flags, stats = audit_season(s)
        store.write_jsonl_gz(os.path.join(OUT, f'{s}_flags.jsonl.gz'), flags)
        boxes = list(store.read_jsonl_gz(os.path.join(RAW, str(s), 'teambox.jsonl.gz')))
        all_stats[s] = stats
        errs = [f for f in flags if f['severity'] == 'error']
        summary['seasons'][str(s)] = {
            'boxes': len(boxes), 'espn_boxes': sum(1 for b in boxes if _src(b) == 'espn'),
            'bbref_boxes': sum(1 for b in boxes if _src(b) == 'bbref'),
            'by_severity': dict(Counter(f['severity'] for f in flags)),
            'by_check': dict(Counter(f['check'] if f['check'] != 'zero_value' else f"zero_value:{f['detail']}" for f in flags)),
            'error_samples': errs[:15]}
        summary['season_stats'][str(s)] = stats
    summary['systematic'] = season_systematic(all_stats)
    summary['source_mix'] = source_mix(all_stats)
    store.write_json(os.path.join(OUT, 'summary.json'), summary)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write(render(summary))
    print(REPORT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
