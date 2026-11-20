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
counts_for_standings：是否計入球隊官方例行賽勝敗紀錄。戰績類計算（勝率、主客場戰績、連勝）一律用這個欄位，
不可用 season_type == 2 代替。
"""
from __future__ import annotations

import csv
import os

from . import store

RAW = os.path.join('data', 'raw', 'espn')
PLAYIN = os.path.join('data', 'raw', 'espn_playin')
OUT = os.path.join('data', 'reference', 'game_classification.csv')
FIELDS = ('game_id', 'season', 'start_utc', 'away', 'home', 'status', 'espn_season_type', 'game_type',
          'counts_for_standings', 'source_file', 'basis')

CUP_STAGES = (('Championship', 'CUP_FINAL'), ('Semifinals', 'CUP_SEMIFINAL'),
              ('Quarterfinals', 'CUP_QUARTERFINAL'), ('Group Play', 'CUP_GROUP'))
COUNTS = {'REGULAR_SEASON': True, 'CUP_GROUP': True, 'CUP_QUARTERFINAL': True, 'CUP_SEMIFINAL': True,
          'CUP_FINAL': False, 'PLAY_IN': False, 'POSTSEASON': False}


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
