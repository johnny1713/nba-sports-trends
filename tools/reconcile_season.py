"""
唯讀數據核對（2024-25 審查用）：只讀取既有檔案，呼叫既有規則函式，不修改任何資料、規則、門檻或既有報告。
輸出 docs/reports/<季>_reconciliation.md 與 docs/reports/<季>_extreme_price_games.csv。

    PYTHONPATH=. python tools/reconcile_season.py 2025
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from collections import Counter, defaultdict

from nba_quant import store
from nba_quant.odds_flags import EXTREME_ML, EXTREME_SIDE, record_key

RAW = os.path.join('data', 'raw', 'espn')
SIDES = {'spread': ('home', 'away'), 'total': ('over', 'under'), 'ml': ('home', 'away')}


def pct(a, b, nd=2):
    return round(100.0 * a / b, nd) if b else None


def quantiles(v):
    if not v:
        return {}
    s = sorted(v)

    def q(p):
        i = (len(s) - 1) * p
        lo, hi = int(i), min(int(i) + 1, len(s) - 1)
        return round(s[lo] + (s[hi] - s[lo]) * (i - lo), 2)
    return {'n': len(s), 'mean': round(sum(s) / len(s), 2), 'p25': q(.25), 'median': q(.5), 'p75': q(.75), 'p90': q(.9),
            'max': s[-1]}


def main(season):
    d = os.path.join(RAW, str(season))
    games = {g['game_id']: g for g in store.read_jsonl_gz(os.path.join(d, 'games.jsonl.gz')) if g['status'] == 'final'}
    odds = [x for x in store.read_jsonl_gz(os.path.join(d, 'odds.jsonl.gz')) if x['provider_type'] == 'book' and x['game_id'] in games]
    flags = list(store.read_jsonl_gz(os.path.join(d, 'odds_flags.jsonl.gz')))
    q = store.read_json(os.path.join(d, 'quality.json'))
    phase = {gid: ('regular' if g['season_type'] == 2 else 'postseason') for gid, g in games.items()}
    code_sha = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    L = [f"# {q['label']} 唯讀數據核對報告", '',
         f'- 程式版本：`{code_sha}`（核對程式 `tools/reconcile_season.py`，唯讀）',
         '- 本報告不修改任何品質門檻、稽核規則、原始資料或既有報告；只重新計算並說明既有數字的定義', '']

    # ------------------------------------------------------------ 1. 統計單位與極端賠率
    rec = defaultdict(dict)       # (gid, prov, stage, market) -> {side: quote}
    for x in odds:
        rec[(x['game_id'], x['provider'], x['stage'], x['market'])][x['side']] = x
    n_records = len(odds)
    n_pairs = len(rec)
    fkind = Counter((f['stage'], f['market'], f['flag'], f['severity']) for f in flags)
    ext = [f for f in flags if f['flag'] == 'price_extreme']
    ext_keys = {record_key(f) for f in ext}
    ext_pairs = defaultdict(set)
    for f in ext:
        ext_pairs[(f['game_id'], f['provider'], f['stage'], f['market'])].add(f['side'])
    L += ['## 1. 統計單位與極端賠率（price_extreme）', '',
          '**統計單位定義**（本報告與既有報告共用）：',
          '- **報價（record）**：一家博彩公司、一個階段、一個市場、**一邊**的一筆價格。品質標記一律以報價為單位。',
          '- **雙邊報價（pair）**：同一家、同一階段、同一市場的兩邊（主／客或大／小）。',
          '- **場次（game）**：一場比賽。', '',
          f'本季莊家報價 {n_records} 筆、雙邊報價 {n_pairs} 組、完賽 {len(games)} 場。', '',
          '**222 與 52／57 的差異**：222 是 `price_extreme` 標記的**報價數**（含開盤、收盤與獨贏）；',
          '52／57 是上次回報中「開盤讓分／開盤總分**至少一邊**超出 [1.5, 2.6] 的**雙邊報價數**」（每組＝一場一市場）。', '',
          '| 階段 | 市場 | 標記報價數 | 涉及雙邊報價數 | 兩邊都被標 | 只標一邊 | 涉及場次 |', '|---|---|---|---|---|---|---|']
    rows_csv = []
    for stage in ('open', 'close'):
        for market in ('spread', 'total', 'ml'):
            ks = [k for k in ext_pairs if k[2] == stage and k[3] == market]
            nrec = sum(len(ext_pairs[k]) for k in ks)
            both = sum(1 for k in ks if len(ext_pairs[k]) == 2)
            L.append(f'| {stage} | {market} | {nrec} | {len(ks)} | {both} | {len(ks) - both} | {len({k[0] for k in ks})} |')
            for k in sorted(ks):
                g = games[k[0]]
                sd = rec[k]
                a, b = SIDES[market]
                rows_csv.append({'game_id': k[0], 'start_utc': g['start_utc'], 'phase': phase[k[0]],
                                 'away': g.get('away_abbr'), 'home': g.get('home_abbr'), 'provider': k[1], 'stage': stage,
                                 'market': market, 'flagged_sides': '/'.join(sorted(ext_pairs[k])),
                                 f'line_{a}': (sd.get(a) or {}).get('line'), f'price_{a}': (sd.get(a) or {}).get('price_decimal'),
                                 f'price_{b}': (sd.get(b) or {}).get('price_decimal')})
    total_ext_rec = len(ext_keys)
    L += [f'| **合計** | | **{total_ext_rec}** | {len(ext_pairs)} | | | {len({k[0] for k in ext_pairs})} |', '',
          f"- 分類門檻（既有規則，未修改）：獨贏賠率 [{EXTREME_ML[0]}, {EXTREME_ML[1]}]、讓分／總分賠率 [{EXTREME_SIDE[0]}, {EXTREME_SIDE[1]}] 之外 → warning",
          '- 完整場次清單：`docs/reports/' + f'{season}_extreme_price_games.csv`（每組雙邊報價一列）', '']
    out_csv = os.path.join('docs', 'reports', f'{season}_extreme_price_games.csv')
    with open(out_csv, 'w', newline='', encoding='utf-8') as fh:
        cols = sorted({k for r in rows_csv for k in r}, key=lambda c: ['game_id', 'start_utc', 'phase', 'away', 'home', 'provider',
                                                                         'stage', 'market', 'flagged_sides'].index(c) if c in
                      ['game_id', 'start_utc', 'phase', 'away', 'home', 'provider', 'stage', 'market', 'flagged_sides'] else 99)
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows_csv)

    # ------------------------------------------------------------ 2. 異常比例的分子分母
    oc = q['odds_checks']
    by_sev = defaultdict(set)
    for f in flags:
        by_sev[f['severity']].add(record_key(f))
    overlap_ew = by_sev['error'] & by_sev['warning']
    L += ['## 2. 異常盤口比例的分子與分母', '',
          f"**0.236% 的定義**：分子 = error 級標記數 {oc['error']}；分母 = 該季執行的檢核次數 {oc['n']}。",
          '**不包含極端賠率**（極端賠率是 warning 級，不計入這個比例）。',
          '⚠️ 這個比例的分子是「標記筆數」，分母是「檢核次數」（一筆報價會被多項檢核），兩者單位不同。'
          '這是既有品質門檻的定義，本報告不修改；以下另列以報價為分母的比例供參考。', '',
          '| 標記類型 | 嚴重度 | 標記筆數（報價）| 占全部報價 % | 是否進入後續模型資料 |', '|---|---|---|---|---|']
    for (stage, market, flag, sev), n in sorted(fkind.items()):
        L.append(f'| {stage}/{market}/{flag} | {sev} | {n} | {pct(n, n_records, 3)} | 否（預設排除）|')
    L += ['', '| 彙總（以不重複報價計）| 筆數 | 占全部報價 % |', '|---|---|---|',
          f"| error | {len(by_sev['error'])} | {pct(len(by_sev['error']), n_records, 3)} |",
          f"| warning（含極端賠率）| {len(by_sev['warning'])} | {pct(len(by_sev['warning']), n_records, 3)} |",
          f"| missing | {len(by_sev['missing'])} | {pct(len(by_sev['missing']), n_records, 3)} |",
          f"| error 與 warning 重疊 | {len(overlap_ew)} | {pct(len(overlap_ew), n_records, 3)} |",
          f"| 任一標記（不重複）| {len(by_sev['error'] | by_sev['warning'] | by_sev['missing'])} | "
          f"{pct(len(by_sev['error'] | by_sev['warning'] | by_sev['missing']), n_records, 3)} |", '',
          '**關係**：極端賠率（`price_extreme`）是 warning 級；方向矛盾（`spread_ml_direction_conflict`）是 error 級。'
          '兩者是不同的規則、各自獨立標記；重疊列出於上表。', '',
          '**是否全部排除於後續模型資料之外**：模型資料只能透過 `usable_quotes()` 取得，它排除所有 error、missing，'
          '以及**未經人工放行**的 warning。目前沒有任何人工放行紀錄 → **全部被標記的報價（含 222 筆極端賠率）都會被排除**。']
    # 直接驗證
    from nba_quant.odds_flags import usable_quotes
    kept = usable_quotes(odds, flags)
    kept_keys = {record_key(x) for x in kept}
    leaked = (by_sev['error'] | by_sev['warning'] | by_sev['missing']) & kept_keys
    L += [f'- 直接驗證：`usable_quotes()` 保留 {len(kept)} 筆；其中被標記的報價 **{len(leaked)} 筆**（應為 0）。', '']

    # ------------------------------------------------------------ 3. 開盤覆蓋率
    excl_gate = by_sev['error'] | by_sev['missing']
    excl_model = excl_gate | by_sev['warning']
    L += ['## 3. 開盤／收盤覆蓋率：三種定義', '',
          '某場某階段某市場「有覆蓋」＝至少一家博彩公司兩邊都有價格（且未被該定義排除）。', '',
          '- **A 原始存在率**：不排除任何標記',
          '- **B 品質門檻定義**（`quality.py` 的 95% 門檻）：排除 error 與 missing，**不排除 warning**',
          '- **C 模型可用定義**（`usable_quotes()`，`season_audit.py` 第 3 節的 95.37%）：排除 error、missing **與 warning**', '',
          '⚠️ **既有兩份報告用的是不同定義**：品質門檻（B）是全季 98.4%，稽核報告（C）的例行賽是 95.37%。'
          '門檻判定（PASS）是依 B 計算；若以 C（模型實際能用的資料）計算，數字較低。本報告不修改門檻，只揭露差異。', '',
          '| 階段/市場 | 賽段 | 分母（完賽場次）| A 分子 | A % | B 分子 | B % | C 分子 | C % |', '|---|---|---|---|---|---|---|---|---|']
    for stage in ('open', 'close'):
        for market in ('spread', 'total', 'ml'):
            for ph in ('regular', 'postseason', 'all'):
                gids = [g for g in games if ph == 'all' or phase[g] == ph]
                cnt = {}
                for name, ex in (('A', set()), ('B', excl_gate), ('C', excl_model)):
                    c = 0
                    for gid in gids:
                        ok = False
                        for (g2, prov, st, m), sd in rec.items():
                            if g2 != gid or st != stage or m != market:
                                continue
                            if all(s in sd and sd[s]['price_decimal'] and record_key(sd[s]) not in ex for s in SIDES[market]):
                                ok = True
                                break
                        c += ok
                    cnt[name] = c
                lab = {'regular': '例行賽', 'postseason': '季後賽', 'all': '全季'}[ph]
                L.append(f"| {stage}/{market} | {lab} | {len(gids)} | {cnt['A']} | {pct(cnt['A'], len(gids))} | "
                         f"{cnt['B']} | {pct(cnt['B'], len(gids))} | {cnt['C']} | {pct(cnt['C'], len(gids))} |")
    # 20 組方向矛盾
    conf = defaultdict(set)
    for f in flags:
        if f['flag'] == 'spread_ml_direction_conflict':
            conf[(f['game_id'], f['provider'], f['stage'])].add(f['market'])
    conf_games = {k[0] for k in conf}
    conf_and_ext = {k[0] for k in conf if (k[0], k[1], k[2], 'spread') in ext_pairs or (k[0], k[1], k[2], 'ml') in ext_pairs}
    L += ['', f'**方向矛盾**：{len(conf)} 組（同一家、同一階段），全部在開盤，涉及 {len(conf_games)} 場；'
          f'每組讓分兩邊＋獨贏兩邊共 4 筆 error 報價（共 {4 * len(conf)} 筆）。',
          '它們是 error 級，**B 與 C 兩種覆蓋率都已排除**；其中 '
          f'{len(conf_and_ext)} 場同時也有極端賠率標記。', '']

    # ------------------------------------------------------------ 4. 開收盤線位變動
    L += ['## 4. 開盤→收盤線位變動（只做客觀統計，不判定對錯）', '',
          '以同一家（本季只有 ESPN BET）同一市場：讓分取主隊線、總分取總分線，|收盤 − 開盤|（分）。',
          '「極端賠率場次」＝該市場開盤雙邊報價至少一邊被標 `price_extreme`。', '',
          '| 市場 | 組別 | 場次 | 平均 | P25 | 中位數 | P75 | P90 | 最大 |', '|---|---|---|---|---|---|---|---|---|']
    for market, side in (('spread', 'home'), ('total', 'over')):
        grp = {'極端賠率場次': [], '一般場次': []}
        for (gid, prov, st, m), sd in rec.items():
            if st != 'open' or m != market or side not in sd:
                continue
            c = rec.get((gid, prov, 'close', market), {}).get(side)
            if not c or sd[side]['line'] is None or c['line'] is None:
                continue
            key = '極端賠率場次' if (gid, prov, 'open', market) in ext_pairs else '一般場次'
            grp[key].append(abs(c['line'] - sd[side]['line']))
        for k, v in grp.items():
            s = quantiles(v)
            L.append(f"| {market} | {k} | {s.get('n', 0)} | {s.get('mean')} | {s.get('p25')} | {s.get('median')} | "
                     f"{s.get('p75')} | {s.get('p90')} | {s.get('max')} |")
    L += ['', '- 大幅變動本身**不等於**資料錯誤（傷兵消息、先發異動都可能造成大幅移動）；本表不據此判定任何紀錄。', '']

    # ------------------------------------------------------------ 5. 單一來源限制
    L += ['## 5. 內部一致性驗證 vs 外部市場交叉驗證', '',
          '| | 內部一致性驗證 | 外部市場交叉驗證 |', '|---|---|---|',
          '| 定義 | 只用同一家自己的報價，檢查是否自相矛盾或超出合理範圍 | 與同場同階段其他博彩公司比對 |',
          '| 本季是否執行 | **是**（全部 1315 場）| **否**（只有 ESPN BET 一家，0 場可執行）|',
          '| 能抓到 | 欄位填錯、兩邊不相反、範圍外、無效／極端賠率、抽水異常、同家讓分與獨贏方向矛盾 | 盤口偏離市場、疑似滾球盤混入、矛盾歸因 |',
          '| 抓不到 | 價格看起來正常但數字錯誤、整家一起偏移、滾球盤或過期盤混入但價格正常 | — |', '',
          '- **沒有被標記 ≠ 沒有異常**。本季未被標記的報價只代表「通過內部一致性檢查」，**未經任何外部市場交叉驗證**。',
          '- 覆蓋率達標只代表價格存在，不代表通過多家來源驗證。', '']
    out = os.path.join('docs', 'reports', f'{season}_reconciliation.md')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print(out, out_csv, len(rows_csv))


if __name__ == '__main__':
    main(int(sys.argv[1]))
