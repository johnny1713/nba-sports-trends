"""
每季資料品質報告（Phase 3）：完整度、盤口覆蓋率、錯誤率。
輸出 data/raw/espn/<季>/quality.json 與 docs/reports/data_quality/<季>.md。

判定（verdict_ok）：
- 例行賽場數與預期相符（允許 NBA 盃冠軍賽 +1）、每隊例行賽場數合理
- 完賽比賽的 complete 比例 ≥ 99%
- 盤口檢核錯誤率 < 1%
不通過就停下來，人工看報告，不繼續下一季。
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from statistics import median

from . import store

RAW = os.path.join('data', 'raw', 'espn')
REPORT_DIR = os.path.join('docs', 'reports', 'data_quality')

# 例行賽預期場數：2019-20 停賽後含泡泡種子賽共 1059 場；2020-21 縮短為 72 場 → 1080
EXPECTED_REG = {2020: 1059, 2021: 1080}
EXPECTED_DEFAULT = 1230
# 每隊例行賽場數下限：2019-20 未進泡泡的 8 隊只打 63~67 場
MIN_TEAM_GAMES = {2020: 63, 2021: 72}


def _load(season, name):
    p = os.path.join(RAW, str(season), name)
    return list(store.read_jsonl_gz(p)) if os.path.exists(p) else []


def _pct(a, b):
    return round(100.0 * a / b, 2) if b else None


def season_report(season: int, live: bool = None) -> dict:
    from .config import LIVE_SEASON
    live = (season == LIVE_SEASON) if live is None else live
    games = _load(season, 'games.jsonl.gz')
    boxes = _load(season, 'teambox.jsonl.gz')
    odds = _load(season, 'odds.jsonl.gz')
    flog = store.read_json(os.path.join(RAW, str(season), 'fetch_log.json'), {}) or {}

    reg = [g for g in games if g['season_type'] == 2]
    post = [g for g in games if g['season_type'] == 3]
    final = [g for g in games if g['status'] == 'final']
    complete = [g for g in final if g.get('complete')]
    ids = [g['game_id'] for g in games]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    status = Counter(g['status'] for g in games)
    incomplete = [(g['game_id'], g.get('complete_reason')) for g in final if not g.get('complete')]

    per_team = Counter()
    for g in reg:
        if g['status'] == 'final':
            per_team[g['home']] += 1
            per_team[g['away']] += 1
    expected = EXPECTED_REG.get(season, EXPECTED_DEFAULT)
    reg_final = sum(1 for g in reg if g['status'] == 'final')

    # ---- box score
    box_by_game = defaultdict(list)
    for b in boxes:
        box_by_game[b['game_id']].append(b)
    box_issues = []
    for g in complete:
        bs = box_by_game.get(g['game_id'], [])
        if len(bs) != 2:
            box_issues.append((g['game_id'], f'{len(bs)} boxes'))
            continue
        for b in bs:
            mins = sum((p.get('minutes') or 0) for p in b.get('players', []))
            want = 240 + 25 * b['overtimes']
            if mins and abs(mins - want) > 6:            # 球員分鐘加總應接近 240（含延長）
                box_issues.append((g['game_id'], f'team {b["team"]} minutes {mins} vs {want}'))
            if not b.get('players'):
                box_issues.append((g['game_id'], f'team {b["team"]} no players'))

    # ---- odds
    final_ids = {g['game_id'] for g in final}
    by_game = defaultdict(list)
    for q in odds:
        by_game[q['game_id']].append(q)
    stage_cov = {}
    for stage in ('open', 'close', 'current_postgame'):
        for market, sides in (('spread', ('home', 'away')), ('total', ('over', 'under')), ('ml', ('home', 'away'))):
            line_ok = price_ok = 0
            for gid in final_ids:
                qs = [q for q in by_game.get(gid, []) if q['provider_type'] == 'book' and q['stage'] == stage and q['market'] == market]
                provs = defaultdict(dict)
                for q in qs:
                    provs[q['provider']][q['side']] = q
                if any(all(s in p for s in sides) for p in provs.values()):
                    line_ok += 1
                if any(all(s in p and p[s]['price_decimal'] for s in sides) for p in provs.values()):
                    price_ok += 1
            stage_cov[f'{stage}/{market}'] = {'line_pct': _pct(line_ok, len(final_ids)), 'price_pct': _pct(price_ok, len(final_ids))}
    books_per_game = [len({q['provider'] for q in by_game.get(gid, []) if q['provider_type'] == 'book'}) for gid in final_ids]
    book_counts = Counter(q['provider'] for q in odds if q['provider_type'] == 'book' and q['side'] in ('home', 'over') and q['market'] == 'spread')
    any_book = sum(1 for n in books_per_game if n > 0)

    # 檢核（每一項都是一次 check；失敗計入錯誤率）
    checks = fails = 0
    fail_examples = defaultdict(list)

    def check(ok, kind, ex):
        nonlocal checks, fails
        checks += 1
        if not ok:
            fails += 1
            if len(fail_examples[kind]) < 8:
                fail_examples[kind].append(ex)

    for gid in final_ids:
        grp = defaultdict(dict)
        for q in by_game.get(gid, []):
            if q['provider_type'] != 'book':
                continue
            grp[(q['provider'], q['stage'], q['market'])][q['side']] = q
        for (prov, stage, market), sd in grp.items():
            tag = f'{gid}/{prov}/{stage}/{market}'
            if market == 'spread' and 'home' in sd and 'away' in sd:
                check(abs(sd['home']['line'] + sd['away']['line']) < 1e-9, 'spread_not_opposite', tag)
                check(abs(sd['home']['line']) <= 25, 'spread_out_of_range', f'{tag} {sd["home"]["line"]}')
            if market == 'total' and 'over' in sd:
                check(170 <= sd['over']['line'] <= 280, 'total_out_of_range', f'{tag} {sd["over"]["line"]}')
            pair = [sd[s]['price_decimal'] for s in sd if sd[s]['price_decimal']]
            for p in pair:
                check(1.01 < p < (60 if market == 'ml' else 5), 'price_out_of_range', f'{tag} {p}')
            if len(pair) == 2:
                ov = sum(1 / p for p in pair)
                check(0.995 <= ov <= 1.15, 'overround_out_of_range', f'{tag} {ov:.3f}')
        # 獨贏熱門方向要與讓分方向一致（同一家、同一階段，讓分 ≥ 2 分才檢查）
        for (prov, stage, market), sd in grp.items():
            if market != 'spread' or 'home' not in sd:
                continue
            ml = grp.get((prov, stage, 'ml'), {})
            if 'home' in ml and 'away' in ml and abs(sd['home']['line']) >= 2:
                home_fav_spread = sd['home']['line'] < 0
                home_fav_ml = ml['home']['price_decimal'] < ml['away']['price_decimal']
                check(home_fav_spread == home_fav_ml, 'ml_spread_direction_conflict', f'{gid}/{prov}/{stage}')

    # "Opening" 提供者是否等於各家 initialSpread 的中位數（決定能否採用）
    op_agree = op_n = 0
    for gid in final_ids:
        qs = by_game.get(gid, [])
        feed = [q['line'] for q in qs if q['provider_type'] == 'opening_feed' and q['market'] == 'spread' and q['side'] == 'home' and q['stage'] == 'current_postgame']
        init = [q['line'] for q in qs if q['provider_type'] == 'book' and q['market'] == 'spread' and q['side'] == 'home' and q['stage'] == 'open']
        if feed and init:
            op_n += 1
            op_agree += abs(feed[0] - median(init)) <= 0.5

    err_rate = fails / checks if checks else 0.0
    complete_rate = len(complete) / len(final) if final else 0.0
    team_counts = sorted(per_team.values())
    reasons = []
    if not live:
        if not (expected <= reg_final <= expected + 1):
            reasons.append(f'例行賽完賽 {reg_final} 場，預期 {expected}（NBA 盃冠軍賽可 +1）')
        lo = MIN_TEAM_GAMES.get(season, 82)
        hi = 75 if season == 2020 else (72 if season == 2021 else 83)   # NBA 盃冠軍賽 ESPN 可能算進例行賽
        if team_counts and (team_counts[0] < lo or team_counts[-1] > hi or len(per_team) != 30):
            reasons.append(f'每隊場數異常：{len(per_team)} 隊，最少 {team_counts[0]}、最多 {team_counts[-1]}')
    if complete_rate < 0.99:
        reasons.append(f'完賽比賽資料完整率 {complete_rate:.1%} < 99%')
    if err_rate >= 0.01:
        reasons.append(f'盤口檢核錯誤率 {err_rate:.2%} ≥ 1%')
    if dup:
        reasons.append(f'重複 game_id {len(dup)} 個')

    rep = {
        'season': season, 'label': f'{season - 1}-{str(season)[2:]}', 'live': live,
        'games': {'total': len(games), 'regular': len(reg), 'regular_final': reg_final, 'expected_regular': expected,
                  'postseason': len(post), 'status': dict(status), 'duplicates': dup,
                  'skipped_at_listing': flog.get('skipped', {})},
        'completeness': {'final': len(final), 'complete': len(complete), 'complete_pct': _pct(len(complete), len(final)),
                         'incomplete_examples': incomplete[:20], 'box_issues': len(box_issues),
                         'box_issue_examples': box_issues[:20]},
        'teams': {'n': len(per_team), 'min_games': team_counts[0] if team_counts else None,
                  'max_games': team_counts[-1] if team_counts else None},
        'odds': {'final_games_with_any_book_pct': _pct(any_book, len(final_ids)),
                 'books_per_game_median': median(books_per_game) if books_per_game else 0,
                 'books': book_counts.most_common(), 'coverage': stage_cov,
                 'timestamps_available': False,
                 'opening_feed_agreement': {'n': op_n, 'agree_pct': _pct(op_agree, op_n)}},
        'checks': {'n': checks, 'fails': fails, 'error_rate_pct': round(100 * err_rate, 3),
                   'by_kind': {k: len(v) for k, v in fail_examples.items()}, 'examples': dict(fail_examples)},
        'fetch': {'requests': flog.get('requests'), 'http_errors': len(flog.get('http_errors', [])),
                  'parse_errors': len(flog.get('parse_errors', [])),
                  'parse_error_examples': flog.get('parse_errors', [])[:10], 'notes_total': flog.get('notes_total', 0)},
        'verdict_ok': not reasons,
        'verdict': '通過' if not reasons else '不通過：' + '；'.join(reasons),
    }
    store.write_json(os.path.join(RAW, str(season), 'quality.json'), rep)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, f'{season}.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_md(rep))
    return rep


def render_md(r):
    g, c, o, k, fe = r['games'], r['completeness'], r['odds'], r['checks'], r['fetch']
    lines = [f"# 資料品質報告：{r['label']}（ESPN season {r['season']}）", '',
             f"**判定：{r['verdict']}**", '',
             '## 場次與完整度', '',
             '| 項目 | 數值 |', '|---|---|',
             f"| 例行賽完賽 / 預期 | {g['regular_final']} / {g['expected_regular']} |",
             f"| 季後賽 | {g['postseason']} |",
             f"| 狀態 | {g['status']} |",
             f"| 列表階段略過 | {g['skipped_at_listing']} |",
             f"| 完賽且資料完整 | {c['complete']} / {c['final']}（{c['complete_pct']}%）|",
             f"| 每隊例行賽場數 | {r['teams']['n']} 隊，{r['teams']['min_games']}～{r['teams']['max_games']} 場 |",
             f"| box score 問題 | {c['box_issues']} |",
             f"| 重複 game_id | {len(g['duplicates'])} |", '']
    if c['incomplete_examples']:
        lines += ['不完整的比賽（前 20 筆）：', ''] + [f'- `{a}`：{b}' for a, b in c['incomplete_examples']] + ['']
    if c['box_issue_examples']:
        lines += ['box score 問題（前 20 筆）：', ''] + [f'- `{a}`：{b}' for a, b in c['box_issue_examples']] + ['']
    lines += ['## 盤口覆蓋率（只計莊家，不含 consensus 等預測來源）', '',
              f"- 至少一家莊家有盤口的完賽比賽：{o['final_games_with_any_book_pct']}%",
              f"- 每場莊家數中位數：{o['books_per_game_median']}",
              f"- 莊家（場次）：{', '.join(f'{a} {b}' for a, b in o['books'][:12])}",
              '- **開盤／收盤時間戳：ESPN 未提供**（欄位保留為空，不推測）',
              f"- \"Opening\" 提供者與各家開盤線中位數一致（±0.5）：{o['opening_feed_agreement']['agree_pct']}%（n={o['opening_feed_agreement']['n']}）", '',
              '| 階段/市場 | 有盤口 % | 有雙邊賠率 % |', '|---|---|---|']
    for key, v in o['coverage'].items():
        lines.append(f"| {key} | {v['line_pct']} | {v['price_pct']} |")
    lines += ['', '## 檢核與錯誤率', '',
              f"- 檢核 {k['n']} 項，失敗 {k['fails']} 項，**錯誤率 {k['error_rate_pct']}%**",
              f"- 依類別：{k['by_kind'] or '無'}", '']
    for kind, exs in k['examples'].items():
        lines += [f'- {kind} 例：' + '、'.join(f'`{e}`' for e in exs[:5])]
    lines += ['', '## 抓取', '',
              f"- 請求 {fe['requests']} 次，HTTP 失敗 {fe['http_errors']}，解析失敗 {fe['parse_errors']}，解析備註 {fe['notes_total']}"]
    for e in fe['parse_error_examples']:
        lines.append(f"  - `{e.get('game_id')}` {e.get('stage')}: {e.get('error')}")
    return '\n'.join(lines) + '\n'
