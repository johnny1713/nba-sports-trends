"""
獨立中立場資料表（唯讀產生；不改 games.jsonl.gz 的 neutral 欄位）。

    PYTHONPATH=. python -m nba_quant.neutral_table
輸出 data/reference/neutral_sites.csv 與 docs/reports/box_quality/v1/neutral_sites.md。

判定規則（使用者 2026-11-20 指定）：
1. 2019-20 泡泡區例行賽：美東日期 2020-07-30 ~ 2020-08-14 的例行賽，全部 neutral（規則判定）。
2. 2019-20 泡泡區季後賽：另列 category=bubble_postseason、phase=postseason，不與例行賽混淆。
3. 2023-24 季中錦標賽拉斯維加斯兩場準決賽：neutral（使用者指定）。
4. ESPN 標記 neutral 且**無任何備註**的 6 場（使用者 2026-11-20 修訂）：ESPN 場館與 BBRef 場館兩個獨立來源都確認位於
   倫敦或墨西哥城才判 neutral（category = international_no_espn_note，與有備註的國際賽分開計數）；證據不足維持 unknown。
4b. 盃賽淘汰賽另外 4 場（2023-24 冠軍戰、2024-25 準決賽 ×2 與冠軍戰）：使用者 2026-11-20 核准為 neutral。
5. 其他 ESPN 標記 neutral 且有賽事備註（倫敦／墨西哥城／巴黎、盃賽淘汰賽）：
   需 ESPN 備註 + BBRef 場館兩個獨立來源一致才判 neutral；只有 ESPN 時為 unknown（BBRef 不能單獨作判定依據，
   ESPN 的旗標與備註也算同一來源）。
未列入此表的比賽 = 一般主場（沿用 ESPN home/away）。
"""
from __future__ import annotations

import csv
import os
import re
from . import asof, store

RAW = os.path.join('data', 'raw', 'espn')
AUDIT = os.path.join('data', 'audit', 'source_compare')
OUT = os.path.join('data', 'reference', 'neutral_sites.csv')
REPORT = os.path.join('docs', 'reports', 'box_quality', 'v1', 'neutral_sites.md')
BUBBLE_FROM, BUBBLE_TO = '2020-07-30', '2020-08-14'
IST_2024_SEMIS = {'401607494', '401607493'}      # 2023-12-07 IND@MIL、2023-12-08 NO@LAL（使用者指定）
NO_NOTE_UNKNOWN = {'400578409', '400578877', '400828169', '400900010', '400900012', '400900026'}   # 名稱沿用；現在依兩源規則判定
CUP_KNOCKOUT_USER = {'401607495', '401734906', '401734907', '401734908'}   # 使用者 2026-11-20 核准為 neutral
NO_NOTE_CITIES = ('London', 'Mexico City')
INTL_WORDS = ('LONDON', 'MEXICO', 'PARIS')
FIELDS = ('game_id', 'season', 'phase', 'date_et', 'start_utc', 'away', 'home', 'status', 'category',
          'espn_neutral_flag', 'espn_note', 'espn_venue_current_name', 'bbref_venue', 'evidence_sources', 'reason')


def et_date(start_utc):
    return asof.et_date(start_utc).isoformat()     # 與特徵截止日同一個定義（UTC−5）


def bbref_venue(meta_lines):
    """BBRef scorebox_meta：場館是「開賽時間」那一行的下一行。盃賽頁面第一行多了賽事名稱（'NBA Cup'），不能用固定位置。"""
    for i, x in enumerate(meta_lines):
        if re.match(r'^\d{1,2}:\d{2} [AP]M, ', x) and i + 1 < len(meta_lines):
            v = meta_lines[i + 1]
            return None if v == 'Logos' else v
    return None


def _venues(season):
    p = os.path.join(AUDIT, str(season), 'compare.jsonl.gz')
    if not os.path.exists(p):
        return {}
    out = {}
    for r in store.read_jsonl_gz(p):
        ev = r.get('espn_venue') or {}
        bm = (r.get('bbref_meta') or {}).get('raw_meta') or []
        out[r['game_id']] = (', '.join(x for x in (ev.get('name'), ev.get('city'), ev.get('state')) if x) or None,
                             bbref_venue(bm))
    return out


def classify(g, espn_venue, bbref_venue):
    """回傳 (status, category, evidence, reason) 或 None（不列入）。"""
    gid, notes = g['game_id'], ' '.join(g.get('notes') or [])
    d = et_date(g['start_utc'])
    if g['season'] == 2020 and g['season_type'] == 2 and BUBBLE_FROM <= d <= BUBBLE_TO:
        return 'neutral', 'bubble_regular', 'rule', '2019-20 泡泡區例行賽（使用者指定日期 2020-07-30~08-14）'
    if g['season'] == 2020 and g['season_type'] == 3 and d >= BUBBLE_FROM:
        return 'neutral', 'bubble_postseason', 'rule', '2019-20 泡泡區季後賽（與例行賽分開標記）'
    if gid in IST_2024_SEMIS:
        return 'neutral', 'ist_knockout', 'user_specified;espn_note', '2023-24 季中錦標賽拉斯維加斯準決賽（使用者指定）'
    if gid in CUP_KNOCKOUT_USER:
        return ('neutral', 'cup_knockout', 'user_approved;espn_note;espn_venue;bbref_venue',
                f'使用者 2026-11-20 核准；ESPN 備註「{notes}」、ESPN 場館「{espn_venue}」、BBRef 場館「{bbref_venue}」')
    if gid in NO_NOTE_UNKNOWN:
        return no_note_rule(espn_venue, bbref_venue)
    if not g.get('neutral'):
        return None
    knockout = 'Semifinal' in notes or 'Championship' in notes
    cat = 'cup_knockout' if knockout else ('international' if any(w in notes.upper() for w in INTL_WORDS) else 'espn_flag_other')
    ev = ['espn_neutral_flag', 'espn_note'] if notes else ['espn_neutral_flag']
    if bbref_venue:
        ev.append('bbref_venue')
    if notes and bbref_venue and _venue_consistent(cat, notes, bbref_venue):
        return 'neutral', cat, ';'.join(ev), f'ESPN 備註「{notes}」與 BBRef 場館「{bbref_venue}」一致'
    if notes and bbref_venue:
        return 'unknown', cat, ';'.join(ev), f'ESPN 備註「{notes}」與 BBRef 場館「{bbref_venue}」無法對應'
    return 'unknown', cat, ';'.join(ev), f'只有 ESPN（備註「{notes}」），缺第二個獨立來源' if notes else 'ESPN 旗標，無備註'


def no_note_rule(espn_venue, bbref_venue):
    """ESPN 標記中立場但無備註的 6 場（使用者 2026-11-20）：ESPN 場館與 BBRef 場館兩個獨立來源都確認位於
    倫敦或墨西哥城（同一城市）才判 neutral；任一來源缺漏或城市不同 → unknown。ESPN 旗標本身不算證據。"""
    for city in NO_NOTE_CITIES:
        if espn_venue and bbref_venue and city in espn_venue and city in bbref_venue:
            return ('neutral', 'international_no_espn_note', 'espn_venue;bbref_venue',
                    f'ESPN 場館「{espn_venue}」與 BBRef 場館「{bbref_venue}」兩個獨立來源皆位於 {city}（ESPN 無賽事備註）')
    return ('unknown', 'espn_flag_only', 'espn_neutral_flag' + (';espn_venue' if espn_venue else '') + (';bbref_venue' if bbref_venue else ''),
            f'證據不足：ESPN 場館「{espn_venue}」、BBRef 場館「{bbref_venue}」未能同時確認位於倫敦或墨西哥城；維持無法確認')


def _venue_consistent(cat, notes, venue):
    v = venue.upper()
    n = notes.upper()
    if cat == 'international':
        return any(w in n and w in v for w in INTL_WORDS) or ('MEXICO' in n and 'MÉXICO' in v)
    if cat == 'cup_knockout':
        return 'LAS VEGAS' in v
    return False


def build():
    rows = []
    for s in sorted(int(x) for x in os.listdir(RAW) if os.path.exists(os.path.join(RAW, x, 'games.jsonl.gz'))):
        venues = _venues(s)
        for g in store.read_jsonl_gz(os.path.join(RAW, str(s), 'games.jsonl.gz')):
            if g['status'] != 'final':
                continue
            ev, bv = venues.get(g['game_id'], (None, None))
            c = classify(g, ev, bv)
            if not c:
                continue
            status, cat, evid, why = c
            rows.append({'game_id': g['game_id'], 'season': s, 'phase': 'regular' if g['season_type'] == 2 else 'postseason',
                         'date_et': et_date(g['start_utc']), 'start_utc': g['start_utc'], 'away': g.get('away_abbr'),
                         'home': g.get('home_abbr'), 'status': status, 'category': cat,
                         'espn_neutral_flag': bool(g.get('neutral')), 'espn_note': ' '.join(g.get('notes') or []),
                         'espn_venue_current_name': ev or '', 'bbref_venue': bv or '', 'evidence_sources': evid,
                         'reason': why})
    rows += playin_rows()
    rows.sort(key=lambda r: (r['start_utc'], r['game_id']))
    return rows


PLAYIN = os.path.join('data', 'raw', 'espn_playin', '2020')


def playin_rows():
    """2019-20 泡泡區附加賽（獨立存放）：ESPN 場館與 BBRef 場館兩個獨立來源都在佛州 Walt Disney World 泡泡區
    （Lake Buena Vista / Bay Lake）才判 neutral；category 獨立為 bubble_play_in，不與泡泡區例行賽或季後賽合併。"""
    p = os.path.join(PLAYIN, 'games.jsonl.gz')
    if not os.path.exists(p):
        return []
    import gzip
    import json
    from .source_audit import bbref_fields, espn_raw_fields
    out = []
    for g in store.read_jsonl_gz(p):
        sm = json.loads(gzip.open(os.path.join(PLAYIN, 'raw', f"espn_summary_{g['game_id']}.json.gz")).read())
        v = espn_raw_fields(sm)[2]
        ev = ', '.join(x for x in (v.get('name'), v.get('city'), v.get('state')) if x)
        html = gzip.open(os.path.join(PLAYIN, 'raw', f"bbref_box_{g['game_id']}.html.gz")).read().decode('utf-8', 'replace')
        bv = bbref_venue(bbref_fields(html, g)[2]['raw_meta'])
        ok = bool(ev and bv and ('Lake Buena Vista' in ev or 'Bay Lake' in ev) and 'Bay Lake' in bv)
        out.append({'game_id': g['game_id'], 'season': g['season'], 'phase': 'play_in', 'date_et': et_date(g['start_utc']),
                    'start_utc': g['start_utc'], 'away': g.get('away_abbr'), 'home': g.get('home_abbr'),
                    'status': 'neutral' if ok else 'unknown', 'category': 'bubble_play_in',
                    'espn_neutral_flag': bool(g.get('neutral')), 'espn_note': ' '.join(g.get('notes') or []),
                    'espn_venue_current_name': ev, 'bbref_venue': bv or '', 'evidence_sources': 'espn_venue;bbref_venue',
                    'reason': (f'ESPN 場館「{ev}」與 BBRef 場館「{bv}」兩個獨立來源皆在佛州泡泡區；ESPN neutral 旗標為 False（同泡泡區其他比賽）'
                               if ok else '證據不足，維持無法確認')})
    return out


def main():
    rows = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    c = Counter((r['category'], r['phase'], r['status']) for r in rows)
    L = ['# 中立場資料表（獨立檔案 `data/reference/neutral_sites.csv`）', '',
         '不改 `games.jsonl.gz` 的 `neutral` 欄位。未列入的比賽沿用 ESPN 主客場。', '',
         '| 類別 | 賽段 | 狀態 | 場數 |', '|---|---|---|---|']
    for (cat, ph, st), n in sorted(c.items()):
        L.append(f'| {cat} | {ph} | {st} | {n} |')
    L += ['', '## 非泡泡區明細', '', '| game_id | 美東日期 | 對戰 | 狀態 | 類別 | ESPN 場館（現名） | BBRef 場館 | 判定理由 |',
          '|---|---|---|---|---|---|---|---|']
    for r in rows:
        if r['category'] in ('bubble_regular', 'bubble_postseason'):
            continue
        L.append(f"| {r['game_id']} | {r['date_et']} | {r['away']} @ {r['home']} | {r['status']} | {r['category']} | "
                 f"{r['espn_venue_current_name']} | {r['bbref_venue']} | {r['reason']} |")
    six = [r for r in rows if r['game_id'] in NO_NOTE_UNKNOWN]
    intl = {r['game_id'] for r in rows if r['category'] == 'international'}
    L += ['', '## ESPN 標記中立場但無備註的 6 場（逐場）', '',
          '| Game ID | 美東日期 | 客隊 | 主隊 | ESPN venue（現名）| BBRef venue | ESPN flag | ESPN note | 狀態 | 判定理由 |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for r in six:
        L.append(f"| {r['game_id']} | {r['date_et']} | {r['away']} | {r['home']} | {r['espn_venue_current_name']} | "
                 f"{r['bbref_venue']} | {r['espn_neutral_flag']} | {r['espn_note'] or '（無）'} | {r['status']} | {r['reason']} |")
    ids = [r['game_id'] for r in rows]
    L += ['', f"重複計數檢查：本表 {len(ids)} 列、{len(set(ids))} 個不同 game_id；"
          f"這 6 場與有備註的國際賽 {len(intl)} 場重疊 {len(intl & {r['game_id'] for r in six})} 場。"
          f"國際賽合計 = {len(intl)} + {len(six)} = {len(intl) + len(six)} 場（不同 game_id）。"]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print(OUT, len(rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
