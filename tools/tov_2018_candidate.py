"""
2017-18 失誤：high-agreement candidate 的不一致紀錄明細（唯讀；不產生 derived 修正版）。

    PYTHONPATH=. python tools/tov_2018_candidate.py
輸出 docs/reports/box_quality/v1/tov_2018_candidate.md
候選公式（僅標記，未核准）：ESPN 球員 TO 加總 + ESPN 球隊統計欄位 `turnovers`
"""
import os

from nba_quant import store

SRC = os.path.join('data', 'audit', 'source_compare', '2018', 'compare.jsonl.gz')
OUT = os.path.join('docs', 'reports', 'box_quality', 'v1', 'tov_2018_candidate.md')


def rows():
    out, n = [], 0
    for r in store.read_jsonl_gz(SRC):
        if not r.get('in_compare_sample'):
            continue
        for t in (r['home'], r['away']):
            ts, bb = r['espn_team_fields'][t], r['bbref_team_totals'][t]
            ps, bps = r['espn_player_to_sum'][t], r['bbref_player_tov_sum'][t]
            n += 1
            cand = ps + int(ts['turnovers'])
            if cand != bb['tov']:
                out.append({'game_id': r['game_id'], 'date_utc': r['start_utc'][:10],
                            'matchup': f"{r['away_abbr']} @ {r['home_abbr']}", 'team_id': t,
                            'team': r['home_abbr'] if t == r['home'] else r['away_abbr'],
                            'espn_turnovers': int(ts['turnovers']), 'espn_teamTurnovers': int(ts['teamTurnovers']),
                            'espn_totalTurnovers': int(ts['totalTurnovers']), 'espn_player_to_sum': ps,
                            'candidate': cand, 'bbref_team_tov': bb['tov'], 'bbref_player_tov_sum': bps,
                            'bbref_team_component': bb['tov'] - bps, 'diff': cand - bb['tov'],
                            'where': '球員層級' if ps != bps else '全隊失誤（非球員）部分'})
    return out, n


def main():
    mm, n = rows()
    L = ['# 2017-18 失誤：high-agreement candidate 的不一致紀錄', '',
         '**狀態：high-agreement candidate（未核准）。不產生 derived 修正版；該季所有依賴失誤的特徵停用；不以 BBRef 整季覆蓋 ESPN。**', '',
         '候選公式：ESPN 球員 TO 加總 + ESPN 球隊統計欄位 `turnovers`（2017-18 該欄實際放的是全隊失誤）。', '',
         f'比對範圍：2017-18 全季 ESPN 原生例行賽 1067 場、{n} 筆球隊紀錄（**全季逐場比對**，非抽樣）。'
         f'一致 {n - len(mm)} / {n}，不一致 {len(mm)} 筆。', '',
         '| Game ID | 日期 (UTC) | 對戰 | 球隊 | ESPN turnovers | ESPN teamTurnovers | ESPN totalTurnovers | ESPN 球員 TO 加總 | '
         '候選值 | BBRef 球隊合計 | BBRef 球員加總 | BBRef 全隊失誤 | 候選 − BBRef | 差異所在 |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for m in mm:
        L.append(f"| {m['game_id']} | {m['date_utc']} | {m['matchup']} | {m['team']} ({m['team_id']}) | {m['espn_turnovers']} | "
                 f"{m['espn_teamTurnovers']} | {m['espn_totalTurnovers']} | {m['espn_player_to_sum']} | {m['candidate']} | "
                 f"{m['bbref_team_tov']} | {m['bbref_player_tov_sum']} | {m['bbref_team_component']} | {m['diff']:+d} | {m['where']} |")
    L += ['', '「差異所在」：ESPN 球員加總 ≠ BBRef 球員加總時為「球員層級」，否則為「全隊失誤（非球員）部分」。',
          '兩個來源哪一邊正確無法從這兩份資料判斷（沒有第三個獨立來源），因此不做任何取捨。']
    with open(OUT, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print(OUT, len(mm), n)


if __name__ == '__main__':
    main()
