"""
每季資料品質報告（Phase 3）。輸出：
  data/raw/espn/<季>/quality.json
  data/raw/espn/<季>/odds_flags.jsonl.gz   盤口品質標記（原始 odds.jsonl.gz 不動）
  docs/reports/data_quality/<季>.md

統計（例行賽與季後賽分開）：場次、完整率、ESPN 原始缺漏數、Basketball-Reference 補值數、
盤口缺漏數、異常賠率數、異常讓分數、各博彩公司覆蓋率。

判定（verdict_ok）：
- 例行賽完賽場數與預期相符（允許 NBA 盃冠軍賽 +1）、每隊場數合理
- 完賽比賽的完整率 ≥ 99%
- 盤口 error 級標記佔檢核數 < 1%
不通過就停下來人工看報告，下一季由 backfill.require_previous_ok() 擋住。
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from statistics import median

from . import store
from .odds_flags import flag_quotes

RAW = os.path.join('data', 'raw', 'espn')
REPORT_DIR = os.path.join('docs', 'reports', 'data_quality')
PHASES = {2: 'regular', 3: 'postseason'}

# 例行賽預期場數：2019-20 停賽後含泡泡種子賽共 1059 場；2020-21 縮短為 72 場 → 1080
EXPECTED_REG = {2020: 1059, 2021: 1080}
EXPECTED_DEFAULT = 1230
# 每隊例行賽場數範圍：2019-20 未進泡泡的 8 隊只打 63~67 場；NBA 盃冠軍賽 ESPN 可能算進例行賽（+1）
TEAM_GAMES = {2020: (63, 75), 2021: (72, 72)}
TEAM_GAMES_DEFAULT = (82, 83)


def _load(season, name):
    p = os.path.join(RAW, str(season), name)
    return list(store.read_jsonl_gz(p)) if os.path.exists(p) else []


def _pct(a, b):
    return round(100.0 * a / b, 2) if b else None


def phase_of(g):
    return PHASES[g['season_type']]


def _phase_block(games, odds_by_game, flags):
    final = [g for g in games if g['status'] == 'final']
    complete = [g for g in final if g.get('complete')]
    src = Counter(g.get('box_source', 'espn') for g in complete)
    espn_missing = sum(1 for g in final if g.get('box_source') == 'bbref' or not g.get('complete'))
    no_book = [g['game_id'] for g in final
               if not any(q['provider_type'] == 'book' for q in odds_by_game.get(g['game_id'], []))]
    ids = {g['game_id'] for g in final}
    fl = [f for f in flags if f['game_id'] in ids]
    sev = Counter(f['severity'] for f in fl)
    kinds = Counter(f['flag'] for f in fl)
    per_book = Counter()
    for gid in ids:
        for p in {q['provider'] for q in odds_by_game.get(gid, []) if q['provider_type'] == 'book'}:
            per_book[p] += 1
    stage_cov = {}
    for stage in ('open', 'close', 'current_postgame'):
        for market, sides in (('spread', ('home', 'away')), ('total', ('over', 'under')), ('ml', ('home', 'away'))):
            line_ok = price_ok = 0
            for gid in ids:
                provs = defaultdict(dict)
                for q in odds_by_game.get(gid, []):
                    if q['provider_type'] == 'book' and q['stage'] == stage and q['market'] == market:
                        provs[q['provider']][q['side']] = q
                if any(all(s in p for s in sides) for p in provs.values()):
                    line_ok += 1
                if any(all(s in p and p[s]['price_decimal'] for s in sides) for p in provs.values()):
                    price_ok += 1
            stage_cov[f'{stage}/{market}'] = {'line_pct': _pct(line_ok, len(ids)), 'price_pct': _pct(price_ok, len(ids))}
    books_per = [len({q['provider'] for q in odds_by_game.get(g, []) if q['provider_type'] == 'book'}) for g in ids]
    return {
        'games': len(games), 'final': len(final), 'status': dict(Counter(g['status'] for g in games)),
        'complete': len(complete), 'complete_pct': _pct(len(complete), len(final)),
        'espn_box_missing': espn_missing, 'bbref_filled': src.get('bbref', 0),
        'still_incomplete': len(final) - len(complete),
        'odds_missing_games': len(no_book), 'odds_missing_examples': no_book[:10],
        'books_per_game_median': median(books_per) if books_per else 0,
        'book_coverage_pct': {p: _pct(c, len(ids)) for p, c in per_book.most_common()},
        'flags': {'error': sev.get('error', 0), 'warning': sev.get('warning', 0), 'missing': sev.get('missing', 0), 'by_kind': dict(kinds)},
        'abnormal_price': sum(v for k, v in kinds.items() if k.startswith('price_') or k == 'overround_out_of_range'),
        'abnormal_spread': sum(v for k, v in kinds.items() if k.startswith('spread_')),
        'abnormal_total': sum(v for k, v in kinds.items() if k.startswith('total_') and k != 'total_placeholder_missing'),
        'placeholder_missing': kinds.get('total_placeholder_missing', 0),
        'coverage': stage_cov,
    }


def season_report(season: int, live: bool = None) -> dict:
    from .config import LIVE_SEASON
    live = (season == LIVE_SEASON) if live is None else live
    games = _load(season, 'games.jsonl.gz')
    boxes = _load(season, 'teambox.jsonl.gz')
    odds = _load(season, 'odds.jsonl.gz')
    flog = store.read_json(os.path.join(RAW, str(season), 'fetch_log.json'), {}) or {}

    odds_by_game, boxes_by_game = defaultdict(list), defaultdict(list)
    for q in odds:
        odds_by_game[q['game_id']].append(q)
    for b in boxes:
        boxes_by_game[b['game_id']].append(b)
    final_ids = {g['game_id'] for g in games if g['status'] == 'final'}
    flags, n_checks = flag_quotes([q for q in odds if q['game_id'] in final_ids])
    flags.sort(key=lambda f: (f['game_id'], f['provider'], f['stage'], f['market'], f['side'], f['flag']))
    store.write_jsonl_gz(os.path.join(RAW, str(season), 'odds_flags.jsonl.gz'), flags)

    by_phase = {ph: _phase_block([g for g in games if phase_of(g) == ph], odds_by_game, flags)
                for ph in ('regular', 'postseason')}

    # box score 合理性：球員分鐘加總應接近 240 + 25×延長賽
    box_issues = []
    for g in games:
        if not g.get('complete'):
            continue
        bs = boxes_by_game.get(g['game_id'], [])
        if len(bs) != 2:
            box_issues.append((g['game_id'], f'{len(bs)} boxes'))
            continue
        for b in bs:
            mins = sum((p.get('minutes') or 0) for p in b.get('players', []))
            want = 240 + 25 * b['overtimes']
            if not b.get('players'):
                box_issues.append((g['game_id'], f'team {b["team"]} no players'))
            elif mins and abs(mins - want) > 6:
                box_issues.append((g['game_id'], f'team {b["team"]} minutes {mins:.1f} vs {want}'))

    per_team = Counter()
    for g in games:
        if g['season_type'] == 2 and g['status'] == 'final':
            per_team[g['home']] += 1
            per_team[g['away']] += 1
    expected = EXPECTED_REG.get(season, EXPECTED_DEFAULT)
    reg_final = by_phase['regular']['final']
    lo, hi = TEAM_GAMES.get(season, TEAM_GAMES_DEFAULT)
    tc = sorted(per_team.values())
    dup = [k for k, v in Counter(g['game_id'] for g in games).items() if v > 1]
    n_final = sum(b['final'] for b in by_phase.values())
    n_complete = sum(b['complete'] for b in by_phase.values())
    n_err = sum(1 for f in flags if f['severity'] == 'error')
    err_rate = n_err / n_checks if n_checks else 0.0

    # 資料來源標記：每場完整的比賽都必須有 box_source，且與兩隊 box score 的 source 一致
    src_problems = []
    for g in games:
        if not g.get('complete'):
            continue
        bsrc = {b['source'].split(':')[0] for b in boxes_by_game.get(g['game_id'], [])}
        if g.get('box_source') not in ('espn', 'bbref') or bsrc != {g.get('box_source')}:
            src_problems.append((g['game_id'], g.get('box_source'), sorted(bsrc)))

    reasons = []
    if src_problems:
        reasons.append(f'資料來源標記缺漏或不一致 {len(src_problems)} 場')
    if not live:
        if not (expected <= reg_final <= expected + 1):
            reasons.append(f'例行賽完賽 {reg_final} 場，預期 {expected}（NBA 盃冠軍賽可 +1）')
        if tc and (tc[0] < lo or tc[-1] > hi or len(per_team) != 30):
            reasons.append(f'每隊例行賽場數異常：{len(per_team)} 隊，{tc[0]}～{tc[-1]} 場（預期 {lo}～{hi}）')
    if n_final and n_complete / n_final < 0.99:
        reasons.append(f'完賽比賽資料完整率 {n_complete / n_final:.1%} < 99%')
    if err_rate >= 0.01:
        reasons.append(f'盤口 error 級標記比例 {err_rate:.2%} ≥ 1%')
    if dup:
        reasons.append(f'重複 game_id {len(dup)} 個')

    rep = {
        'season': season, 'label': f'{season - 1}-{str(season)[2:]}', 'live': live,
        'expected_regular': expected, 'by_phase': by_phase,
        'teams': {'n': len(per_team), 'min_games': tc[0] if tc else None, 'max_games': tc[-1] if tc else None,
                  'expected_range': [lo, hi]},
        'duplicates': dup, 'skipped_at_listing': flog.get('skipped', {}),
        'box_issues': len(box_issues), 'box_issue_examples': box_issues[:20],
        'source_label_problems': len(src_problems), 'source_label_examples': src_problems[:10],
        'incomplete_examples': [(g['game_id'], g.get('complete_reason')) for g in games
                                if g['status'] == 'final' and not g.get('complete')][:20],
        'odds_checks': {'n': n_checks, 'error': n_err,
                        'warning': sum(1 for f in flags if f['severity'] == 'warning'),
                        'missing': sum(1 for f in flags if f['severity'] == 'missing'),
                        'error_rate_pct': round(100 * err_rate, 4), 'examples': _examples(flags)},
        'anomaly_analysis': anomaly_analysis(odds, flags, final_ids),
        'timestamps_available': False,
        'opening_feed_agreement': _opening_agreement(odds_by_game, final_ids),
        'fetch': {'requests': flog.get('requests'), 'http_errors': len(flog.get('http_errors', [])),
                  'parse_errors': len(flog.get('parse_errors', [])),
                  'parse_error_examples': flog.get('parse_errors', [])[:10]},
        'verdict_ok': not reasons,
        'verdict': '通過' if not reasons else '不通過：' + '；'.join(reasons),
    }
    store.write_json(os.path.join(RAW, str(season), 'quality.json'), rep)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, f'{season}.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_md(rep))
    return rep


def _examples(flags, per_kind=5):
    out = defaultdict(list)
    for f in flags:
        if len(out[f['flag']]) < per_kind:
            out[f['flag']].append(f"{f['game_id']}/{f['provider']}/{f['stage']}/{f['market']}/{f['side']}: {f['detail']}")
    return dict(out)


def _opening_agreement(odds_by_game, final_ids):
    agree = n = 0
    for gid in final_ids:
        qs = odds_by_game.get(gid, [])
        feed = [q['line'] for q in qs if q['provider_type'] == 'opening_feed' and q['market'] == 'spread'
                and q['side'] == 'home' and q['stage'] == 'current_postgame']
        init = [q['line'] for q in qs if q['provider_type'] == 'book' and q['market'] == 'spread'
                and q['side'] == 'home' and q['stage'] == 'open']
        if feed and init:
            n += 1
            agree += abs(feed[0] - median(init)) <= 0.5
    return {'n': n, 'agree_pct': _pct(agree, n)}


def render_md(r):
    P = r['by_phase']
    cols = ['regular', 'postseason']
    L = [f"# 資料品質報告：{r['label']}（ESPN season {r['season']}）", '', f"**判定：{r['verdict']}**", '',
         '## 場次、完整度與缺漏（例行賽、季後賽分開）', '',
         '| 項目 | 例行賽 | 季後賽 |', '|---|---|---|']

    def row(name, fn):
        L.append(f'| {name} | ' + ' | '.join(str(fn(P[c])) for c in cols) + ' |')

    row('場次（含延賽）', lambda b: b['games'])
    row('完賽', lambda b: b['final'])
    row('狀態', lambda b: b['status'])
    row('資料完整', lambda b: f"{b['complete']}（{b['complete_pct']}%）")
    row('ESPN 原始 box score 缺漏', lambda b: b['espn_box_missing'])
    row('Basketball-Reference 補值（得分已核對）', lambda b: b['bbref_filled'])
    row('補值後仍不完整', lambda b: b['still_incomplete'])
    row('盤口缺漏（無任何莊家）', lambda b: b['odds_missing_games'])
    row('異常賠率（標記數）', lambda b: b['abnormal_price'])
    row('異常讓分（標記數）', lambda b: b['abnormal_spread'])
    row('異常總分（標記數）', lambda b: b['abnormal_total'])
    row('總分佔位符 -1（視為缺失）', lambda b: b.get('placeholder_missing', 0))
    row('每場莊家數中位數', lambda b: b['books_per_game_median'])
    L += ['', f"- 例行賽預期 {r['expected_regular']} 場；每隊 {r['teams']['min_games']}～{r['teams']['max_games']} 場"
          f"（{r['teams']['n']} 隊，預期 {r['teams']['expected_range'][0]}～{r['teams']['expected_range'][1]}）",
          f"- 列表階段略過：{r['skipped_at_listing']}",
          f"- box score 合理性問題：{r['box_issues']}；重複 game_id：{len(r['duplicates'])}；"
          f"資料來源標記缺漏或不一致：{r['source_label_problems']} 場", '']
    for gid, why in r['incomplete_examples']:
        L.append(f'  - 不完整 `{gid}`：{why}')
    L += ['', '## 各博彩公司覆蓋率（該公司有盤口的完賽比賽比例）', '', '| 博彩公司 | 例行賽 % | 季後賽 % |', '|---|---|---|']
    books = list(P['regular']['book_coverage_pct'])
    books += [b for b in P['postseason']['book_coverage_pct'] if b not in books]
    for b in books:
        L.append(f"| {b} | {P['regular']['book_coverage_pct'].get(b, 0)} | {P['postseason']['book_coverage_pct'].get(b, 0)} |")
    L += ['', '## 盤口欄位覆蓋率（至少一家莊家具備）', '',
          '- **開盤／收盤時間戳：ESPN 未提供**（欄位保留為空，不推測）',
          f"- \"Opening\" 提供者與各家開盤線中位數一致（±0.5）：{r['opening_feed_agreement']['agree_pct']}%（n={r['opening_feed_agreement']['n']}）", '',
          '| 階段/市場 | 例行賽 有盤口% | 例行賽 雙邊賠率% | 季後賽 有盤口% | 季後賽 雙邊賠率% |', '|---|---|---|---|---|']
    for k in P['regular']['coverage']:
        a, b = P['regular']['coverage'][k], P['postseason']['coverage'][k]
        L.append(f"| {k} | {a['line_pct']} | {a['price_pct']} | {b['line_pct']} | {b['price_pct']} |")
    oc = r['odds_checks']
    L += ['', '## 盤口品質標記（原始資料不動，標記另存 odds_flags.jsonl.gz）', '',
          f"- 檢核 {oc['n']} 項：被標記的單筆盤口 error {oc['error']}、warning {oc['warning']}、缺失值 {oc.get('missing', 0)}，**error 比例 {oc['error_rate_pct']}%**",
          '- 缺失值規則：ESPN 以總分 ≤ 0（實測為 -1）表示該莊家沒有開總分 → 視同沒有這筆盤口，計入缺漏、不計入異常',
          '- 以**單筆盤口紀錄**為單位排除：error 一律不進模型；warning（極端但可能真實）預設不進模型，需人工放行',
          '- 同一場比賽的其他莊家、其他盤口、同組另一邊（若無問題）全部保留，不會因一筆異常排除整場', '']
    for kind, exs in oc['examples'].items():
        L.append(f'- {kind}：' + '；'.join(f'`{e}`' for e in exs))
    L += render_anomaly(r.get('anomaly_analysis'))
    fe = r['fetch']
    L += ['', '## 抓取', '', f"- 請求 {fe['requests']} 次，HTTP 失敗 {fe['http_errors']}，解析失敗 {fe['parse_errors']}"]
    for e in fe['parse_error_examples']:
        L.append(f"  - `{e.get('game_id')}` {e.get('stage')}: {e.get('error')}")
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- 異常盤口分析
def anomaly_analysis(odds, flags, final_ids, min_peers=3):
    """
    1. 依博彩公司：error 筆數 / 該公司全部盤口筆數
    2. 依異常類型
    3. 極端讓分與其他莊家共識比較：|自己 − 其他莊家中位數| ≤ 1.5 → 「極端但與市場一致」；否則「與市場矛盾＝錯誤」
    4. 讓分×獨贏方向矛盾：檢查是否同一家、同一階段；並以其他莊家共識判斷是哪一筆偏離
    """
    by_game = defaultdict(list)
    for q in odds:
        if q['game_id'] in final_ids and q['provider_type'] == 'book':
            by_game[q['game_id']].append(q)
    total_by_book = Counter(q['provider'] for qs in by_game.values() for q in qs)
    err = [f for f in flags if f['severity'] == 'error']
    by_book = [{'provider': b, 'error_records': n, 'book_records': total_by_book[b],
                'rate_pct': _pct(n, total_by_book[b])} for b, n in Counter(f['provider'] for f in err).most_common()]
    top_share = _pct(by_book[0]['error_records'], len(err)) if by_book else None

    def peers(gid, stage, market, side, prov):
        return [q['line'] for q in by_game[gid] if q['provider'] != prov and q['stage'] == stage
                and q['market'] == market and q['side'] == side and q['line'] is not None and q['line'] > 0 - 1e9]

    extremes = []
    for f in err:
        if f['flag'] != 'spread_out_of_range' or f['side'] != 'home':
            continue
        mine = next(q['line'] for q in by_game[f['game_id']] if q['provider'] == f['provider'] and q['stage'] == f['stage']
                    and q['market'] == 'spread' and q['side'] == 'home')
        pl = peers(f['game_id'], f['stage'], 'spread', 'home', f['provider'])
        cons = median(pl) if len(pl) >= min_peers else None
        verdict = ('其他莊家不足，無法判斷' if cons is None else
                   ('極端但與市場一致' if abs(mine - cons) <= 1.5 else '與市場矛盾（錯誤）'))
        extremes.append({'game_id': f['game_id'], 'provider': f['provider'], 'line': mine,
                         'peer_median': cons, 'n_peers': len(pl), 'verdict': verdict})

    attrib = Counter()
    same_book_stage = True
    for f in err:
        if f['flag'] != 'spread_ml_direction_conflict' or f['market'] != 'spread' or f['side'] != 'home':
            continue
        qs = [q for q in by_game[f['game_id']] if q['provider'] == f['provider'] and q['stage'] == f['stage']]
        sp = {q['side']: q['line'] for q in qs if q['market'] == 'spread'}
        ml = {q['side']: q['price_decimal'] for q in qs if q['market'] == 'ml'}
        same_book_stage &= ('home' in sp and 'home' in ml and 'away' in ml)
        pl = peers(f['game_id'], f['stage'], 'spread', 'home', f['provider'])
        mlh = {q['provider']: q['price_decimal'] for q in by_game[f['game_id']] if q['stage'] == f['stage'] and q['market'] == 'ml' and q['side'] == 'home'}
        mla = {q['provider']: q['price_decimal'] for q in by_game[f['game_id']] if q['stage'] == f['stage'] and q['market'] == 'ml' and q['side'] == 'away'}
        others_fav = [mlh[p] < mla[p] for p in mlh if p != f['provider'] and p in mla]
        if len(pl) < min_peers or len(others_fav) < min_peers:
            attrib['其他莊家不足，無法歸因'] += 1
            continue
        cons = median(pl)
        sp_ok = abs(sp['home'] - cons) <= 1.0
        ml_ok = (ml['home'] < ml['away']) == (sum(others_fav) > len(others_fav) / 2)
        if sp_ok and not ml_ok:
            attrib['讓分與市場一致、獨贏偏離（錯在獨贏）'] += 1
        elif ml_ok and not sp_ok:
            attrib['獨贏與市場一致、讓分偏離（錯在讓分）'] += 1
        else:
            attrib['兩者都偏離或都一致（無法歸因）'] += 1
    return {'error_records': len(err), 'by_book': by_book, 'top_book_share_pct': top_share,
            'by_kind': dict(Counter(f['flag'] for f in err)),
            'by_severity': dict(Counter(f['severity'] for f in flags)),
            'extreme_spreads': extremes, 'direction_conflict_attribution': dict(attrib),
            'direction_check_same_book_same_stage': same_book_stage}


def render_anomaly(a):
    if not a:
        return []
    L = ['', '## 異常盤口分析', '',
         f"- error 級單筆紀錄 {a['error_records']} 筆；最多的一家佔 {a['top_book_share_pct']}%", '',
         '| 博彩公司 | error 筆數 | 該公司盤口筆數 | 比例 % |', '|---|---|---|---|']
    for b in a['by_book']:
        L.append(f"| {b['provider']} | {b['error_records']} | {b['book_records']} | {b['rate_pct']} |")
    L += ['', f"- 依類型：{a['by_kind'] or '無'}", f"- 依嚴重度（含 warning／缺失值）：{a['by_severity']}"]
    if a['extreme_spreads']:
        L += ['', '極端讓分抽查（與同場其他莊家的中位數比較，±1.5 以內視為與市場一致）：', '',
              '| game_id | 博彩公司 | 主隊讓分 | 其他莊家中位數 | 其他莊家數 | 判定 |', '|---|---|---|---|---|---|']
        for e in a['extreme_spreads']:
            L.append(f"| {e['game_id']} | {e['provider']} | {e['line']} | {e['peer_median']} | {e['n_peers']} | {e['verdict']} |")
    if a['direction_conflict_attribution']:
        L += ['', f"讓分×獨贏方向矛盾：檢查一律在**同一家、同一階段**內比較（本季全部符合：{a['direction_check_same_book_same_stage']}），"
              '以主隊讓分 < 0 ⇔ 主隊獨贏賠率較低判定。歸因（與其他莊家共識比較）：']
        for k, v in a['direction_conflict_attribution'].items():
            L.append(f'- {k}：{v} 組')
    return L
