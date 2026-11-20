"""
盤口品質標記（要求：極端賠率與異常盤口保留原始資料，另建獨立標記，不得未經檢查就進模型）。

- 原始盤口檔 odds.jsonl.gz **永不修改**；標記另存 odds_flags.jsonl.gz。
- 每一筆標記：game_id / provider / stage / market / flag / severity / detail。
- severity:
    'error'   明顯錯誤（總分 2001、讓分兩邊同號、讓分與獨贏熱門方向相反、水位不合理）→ 模型一律排除
    'warning' 合理但極端（例如 -13000 的獨贏）→ 預設排除，人工檢查後才可放行
- 模型載入盤口時必須呼叫 usable_quotes()，它會把有任何標記的整組（同家、同階段、同市場）剔除。
"""
from __future__ import annotations

from collections import defaultdict

SPREAD_MAX = 25.0
TOTAL_RANGE = (170.0, 280.0)
OVERROUND_RANGE = (0.995, 1.15)
EXTREME_ML = (1.02, 15.0)          # 獨贏小數賠率超出此範圍 → warning
EXTREME_SIDE = (1.5, 2.6)          # 讓分／大小分賠率超出此範圍 → warning


def group_quotes(quotes):
    grp = defaultdict(dict)
    for q in quotes:
        if q.get('provider_type') != 'book':
            continue
        grp[(q['game_id'], q['provider'], q['stage'], q['market'])][q['side']] = q
    return grp


def flag_quotes(quotes):
    """回傳 (flags, n_checks)。只檢查莊家（book）盤口。"""
    grp = group_quotes(quotes)
    flags, n = [], 0

    def add(key, flag, severity, detail):
        gid, prov, stage, market = key
        flags.append({'game_id': gid, 'provider': prov, 'stage': stage, 'market': market,
                      'flag': flag, 'severity': severity, 'detail': detail})

    for key, sd in grp.items():
        gid, prov, stage, market = key
        if market == 'spread' and 'home' in sd and 'away' in sd:
            h, a = sd['home']['line'], sd['away']['line']
            n += 2
            if abs(h + a) > 1e-9:
                add(key, 'spread_sign_mismatch', 'error', f'home {h} away {a}')
            if abs(h) > SPREAD_MAX:
                add(key, 'spread_out_of_range', 'error', f'home {h}')
        if market == 'total':
            lines = {sd[s]['line'] for s in sd}
            n += 1
            if len(lines) > 1:
                add(key, 'total_lines_differ', 'error', str(sorted(lines)))
            for ln in lines:
                if not (TOTAL_RANGE[0] <= ln <= TOTAL_RANGE[1]):
                    add(key, 'total_out_of_range', 'error', f'{ln}')
        prices = {s: sd[s]['price_decimal'] for s in sd if sd[s]['price_decimal'] is not None}
        lo, hi = EXTREME_ML if market == 'ml' else EXTREME_SIDE
        for s, p in prices.items():
            n += 1
            if p <= 1.0:
                add(key, 'price_invalid', 'error', f'{s} {p}')
            elif not (lo <= p <= hi):
                add(key, 'price_extreme', 'warning', f'{s} {p}')
        if len(prices) == 2:
            ov = sum(1 / p for p in prices.values())
            n += 1
            if not (OVERROUND_RANGE[0] <= ov <= OVERROUND_RANGE[1]):
                add(key, 'overround_out_of_range', 'error', f'{ov:.4f}')
    # 讓分方向 vs 獨贏熱門（同家、同階段；讓分 ≥ 2 分才比）
    for key, sd in grp.items():
        gid, prov, stage, market = key
        if market != 'spread' or 'home' not in sd:
            continue
        ml = grp.get((gid, prov, stage, 'ml'), {})
        hp = (ml.get('home') or {}).get('price_decimal')
        ap = (ml.get('away') or {}).get('price_decimal')
        if hp and ap and abs(sd['home']['line']) >= 2:
            n += 1
            if (sd['home']['line'] < 0) != (hp < ap):
                add(key, 'spread_ml_direction_conflict', 'error',
                    f'home spread {sd["home"]["line"]} but ML home {hp} away {ap}')
                add((gid, prov, stage, 'ml'), 'spread_ml_direction_conflict', 'error', 'see spread')
    return flags, n


def usable_quotes(quotes, flags, allow_warnings=frozenset()):
    """
    給模型用：剔除有標記的整組盤口。allow_warnings 是人工檢查後明確放行的 (game_id, provider, stage, market)。
    """
    bad = set()
    for f in flags:
        k = (f['game_id'], f['provider'], f['stage'], f['market'])
        if f['severity'] == 'error' or k not in allow_warnings:
            bad.add(k)
    return [q for q in quotes if q.get('provider_type') == 'book'
            and (q['game_id'], q['provider'], q['stage'], q['market']) not in bad]
