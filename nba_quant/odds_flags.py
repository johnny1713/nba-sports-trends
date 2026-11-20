"""
盤口品質標記（要求：極端賠率與異常盤口保留原始資料，另建獨立標記，不得未經檢查就進模型）。

- 原始盤口檔 odds.jsonl.gz **永不修改**；標記另存 odds_flags.jsonl.gz。
- 每一筆標記對應**單筆盤口紀錄**：game_id / provider / stage / market / side / flag / severity / detail。
  只影響單邊的問題（例如某一邊賠率極端）只標那一邊；本質上是兩邊之間的問題
  （讓分兩邊同號、水位不合理、讓分與獨贏方向矛盾、兩邊總分不同）兩邊各標一筆。
- 排除以單筆紀錄為單位：同一場的其他莊家、同一家的其他盤口、同一組的另一邊（若沒問題）全部保留。
  不會因為一筆異常就排除整場比賽。
- severity:
    'error'   明顯錯誤（總分 2001、讓分兩邊同號、讓分與獨贏熱門方向相反、水位不合理）→ 模型一律排除
    'warning' 合理但極端（例如 -13000 的獨贏）→ 預設排除，人工檢查後才可放行
- 模型載入盤口時必須呼叫 usable_quotes()。注意：去水需要同一家同一階段的兩邊價格，
  若其中一邊被排除，該組就無法去水——這是下游自然結果，不是這裡把整組刪掉。
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
            if abs(h + a) > 1e-9:
                add(key, 'spread_sign_mismatch', 'error', f'home {h} away {a}', ('home', 'away'))
            if abs(h) > SPREAD_MAX:
                add(key, 'spread_out_of_range', 'error', f'home {h}', ('home', 'away'))
        if market == 'total':
            lines = {sd[s]['line'] for s in sd}
            n += 1
            if len(lines) > 1:
                add(key, 'total_lines_differ', 'error', str(sorted(lines)), tuple(sd))
            for s_ in sd:
                ln = sd[s_]['line']
                if not (TOTAL_RANGE[0] <= ln <= TOTAL_RANGE[1]):
                    add(key, 'total_out_of_range', 'error', f'{ln}', (s_,))
        prices = {s: sd[s]['price_decimal'] for s in sd if sd[s]['price_decimal'] is not None}
        lo, hi = EXTREME_ML if market == 'ml' else EXTREME_SIDE
        for s, p in prices.items():
            n += 1
            if p <= 1.0:
                add(key, 'price_invalid', 'error', f'{s} {p}', (s,))
            elif not (lo <= p <= hi):
                add(key, 'price_extreme', 'warning', f'{s} {p}', (s,))
        if len(prices) == 2:
            ov = sum(1 / p for p in prices.values())
            n += 1
            if not (OVERROUND_RANGE[0] <= ov <= OVERROUND_RANGE[1]):
                add(key, 'overround_out_of_range', 'error', f'{ov:.4f}', tuple(prices))
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
                    f'home spread {sd["home"]["line"]} but ML home {hp} away {ap}', tuple(sd))
                add((gid, prov, stage, 'ml'), 'spread_ml_direction_conflict', 'error', 'see spread', ('home', 'away'))
    return flags, n


def record_key(x):
    return (x['game_id'], x['provider'], x['stage'], x['market'], x['side'])


def usable_quotes(quotes, flags, allow_warnings=frozenset()):
    """
    給模型用：以**單筆紀錄**為單位剔除有標記的盤口，其餘全部保留。
    allow_warnings：人工檢查後明確放行的單筆紀錄 key (game_id, provider, stage, market, side)。
    """
    bad = {record_key(f) for f in flags if f['severity'] == 'error' or record_key(f) not in allow_warnings}
    return [q for q in quotes if q.get('provider_type') == 'book' and record_key(q) not in bad]
