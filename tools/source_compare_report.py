"""
ESPN vs BBRef 同場比對報告 + 2017-18 失誤欄位探查（唯讀；讀 data/audit/source_compare/<季>/compare.jsonl.gz）。

    PYTHONPATH=. python tools/source_compare_report.py

輸出：
    docs/reports/box_quality/v1/source_compare.md
    data/audit/box_quality/v1/source_compare_stats.json
    docs/reports/box_quality/v1/source_compare_mismatches.csv（候選欄位與已存資料欄位的完整不一致紀錄）

⚠️ 不產生任何 derived 修正版（使用者 2026-11-20 指示）：即使某欄位一致率 ≥ 99%，也只列為「高度一致的候選欄位」。
產生修正版之前必須先完成：定義一致性確認、完整不一致紀錄、集中度（球隊／月份／球季／比賽類型）、
方向與系統性偏差、確認 ESPN 欄位是真的錯誤而非定義不同；並經使用者核准。
"""
from __future__ import annotations

import math
import os
import statistics
from collections import Counter, defaultdict

from nba_quant import store

AUDIT = os.path.join('data', 'audit', 'source_compare')
RAW = os.path.join('data', 'raw', 'espn')
REPORT = os.path.join('docs', 'reports', 'box_quality', 'v1', 'source_compare.md')
STATS = os.path.join('data', 'audit', 'box_quality', 'v1', 'source_compare_stats.json')
MISMATCH_CSV = os.path.join('docs', 'reports', 'box_quality', 'v1', 'source_compare_mismatches.csv')
CANDIDATE_EXACT = 0.99           # 只用來標示「高度一致的候選欄位」，不會觸發任何修正

ESPN_SPLIT = {'fgm': ('fieldGoalsMade-fieldGoalsAttempted', 0), 'fga': ('fieldGoalsMade-fieldGoalsAttempted', 1),
              'fg3m': ('threePointFieldGoalsMade-threePointFieldGoalsAttempted', 0),
              'fg3a': ('threePointFieldGoalsMade-threePointFieldGoalsAttempted', 1),
              'ftm': ('freeThrowsMade-freeThrowsAttempted', 0), 'fta': ('freeThrowsMade-freeThrowsAttempted', 1)}
ESPN_PLAIN = {'oreb': 'offensiveRebounds', 'dreb': 'defensiveRebounds', 'trb': 'totalRebounds'}
BBREF_KEY = {'fgm': 'fg', 'fga': 'fga', 'fg3m': 'fg3', 'fg3a': 'fg3a', 'ftm': 'ft', 'fta': 'fta',
             'oreb': 'orb', 'dreb': 'drb', 'trb': 'trb', 'tov': 'tov', 'pts': 'pts'}
TOV_VARIANTS = ('turnovers', 'teamTurnovers', 'totalTurnovers', 'player_to_sum', 'player_to_sum+teamTurnovers',
                'player_to_sum+turnovers')


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def espn_value(ts, field):
    if field in ESPN_SPLIT:
        k, i = ESPN_SPLIT[field]
        v = ts.get(k)
        if not v or '-' not in v:
            return None
        return _int(v.split('-')[i])
    if field in ESPN_PLAIN:
        return _int(ts.get(ESPN_PLAIN[field]))
    return None


def tov_variant(ts, psum, name):
    if name == 'player_to_sum':
        return psum
    if name in ('player_to_sum+teamTurnovers', 'player_to_sum+turnovers'):
        t = _int(ts.get(name.split('+')[1]))
        return psum + t if psum is not None and t is not None else None
    return _int(ts.get(name))


def diff_stats(pairs):
    """pairs: [(espn, bbref)]"""
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    n = len(pairs)
    if not n:
        return None
    d = [a - b for a, b in pairs]
    md = statistics.mean(d)
    sd = statistics.stdev(d) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else float('nan')
    dist = Counter(max(-3, min(3, x)) for x in d)
    exact = sum(1 for x in d if x == 0) / n
    return {'n': n, 'espn_mean': round(statistics.mean(a for a, _ in pairs), 3),
            'bbref_mean': round(statistics.mean(b for _, b in pairs), 3), 'mean_diff': round(md, 3),
            'ci95': [round(md - half, 3), round(md + half, 3)] if n > 1 else None,
            'dist': {str(k): dist.get(k, 0) for k in range(-3, 4)}, 'exact_share': round(exact, 4),
            'systematic': bool(n > 1 and exact < 0.95 and (md - half > 0 or md + half < 0))}


def load():
    rows = {}
    for s in sorted(os.listdir(AUDIT)) if os.path.isdir(AUDIT) else []:
        p = os.path.join(AUDIT, s, 'compare.jsonl.gz')
        if os.path.exists(p):
            rows[int(s)] = list(store.read_jsonl_gz(p))
    return rows


def stored_boxes(season):
    return {(b['game_id'], b['team']): b for b in store.read_jsonl_gz(os.path.join(RAW, str(season), 'teambox.jsonl.gz'))}


def analyse(rows_by_season):
    out = {}
    for season, rows in rows_by_season.items():
        rows = [r for r in rows if r.get('in_compare_sample') and r.get('espn_team_fields') and r.get('bbref_team_totals')]
        stored = stored_boxes(season)
        per = defaultdict(list)
        months, teams = set(), set()
        for r in rows:
            months.add(r['start_utc'][:7])
            for tid in (r['home'], r['away']):
                ts = r['espn_team_fields'].get(tid)
                bb = r['bbref_team_totals'].get(tid)
                if not ts or not bb:
                    continue
                teams.add(tid)
                for f in list(ESPN_SPLIT) + list(ESPN_PLAIN):
                    per[f].append((espn_value(ts, f), bb.get(BBREF_KEY[f])))
                psum = (r.get('espn_player_to_sum') or {}).get(tid)
                for v in TOV_VARIANTS:
                    per[f'tov[{v}]'].append((tov_variant(ts, psum, v), bb.get('tov')))
                bps = (r.get('bbref_player_tov_sum') or {}).get(tid)
                per['tov[player_to_sum] vs bbref_player_tov_sum'].append((psum, bps))
                # 全隊失誤（不記在任何球員名下）：BBRef = 球隊合計 − 球員加總；ESPN 兩個候選欄位
                gap = bb.get('tov') - bps if bb.get('tov') is not None and bps is not None else None
                for v in ('turnovers', 'teamTurnovers'):
                    per[f'team_tov[{v}] vs bbref_team_minus_player'].append((_int(ts.get(v)), gap))
                sb = stored.get((r['game_id'], tid))
                if sb:
                    for f in ('pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'tov'):
                        per[f'stored.{f}'].append((sb.get(f), bb.get(BBREF_KEY[f])))
        out[season] = {'games': len(rows), 'months': sorted(months), 'teams': len(teams),
                       'fields': {k: diff_stats(v) for k, v in per.items()}}
    return out


def _phase(r):
    return 'regular' if r.get('season_type') == 2 else 'postseason'


def _pairs(r, tid, field):
    """回傳 (espn, bbref) 或 None。field 為分析鍵（含 tov[...] 與 stored.*）。"""
    ts = (r.get('espn_team_fields') or {}).get(tid)
    bb = (r.get('bbref_team_totals') or {}).get(tid)
    if not ts or not bb:
        return None
    if field.startswith('tov['):
        v = field[4:-1]
        return tov_variant(ts, (r.get('espn_player_to_sum') or {}).get(tid), v), bb.get('tov')
    return espn_value(ts, field), bb.get(BBREF_KEY[field])


def best_tov_field(season_stats):
    c = [(k, v) for k, v in season_stats['fields'].items() if k.startswith('tov[') and ' vs ' not in k and v]
    return max(c, key=lambda kv: kv[1]['exact_share'])[0] if c else None


def mismatches(rows_by_season, stats):
    """完整不一致紀錄：一致率 ≥ 95%（未達 100%）的欄位，以及每季最接近 BBRef 的 ESPN 失誤欄位（不論一致率）。"""
    out = []
    for season, rows in rows_by_season.items():
        stored = stored_boxes(season)
        for k, st in stats[season]['fields'].items():
            best_tov = k == best_tov_field(stats[season])
            if not st or st['exact_share'] == 1 or ' vs ' in k or (st['exact_share'] < 0.95 and not best_tov):
                continue
            for r in rows:
                if not r.get('in_compare_sample'):
                    continue
                for tid in (r['home'], r['away']):
                    if k.startswith('stored.'):
                        f = k[7:]
                        sb, bb = stored.get((r['game_id'], tid)), (r.get('bbref_team_totals') or {}).get(tid)
                        if not sb or not bb:
                            continue
                        pr = (sb.get(f), bb.get(BBREF_KEY[f]))
                    else:
                        pr = _pairs(r, tid, k)
                    if not pr or pr[0] is None or pr[1] is None or pr[0] == pr[1]:
                        continue
                    out.append({'season': season, 'field': k, 'game_id': r['game_id'], 'start_utc': r['start_utc'],
                                'month': r['start_utc'][:7], 'phase': _phase(r), 'team': tid,
                                'team_abbr': r['home_abbr'] if tid == r['home'] else r['away_abbr'],
                                'home_away': 'home' if tid == r['home'] else 'away',
                                'espn': pr[0], 'bbref': pr[1], 'diff': pr[0] - pr[1]})
    out.sort(key=lambda x: (x['season'], x['field'], x['start_utc'], x['game_id'], x['team']))
    return out


def concentration(mm, rows_by_season, key):
    """不一致紀錄依 key（team_abbr / month / phase / season / home_away）分組，對照該組的總筆數。"""
    tot = Counter()
    for season, rows in rows_by_season.items():
        for r in rows:
            if not r.get('in_compare_sample') or not r.get('espn_team_fields') or not r.get('bbref_team_totals'):
                continue
            for tid in (r['home'], r['away']):
                rec = {'season': season, 'month': r['start_utc'][:7], 'phase': _phase(r),
                       'team_abbr': r['home_abbr'] if tid == r['home'] else r['away_abbr'],
                       'home_away': 'home' if tid == r['home'] else 'away'}
                tot[rec[key]] += 1
    c = Counter(m[key] for m in mm)
    return [(k, c[k], tot[k]) for k in sorted(c, key=lambda k: (-c[k] / max(tot[k], 1), str(k)))]


def definition_checks(rows_by_season):
    """兩個來源各自的內部恆等式，用來判斷「定義」：
    ESPN：totalTurnovers = turnovers + teamTurnovers？turnovers = 球員 TO 加總？
    BBRef：球隊 tov 合計 − 球員 tov 加總（= 是否把全隊失誤算進球隊合計）
    籃板：各來源 oreb + dreb = trb？（BBRef 不含全隊籃板；ESPN 是否含？）"""
    out = {}
    for season, rows in rows_by_season.items():
        c = Counter()
        bb_gap = Counter()
        for r in rows:
            if not r.get('in_compare_sample'):
                continue
            for tid in (r['home'], r['away']):
                ts = (r.get('espn_team_fields') or {}).get(tid)
                bb = (r.get('bbref_team_totals') or {}).get(tid)
                if ts:
                    t, tt, tot = _int(ts.get('turnovers')), _int(ts.get('teamTurnovers')), _int(ts.get('totalTurnovers'))
                    ps = (r.get('espn_player_to_sum') or {}).get(tid)
                    c['espn_n'] += 1
                    c['espn_total_eq_tov_plus_team'] += (None not in (t, tt, tot) and tot == t + tt)
                    c['espn_turnovers_eq_player_sum'] += (t is not None and ps is not None and t == ps)
                    c['espn_total_eq_player_sum'] += (tot is not None and ps is not None and tot == ps)
                    o, d, trb = espn_value(ts, 'oreb'), espn_value(ts, 'dreb'), espn_value(ts, 'trb')
                    c['espn_oreb_plus_dreb_eq_trb'] += (None not in (o, d, trb) and o + d == trb)
                if bb:
                    pts = (r.get('bbref_player_tov_sum') or {}).get(tid)
                    c['bbref_n'] += 1
                    if bb.get('tov') is not None and pts is not None:
                        bb_gap[bb['tov'] - pts] += 1
                    c['bbref_orb_plus_drb_eq_trb'] += (None not in (bb.get('orb'), bb.get('drb'), bb.get('trb'))
                                                       and bb['orb'] + bb['drb'] == bb['trb'])
        out[season] = {**dict(c), 'bbref_team_minus_player_tov': {str(k): v for k, v in sorted(bb_gap.items())}}
    return out


def coverage(season, rows, fetch_log):
    """實際完成比對的場數、兩隊 box 筆數、未能比對的場次與原因。"""
    sample = [r for r in rows if r.get('in_compare_sample')]
    errs = defaultdict(list)
    for e in fetch_log.get('errors', []):
        errs[e['game_id']].append(f"{e['source']}: {e['error']}")
    done, failed = [], []
    boxes = 0
    for r in sample:
        why = list(errs.get(r['game_id'], []))
        n = 0
        for tid in (r['home'], r['away']):
            if (r.get('espn_team_fields') or {}).get(tid) and (r.get('bbref_team_totals') or {}).get(tid):
                n += 1
            else:
                why.append(f'team {tid}: ' + ('缺 ESPN 球隊統計' if not (r.get('espn_team_fields') or {}).get(tid) else '缺 BBRef 球隊合計'))
        boxes += n
        (done if n == 2 else failed).append((r, sorted(set(why))))
    target = len(sample)
    games_all = [g for g in store.read_jsonl_gz(os.path.join(RAW, str(season), 'games.jsonl.gz'))
                 if g['status'] == 'final' and g['season_type'] == 2]
    return {'regular_final_games': len(games_all),
            'excluded_bbref_box_games': sum(1 for g in games_all if g.get('box_source') == 'bbref'),
            'excluded_incomplete': sum(1 for g in games_all if not g.get('complete')),
            'target': target, 'compared_games': len(done), 'compared_team_boxes': boxes,
            'failed': [{'game_id': r['game_id'], 'start_utc': r['start_utc'], 'matchup': f"{r['away_abbr']} @ {r['home_abbr']}",
                        'reasons': why} for r, why in failed]}


def season_label(s):
    return f'{s - 1}-{str(s)[2:]}'


def _cands(stats):
    return {s: [k for k, v in st['fields'].items() if v and v['exact_share'] >= CANDIDATE_EXACT and not k.startswith('stored.')
                and ' vs ' not in k] for s, st in stats.items()}


def render(stats, cov, defs, mm, conc, logs):
    L = ['# ESPN vs BBRef 同場比對（box score v1）', '',
         '唯讀比對。每季固定種子（20261120）依月份輪流、優先未涵蓋的球隊抽約 30 場 ESPN 原生 box score 的例行賽；'
         '2017-18 為該季全部 ESPN 原生例行賽。差 = ESPN − BBRef。「系統性」= 完全一致 < 95% 且平均差 95% CI 不含 0。', '',
         '**本報告不產生任何修正版資料。** 一致率 ≥ 99% 的欄位只標示為「高度一致的候選欄位」；'
         '產生 derived 修正版須經使用者核准。', '',
         '## 0. 覆蓋與抓取紀錄', '',
         '| 球季 | 例行賽完賽 | 其中 BBRef 補值（不抽）| 抽樣目標 | 完成比對場數 | 兩隊 box 筆數 | 未能比對 | 月份數 | 球隊數 | ESPN 請求 | BBRef 請求 |',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    for s in sorted(stats):
        c, fl = cov[s], logs.get(s, {})
        L.append(f"| {season_label(s)} | {c['regular_final_games']} | {c['excluded_bbref_box_games']} | {c['target']} | "
                 f"{c['compared_games']} | {c['compared_team_boxes']} | {len(c['failed'])} | {len(stats[s]['months'])} | "
                 f"{stats[s]['teams']} | {fl.get('espn_requests', '')} | {fl.get('bbref_requests', '')} |")
    for s in sorted(cov):
        if cov[s]['failed']:
            L += ['', f'**{season_label(s)} 未能比對的場次**', '', '| game_id | 開賽 UTC | 對戰 | 原因 |', '|---|---|---|---|']
            for f in cov[s]['failed']:
                L.append(f"| {f['game_id']} | {f['start_utc']} | {f['matchup']} | {'；'.join(f['reasons']) or '不明'} |")
    L += ['', '## 1. 統計定義檢查（各來源內部恆等式）', '',
          '| 球季 | ESPN 筆數 | total = turnovers + team | turnovers = 球員加總 | total = 球員加總 | ESPN oreb+dreb = trb | '
          'BBRef 筆數 | BBRef orb+drb = trb | BBRef 球隊 tov − 球員 tov 加總（值:筆數） |', '|---|---|---|---|---|---|---|---|---|']
    for s in sorted(defs):
        d = defs[s]
        n, b = d.get('espn_n', 0), d.get('bbref_n', 0)
        pct = lambda k, m: f"{d.get(k, 0)}/{m}" if m else ''
        L.append(f"| {season_label(s)} | {n} | {pct('espn_total_eq_tov_plus_team', n)} | {pct('espn_turnovers_eq_player_sum', n)} | "
                 f"{pct('espn_total_eq_player_sum', n)} | {pct('espn_oreb_plus_dreb_eq_trb', n)} | {b} | "
                 f"{pct('bbref_orb_plus_drb_eq_trb', b)} | {', '.join(f'{k}:{v}' for k, v in d['bbref_team_minus_player_tov'].items())} |")
    cands = _cands(stats)
    L += ['', '## 2. 高度一致的候選欄位（一致率 ≥ 99%；僅標示，不觸發修正）', '']
    for s in sorted(cands):
        fields = stats[s]['fields']
        listed = ', '.join('`%s` %.2f%%' % (k, 100 * fields[k]['exact_share']) for k in cands[s]) or '無'
        bt = best_tov_field(stats[s])
        tail = '；最接近 BBRef 的 ESPN 失誤欄位 `%s` %.2f%%' % (bt, 100 * fields[bt]['exact_share']) if bt else ''
        L.append(f'- {season_label(s)}：{listed}{tail}')
    L += ['', '## 3. 不一致紀錄的集中度', '',
          f'完整不一致紀錄共 {len(mm)} 筆，見 `docs/reports/box_quality/v1/source_compare_mismatches.csv`。'
          '下表依欄位分組；「佔比」= 該組不一致筆數 / 該組總筆數。', '']
    for (season, field), groups in conc.items():
        n = sum(1 for m in mm if m['season'] == season and m['field'] == field)
        dirs = Counter(('+' if m['diff'] > 0 else '−') for m in mm if m['season'] == season and m['field'] == field)
        diffs = Counter(m['diff'] for m in mm if m['season'] == season and m['field'] == field)
        L += [f"**{season_label(season)} `{field}`**：{n} 筆不一致；方向 ESPN 較大 {dirs.get('+', 0)} / 較小 {dirs.get('−', 0)}；"
              f"差值分布 {', '.join(f'{k:+d}:{v}' for k, v in sorted(diffs.items()))}", '']
        for key, rows in groups.items():
            top = ', '.join(f'{k} {a}/{b}' for k, a, b in rows[:8])
            L.append(f'- 依 {key}：{top}')
        L.append('')
    for s in sorted(stats):
        L += ['', f'## {season_label(s)} 逐欄位比對', '',
              '| 欄位 | n | ESPN 平均 | BBRef 平均 | 平均差 | 95% CI | ≤−3 | −2 | −1 | 0 | +1 | +2 | ≥+3 | 完全一致 | 系統性 |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
        for k, st in stats[s]['fields'].items():
            if not st:
                continue
            d = st['dist']
            ci = f"[{st['ci95'][0]:+.2f}, {st['ci95'][1]:+.2f}]" if st['ci95'] else ''
            L.append(f"| {k} | {st['n']} | {st['espn_mean']} | {st['bbref_mean']} | {st['mean_diff']:+.3f} | {ci} | "
                     + ' | '.join(str(d[str(i)]) for i in range(-3, 4))
                     + f" | {st['exact_share']:.1%} | {'是' if st['systematic'] else ''} |")
    return '\n'.join(L) + '\n'


def main():
    import csv
    import json
    rows = load()
    stats = analyse(rows)
    logs = {}
    for s in rows:
        p = os.path.join(AUDIT, str(s), 'fetch_log.json')
        if os.path.exists(p):
            logs[s] = json.load(open(p, encoding='utf-8'))
    cov = {s: coverage(s, rows[s], logs.get(s, {})) for s in rows}
    defs = definition_checks(rows)
    mm = mismatches(rows, stats)
    conc = {}
    for m in mm:
        conc.setdefault((m['season'], m['field']), None)
    for key in list(conc):
        sub = [m for m in mm if (m['season'], m['field']) == key]
        one = {key[0]: rows[key[0]]}
        conc[key] = {k: concentration(sub, one, k) for k in ('team_abbr', 'month', 'phase', 'home_away')}
    store.write_json(STATS, {'seasons': {str(k): v for k, v in stats.items()}, 'coverage': {str(k): v for k, v in cov.items()},
                             'definition_checks': {str(k): v for k, v in defs.items()},
                             'candidates_ge_99pct': {str(k): v for k, v in _cands(stats).items()},
                             'derived_generated': False})
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(MISMATCH_CSV, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['season', 'field', 'game_id', 'start_utc', 'month', 'phase', 'team', 'team_abbr',
                                           'home_away', 'espn', 'bbref', 'diff'])
        w.writeheader()
        w.writerows(mm)
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write(render(stats, cov, defs, mm, conc, logs))
    print(REPORT, len(mm))


if __name__ == '__main__':
    main()
