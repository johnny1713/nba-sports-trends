"""
回測統計：每個數字都附樣本數與不確定性（Phase 3 前補充要求 5）。

- 命中率：Wilson 信賴區間
- ROI：以「每單位下注的損益」做 bootstrap 信賴區間；另給單尾 p 值（H0: ROI ≤ 0）
- 與市場基準比較：成對 bootstrap（同一批比賽，差值的信賴區間），不比兩個獨立數字
- 機率品質：Brier、Log Loss、校準分箱
- 風險：最大回撤、最大連敗
結算：win / loss / push（退回本金，不計入命中率分母，損益 0）。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

MIN_SAMPLE_WARN = 300      # 少於這個數字，報表一律標示「樣本不足，結論不可靠」
_Z = {0.90: 1.6449, 0.95: 1.96, 0.99: 2.5758}


def wilson_ci(k: int, n: int, level: float = 0.95):
    if n == 0:
        return (None, None)
    z = _Z[level]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def bet_profit(result: str, price_decimal: float, stake: float = 1.0) -> float:
    if result == 'win':
        return stake * (price_decimal - 1)
    if result == 'loss':
        return -stake
    if result == 'push':
        return 0.0
    raise ValueError(f'unknown result {result!r}')


def bootstrap_ci(values: Sequence[float], stat=np.mean, level=0.95, B=10000, seed=12345):
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return (None, None)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, v.size, size=(B, v.size))
    sims = stat(v[idx], axis=1)
    a = (1 - level) / 2
    return (float(np.quantile(sims, a)), float(np.quantile(sims, 1 - a)))


def max_drawdown(profits: Sequence[float]) -> float:
    eq = np.cumsum(np.asarray(profits, dtype=float))
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    return float(np.max(peak - eq))


def max_losing_streak(results: Sequence[str]) -> int:
    best = cur = 0
    for r in results:
        if r == 'loss':
            cur += 1
            best = max(best, cur)
        elif r == 'win':
            cur = 0
    return best


def betting_summary(bets: List[Dict], level=0.95, seed=12345) -> Dict:
    """bets: [{'result': 'win|loss|push', 'price': 小數賠率, 'stake': 1.0, 'ev': 可選, 'clv': 可選}]，依時間排序。"""
    n = len(bets)
    if n == 0:
        return {'n': 0, 'warning': '沒有任何下注'}
    res = [b['result'] for b in bets]
    stakes = np.array([b.get('stake', 1.0) for b in bets], dtype=float)
    profits = np.array([bet_profit(b['result'], b['price'], b.get('stake', 1.0)) for b in bets])
    wins, losses, pushes = res.count('win'), res.count('loss'), res.count('push')
    decided = wins + losses
    per_unit = profits / stakes
    roi = float(profits.sum() / stakes.sum())
    lo, hi = bootstrap_ci(per_unit, level=level, seed=seed)
    # 單尾 p 值：bootstrap 平移到 ROI=0 的虛無分佈
    rng = np.random.default_rng(seed + 1)
    centered = per_unit - per_unit.mean()
    sims = centered[rng.integers(0, n, size=(10000, n))].mean(axis=1)
    p_value = float((sims >= per_unit.mean()).mean())
    prices = np.array([b['price'] for b in bets], dtype=float)
    out = {
        'n': n, 'wins': wins, 'losses': losses, 'pushes': pushes,
        'hit_rate': wins / decided if decided else None,
        'hit_rate_ci': wilson_ci(wins, decided, level),
        'avg_price': float(prices.mean()),
        'breakeven_hit_rate': float(np.mean(1 / prices)),
        'staked': float(stakes.sum()), 'profit': float(profits.sum()),
        'roi': roi, 'roi_ci': (lo, hi), 'roi_p_value_gt0': p_value,
        'max_drawdown': max_drawdown(profits), 'max_losing_streak': max_losing_streak(res),
        'ci_level': level,
    }
    for k in ('ev', 'clv'):
        vals = [b[k] for b in bets if b.get(k) is not None]
        out[f'avg_{k}'] = float(np.mean(vals)) if vals else None
        out[f'avg_{k}_ci'] = bootstrap_ci(vals, level=level, seed=seed) if vals else (None, None)
        out[f'{k}_n'] = len(vals)
    out['warning'] = _sample_warning(n, out['roi_ci'])
    return out


def _sample_warning(n, ci):
    msgs = []
    if n < MIN_SAMPLE_WARN:
        msgs.append(f'樣本只有 {n} 筆（< {MIN_SAMPLE_WARN}），結論不可靠')
    if ci[0] is not None and ci[0] < 0 < ci[1]:
        msgs.append('ROI 信賴區間包含 0：無法排除「沒有優勢」')
    return '；'.join(msgs) or None


def brier(p: Sequence[float], y: Sequence[int]) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p: Sequence[float], y: Sequence[int], eps=1e-12) -> float:
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def paired_diff(model_loss: Sequence[float], base_loss: Sequence[float], level=0.95, seed=12345) -> Dict:
    """同一批比賽上，模型損失 − 基準損失（逐場）。負值 = 模型較好。信賴區間不含 0 才算有差。"""
    d = np.asarray(model_loss, float) - np.asarray(base_loss, float)
    lo, hi = bootstrap_ci(d, level=level, seed=seed)
    return {'n': int(d.size), 'mean_diff': float(d.mean()) if d.size else None, 'ci': (lo, hi),
            'model_better': bool(hi is not None and hi < 0), 'model_worse': bool(lo is not None and lo > 0)}


def per_game_brier(p, y):
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def per_game_logloss(p, y, eps=1e-12):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def calibration_bins(p: Sequence[float], y: Sequence[int], bins: int = 10, level=0.95):
    p, y = np.asarray(p, float), np.asarray(y, int)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= edges[i + 1]))
        n = int(m.sum())
        k = int(y[m].sum())
        out.append({'lo': float(edges[i]), 'hi': float(edges[i + 1]), 'n': n,
                    'mean_pred': float(p[m].mean()) if n else None,
                    'observed': k / n if n else None, 'observed_ci': wilson_ci(k, n, level)})
    return out


def by_price_bucket(bets: List[Dict], edges=(1.0, 1.5, 1.8, 2.0, 2.5, 4.0, 1e9)) -> List[Dict]:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sub = [b for b in bets if lo <= b['price'] < hi]
        s = betting_summary(sub) if sub else {'n': 0}
        s['bucket'] = (lo, hi)
        out.append(s)
    return out
