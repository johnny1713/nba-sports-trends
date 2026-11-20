"""
比賽分類表（使用者 2026-11-20 決策）：以獨立欄位標記資料用途，不只靠 ESPN season_type（2 = 例行賽）判斷。

    PYTHONPATH=. python -m nba_quant.game_class
輸出 data/reference/game_classification.csv（不修改 games.jsonl.gz）。

game_type：
    REGULAR_SEASON     一般例行賽
    CUP_GROUP          季中錦標賽／NBA Cup 小組賽（計入例行賽戰績）
    CUP_QUARTERFINAL   淘汰賽八強（計入例行賽戰績）
    CUP_SEMIFINAL      淘汰賽四強（計入例行賽戰績）
    CUP_FINAL          冠軍戰（**不計入**例行賽戰績；ESPN 仍歸類為 season_type 2）
    PLAY_IN            附加賽（不計入例行賽戰績；不混入例行賽訓練資料）
    POSTSEASON         季後賽
counts_for_standings：**只**表示是否計入球隊官方例行賽勝敗紀錄（使用者 2026-11-20 第三輪）。
戰績類計算（勝率、主客場戰績、連勝、排名）用這個欄位；**不可**拿它決定其他特徵或樣本是否使用該場。
其他用途各自有獨立欄位（USES）：
    use_team_stats F1 球季累計效率、F2 近期狀態：一般例行賽（含盃賽小組賽／八強／四強）與盃賽冠軍戰；
                   不含 PLAY_IN、POSTSEASON（使用者 2026-11-20 第四輪）
    use_fatigue    F5 賽程疲勞（休息天數、背靠背、四天三賽）：所有實際出賽的比賽
    use_elo        Elo 歷史更新：所有比賽，依開賽時間順序；預測只能用開打前已知的評分
    train_sample   第一版模型訓練樣本：例行賽（含盃賽各階段，含冠軍戰）；不含 PLAY_IN、POSTSEASON
    eval_group     評估分組：regular / play_in / postseason（季後賽為獨立評估資料）
Elo 的歷史更新與訓練樣本分開：Elo 納入季後賽，不代表季後賽進入訓練樣本。
"""
from __future__ import annotations

import csv
import os

from . import store

RAW = os.path.join('data', 'raw', 'espn')
PLAYIN = os.path.join('data', 'raw', 'espn_playin')
OUT = os.path.join('data', 'reference', 'game_classification.csv')
FIELDS = ('game_id', 'season', 'start_utc', 'away', 'home', 'status', 'espn_season_type', 'game_type',
          'counts_for_standings', 'use_team_stats', 'use_fatigue', 'use_elo', 'train_sample', 'eval_group',
          'source_file', 'basis')

CUP_STAGES = (('Championship', 'CUP_FINAL'), ('Semifinals', 'CUP_SEMIFINAL'),
              ('Quarterfinals', 'CUP_QUARTERFINAL'), ('Group Play', 'CUP_GROUP'))
COUNTS = {'REGULAR_SEASON': True, 'CUP_GROUP': True, 'CUP_QUARTERFINAL': True, 'CUP_SEMIFINAL': True,
          'CUP_FINAL': False, 'PLAY_IN': False, 'POSTSEASON': False}
_REG = {'use_team_stats': True, 'use_fatigue': True, 'use_elo': True, 'train_sample': True, 'eval_group': 'regular'}
USES = {'REGULAR_SEASON': _REG, 'CUP_GROUP': _REG, 'CUP_QUARTERFINAL': _REG, 'CUP_SEMIFINAL': _REG,
        'CUP_FINAL': _REG,
        'PLAY_IN': {'use_team_stats': False, 'use_fatigue': True, 'use_elo': True, 'train_sample': False, 'eval_group': 'play_in'},
        'POSTSEASON': {'use_team_stats': False, 'use_fatigue': True, 'use_elo': True, 'train_sample': False,
                       'eval_group': 'postseason'}}


def uses(game_type):
    """各用途的納入規則（與 counts_for_standings 無關）。"""
    return dict(USES[game_type])


def classify(g):
    """回傳 (game_type, counts_for_standings, basis)。"""
    st = g['season_type']
    if st == 5:
        return 'PLAY_IN', False, 'ESPN season_type 5（附加賽）'
    if st == 3:
        return 'POSTSEASON', False, 'ESPN season_type 3'
    if st != 2:
        raise ValueError(f"{g['game_id']}: 未知的 season_type {st}")
    notes = ' '.join(g.get('notes') or [])
    if 'Tournament' in notes or 'Cup' in notes:
        for key, gt in CUP_STAGES:
            if key in notes:
                return gt, COUNTS[gt], f'ESPN 備註「{notes}」'
        raise ValueError(f"{g['game_id']}: 無法辨識的盃賽備註 {notes!r}")
    return 'REGULAR_SEASON', True, 'ESPN season_type 2，無盃賽備註'


def build():
    rows = []
    sources = [(os.path.join(RAW, s, 'games.jsonl.gz')) for s in sorted(os.listdir(RAW))]
    if os.path.isdir(PLAYIN):
        sources += [os.path.join(PLAYIN, s, 'games.jsonl.gz') for s in sorted(os.listdir(PLAYIN))]
    for p in sources:
        if not os.path.exists(p):
            continue
        for g in store.read_jsonl_gz(p):
            gt, counts, basis = classify(g)
            rows.append({'game_id': g['game_id'], 'season': g['season'], 'start_utc': g['start_utc'],
                         'away': g.get('away_abbr'), 'home': g.get('home_abbr'), 'status': g['status'],
                         'espn_season_type': g['season_type'], 'game_type': gt, 'counts_for_standings': counts,
                         **uses(gt),
                         'source_file': p.replace(os.sep, '/'), 'basis': basis})
    ids = [r['game_id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('game_id 重複：play-in 與一般資料重疊')
    rows.sort(key=lambda r: (r['start_utc'], r['game_id']))
    return rows


def main():
    rows = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    for k, v in sorted(Counter((r['season'], r['game_type'], r['counts_for_standings']) for r in rows if r['status'] == 'final').items()):
        print(k, v)
    print(OUT, len(rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
