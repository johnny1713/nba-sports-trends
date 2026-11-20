"""
盤口品質標記（要求：極端賠率與異常盤口保留原始資料，另建獨立標記，不得未經檢查就進模型）。

- 原始盤口檔 odds.jsonl.gz **永不修改**；標記另存 odds_flags.jsonl.gz。
- 每一筆標記對應**單筆盤口紀錄**：game_id / provider / stage / market / side / flag / severity / detail。
  只影響單邊的問題只標那一邊；本質上是整個市場的問題（讓分線兩邊共用、水位、方向矛盾）整個市場兩邊都標。
- 排除以單筆紀錄為單位：同一場的其他莊家、同一家的其他盤口全部保留，不會因一筆異常排除整場。
- severity:
    'missing' 缺失值佔位符（ESPN 以總分 **剛好 -1** 表示「沒有總分」；其他負數不是佔位符）→ 視同沒有這筆盤口；計入缺漏、不計入異常
    'error'   明顯錯誤 → 模型一律排除
    'warning' 偏高／極端但可能合理 → 預設排除，人工確認後才可放行
- 模型載入盤口時必須呼叫 usable_quotes()。去水需要同一家同一階段的兩邊價格，
  若其中一邊被排除，該組自然無法去水——這是下游結果，不是這裡刪整組。

**以下門檻只適用 ESPN 的美國莊家盤口。台灣運彩正常抽水約 1.16，絕對不可套用。**

抽水（overround = 同一家、同一階段的雙邊 1/賠率 相加）分級，依 2014-15～2018-19 實測分布訂定
（讓分／大小分最高 1.083；獨贏 99.99% 分位 1.082，最高 1.46 為孤例）：
    一般        1.00 ≤ x ≤ 1.10
    偏高 warning 1.10 < x ≤ 1.25，或 0.98 ≤ x < 1.00
    錯誤 error   x > 1.25，或 x < 0.98

盤口偏離市場（2019-20 實測發現）：ESPN 的「賽後 current」對部分莊家其實是**比賽中最後的滾球盤**
（例：公牛@黃蜂 其他莊家總分約 218，DraftKings 252.5，實際 251）。這是資料洩漏，範圍檢查抓不到。
同場同階段有 ≥ 3 家其他有效莊家時，與其他莊家中位數比較：
    讓分 |差| > 4 分、總分 |差| > 6 分、獨贏去水主隊勝率 |差| > 0.15 → error（兩邊都標）
    detail 註明是否比市場更接近實際結果（疑似滾球盤混入）
單一莊家的年份（2024-25 起）無法比對，這類污染只能靠開盤／收盤欄位本身的定義避免。

讓分×獨贏方向矛盾（同一家、同一階段：主隊讓分 < 0 ⇔ 主隊獨贏賠率較低；讓分 ≥ 2 分才比）——
2026-11-20 使用者決定，以同場同階段**其他至少 3 家有效莊家**的市場共識歸因：
    讓分偏離共識、獨贏與共識一致 → 只標讓分盤（兩邊都標：讓分線是兩隊共用的，不能只排除一隊）
    獨贏偏離共識、讓分與共識一致 → 只標獨贏盤（兩邊都標：雙邊價格是同一組報價）
    無法明確歸因，或可比較的莊家不足 3 家 → 保守處理，兩個市場都標
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

SPREAD_MAX = 25.0
TOTAL_RANGE = (170.0, 280.0)
OVERROUND_NORMAL = (1.00, 1.10)
OVERROUND_PLAUSIBLE = (0.98, 1.25)
EXTREME_ML = (1.02, 15.0)          # 獨贏小數賠率超出此範圍 → warning
EXTREME_SIDE = (1.5, 2.6)          # 讓分／大小分賠率超出此範圍 → warning
CONFLICT_MIN_SPREAD = 2.0
PEERS_MIN = 3
DEVIATION_MAX = {'spread': 4.0, 'total': 6.0, 'ml': 0.15}
SPREAD_AGREE_TOL = 1.0             # 與其他莊家中位數相差 ≤ 1 分視為一致
ML_CONSENSUS_SHARE = 2 / 3         # 其他莊家至少 2/3 同意熱門方向才算有共識


def group_quotes(quotes):
    grp = defaultdict(dict)
    for q in quotes:
        if q.get('provider_type') != 'book':
            continue
        grp[(q['game_id'], q['provider'], q['stage'], q['market'])][q['side']] = q
    return grp


def overround_tier(ov):
    if OVERROUND_NORMAL[0] <= ov <= OVERROUND_NORMAL[1]:
        return None
    if OVERROUND_PLAUSIBLE[0] <= ov <= OVERROUND_PLAUSIBLE[1]:
        return 'warning'
    return 'error'


def flag_quotes(quotes, results=None):
    """回傳 (flags, n_checks)。只檢查莊家（book）盤口。results: {game_id: (home_pts, away_pts)}，用來註明疑似滾球盤。"""
    grp = group_quotes(quotes)
    flags, n = [], 0
    structural_bad = set()        # (gid, prov, stage, market)：自身結構有誤，不可當比較基準

    def add(key, flag, severity, detail, sides):
        gid, prov, stage, market = key
        for side in sides:
            flags.append({'game_id': gid, 'provider': prov, 'stage': stage, 'market': market, 'side': side,
                          'flag': flag, 'severity': severity, 'detail': detail})

    for key, sd in grp.items():
        gid, prov, stage, market = key
        if market == 'spread' and 'home' in sd and 'away' in sd:
            h, a = sd['home']['line'], sd['away']['line']
            n += 2
            if abs(h) >= 100 and abs(a) >= 100:
                # ESPN 把賠率填進盤口欄位（2022-23 ESPN BET 的 close 實測：主 -110 / 客 +110）
                add(key, 'line_field_contains_price', 'error', f'home {h} away {a}', ('home', 'away'))
                structural_bad.add(key)
                continue
            if abs(h + a) > 1e-9:
                add(key, 'spread_sign_mismatch', 'error', f'home {h} away {a}', ('home', 'away'))
                structural_bad.add(key)
            if abs(h) > SPREAD_MAX:
                add(key, 'spread_out_of_range', 'error', f'home {h}', ('home', 'away'))
                structural_bad.add(key)
        if market == 'total':
            lines = {sd[s]['line'] for s in sd}
            n += 1
            if len(lines) > 1 and min(lines) > 100:
                add(key, 'total_lines_differ', 'error', str(sorted(lines)), tuple(sd))
            for s_ in sd:
                ln = sd[s_]['line']
                if ln == -1.0:
                    # 缺失值規則：ESPN 用 -1 表示該莊家沒有開總分（2017-18 實測：同場其他莊家都有正常總分）
                    add(key, 'total_placeholder_missing', 'missing', f'{ln}', (s_,))
                    structural_bad.add(key)
                elif ln <= -100 or (ln >= 100 and ln == sd[s_].get('price_american')):
                    add(key, 'line_field_contains_price', 'error', f'{ln}', (s_,))
                    structural_bad.add(key)
                elif not (TOTAL_RANGE[0] <= ln <= TOTAL_RANGE[1]):
                    add(key, 'total_out_of_range', 'error', f'{ln}', (s_,))
        prices = {s: sd[s]['price_decimal'] for s in sd if sd[s]['price_decimal'] is not None}
        lo, hi = EXTREME_ML if market == 'ml' else EXTREME_SIDE
        for s, p in prices.items():
            n += 1
            if p <= 1.0:
                add(key, 'price_invalid', 'error', f'{s} {p}', (s,))
                structural_bad.add(key)
            elif not (lo <= p <= hi):
                add(key, 'price_extreme', 'warning', f'{s} {p}', (s,))
        if len(prices) == 2:
            ov = sum(1 / p for p in prices.values())
            n += 1
            tier = overround_tier(ov)
            if tier == 'warning':
                add(key, 'overround_high', 'warning', f'{ov:.4f}', tuple(prices))
            elif tier == 'error':
                add(key, 'overround_out_of_range', 'error', f'{ov:.4f}', tuple(prices))
                structural_bad.add(key)

    # ---- 盤口偏離市場（疑似滾球盤混入等）
    def value(key):
        sd = grp[key]
        m = key[3]
        if m == 'spread':
            return sd['home']['line'] if 'home' in sd else None
        if m == 'total':
            ln = next(iter(sd.values()))['line']
            return ln if ln > 100 else None
        hp, ap = (sd.get('home') or {}).get('price_decimal'), (sd.get('away') or {}).get('price_decimal')
        return (1 / hp) / (1 / hp + 1 / ap) if hp and ap else None

    by_gsm = defaultdict(list)
    for key in grp:
        if key in structural_bad:
            continue
        v = value(key)
        if v is not None:
            by_gsm[(key[0], key[2], key[3])].append((key, v))
    deviated = set()
    for (gid, stage, market), items in by_gsm.items():
        if len(items) < PEERS_MIN + 1:
            continue
        # 共識 = 全部莊家的中位數；必須有 ≥ 2/3 的其他莊家落在容許範圍內，才算真的有市場共識。
        # （只用「其他莊家中位數」會在多家同時出錯時把正常莊家也誤判——測試 test_conflicting_books_are_not_used_as_peers）
        med = median(w for _, w in items)
        tol = DEVIATION_MAX[market]
        for key, v in items:
            peers = [w for k2, w in items if k2 != key]
            n += 1
            if abs(v - med) <= tol:
                continue
            if sum(abs(w - med) <= tol for w in peers) < ML_CONSENSUS_SHARE * len(peers):
                continue                       # 沒有明確共識：不判定（無法歸因就不排除）
            if True:
                note = ''
                if results and gid in results and market in ('spread', 'total'):
                    hp_, ap_ = results[gid]
                    actual = (hp_ + ap_) if market == 'total' else (ap_ - hp_)   # 主隊讓分的事後公平值 = −(主隊淨勝)
                    if abs(v - actual) < abs(med - actual):
                        note = '；比市場更接近實際結果（疑似滾球盤混入）'
                fmt = (lambda x: f'{x:.3f}') if market == 'ml' else (lambda x: f'{x:g}')
                add(key, 'line_deviates_from_market', 'error',
                    f"{fmt(v)} vs market median {fmt(med)} (n={len(items)}){note}", tuple(grp[key]))
                deviated.add(key)

    # ---- 讓分×獨贏方向矛盾（同一家、同一階段）
    def info(gid, prov, stage):
        sp = grp.get((gid, prov, stage, 'spread'), {})
        ml = grp.get((gid, prov, stage, 'ml'), {})
        if 'home' not in sp or 'home' not in ml or 'away' not in ml:
            return None
        hp, ap = ml['home']['price_decimal'], ml['away']['price_decimal']
        if not hp or not ap:
            return None
        return sp['home']['line'], hp < ap

    conflicts = set()
    by_gs = defaultdict(set)
    for (gid, prov, stage, market) in grp:
        by_gs[(gid, stage)].add(prov)
    for (gid, stage), provs in by_gs.items():
        for prov in provs:
            if (gid, prov, stage, 'spread') in structural_bad or (gid, prov, stage, 'ml') in structural_bad:
                continue
            x = info(gid, prov, stage)
            if x and abs(x[0]) >= CONFLICT_MIN_SPREAD:
                n += 1
                if (x[0] < 0) != x[1]:
                    conflicts.add((gid, prov, stage))

    for (gid, prov, stage) in sorted(conflicts):
        line, fav_home = info(gid, prov, stage)
        peer_lines, peer_fav = [], []
        for p in by_gs[(gid, stage)]:
            if p == prov or (gid, p, stage) in conflicts:
                continue
            if ((gid, p, stage, 'spread') in structural_bad or (gid, p, stage, 'ml') in structural_bad
                    or (gid, p, stage, 'spread') in deviated or (gid, p, stage, 'ml') in deviated):
                continue
            y = info(gid, p, stage)
            if y:
                peer_lines.append(y[0])
                peer_fav.append(y[1])
        sp_key, ml_key = (gid, prov, stage, 'spread'), (gid, prov, stage, 'ml')
        verdict = 'unattributable'
        if len(peer_lines) >= PEERS_MIN:
            cons_line = median(peer_lines)
            share_home = sum(peer_fav) / len(peer_fav)
            cons_fav = True if share_home >= ML_CONSENSUS_SHARE else (False if share_home <= 1 - ML_CONSENSUS_SHARE else None)
            spread_ok = abs(line - cons_line) <= SPREAD_AGREE_TOL
            ml_ok = None if cons_fav is None else (fav_home == cons_fav)
            if not spread_ok and ml_ok is True:
                verdict = 'spread'
            elif spread_ok and ml_ok is False:
                verdict = 'ml'
            detail = f'home spread {line}, peers median {cons_line} (n={len(peer_lines)}), peers home-fav share {share_home:.2f}'
        else:
            detail = f'home spread {line}; only {len(peer_lines)} comparable books (< {PEERS_MIN})'
        if verdict == 'spread':
            add(sp_key, 'spread_deviates_from_market', 'error', detail, ('home', 'away'))
        elif verdict == 'ml':
            add(ml_key, 'ml_deviates_from_market', 'error', detail, ('home', 'away'))
        else:
            add(sp_key, 'spread_ml_direction_conflict', 'error', detail, ('home', 'away'))
            add(ml_key, 'spread_ml_direction_conflict', 'error', detail, ('home', 'away'))
    return flags, n


def record_key(x):
    return (x['game_id'], x['provider'], x['stage'], x['market'], x['side'])


def usable_quotes(quotes, flags, allow_warnings=frozenset()):
    """
    給模型用：以**單筆紀錄**為單位剔除有標記的盤口，其餘全部保留。
    allow_warnings：人工確認後明確放行的單筆紀錄 key (game_id, provider, stage, market, side)。
    """
    bad = {record_key(f) for f in flags
           if f['severity'] in ('error', 'missing') or record_key(f) not in allow_warnings}
    return [q for q in quotes if q.get('provider_type') == 'book' and record_key(q) not in bad]
