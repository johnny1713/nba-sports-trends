"""
附加賽（Play-In）資料品質報告（唯讀）。

    PYTHONPATH=. python tools/playin_report.py
讀 data/raw/espn_playin/<季>/，輸出 docs/reports/box_quality/v1/play_in.md。
檢查：場次數、來源與抓取時間、原始檔 sha256、兩隊 box、得分恆等式、得分 = ESPN 計分板、
ESPN vs BBRef 逐欄位、失誤欄位定義（ESPN 球員／全隊／合計 vs BBRef 球隊合計／球員加總）、
game_type 在分類表中一致為 PLAY_IN。
"""
import csv
import gzip
import hashlib
import json
import os
from collections import Counter

from nba_quant import store
from nba_quant.source_audit import bbref_fields, espn_raw_fields

ROOT = os.path.join('data', 'raw', 'espn_playin')
OUT = os.path.join('docs', 'reports', 'box_quality', 'v1', 'play_in.md')
FIELDS = ('pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'tov')


def sha_ok(d, prov):
    bad = []
    for f, m in prov.get('files', {}).items():
        b = gzip.open(os.path.join(d, f)).read()
        if hashlib.sha256(b).hexdigest() != m['sha256_uncompressed']:
            bad.append(f)
    return len(prov.get('files', {})), bad


def label(s):
    return f'{s - 1}-{str(s)[2:]}'


def main():
    gc = {r['game_id']: r for r in csv.DictReader(open(os.path.join('data', 'reference', 'game_classification.csv'), encoding='utf-8'))}
    L = ['# 附加賽（Play-In）資料品質報告', '',
         '唯讀報告。附加賽獨立存放在 `data/raw/espn_playin/<季>/`，不混入 `data/raw/espn/`，也不進例行賽訓練樣本（`train_sample` = False）。'
         '2025-26 為鎖定測試期，不抓取。', '',
         '## 1. 總覽', '',
         '| 球季 | 預期 | 找到 | box 來源 | 兩隊 box 完整 | 得分恆等式 | 得分 = ESPN 計分板 | ESPN vs BBRef 10 欄位全一致 | 只有失誤不一致 | 原始檔 sha256 | 分類表 game_type |',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    details, tov_rows = [], []
    for s in sorted(int(x) for x in os.listdir(ROOT)):
        d = os.path.join(ROOT, str(s))
        ver = store.read_json(os.path.join(d, 'verification.json'))
        prov = store.read_json(os.path.join(d, 'provenance.json'))
        vb = store.read_json(os.path.join(d, 'verification_bbref.json'), None)
        pb = store.read_json(os.path.join(d, 'provenance_bbref.json'), None)
        games = list(store.read_jsonl_gz(os.path.join(d, 'games.jsonl.gz')))
        n_files, bad = sha_ok(d, prov)
        if pb:
            n2, bad2 = sha_ok(d, pb)
            n_files, bad = n_files + n2, bad + bad2
        both = ident = score = allmatch = tov_only = 0
        sources = Counter()
        espn_checks = {c['game_id']: c for c in ver['games'] if 'teams' in c}
        bb_checks = {c['game_id']: c for c in (vb or {}).get('games', [])}
        for g in games:
            gid = g['game_id']
            if gid in espn_checks:
                c = espn_checks[gid]
                sources['espn'] += 1
                t = c['teams'].values()
                both += c['both_teams_present']
                ident += all(x['pts_identity_ok'] for x in t)
                score += all(x['pts_eq_scoreboard'] for x in t)
                diffs = {k for x in t for k, (a, b) in x['espn_vs_bbref'].items() if a != b}
                allmatch += not diffs
                tov_only += diffs == {'tov'}
                # 失誤定義
                sm = json.loads(gzip.open(os.path.join(d, 'raw', f'espn_summary_{gid}.json.gz')).read())
                ts, pto, _, _ = espn_raw_fields(sm)
                html = gzip.open(os.path.join(d, 'raw', f'bbref_box_{gid}.html.gz')).read().decode('utf-8', 'replace')
                bt, bp, _ = bbref_fields(html, g)
                for tid in ts:
                    tov_rows.append((s, gid, tid, int(ts[tid]['turnovers']), int(ts[tid]['teamTurnovers']),
                                     int(ts[tid]['totalTurnovers']), pto[tid], bt[tid]['tov'], bp[tid]))
            elif gid in bb_checks:
                c = bb_checks[gid]
                sources['bbref（ESPN 無資料）'] += 1
                t = c['teams'].values()
                both += c['both_teams_present']
                ident += all(x['pts_identity_ok'] for x in t)
                score += all(x['pts_eq_espn_scoreboard'] for x in t)
            details.append((s, g, gc.get(gid, {}).get('game_type'),
                            'espn' if gid in espn_checks else ('bbref' if gid in bb_checks else '無')))
        types = Counter(gc.get(g['game_id'], {}).get('game_type') for g in games)
        n = len(games)
        L.append(f"| {label(s)} | {ver.get('expected_games', 1)} | {n} | {', '.join(f'{k} {v}' for k, v in sources.items()) or '—'} | "
                 f"{both}/{n} | {ident}/{n} | {score}/{n} | {allmatch if sources.get('espn') else '不適用'}"
                 f"{'/' + str(sources['espn']) if sources.get('espn') else ''} | "
                 f"{tov_only if sources.get('espn') else '—'} | {n_files - len(bad)}/{n_files} 相符 | "
                 f"{', '.join(f'{k} {v}' for k, v in types.items())} |")
    L += ['', '## 2. 失誤欄位定義（ESPN 有 box score 的場次）', '',
          '| 球季 | 球隊紀錄 | ESPN total = 球員 + 全隊 | ESPN 球員加總 = BBRef 球員加總 | BBRef 球隊合計 = 球員加總（不含全隊失誤）| ESPN total = BBRef 球隊合計 |',
          '|---|---|---|---|---|---|']
    by = {}
    for r in tov_rows:
        by.setdefault(r[0], []).append(r)
    for s, rows in sorted(by.items()):
        n = len(rows)
        L.append(f"| {label(s)} | {n} | {sum(r[5] == r[3] + r[4] for r in rows)}/{n} | {sum(r[6] == r[8] for r in rows)}/{n} | "
                 f"{sum(r[7] == r[8] for r in rows)}/{n} | {sum(r[5] == r[7] for r in rows)}/{n} |")
    L += ['', '判讀：',
          '- ESPN 內部一致（total = 球員 + 全隊）且球員失誤與 BBRef 100% 相同；ESPN 的定義與正式回補資料相同（`totalTurnovers`）。',
          '- 2021-22～2023-24 的 BBRef 附加賽頁面，球隊合計**不含全隊失誤**（36/36 筆 = 球員加總），所以只要該隊有全隊失誤，ESPN 就比 BBRef 多。'
          '這是 BBRef 頁面的定義差異，不是 ESPN 錯誤；ESPN 球員加總與 BBRef 一致可佐證。',
          '- 2024-25 的 BBRef 頁面含全隊失誤，與 ESPN 12/12 相同。2019-20 那場兩隊全隊失誤都是 0，無法判斷 BBRef 當時的定義。',
          '- **2020-21 只有 BBRef**（ESPN 球隊統計空白、球員數字全 0）。BBRef 球隊合計 12/12 = 球員加總，**不含全隊失誤**，'
          '與正式資料的失誤定義不同，且沒有來源可以補上。使用該季附加賽失誤時須標註此限制。']
    L += ['', '## 3. 逐場', '', '| 球季 | Game ID | 開賽 UTC | 對戰 | 比分 | ESPN 備註 | game_type | box 來源 |', '|---|---|---|---|---|---|---|---|']
    for s, g, gt, src in details:
        L.append(f"| {label(s)} | {g['game_id']} | {g['start_utc']} | {g['away_abbr']} @ {g['home_abbr']} | "
                 f"{g['away_pts']}–{g['home_pts']} | {' '.join(g.get('notes') or [])} | {gt} | {src} |")
    with open(OUT, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print(OUT)


if __name__ == '__main__':
    main()
