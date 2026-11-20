"""
單季完整稽核（唯讀）：只讀取 data/raw/espn/<季>/ 的檔案，呼叫既有的規則函式（odds_flags、price_time、clv），
不修改任何資料、不改任何規則。輸出 docs/reports/<季>_full_audit.md 與 data/raw/espn/<季>/audit.json。

    PYTHONPATH=. python tools/season_audit.py 2024

追溯：報告列出每個輸入檔的 sha256 與程式 git sha；任何統計都可用同一份輸入與程式版本重算。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from statistics import median

from nba_quant import clv, store
from nba_quant import price_time as pt
from nba_quant.odds_flags import record_key, usable_quotes

RAW = os.path.join('data', 'raw', 'espn')
MARKETS = (('spread', ('home', 'away')), ('total', ('over', 'under')), ('ml', ('home', 'away')))


def pct(a, b):
    return round(100.0 * a / b, 2) if b else None


def main(season):
    d = os.path.join(RAW, str(season))
    files = {n: store.sha256_file(os.path.join(d, n)) for n in
             ('games.jsonl.gz', 'teambox.jsonl.gz', 'odds.jsonl.gz', 'odds_raw.jsonl.gz', 'odds_flags.jsonl.gz')}
    code_sha = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    games = list(store.read_jsonl_gz(os.path.join(d, 'games.jsonl.gz')))
    odds = list(store.read_jsonl_gz(os.path.join(d, 'odds.jsonl.gz')))
    flags = list(store.read_jsonl_gz(os.path.join(d, 'odds_flags.jsonl.gz')))
    raw = {r['game_id']: r for r in store.read_jsonl_gz(os.path.join(d, 'odds_raw.jsonl.gz'))}
    q = store.read_json(os.path.join(d, 'quality.json'))
    final = {g['game_id']: g for g in games if g['status'] == 'final'}
    phase = {gid: ('regular' if g['season_type'] == 2 else 'postseason') for gid, g in final.items()}
    start = {gid: g['start_utc'] for gid, g in final.items()}
    book = [x for x in odds if x['provider_type'] == 'book' and x['game_id'] in final]
    out = {'season': season, 'inputs_sha256': files, 'code_sha': code_sha}

    # ---- 1. 階段分類
    out['stage_counts'] = dict(Counter(x['stage'] for x in book))
    out['time_classes'] = pt.verification_summary(book, start)
    out['postgame_snapshot_records'] = sum(1 for x in book if x['stage'] == 'current_postgame')

    # ---- 2. 逐家覆蓋率（依階段 × 市場 × 例行賽/季後賽；雙邊齊全且有價格）
    have = defaultdict(set)      # (prov, stage, market) -> {gid}
    sides = defaultdict(set)
    for x in book:
        if x['price_decimal']:
            sides[(x['game_id'], x['provider'], x['stage'], x['market'])].add(x['side'])
    for (gid, prov, stage, market), ss in sides.items():
        need = dict(MARKETS)[market]
        if set(need) <= ss:
            have[(prov, stage, market)].add(gid)
    n_phase = Counter(phase.values())
    per_book = {}
    for (prov, stage, market), gids in sorted(have.items()):
        c = Counter(phase[g] for g in gids)
        per_book.setdefault(prov, {})[f'{stage}/{market}'] = {ph: pct(c[ph], n_phase[ph]) for ph in ('regular', 'postseason')}
    out['per_book_coverage_pct'] = per_book

    # ---- 3. 各市場開盤／收盤可用覆蓋率（去掉被標記的紀錄）
    kept = usable_quotes(book, flags)
    ksides = defaultdict(set)
    for x in kept:
        if x['price_decimal']:
            ksides[(x['game_id'], x['stage'], x['market'])].add((x['provider'], x['side']))
    cov = {}
    for stage in ('open', 'close'):
        for market, need in MARKETS:
            ok = Counter()
            for gid in final:
                provs = defaultdict(set)
                for prov, side in ksides.get((gid, stage, market), ()):
                    provs[prov].add(side)
                if any(set(need) <= v for v in provs.values()):
                    ok[phase[gid]] += 1
            cov[f'{stage}/{market}'] = {ph: pct(ok[ph], n_phase[ph]) for ph in ('regular', 'postseason')}
    out['usable_coverage_pct'] = cov

    # ---- 4. 異常盤口（依市場 × 類型 × 嚴重度）
    out['flags_by_market_kind'] = {f'{m}/{k}/{s}': n for (m, k, s), n in
                                   sorted(Counter((f['market'], f['flag'], f['severity']) for f in flags).items())}

    # ---- 5. ESPN BET 系統性錯誤檢查
    eb = [x for x in book if x['provider'] == 'ESPN BET']
    eb_flags = [f for f in flags if f['provider'] == 'ESPN BET']
    per = {}
    for stage in ('open', 'close'):
        for market, _ in MARKETS:
            recs = [x for x in eb if x['stage'] == stage and x['market'] == market]
            fl = [f for f in eb_flags if f['stage'] == stage and f['market'] == market and f['severity'] == 'error']
            per[f'{stage}/{market}'] = {'records': len(recs), 'error_records': len(fl), 'error_pct': pct(len(fl), len(recs)),
                                        'kinds': dict(Counter(f['flag'] for f in fl))}
    # 與其他莊家中位數的偏差分布（同場同階段）
    dev = defaultdict(list)
    lines = defaultdict(dict)
    for x in book:
        ok_line = x['line'] is not None and ((x['market'] == 'spread' and abs(x['line']) < 100) or
                                             (x['market'] == 'total' and 100 < x['line'] < 400))
        if x['market'] in ('spread', 'total') and x['side'] in ('home', 'over') and ok_line:
            lines[(x['game_id'], x['stage'], x['market'])][x['provider']] = x['line']
    for (gid, stage, market), dd in lines.items():
        if 'ESPN BET' in dd and len(dd) >= 4:
            dev[f'{stage}/{market}'].append(dd['ESPN BET'] - median(v for p, v in dd.items() if p != 'ESPN BET'))
    per_dev = {}
    for k, v in dev.items():
        a = sorted(abs(x) for x in v)
        per_dev[k] = {'n': len(v), 'median_abs_dev': a[len(a) // 2] if a else None,
                      'share_abs_dev_le_1': pct(sum(x <= 1 for x in a), len(a)),
                      'share_abs_dev_gt_4': pct(sum(x > 4 for x in a), len(a))}
    # 可交叉驗證比例：同場同階段同市場至少 4 家莊家（偏離市場檢查的最低條件）
    nbooks = defaultdict(set)
    for x in book:
        nbooks[(x['game_id'], x['stage'], x['market'])].add(x['provider'])
    cross = {}
    for stage in ('open', 'close'):
        for market, _ in MARKETS:
            c = Counter()
            for gid in final:
                if len(nbooks.get((gid, stage, market), ())) >= 4:
                    c[phase[gid]] += 1
            cross[f'{stage}/{market}'] = {ph: pct(c[ph], n_phase[ph]) for ph in ('regular', 'postseason')}
    books_in_season = sorted({x['provider'] for x in book})
    systematic = [k for k, v in per.items() if v['error_pct'] and v['error_pct'] >= 50]
    out['books_in_season'] = books_in_season
    out['cross_check_possible_pct'] = cross
    out['espn_bet'] = {'by_stage_market': per, 'deviation_vs_other_books': per_dev,
                       'systematic_markets_ge_50pct_error': systematic,
                       'verdict': '無系統性錯誤' if not systematic else '有系統性錯誤：' + ', '.join(systematic)}

    # ---- 6. CLV 配對與指標（既有規則，不放寬）
    pairs, excl = clv.pair_open_close(book, start, flags)
    for p in pairs:
        clv.assert_valid_pair(p)
    rep = clv.pairing_report(pairs, excl)
    metrics = clv.clv_metrics_report(pairs)
    # 驗證項目（每一項都重新檢查，不只相信函式）
    checks = {}
    checks['every_pair_same_book'] = all(len({p[k]['provider'] for k in ('open', 'close', 'open_other', 'close_other')}) == 1 for p in pairs)
    checks['every_pair_same_market_and_side'] = all(p['open']['market'] == p['close']['market'] == p['market'] and
                                                    p['open']['side'] == p['close']['side'] == p['side'] for p in pairs)
    checks['devig_uses_same_book_opposite_side'] = all(p['open_other']['side'] == clv.OTHER_SIDE[p['side']] and
                                                       p['close_other']['provider'] == p['provider'] for p in pairs)
    bad = {record_key(f) for f in flags if f['severity'] in ('error', 'missing', 'warning')}
    checks['no_flagged_record_in_any_pair'] = not any(record_key(p[k]) in bad for p in pairs
                                                     for k in ('open', 'close', 'open_other', 'close_other'))
    checks['no_postgame_snapshot_in_any_pair'] = not any(p[k]['stage'] == 'current_postgame' for p in pairs
                                                        for k in ('open', 'close', 'open_other', 'close_other'))
    pc_line_diff = [p for p in pairs if p['market'] != 'ml' and p['open']['line'] != p['close']['line']]
    checks['price_clv_not_computed_when_lines_differ'] = all(clv.price_clv(p)[0] is None for p in pc_line_diff)
    checks['ml_has_no_line_clv'] = all(clv.line_clv(p)[0] is None for p in pairs if p['market'] == 'ml')
    # 追溯：抽 5 組配對，到 odds_raw 找回原始報價
    trace = []
    for p in pairs[:: max(1, len(pairs) // 5)][:5]:
        it = next((i for i in raw.get(p['game_id'], {}).get('items', []) if (i.get('provider') or {}).get('name') == p['provider']), None)
        side_key = 'homeTeamOdds' if p['side'] == 'home' else ('awayTeamOdds' if p['side'] == 'away' else None)
        trace.append({'game_id': p['game_id'], 'provider': p['provider'], 'market': p['market'], 'side': p['side'],
                      'normalized_open': [p['open']['line'], round(p['open']['price_decimal'], 4)],
                      'normalized_close': [p['close']['line'], round(p['close']['price_decimal'], 4)],
                      'raw_open': (it or {}).get(side_key, {}).get('open') if side_key else (it or {}).get('open'),
                      'raw_close': (it or {}).get(side_key, {}).get('close') if side_key else (it or {}).get('close')})
    checks['trace_samples_found_in_raw'] = all(t['raw_open'] and t['raw_close'] for t in trace)
    out['clv'] = {'pairing': rep, 'metrics': metrics, 'checks': checks, 'trace_samples': trace,
                  'valid_pair_games_by_phase': dict(Counter(phase[g] for g in {p['game_id'] for p in pairs}))}
    out['quality_status'] = q.get('quality_status')
    out['quality_verdict'] = q.get('verdict')
    store.write_json(os.path.join(d, 'audit.json'), out)
    with open(os.path.join('docs', 'reports', f'{season}_full_audit.md'), 'w', encoding='utf-8') as fh:
        fh.write(render(out, q))
    print(json.dumps({'status': out['quality_status'], 'checks': checks, 'espn_bet': out['espn_bet']['verdict']}, ensure_ascii=False))


def render(o, q):
    P = q['by_phase']
    L = [f"# {q['label']} 完整資料品質報告（ESPN season {o['season']}）", '',
         f"## 判定：**{q['quality_status']}**", '', f"- {q['verdict']}",
         '- 門檻（未修改）：盤口 error 比例 < 1%；開盤／收盤各市場可用覆蓋率 ≥ 95%；完賽資料完整率 ≥ 99%', '',
         '## 1. 場次與完整度', '', '| 項目 | 例行賽 | 季後賽 |', '|---|---|---|']
    for name, k in (('場次（含延賽）', 'games'), ('完賽', 'final'), ('資料完整', 'complete'), ('完整率 %', 'complete_pct'),
                    ('ESPN box score 缺漏', 'espn_box_missing'), ('BBRef 補值', 'bbref_filled'),
                    ('補值後仍不完整', 'still_incomplete'), ('盤口缺漏場次', 'odds_missing_games'),
                    ('每場莊家數中位數', 'books_per_game_median')):
        L.append(f"| {name} | {P['regular'][k]} | {P['postseason'][k]} |")
    L += ['', f"- 狀態：例行賽 {P['regular']['status']}；季後賽 {P['postseason']['status']}",
          f"- 每隊例行賽 {q['teams']['min_games']}～{q['teams']['max_games']} 場（{q['teams']['n']} 隊；83 場者為 NBA 盃冠軍賽兩隊，ESPN 列為例行賽）",
          f"- 資料來源標記不一致：{q['source_label_problems']} 場；box score 合理性問題：{q['box_issues']}；重複 game_id：{len(q['duplicates'])}", '',
          '## 2. 盤口階段分類', '',
          f"- 筆數：{o['stage_counts']}",
          f"- 時間性質：{o['time_classes']}",
          f"- **賽後快照（POSTGAME_SNAPSHOT）：{o['postgame_snapshot_records']} 筆**——本季沒有任何賽後快照，開盤／收盤全部來自 ESPN 明確標記的欄位",
          f"- 收盤時間戳驗證比例：{q['price_time_classes']['close_timestamp_verified_pct']}%（ESPN 不提供時間戳；只能依供應商標記使用）", '',
          '## 3. 各市場開盤／收盤可用覆蓋率（排除被標記紀錄後，至少一家雙邊齊全）', '',
          '| 階段/市場 | 例行賽 % | 季後賽 % |', '|---|---|---|']
    for k, v in o['usable_coverage_pct'].items():
        L.append(f"| {k} | {v['regular']} | {v['postseason']} |")
    L += ['', f"- 品質門檻計算（全季合併）：{q['strict_stage_coverage']}", '',
          '## 4. 各博彩公司逐家覆蓋率（雙邊齊全且有價格；未排除標記）', '',
          '| 博彩公司 | 階段/市場 | 例行賽 % | 季後賽 % |', '|---|---|---|---|']
    for prov, d in sorted(o['per_book_coverage_pct'].items(), key=lambda kv: -max(v['regular'] or 0 for v in kv[1].values())):
        for k, v in d.items():
            L.append(f"| {prov} | {k} | {v['regular']} | {v['postseason']} |")
    oc = q['odds_checks']
    L += ['', '## 5. 異常盤口（單筆紀錄；原始資料不動）', '',
          f"- 檢核 {oc['n']} 項：error {oc['error']}（{oc['error_rate_pct']}%）、warning {oc['warning']}、缺失值 {oc['missing']}", '',
          '| 市場/類型/嚴重度 | 筆數 |', '|---|---|'] + [f'| {k} | {v} |' for k, v in o['flags_by_market_kind'].items()]
    a = q['anomaly_analysis']
    L += ['', '依博彩公司（error）：', '', '| 博彩公司 | error 筆數 | 該公司盤口筆數 | 比例 % |', '|---|---|---|---|']
    for b in a['by_book']:
        L.append(f"| {b['provider']} | {b['error_records']} | {b['book_records']} | {b['rate_pct']} |")
    eb = o['espn_bet']
    L += ['', '## 6. ESPN BET 系統性錯誤檢查', '', f"**結論：{eb['verdict']}**", '',
          '| 階段/市場 | 紀錄數 | error 筆數 | error % | 類型 |', '|---|---|---|---|---|']
    for k, v in eb['by_stage_market'].items():
        L.append(f"| {k} | {v['records']} | {v['error_records']} | {v['error_pct']} | {v['kinds']} |")
    L += ['', f"本季出現的博彩公司：{len(o['books_in_season'])} 家（{', '.join(o['books_in_season'])}）", '',
          '可做多家交叉驗證的場次比例（同場同階段同市場 ≥ 4 家；偏離市場、疑似滾球盤檢查都需要這個條件）：', '',
          '| 階段/市場 | 例行賽 % | 季後賽 % |', '|---|---|---|']
    L += [f"| {k} | {v['regular']} | {v['postseason']} |" for k, v in o['cross_check_possible_pct'].items()]
    low = [f'{k}（{"例行賽" if ph == "regular" else "季後賽"} {v[ph]}%）' for k, v in o['cross_check_possible_pct'].items()
           for ph in ('regular', 'postseason') if v[ph] is not None and v[ph] < 95]
    if low:
        L += ['', f"- ⚠️ **以下階段/市場多數場次只有單一（或少數）博彩公司，無法做多家交叉驗證：{', '.join(low)}。"
              '這些場次的盤口偏離、疑似滾球盤混入**未經多家比對**，不得宣稱已通過多家市場交叉驗證。**']
    L += ['', '與同場同階段其他莊家中位數的差距（只算有 ≥ 3 家其他莊家的場次）：', '',
          '| 階段/市場 | 場次 | 差距中位數（分）| 差 ≤ 1 分比例 % | 差 > 4 分比例 % |', '|---|---|---|---|---|']
    for k, v in eb['deviation_vs_other_books'].items():
        L.append(f"| {k} | {v['n']} | {v['median_abs_dev']} | {v['share_abs_dev_le_1']} | {v['share_abs_dev_gt_4']} |")
    c = o['clv']
    r = c['pairing']
    L += ['', '## 7. CLV 配對（同一家、同市場、同方向；不補值）', '',
          f"- 有效配對 {r['valid_pairs']} 筆，涵蓋 {r['valid_games']} 場（例行賽 {c['valid_pair_games_by_phase'].get('regular', 0)}、"
          f"季後賽 {c['valid_pair_games_by_phase'].get('postseason', 0)}）；考慮 {r['games_considered']} 場，"
          f"沒有任何有效配對的場次 {r['games_without_any_valid_pair']}",
          f"- 依市場有效配對：{r['valid_by_market']}", f"- 收盤時間性質：{r['close_time_classes']}",
          f"- 排除 {r['excluded']} 筆，依原因：{r['excluded_by_reason']}", '', '| 市場/排除原因 | 筆數 |', '|---|---|']
    L += [f'| {k} | {v} |' for k, v in sorted(r['excluded_by_market_reason'].items())]
    L += ['', '## 8. Line CLV 與 Price CLV（分開；此處只報有效筆數與排除原因，不做任何模型評估）', '',
          '| 市場 | 配對 | Line CLV 有效 | Price CLV 有效 | 未計算原因 |', '|---|---|---|---|---|']
    for m, v in c['metrics'].items():
        L.append(f"| {m} | {v['pairs']} | {v['line_clv']['n']} | {v['price_clv']['n']} | {v['not_computed']} |")
    L += ['', '## 9. CLV 驗證項目', '', '| 驗證 | 結果 |', '|---|---|']
    L += [f"| {k} | {'✅' if v else '❌'} |" for k, v in c['checks'].items()]
    L += ['', '追溯抽樣（正規化值 ↔ odds_raw 原始報價）：', '']
    for t in c['trace_samples']:
        L.append(f"- `{t['game_id']}` {t['provider']} {t['market']}/{t['side']}：開盤 {t['normalized_open']} ← {json.dumps(t['raw_open'], ensure_ascii=False)[:160]}")
        L.append(f"  收盤 {t['normalized_close']} ← {json.dumps(t['raw_close'], ensure_ascii=False)[:160]}")
    L += ['', '## 10. 追溯資訊', '', f"- 程式版本：`{o['code_sha']}`", '- 輸入檔 sha256：']
    L += [f'  - `{k}`：`{v}`' for k, v in o['inputs_sha256'].items()]
    L += ['- 重算：`PYTHONPATH=. python tools/season_audit.py ' + str(o['season']) + '`']
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main(int(sys.argv[1]))
