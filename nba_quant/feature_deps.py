"""
特徵依賴關係與資料可用性檢查（使用者 2026-11-20 第五輪）。

這是規則與檢查，不是特徵實作：只定義「每個特徵依賴哪些基礎欄位」，並判斷某季是否可用。
特徵實作時，每個特徵都必須在這裡登記；可用性一律由這裡判定，不可在特徵程式裡另外判斷。

規則
1. 可用性沿依賴鏈傳遞：任何特徵只要依賴鏈（含間接、含跨球季先驗）碰到不可用的基礎欄位，就不可用。
2. 不可用的基礎欄位不補值、不以 BBRef 覆蓋（2017-18 失誤）。
3. 跨球季（cross）有兩種，都可能把上一季的資料帶進本季：
   - 'prior'：以上季值當收縮先驗（F1、依賴 F1 Pace 的 F7）。
   - 'window'：近 N 場／指數加權視窗在季初往回數到上季（F2、F7 聯盟近期得分）。
   若上一季同一節點不可用，狀態為 available_prior_excluded：本季可算，但不得使用上一季不可用的比賽或數值
   （先驗退回其他可用來源；視窗跳過、不補值），實作時須記錄。
5. 模型輸入：check_model_inputs() 對整組輸入逐一檢查；未登記的特徵直接報錯，避免繞過依賴檢查。
4. 比賽範圍：F1、F2、F3、F4、F7 都是 use_team_stats（一般例行賽、盃賽各階段、盃賽冠軍戰）；
   F5 是 use_fatigue；Elo 是 use_elo（game_class.py）。範圍相同不代表欄位都可用。
"""
from __future__ import annotations

import os
from collections import Counter

from . import store

# ---- 基礎欄位：本隊 box、對手 box、比分、賽程
BOX_FIELDS = ('pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'tov')
GAME_BOX_FIELDS = ('overtimes',)        # 比賽長度（兩隊相同；Pace 換算每 48 分鐘用）
BASE = set(BOX_FIELDS) | {f'opp_{f}' for f in BOX_FIELDS} | set(GAME_BOX_FIELDS) | {'score', 'opp_score', 'game_date', 'game_result'}

# ---- 中間量（衍生欄位）
DERIVED = {
    'possessions': ('fga', 'oreb', 'tov', 'fta', 'opp_fga', 'opp_oreb', 'opp_tov', 'opp_fta'),   # 兩隊平均
    'pace': ('possessions', 'overtimes'),
    'ortg': ('pts', 'possessions'),
    'drtg': ('opp_pts', 'possessions'),
    'net_rating': ('ortg', 'drtg'),
    'margin': ('score', 'opp_score'),
    'efg_off': ('fgm', 'fg3m', 'fga'),
    'efg_def': ('opp_fgm', 'opp_fg3m', 'opp_fga'),
    'tov_rate_off': ('tov', 'fga', 'fta'),
    'tov_rate_def': ('opp_tov', 'opp_fga', 'opp_fta'),
    'orb_rate_off': ('oreb', 'opp_dreb'),
    'orb_rate_def': ('opp_oreb', 'dreb'),
    'ft_rate_off': ('ftm', 'fga'),
    'ft_rate_def': ('opp_ftm', 'opp_fga'),
    'total_points': ('score', 'opp_score'),
}

# ---- 特徵（family, 依賴, 跨球季方式：None / 'prior' / 'window'）
FEATURES = {
    'F1.ortg': ('F1', ('ortg',), 'prior'),
    'F1.drtg': ('F1', ('drtg',), 'prior'),
    'F1.net_rating': ('F1', ('net_rating',), 'prior'),
    'F1.pace': ('F1', ('pace',), 'prior'),
    'F2.ewm_net_rating': ('F2', ('net_rating',), 'window'),
    'F2.last5_net_rating': ('F2', ('net_rating',), 'window'),
    'F2.last10_net_rating': ('F2', ('net_rating',), 'window'),
    'F3.efg_off': ('F3', ('efg_off',), None),
    'F3.efg_def': ('F3', ('efg_def',), None),
    'F3.tov_rate_off': ('F3', ('tov_rate_off',), None),
    'F3.tov_rate_def': ('F3', ('tov_rate_def',), None),
    'F3.orb_rate_off': ('F3', ('orb_rate_off',), None),
    'F3.orb_rate_def': ('F3', ('orb_rate_def',), None),
    'F3.ft_rate_off': ('F3', ('ft_rate_off',), None),
    'F3.ft_rate_def': ('F3', ('ft_rate_def',), None),
    'F4.srs_margin': ('F4', ('margin',), None),             # 以比分差解 ridge SRS
    'F4.srs_net_rating': ('F4', ('net_rating',), None),     # 以每百回合淨值解（依賴回合數）
    'F5.rest_days': ('F5', ('game_date',), None),
    'F5.back_to_back': ('F5', ('game_date',), None),
    'F5.three_in_four': ('F5', ('game_date',), None),
    'F5.road_trip_length': ('F5', ('game_date',), None),
    'F5.games_last_7_days': ('F5', ('game_date',), None),
    'F7.pace_sum': ('F7', ('pace',), 'prior'),                 # 與 Pace 相關：依賴回合數
    'F7.league_recent_points': ('F7', ('total_points',), 'window'),   # 只用比分，與 Pace 無關
    'ELO.rating': ('ELO', ('game_result',), None),
}

FAMILY_SCOPE = {'F1': 'use_team_stats', 'F2': 'use_team_stats', 'F3': 'use_team_stats', 'F4': 'use_team_stats',
                'F7': 'use_team_stats', 'F5': 'use_fatigue', 'ELO': 'use_elo'}

# ---- 不可用的基礎欄位（整季）：使用者決策
SEASON_UNAVAILABLE = {2018: {'tov', 'opp_tov'}}       # 2017-18 失誤整季不可用（含 BBRef 補值場次；不補值、不覆蓋）


def closure(node, _stack=()):
    """回傳 node 依賴的所有基礎欄位（遞迴）。偵測循環。"""
    if node in _stack:
        raise ValueError(f'循環依賴：{" -> ".join(_stack + (node,))}')
    if node in BASE:
        return {node}
    if node in DERIVED:
        deps = DERIVED[node]
    elif node in FEATURES:
        deps = FEATURES[node][1]
    else:
        raise KeyError(f'未登記的節點：{node}')
    out = set()
    for d in deps:
        out |= closure(d, _stack + (node,))
    return out


def path_to(node, base, _path=()):
    """回傳一條從 node 到 base 的依賴路徑（給報告說明「為什麼不可用」）。"""
    _path = _path + (node,)
    if node == base:
        return _path
    deps = DERIVED.get(node) or (FEATURES[node][1] if node in FEATURES else ())
    for d in deps:
        p = path_to(d, base, _path)
        if p:
            return p
    return None


def unavailable_bases(season):
    return set(SEASON_UNAVAILABLE.get(season, set()))


def availability(feature, season):
    """回傳 (status, reason)。status: available / unavailable / available_prior_excluded。"""
    _, deps, cross = FEATURES[feature]
    bad = closure(feature) & unavailable_bases(season)
    if bad:
        b = sorted(bad)[0]
        return 'unavailable', f"{season}: {' -> '.join(path_to(feature, b))} 不可用"
    if cross:
        prev_bad = closure(feature) & unavailable_bases(season - 1)
        if prev_bad:
            b = sorted(prev_bad)[0]
            how = ('收縮先驗不得使用該季的值，只能退回其他可用來源' if cross == 'prior'
                   else '季初視窗不得往回數到該季的比賽（跳過、不補值）')
            chain = ' -> '.join(path_to(feature, b))
            return 'available_prior_excluded', f'上季 {season - 1} 的 {chain} 不可用：{how}，並記錄'
    return 'available', ''


def check_model_inputs(features, season):
    """模型輸入清單檢查：回傳 {feature: (status, reason)}；未登記的特徵直接 KeyError。
    模型只能使用 available；available_prior_excluded 須附排除紀錄才可使用；unavailable 一律不得進模型。"""
    return {f: availability(f, season) for f in features}


def season_matrix(seasons):
    return {s: {f: availability(f, s) for f in sorted(FEATURES)} for s in seasons}


def box_field_check(season, scope_games, boxes, tov_rule):
    """資料層檢查：範圍內每筆球隊 box 的每個欄位是否存在且可用。回傳 {field: (usable, total)}。"""
    out = Counter()
    tot = 0
    for g in scope_games:
        for t in (g['home'], g['away']):
            b = boxes.get((g['game_id'], t))
            tot += 1
            if not b:
                continue
            for f in BOX_FIELDS:
                if b.get(f) is None:
                    continue
                if f == 'tov' and not tov_rule(b, g):
                    continue
                if f in SEASON_UNAVAILABLE.get(season, set()):
                    continue
                out[f] += 1
    return {f: (out[f], tot) for f in BOX_FIELDS}


def report(seasons=None):
    """產生 docs/reports/model_data/v1/feature_availability.md（依賴鏈、每季可用性、資料層檢查）。"""
    import csv
    from .model_data_stats import LOCKED_SEASONS, RAW, PLAYIN, tov_definition
    cls = {r['game_id']: r for r in csv.DictReader(open(os.path.join('data', 'reference', 'game_classification.csv'),
                                                       encoding='utf-8'))}
    if seasons is None:
        seasons = sorted(int(x) for x in os.listdir(RAW) if x.isdigit() and int(x) not in LOCKED_SEASONS)
    L = ['# 特徵依賴關係與資料可用性（v1）', '',
         '由 `nba_quant/feature_deps.py` 產生。可用性沿依賴鏈傳遞（含跨球季收縮先驗）；不可用的基礎欄位不補值、不以 BBRef 覆蓋。',
         '2024-25 只做資料品質檢查；2025-26 不讀取。', '', '## 1. 依賴鏈', '', '| 特徵 | 範圍欄位 | 直接依賴 | 基礎欄位（遞迴）| 跨球季 |',
         '|---|---|---|---|---|']
    for f in sorted(FEATURES):
        fam, deps, cross = FEATURES[f]
        L.append(f"| {f} | {FAMILY_SCOPE[fam]} | {', '.join(deps)} | {', '.join(sorted(closure(f)))} | {cross or ''} |")
    L += ['', '## 2. 每季可用性（不是 available 的才列出）', '', '| 球季 | 特徵 | 狀態 | 原因（依賴路徑）|', '|---|---|---|---|']
    for s, m in season_matrix(seasons).items():
        for f, (st, why) in m.items():
            if st != 'available':
                L.append(f'| {s - 1}-{str(s)[2:]} | {f} | {st} | {why} |')
    L += ['', '## 3. 資料層檢查（F1～F4、F7 範圍 `use_team_stats` 內的球隊 box）', '',
          '| 球季 | 球隊 box | ' + ' | '.join(BOX_FIELDS) + ' |', '|---|---|' + '---|' * len(BOX_FIELDS)]
    for s in seasons:
        games = []
        for p in (os.path.join(RAW, str(s), 'games.jsonl.gz'), os.path.join(PLAYIN, str(s), 'games.jsonl.gz')):
            if os.path.exists(p):
                games += [g for g in store.read_jsonl_gz(p) if g['status'] == 'final' and cls[g['game_id']]['use_team_stats'] == 'True']
        boxes = {}
        for p in (os.path.join(RAW, str(s), 'teambox.jsonl.gz'),):
            for b in store.read_jsonl_gz(p):
                boxes[(b['game_id'], b['team'])] = b
        rule = lambda b, g, s=s: tov_definition(b, cls[g['game_id']]['game_type'], s)[1]
        chk = box_field_check(s, sorted(games, key=lambda g: (g['start_utc'], g['game_id'])), boxes, rule)
        tot = next(iter(chk.values()))[1]
        L.append(f'| {s - 1}-{str(s)[2:]} | {tot} | ' + ' | '.join(
            ('全部' if a == b else f'**{a}/{b}**') for a, b in (chk[f] for f in BOX_FIELDS)) + ' |')
    out = os.path.join('docs', 'reports', 'model_data', 'v1', 'feature_availability.md')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    return out


if __name__ == '__main__':
    print(report())
