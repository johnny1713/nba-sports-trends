"""
模型資料統計 v1（使用者 2026-11-20 第四輪：quality.py 方案 A）。

    PYTHONPATH=. python -m nba_quant.model_data_stats

- **不修改、不呼叫** nba_quant/quality.py（凍結的盤口品質 v1），不讀寫任何既有盤口品質報告。
- 依 `data/reference/game_classification.csv` 的 `game_type` 與各用途欄位計算場數與資料覆蓋率：
  例行賽戰績（counts_for_standings）、F1/F2（use_team_stats）、F5 賽程疲勞（use_fatigue）、Elo（use_elo）、
  訓練樣本（train_sample）、評估分組（eval_group）。
- 失誤定義（tov_definition）逐筆標記；需要總失誤的特徵只能用 `tov_usable` = True 的球隊 box。
- 鎖定測試期：2025-26（LOCKED_SEASONS）不讀取；2024-25（DATA_QUALITY_ONLY）只輸出資料品質統計並標記。
- 輸出（新路徑，與盤口品質報告分開）：
    data/audit/model_data/v1/summary.json
    docs/reports/model_data/v1/README.md
- 輸出順序固定：所有清單都以 (球季, 主鍵, 次要鍵) 排序，相同輸入重跑位元組相同。

這是資料統計，不是模型：不計算任何特徵值、不做預測、不評估。
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict

from . import store

VERSION = 'v1'
RAW = os.path.join('data', 'raw', 'espn')
PLAYIN = os.path.join('data', 'raw', 'espn_playin')
CLASSIFICATION = os.path.join('data', 'reference', 'game_classification.csv')
OUT_JSON = os.path.join('data', 'audit', 'model_data', VERSION, 'summary.json')
OUT_MD = os.path.join('docs', 'reports', 'model_data', VERSION, 'README.md')
LOCKED_SEASONS = (2026,)           # 2025-26：模型凍結前完全鎖定，不讀
DATA_QUALITY_ONLY = (2025,)        # 2024-25：只做資料品質統計；不得用於特徵選擇、調參、選模、評估、回測
USES = ('counts_for_standings', 'use_team_stats', 'use_fatigue', 'use_elo', 'train_sample')
EXPECTED_TEAM_GAMES = {2020: (63, 75), 2021: (72, 72)}     # 縮水球季；其他季 82
BOOL = {'True': True, 'False': False}


def load_classification(path=CLASSIFICATION):
    rows = {}
    for r in csv.DictReader(open(path, encoding='utf-8')):
        for k in USES:
            r[k] = BOOL[r[k]]
        r['season'] = int(r['season'])
        rows[r['game_id']] = r
    return rows


def tov_definition(box, game_type, season):
    """每筆球隊 box 的失誤定義。回傳 (definition, usable_for_total_turnover_features)。"""
    src = str(box.get('source', ''))
    if season == 2018:
        # 使用者決策：2017-18 整季依賴失誤的特徵停用（ESPN 欄位錯位）；BBRef 補值場次也一併不用，不以 BBRef 覆蓋
        return ('bbref_team_total_season_disabled' if src.startswith('bbref') else 'espn_2017_18_field_shift'), False
    if src.startswith('bbref'):
        if game_type == 'PLAY_IN':
            # 2020-21 附加賽：BBRef 球隊合計 = 球員加總，不含全隊失誤（play_in.md 第 2 節）
            return 'bbref_player_only', False
        return 'bbref_team_total', True
    return 'espn_total_incl_team', True


def _boxes(season):
    out = []
    p = os.path.join(RAW, str(season), 'teambox.jsonl.gz')
    if os.path.exists(p):
        out += list(store.read_jsonl_gz(p))
    for name in ('teambox.jsonl.gz', 'teambox_bbref.jsonl.gz'):
        p = os.path.join(PLAYIN, str(season), name)
        if os.path.exists(p):
            out += list(store.read_jsonl_gz(p))
    return out


def _games(season):
    out = []
    for p in (os.path.join(RAW, str(season), 'games.jsonl.gz'), os.path.join(PLAYIN, str(season), 'games.jsonl.gz')):
        if os.path.exists(p):
            out += list(store.read_jsonl_gz(p))
    return out


def season_stats(season, cls):
    if season in LOCKED_SEASONS:
        raise PermissionError(f'{season} 為鎖定測試期，模型凍結前不讀取')
    games = {g['game_id']: g for g in _games(season) if g['status'] == 'final'}
    missing_cls = sorted(gid for gid in games if gid not in cls)
    if missing_cls:
        raise ValueError(f'{season}: {len(missing_cls)} 場不在分類表中，例如 {missing_cls[:3]}')
    boxes = defaultdict(dict)
    for b in _boxes(season):
        if b['game_id'] in games:
            boxes[b['game_id']][b['team']] = b
    st = {'season': season, 'locked_status': 'data_quality_only' if season in DATA_QUALITY_ONLY else 'open',
          'final_games_by_type': dict(sorted(Counter(cls[g]['game_type'] for g in games).items())),
          'uses': {}}
    for use in USES:
        gs = sorted((g for g in games.values() if cls[g['game_id']][use]), key=lambda g: (g['start_utc'], g['game_id']))
        per_team = Counter()
        both = tov_ok = 0
        tov_defs = Counter()
        src = Counter()
        for g in gs:
            per_team[g['home']] += 1
            per_team[g['away']] += 1
            bx = boxes.get(g['game_id'], {})
            if g['home'] in bx and g['away'] in bx:
                both += 1
            for t in (g['home'], g['away']):
                if t in bx:
                    d, ok = tov_definition(bx[t], cls[g['game_id']]['game_type'], season)
                    tov_defs[d] += 1
                    tov_ok += ok
                    src['bbref' if str(bx[t].get('source', '')).startswith('bbref') else 'espn'] += 1
        tc = sorted(per_team.values())
        same_start = sum(n - 1 for n in Counter(g['start_utc'] for g in gs).values() if n > 1)
        st['uses'][use] = {
            'games': len(gs), 'game_types': dict(sorted(Counter(cls[g['game_id']]['game_type'] for g in gs).items())),
            'teams': len(per_team), 'team_games_min': tc[0] if tc else None, 'team_games_max': tc[-1] if tc else None,
            'games_with_both_boxes': both, 'box_coverage': round(both / len(gs), 4) if gs else None,
            'team_boxes_by_source': dict(sorted(src.items())),
            'tov_definition': dict(sorted(tov_defs.items())), 'team_boxes_tov_usable': tov_ok,
            'games_sharing_start_time': same_start}
    lo, hi = EXPECTED_TEAM_GAMES.get(season, (82, 82))
    s = st['uses']['counts_for_standings']
    st['standings_check'] = {'expected_team_games': [lo, hi], 'ok': s['teams'] == 30 and lo <= s['team_games_min']
                             and s['team_games_max'] <= hi}
    st['eval_groups'] = dict(sorted(Counter(cls[g]['eval_group'] for g in games).items()))
    return st


def compute(seasons=None, cls=None):
    cls = cls if cls is not None else load_classification()
    if seasons is None:
        seasons = sorted(int(x) for x in os.listdir(RAW) if x.isdigit() and int(x) not in LOCKED_SEASONS)
    return {'version': VERSION, 'locked_seasons': list(LOCKED_SEASONS), 'data_quality_only': list(DATA_QUALITY_ONLY),
            'seasons': [season_stats(s, cls) for s in sorted(seasons)]}


def label(s):
    return f'{s - 1}-{str(s)[2:]}'


NAMES = {'counts_for_standings': '例行賽戰績', 'use_team_stats': 'F1/F2', 'use_fatigue': 'F5 疲勞', 'use_elo': 'Elo',
         'train_sample': '訓練樣本'}


def render(res):
    L = [f'# 模型資料統計 {VERSION}', '',
         '依 `data/reference/game_classification.csv` 計算。**不使用、不修改** `quality.py` 與盤口品質報告（凍結的盤口品質 v1）。',
         '2024-25 標記為 data_quality_only：只做資料品質統計，不得用於特徵選擇、調參、選模、評估或回測。2025-26 不讀取。', '',
         '## 1. 各用途的場數（完賽）', '',
         '| 球季 | 狀態 | ' + ' | '.join(NAMES[u] for u in USES) + ' | 戰績每隊場數 | 戰績檢查 |',
         '|---|---|' + '---|' * len(USES) + '---|---|']
    for st in res['seasons']:
        u = st['uses']
        s = u['counts_for_standings']
        L.append(f"| {label(st['season'])} | {st['locked_status']} | " + ' | '.join(str(u[k]['games']) for k in USES)
                 + f" | {s['team_games_min']}～{s['team_games_max']} | {'OK' if st['standings_check']['ok'] else '異常'} |")
    L += ['', '## 2. box score 覆蓋率與失誤可用性', '',
          '| 球季 | 用途 | 場數 | 兩隊 box 完整 | 覆蓋率 | 失誤可用（球隊 box）| 失誤定義 |', '|---|---|---|---|---|---|---|']
    for st in res['seasons']:
        for k in ('use_team_stats', 'use_fatigue', 'use_elo'):
            u = st['uses'][k]
            L.append(f"| {label(st['season'])} | {NAMES[k]} | {u['games']} | {u['games_with_both_boxes']} | "
                     f"{u['box_coverage']:.2%} | {u['team_boxes_tov_usable']} | "
                     f"{', '.join(f'{a} {b}' for a, b in u['tov_definition'].items())} |")
    L += ['', '## 3. 各用途包含的比賽類型', '', '| 球季 | 用途 | game_type |', '|---|---|---|']
    for st in res['seasons']:
        for k in USES:
            L.append(f"| {label(st['season'])} | {NAMES[k]} | "
                     f"{', '.join(f'{a} {b}' for a, b in st['uses'][k]['game_types'].items())} |")
    return '\n'.join(L) + '\n'


def main():
    res = compute()
    store.write_json(OUT_JSON, res)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, 'w', encoding='utf-8') as fh:
        fh.write(render(res))
    print(OUT_JSON, OUT_MD)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
