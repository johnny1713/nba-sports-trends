"""
CLV 開盤／收盤配對規範（2026-11-20 使用者決定）。CLV 的任何計算都只能使用這裡產生的配對。

規則：
1. 同一場比賽的開盤與收盤，必須來自**同一家**博彩公司（以 provider 名稱比對）。
2. 必須是**相同市場**（spread／total／ml）且**相同方向**（home／away／over／under）。
3. 不允許跨博彩公司、跨市場、跨方向配對——配對鍵是 (game_id, provider, market, side)，結構上就不可能混配。
4. 缺開盤或缺收盤時，該筆不計入 CLV；**不得**用賽後快照（POSTGAME_SNAPSHOT）、其他莊家、或其他階段的價格補值。
5. 開盤必須是賽前價格（PROVIDER_LABELED_OPEN 或 TIMESTAMP_VERIFIED_OPEN）；
   收盤必須是 PROVIDER_LABELED_CLOSE 或 TIMESTAMP_VERIFIED_CLOSE（見 price_time.py）。
6. 被品質標記為 error／missing／未放行 warning 的單筆紀錄不參與配對（見 odds_flags.py）。
7. 報告必須揭露：有效配對數、排除數與每一種排除原因的筆數（pairing_report）。

去水（計算 CLV 時需要同一家、同一階段的另一邊價格）也必須是**同一家**的報價，不得借用其他莊家。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from . import price_time as pt
from .odds_flags import record_key

OTHER_SIDE = {'home': 'away', 'away': 'home', 'over': 'under', 'under': 'over'}

# 排除原因
MISSING_OPEN = 'missing_open'
MISSING_CLOSE = 'missing_close'
OPEN_NOT_PREGAME = 'open_not_pregame'
CLOSE_NOT_ELIGIBLE = 'close_not_clv_eligible'
MISSING_PRICE = 'missing_price'
FLAGGED = 'flagged_record'
MISSING_OTHER_SIDE = 'missing_same_book_other_side_for_devig'


def pair_open_close(quotes: Iterable[dict], start_by_game: Dict[str, str], flags: Iterable[dict] = (),
                    allow_warnings=frozenset()) -> Tuple[List[dict], List[dict]]:
    """
    回傳 (pairs, exclusions)。
    pairs：{game_id, provider, market, side, open, close, open_other, close_other, open_class, close_class}
    exclusions：{game_id, provider, market, side, reason}
    只看莊家（book）盤口；賽後快照與我們自己的快照完全不參與。
    """
    bad = {record_key(f) for f in flags
           if f['severity'] in ('error', 'missing') or record_key(f) not in allow_warnings}
    by = defaultdict(dict)                      # (gid, prov, market, side) -> {stage: quote}
    for q in quotes:
        if q.get('provider_type') not in (None, 'book') or q['stage'] not in ('open', 'close'):
            continue                            # 賽後快照、我們的快照：不參與 CLV（不補值）
        by[(q['game_id'], q['provider'], q['market'], q['side'])][q['stage']] = q

    pairs, excl = [], []

    def ex(key, reason):
        gid, prov, market, side = key
        excl.append({'game_id': gid, 'provider': prov, 'market': market, 'side': side, 'reason': reason})

    for key, st in sorted(by.items()):
        gid, prov, market, side = key
        o, c = st.get('open'), st.get('close')
        if o is None:
            ex(key, MISSING_OPEN)
            continue
        if c is None:
            ex(key, MISSING_CLOSE)
            continue
        if record_key(o) in bad or record_key(c) in bad:
            ex(key, FLAGGED)
            continue
        start = start_by_game.get(gid)
        oc, cc = pt.classify(o, start), pt.classify(c, start)
        if oc not in (pt.PROVIDER_LABELED_OPEN, pt.TIMESTAMP_VERIFIED_OPEN):
            ex(key, OPEN_NOT_PREGAME)
            continue
        if cc not in pt.CLV_ALLOWED:
            ex(key, CLOSE_NOT_ELIGIBLE)
            continue
        if not o.get('price_decimal') or not c.get('price_decimal'):
            ex(key, MISSING_PRICE)
            continue
        other = OTHER_SIDE[side]
        oo = by.get((gid, prov, market, other), {}).get('open')       # 同一家、同一市場、同一階段的另一邊
        co = by.get((gid, prov, market, other), {}).get('close')
        if (not oo or not co or not oo.get('price_decimal') or not co.get('price_decimal')
                or record_key(oo) in bad or record_key(co) in bad):
            ex(key, MISSING_OTHER_SIDE)
            continue
        pairs.append({'game_id': gid, 'provider': prov, 'market': market, 'side': side,
                      'open': o, 'close': c, 'open_other': oo, 'close_other': co,
                      'open_class': oc, 'close_class': cc})
    for p in pairs:
        assert_valid_pair(p)
    return pairs, excl


def assert_valid_pair(p: dict):
    """CLV 計算入口的保險：配對中的四筆價格必須同一場、同一家、同一市場，方向正確，階段正確。"""
    legs = {'open': p['open'], 'close': p['close'], 'open_other': p['open_other'], 'close_other': p['close_other']}
    for name, q in legs.items():
        if q['game_id'] != p['game_id'] or q['provider'] != p['provider'] or q['market'] != p['market']:
            raise ValueError(f'CLV pair mixes games/books/markets: {name}')
    if p['open']['side'] != p['side'] or p['close']['side'] != p['side']:
        raise ValueError('CLV pair side mismatch')
    if p['open_other']['side'] != OTHER_SIDE[p['side']] or p['close_other']['side'] != OTHER_SIDE[p['side']]:
        raise ValueError('CLV devig leg is not the opposite side')
    if p['open']['stage'] != 'open' or p['open_other']['stage'] != 'open':
        raise ValueError('CLV open leg is not an opening price')
    if p['close']['stage'] != 'close' or p['close_other']['stage'] != 'close':
        raise ValueError('CLV close leg is not a closing price')
    if p.get('close_class') not in pt.CLV_ALLOWED:
        raise ValueError(f"CLV close leg class {p.get('close_class')} is not an eligible closing price")
    if p.get('open_class') not in (pt.PROVIDER_LABELED_OPEN, pt.TIMESTAMP_VERIFIED_OPEN):
        raise ValueError(f"CLV open leg class {p.get('open_class')} is not a pre-game opening price")


def devig_prob(price, other_price):
    a, b = 1 / price, 1 / other_price
    return a / (a + b)


def clv_prob(p: dict) -> float:
    """以同一家的雙邊價格去水：收盤去水機率 − 開盤去水機率（正值 = 開盤下注得到比收盤更好的價格）。"""
    assert_valid_pair(p)
    return (devig_prob(p['close']['price_decimal'], p['close_other']['price_decimal'])
            - devig_prob(p['open']['price_decimal'], p['open_other']['price_decimal']))


def pairing_report(pairs: List[dict], exclusions: List[dict]) -> dict:
    """CLV 報告必附：有效配對、排除數與原因（依原因、市場分開）。"""
    games_valid = {p['game_id'] for p in pairs}
    games_all = games_valid | {e['game_id'] for e in exclusions}
    return {
        'valid_pairs': len(pairs), 'excluded': len(exclusions),
        'valid_games': len(games_valid), 'games_considered': len(games_all),
        'games_without_any_valid_pair': len(games_all - games_valid),
        'excluded_by_reason': dict(Counter(e['reason'] for e in exclusions)),
        'excluded_by_market_reason': {f"{m}/{r}": n for (m, r), n in Counter((e['market'], e['reason']) for e in exclusions).items()},
        'valid_by_market': dict(Counter(p['market'] for p in pairs)),
        'close_time_classes': dict(Counter(p['close_class'] for p in pairs)),
    }
