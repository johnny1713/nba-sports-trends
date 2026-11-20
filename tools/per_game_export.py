"""
逐場稽核匯出（唯讀）：只讀取 data/raw/espn/<季>/ 既有檔案，呼叫既有規則函式（odds_flags、clv），
不修改任何資料或規則。輸出 docs/reports/<季>_per_game_audit.csv，每場完賽比賽一列。

    PYTHONPATH=. python tools/per_game_export.py 2025
"""
from __future__ import annotations

import csv
import os
import sys
from collections import Counter, defaultdict

from nba_quant import clv, store
from nba_quant.odds_flags import usable_quotes

RAW = os.path.join('data', 'raw', 'espn')
MARKETS = (('spread', ('home', 'away')), ('total', ('over', 'under')), ('ml', ('home', 'away')))


def tier(n):
    return '0' if n == 0 else ('1' if n == 1 else ('2-3' if n <= 3 else '4+'))


def main(season):
    d = os.path.join(RAW, str(season))
    games = [g for g in store.read_jsonl_gz(os.path.join(d, 'games.jsonl.gz')) if g['status'] == 'final']
    odds = [x for x in store.read_jsonl_gz(os.path.join(d, 'odds.jsonl.gz')) if x['provider_type'] == 'book']
    flags = list(store.read_jsonl_gz(os.path.join(d, 'odds_flags.jsonl.gz')))
    start = {g['game_id']: g['start_utc'] for g in games}
    by_g = defaultdict(list)
    for x in odds:
        by_g[x['game_id']].append(x)
    fl_g = defaultdict(list)
    for f in flags:
        fl_g[f['game_id']].append(f)
    kept = defaultdict(list)
    for x in usable_quotes(odds, flags):
        kept[x['game_id']].append(x)
    pairs, excl = clv.pair_open_close(odds, start, flags)
    pg, eg = Counter(p['game_id'] for p in pairs), defaultdict(Counter)
    for e in excl:
        eg[e['game_id']][e['reason']] += 1
    rows = []
    for g in sorted(games, key=lambda g: (g['start_utc'], g['game_id'])):
        gid = g['game_id']
        r = {'game_id': gid, 'start_utc': g['start_utc'], 'phase': 'regular' if g['season_type'] == 2 else 'postseason',
             'away': g.get('away_abbr'), 'home': g.get('home_abbr'), 'away_pts': g['away_pts'], 'home_pts': g['home_pts'],
             'complete': g.get('complete'), 'box_source': g.get('box_source')}
        for stage in ('open', 'close'):
            for m, sides in MARKETS:
                books = {x['provider'] for x in by_g[gid] if x['stage'] == stage and x['market'] == m}
                usable = defaultdict(set)
                for x in kept[gid]:
                    if x['stage'] == stage and x['market'] == m and x['price_decimal']:
                        usable[x['provider']].add(x['side'])
                k = f'{stage}_{m}'
                r[f'{k}_books'] = len(books)
                r[f'{k}_book_tier'] = tier(len(books))
                r[f'{k}_cross_checkable'] = len(books) >= 4
                r[f'{k}_usable'] = any(set(sides) <= v for v in usable.values())
        sev = Counter(f['severity'] for f in fl_g[gid])
        r['flag_error'] = sev.get('error', 0)
        r['flag_warning'] = sev.get('warning', 0)
        r['flag_missing'] = sev.get('missing', 0)
        r['flag_kinds'] = ';'.join(f'{k}:{v}' for k, v in sorted(Counter(f['flag'] for f in fl_g[gid]).items()))
        r['clv_valid_pairs'] = pg.get(gid, 0)
        r['clv_excluded'] = ';'.join(f'{k}:{v}' for k, v in sorted(eg[gid].items()))
        r['checks_not_run'] = '' if all(r[f'{s}_{m}_cross_checkable'] for s in ('open', 'close') for m, _ in MARKETS) else \
            'line_deviates_from_market;suspected_live_line;conflict_attribution'
        rows.append(r)
    out = os.path.join('docs', 'reports', f'{season}_per_game_audit.csv')
    with open(out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(out, len(rows))


if __name__ == '__main__':
    main(int(sys.argv[1]))
