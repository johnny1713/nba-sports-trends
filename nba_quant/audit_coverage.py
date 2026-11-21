"""
box score 稽核涵蓋清單（audit coverage manifest；使用者 2026-11-21 核准，fail closed）。

    PYTHONPATH=. python -m nba_quant.audit_coverage            # 為每一季產生清單

產生（build_manifest）：
- 重新執行 box 稽核 v1（box_audit.audit_season，唯讀、不寫 flag 檔），結果必須與既有 flag 檔**逐筆相同**，
  才代表既有稽核對應目前的原始資料；不同 → 拒絕產生（stale_audit）。verify_flags=False 只會略過產生時的比對，
  **讀取時一定會重新稽核**，所以這種清單若與實際稽核不一致，永遠無法通過 verify。
- 記錄：原始 teambox／games 檔的 sha256、flag 檔的 sha256、應稽核與已稽核的 game_id（排序、不重複）、數量、稽核版本、
  稽核程式指紋（AUDIT_CODE_FILES 每個檔案各自的 sha256 與組合指紋）、產生時間、內容指紋。
  輸出到獨立路徑 data/audit/box_quality/v1/coverage/<季>.json（排序鍵 JSON）。不修改原始資料、不修改既有 flag 檔。

讀取（verify / verify_and_load）：資料存取層讀 audit flag 前呼叫，順序：
  flag 檔與清單存在 → 清單可解析且為物件 → 稽核版本 → 稽核程式指紋（每個檔案 + 組合）→ 欄位結構 →
  內容指紋 → 球季、原始檔路徑 → 原始 box／賽程檔存在且指紋相符 → flag 檔指紋相符 → ID 無重複、數量相符、
  應稽核 = 已稽核 → 以**同一份已讀取的原始位元組**推得的稽核範圍與清單相同（比賽 ID、球隊 box 數）→
  flag 只在已稽核比賽內 → **用目前的稽核程式重新稽核，與 flag 檔逐筆完全相同**。
任何一項不符都拋出 AuditIntegrityError（帶錯誤代碼），F1 不得計算；不吞例外、不降級、不沿用舊結果。

稽核程式指紋：AUDIT_CODE_FILES（會影響稽核資料解析、稽核結果或清單驗證的專案程式）每個檔案先把 CRLF 統一成 LF
再算 sha256；組合指紋 = sha256（依路徑排序的「路徑:sha256」逐行）。任何一個檔案變動 → 舊清單失效。
內容指紋 content_sha256：排除 audit_timestamp（稽核事件時間，metadata）與指紋本身後以固定序列化計算；
相同原始資料、相同 flag、相同稽核程式 → 相同內容指紋，與產生時間無關。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from . import box_audit, game_class, integrity, store
from .integrity import AuditIntegrityError, Snapshot  # noqa: F401（錯誤類別定義在 integrity，這裡重新匯出）

AUDIT_VERSION = 'box_quality_v1'
REQUIRED_AUDIT_VERSION = AUDIT_VERSION
# 稽核程式依賴集合（2026-11-21 決策）：
#   box_audit.py      稽核規則與稽核範圍定義（audit_season、scope_from_records）
#   audit_coverage.py 清單的產生與驗證規則（本檔）
#   store.py          原始資料與 flag 檔的解析（read_jsonl_gz、parse_jsonl_gz_bytes）與寫出
#   integrity.py      唯一性、來源隔離（espn／espn_playin）、資料快照與內容指紋
#   game_class.py     比賽分類規則（classify、uses、COUNTS、row）：決定比賽類型與 F1／F5／Elo 用途；
#                     分類規則改變 → 舊清單失效 → 必須重建分類表並重新驗證
# 五者的專案內 import 只有彼此；其餘皆為 Python 標準函式庫。資料存取層（data_access.py）與 F1 是 flag 的使用端，
# 不影響稽核結果或清單驗證，不納入（其行為由 F1 測試與九季輸出比對把關）。
AUDIT_CODE_FILES = ('nba_quant/audit_coverage.py', 'nba_quant/box_audit.py', 'nba_quant/game_class.py',
                    'nba_quant/integrity.py', 'nba_quant/store.py')
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 「沒有任何資料」例外的明確 allowlist（使用者 2026-11-21 決策）。season key 與 data/raw/espn/<季>/、分類表 season 欄相同：
# 以球季結束年份表示（2015 = 2014-15）。只有 2014（= 2013-14，第一個開發季 2014-15 的上一季，專案從未抓取）可以是空的；
# 其他任何球季沒有資料一律拒絕（season_no_data）。
NO_DATA_SEASONS = (2014,)
PLAYIN_RAW = os.path.join('data', 'raw', 'espn_playin')
# 內容指紋排除的欄位：audit_timestamp 是「稽核事件時間」metadata，不屬於稽核內容；content_sha256 是指紋本身
CONTENT_EXCLUDED_FIELDS = ('audit_timestamp', 'content_sha256')
SCHEMA = {'season': int, 'audit_version': str, 'audit_code_sha256': str, 'audit_code_files': dict,
          'raw_boxscore_file': str, 'raw_boxscore_file_hash': str, 'raw_games_file_hash': str, 'flags_file_hash': str,
          'expected_game_ids': list, 'audited_game_ids': list, 'expected_game_count': int, 'audited_game_count': int,
          'audited_team_box_count': int, 'content_excluded_fields': list, 'audit_timestamp': str, 'content_sha256': str}


# AuditIntegrityError 的錯誤代碼：flags_missing、manifest_missing、manifest_unreadable、manifest_invalid、version、
# audit_code_mismatch、content_hash、season、raw_file_mismatch、raw_missing、raw_unreadable、raw_boxscore_hash、
# raw_games_hash、flags_hash、flags_unreadable、duplicate_ids、count、not_all_audited、scope_mismatch、
# flag_outside_scope、stale_audit、duplicate_game、duplicate_box、source_mismatch、season_no_data、snapshot_mismatch。


def paths(season, root='.'):
    raw = os.path.join(root, box_audit.RAW, str(season))
    base = os.path.join(root, 'data', 'audit', 'box_quality', 'v1')
    return {'teambox': os.path.join(raw, 'teambox.jsonl.gz'), 'games': os.path.join(raw, 'games.jsonl.gz'),
            'flags': os.path.join(base, f'{season}_flags.jsonl.gz'),
            'manifest': os.path.join(base, 'coverage', f'{season}.json')}


def playin_paths(season, root='.'):
    d = os.path.join(root, PLAYIN_RAW, str(season))
    return {'espn_playin_games': os.path.join(d, 'games.jsonl.gz'),
            'espn_playin': os.path.join(d, 'teambox.jsonl.gz'),
            'espn_playin_bbref': os.path.join(d, 'teambox_bbref.jsonl.gz')}


def raw_boxscore_relpath(season):
    return '/'.join(box_audit.RAW.split(os.sep) + [str(season), 'teambox.jsonl.gz'])


# ---------- 稽核程式指紋 ----------

def code_file_sha(rel, code_root=None):
    p = os.path.join(code_root or CODE_ROOT, *rel.split('/'))
    if not os.path.isfile(p):
        raise AuditIntegrityError('audit_code_mismatch', f'稽核程式檔不存在：{rel}')
    with open(p, 'rb') as fh:
        data = fh.read()
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()      # CRLF → LF：不同 checkout 換行格式不影響


def code_files(code_root=None):
    return {rel: code_file_sha(rel, code_root) for rel in sorted(AUDIT_CODE_FILES)}


def combine_code_sha(files):
    return hashlib.sha256(''.join(f'{k}:{files[k]}\n' for k in sorted(files)).encode('utf-8')).hexdigest()


def _code_sha():
    return combine_code_sha(code_files())


# ---------- 內容指紋 ----------

def canonical_content(m):
    """內容指紋的固定序列化：排除 CONTENT_EXCLUDED_FIELDS、鍵排序、無空白、UTF-8。與檔案的排版格式無關。"""
    body = {k: v for k, v in m.items() if k not in CONTENT_EXCLUDED_FIELDS}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def content_sha(m):
    return hashlib.sha256(canonical_content(m)).hexdigest()


# ---------- 讀檔（一次讀入位元組：指紋與解析用同一份）----------

def _read_bytes(path, code, what):
    if not os.path.isfile(path):
        raise AuditIntegrityError(code, f'{what} 不存在：{path}')
    with open(path, 'rb') as fh:
        return fh.read()


def _parse_gz(data, code, what):
    try:
        rows = store.parse_jsonl_gz_bytes(data)
    except Exception as e:                                               # 轉成帶代碼的錯誤後拋出，不吞掉
        raise AuditIntegrityError(code, f'{what} 無法解析：{type(e).__name__}: {e}') from e
    if not all(isinstance(r, dict) for r in rows):
        raise AuditIntegrityError(code, f'{what} 含有非物件的紀錄')
    return rows


def _load_raw_full(season, root='.'):
    """讀入原始 teambox／games 位元組（各一次）並解析；回傳 (teambox_sha, games_sha, 稽核範圍 games, 稽核範圍 boxes,
    全部 games 紀錄, 全部 box 紀錄)。唯一性在稽核範圍建立前檢查（duplicate_game／duplicate_box）。"""
    p = paths(season, root)
    tb = _read_bytes(p['teambox'], 'raw_missing', '原始 box score 檔')
    gm = _read_bytes(p['games'], 'raw_missing', '原始賽程檔')
    game_rows = _parse_gz(gm, 'raw_unreadable', '原始賽程檔')
    box_rows = _parse_gz(tb, 'raw_unreadable', '原始 box score 檔')
    try:
        games, boxes = box_audit.scope_from_records(game_rows, box_rows)
    except AuditIntegrityError:
        raise
    except Exception as e:
        raise AuditIntegrityError('raw_unreadable', f'{season}: 原始資料欄位不完整：{type(e).__name__}: {e}') from e
    return hashlib.sha256(tb).hexdigest(), hashlib.sha256(gm).hexdigest(), games, boxes, game_rows, box_rows


def load_raw(season, root='.'):
    """回傳 (teambox_sha, games_sha, 稽核範圍 games, 稽核範圍 boxes)。"""
    return _load_raw_full(season, root)[:4]


def _reaudit(season, root, games, boxes):
    try:
        flags, _ = box_audit.audit_season(season, root, scope=(games, boxes))
    except Exception as e:
        raise AuditIntegrityError('stale_audit', f'{season}: 重新稽核失敗：{type(e).__name__}: {e}') from e
    return flags


def _flag_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f'第 {i} 筆不同：flag 檔 {x} ≠ 重新稽核 {y}'
    return f'筆數不同：flag 檔 {len(a)} 筆 ≠ 重新稽核 {len(b)} 筆'


# ---------- 產生 ----------

def build_manifest(season, root='.', verify_flags=True, now=None):
    p = paths(season, root)
    fl_bytes = _read_bytes(p['flags'], 'flags_missing', 'audit flag 檔')
    tb_sha, gm_sha, games, boxes = load_raw(season, root)
    if verify_flags:
        existing = _parse_gz(fl_bytes, 'flags_unreadable', 'audit flag 檔')
        redo = _reaudit(season, root, games, boxes)
        if existing != redo:
            raise AuditIntegrityError('stale_audit', f'{season}: 重新稽核結果與既有 flag 檔不同；必須重新執行資料稽核。'
                                                     + _flag_diff(existing, redo))
    ids = sorted({b['game_id'] for b in boxes})
    files = code_files()
    m = {'season': season, 'audit_version': AUDIT_VERSION,
         'audit_code_files': files, 'audit_code_sha256': combine_code_sha(files),
         'raw_boxscore_file': raw_boxscore_relpath(season),
         'raw_boxscore_file_hash': tb_sha, 'raw_games_file_hash': gm_sha,
         'flags_file_hash': hashlib.sha256(fl_bytes).hexdigest(),
         'expected_game_ids': ids, 'audited_game_ids': list(ids),
         'expected_game_count': len(ids), 'audited_game_count': len(ids),
         'audited_team_box_count': len(boxes),
         'content_excluded_fields': list(CONTENT_EXCLUDED_FIELDS),
         'audit_timestamp': now or datetime.now(timezone.utc).isoformat(timespec='seconds')}
    m['content_sha256'] = content_sha(m)       # 相同原始資料 + 相同 flag + 相同稽核程式 → 相同內容指紋（與時間無關）
    os.makedirs(os.path.dirname(p['manifest']), exist_ok=True)
    store.write_json(p['manifest'], m)
    return m


# ---------- 驗證 ----------

def _read_manifest(path, season):
    raw = _read_bytes(path, 'manifest_missing', '稽核涵蓋清單')
    try:
        m = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise AuditIntegrityError('manifest_unreadable', f'{season}: 清單無法解析：{type(e).__name__}: {e}') from e
    if not isinstance(m, dict):
        raise AuditIntegrityError('manifest_invalid', f'{season}: 清單不是 JSON 物件（{type(m).__name__}）')
    return m


def _check_code(m, season):
    files, combo = m.get('audit_code_files'), m.get('audit_code_sha256')
    if not isinstance(files, dict) or not isinstance(combo, str):
        raise AuditIntegrityError('audit_code_mismatch', f'{season}: 清單缺少稽核程式指紋欄位')
    if set(files) != set(AUDIT_CODE_FILES):
        raise AuditIntegrityError('audit_code_mismatch', f'{season}: 清單的稽核程式檔案集合 {sorted(files)} ≠ '
                                                         f'{sorted(AUDIT_CODE_FILES)}')
    if combine_code_sha(files) != combo:
        raise AuditIntegrityError('audit_code_mismatch', f'{season}: 組合指紋與各檔指紋不一致')
    cur = code_files()
    changed = [k for k in sorted(cur) if cur[k] != files[k]]
    if changed:
        raise AuditIntegrityError('audit_code_mismatch', f'{season}: 稽核程式已變更 {changed}（即使 audit_version 未更新）；'
                                                         '必須重新稽核並重建清單')


def _check_schema(m, season):
    if set(m) != set(SCHEMA):
        raise AuditIntegrityError('manifest_invalid', f'{season}: 清單欄位不符（缺少 {sorted(set(SCHEMA) - set(m))}，'
                                                      f'多出 {sorted(set(m) - set(SCHEMA))}）')
    for k, t in SCHEMA.items():
        if not isinstance(m[k], t) or (t is int and isinstance(m[k], bool)):
            raise AuditIntegrityError('manifest_invalid', f'{season}: 欄位 {k} 型別錯誤（{type(m[k]).__name__}）')
    for k in ('expected_game_ids', 'audited_game_ids'):
        if not all(isinstance(x, str) for x in m[k]):
            raise AuditIntegrityError('manifest_invalid', f'{season}: {k} 含非字串的 game_id')
    if m['content_excluded_fields'] != list(CONTENT_EXCLUDED_FIELDS):
        raise AuditIntegrityError('manifest_invalid', f'{season}: content_excluded_fields 與程式不符')


def verify_and_load(season, root='.'):
    """讀取前的完整性檢查；全部通過才回傳 (清單, flag 紀錄)，否則拋出 AuditIntegrityError（fail closed）。
    回傳的 flag 紀錄就是計算指紋與重新稽核比對的那一份位元組解析出來的，呼叫端不需要再讀檔。"""
    return _verify(season, root)[:2]


def _verify(season, root='.'):
    p = paths(season, root)
    if not os.path.isfile(p['flags']):
        raise AuditIntegrityError('flags_missing', f'{season}: audit flag 檔不存在')
    m = _read_manifest(p['manifest'], season)
    if m.get('audit_version') != REQUIRED_AUDIT_VERSION:
        raise AuditIntegrityError('version', f'{season}: 稽核版本 {m.get("audit_version")} ≠ {REQUIRED_AUDIT_VERSION}')
    _check_code(m, season)
    if not isinstance(m.get('content_sha256'), str):
        raise AuditIntegrityError('content_hash', f'{season}: 清單缺少內容指紋')
    _check_schema(m, season)
    if m['content_sha256'] != content_sha(m):
        raise AuditIntegrityError('content_hash', f'{season}: 清單內容指紋不符（清單被修改）')
    if m['season'] != season:
        raise AuditIntegrityError('season', f'清單球季 {m["season"]} ≠ {season}')
    if m['raw_boxscore_file'] != raw_boxscore_relpath(season):
        raise AuditIntegrityError('raw_file_mismatch', f'{season}: 清單的原始檔路徑 {m["raw_boxscore_file"]} ≠ '
                                                       f'{raw_boxscore_relpath(season)}')
    tb_sha, gm_sha, games, boxes, game_rows, box_rows = _load_raw_full(season, root)
    if tb_sha != m['raw_boxscore_file_hash']:
        raise AuditIntegrityError('raw_boxscore_hash', f'{season}: 原始 box score 指紋不符，清單失效，必須重新稽核')
    if gm_sha != m['raw_games_file_hash']:
        raise AuditIntegrityError('raw_games_hash', f'{season}: 原始賽程指紋不符，清單失效，必須重新稽核')
    fl_bytes = _read_bytes(p['flags'], 'flags_missing', 'audit flag 檔')
    if hashlib.sha256(fl_bytes).hexdigest() != m['flags_file_hash']:
        raise AuditIntegrityError('flags_hash', f'{season}: flag 檔指紋不符')
    flags = _parse_gz(fl_bytes, 'flags_unreadable', 'audit flag 檔')
    exp, aud = m['expected_game_ids'], m['audited_game_ids']
    if len(exp) != len(set(exp)) or len(aud) != len(set(aud)):
        raise AuditIntegrityError('duplicate_ids', f'{season}: 清單中有重複的 game_id')
    if m['expected_game_count'] != len(exp) or m['audited_game_count'] != len(aud):
        raise AuditIntegrityError('count', f'{season}: 清單數量欄位與 ID 清單不符')
    if set(exp) != set(aud):
        raise AuditIntegrityError('not_all_audited', f'{season}: 應稽核與已稽核不同（未稽核 {sorted(set(exp) - set(aud))[:5]}，'
                                                     f'多餘 {sorted(set(aud) - set(exp))[:5]}）')
    cur = sorted({b['game_id'] for b in boxes})
    if cur != sorted(exp):
        raise AuditIntegrityError('scope_mismatch', f'{season}: 目前原始資料的比賽與清單不同（新增 {sorted(set(cur) - set(exp))[:5]}，'
                                                    f'不存在 {sorted(set(exp) - set(cur))[:5]}）')
    if m['audited_team_box_count'] != len(boxes):
        raise AuditIntegrityError('scope_mismatch', f'{season}: 清單球隊 box 數 {m["audited_team_box_count"]} ≠ '
                                                    f'目前稽核範圍 {len(boxes)}')
    bad = {f.get('game_id') for f in flags} - set(aud)
    if bad:
        raise AuditIntegrityError('flag_outside_scope', f'{season}: flag 出現在未稽核的比賽 {sorted(map(str, bad))[:5]}')
    redo = _reaudit(season, root, games, boxes)
    if flags != redo:                                                    # 逐筆、全部欄位、含順序
        raise AuditIntegrityError('stale_audit', f'{season}: 目前稽核程式的重新稽核結果與 flag 檔不同；' + _flag_diff(flags, redo))
    return m, flags, game_rows, box_rows


def verify(season, root='.'):
    return verify_and_load(season, root)[0]


def classification_index(rows):
    """分類表列 → {game_id: 列}；game_id 重複 → classification_duplicate（不依順序取捨）。"""
    out = {}
    for r in rows:
        if r['game_id'] in out:
            raise AuditIntegrityError('classification_duplicate', f"分類表 game_id 重複：{r['game_id']}")
        out[r['game_id']] = r
    return out


def verify_classification(season, sourced_games, classification):
    """用同一份已讀取的原始賽程重新分類（game_class.row），與分類表該季的列逐筆、逐欄位（game_class.FIELDS 全部）比對。
    sourced_games：[(來源 espn／espn_playin, games 紀錄)]。回傳 {game_id: 已驗證的分類列}。
    缺漏 → classification_missing；分類表多出該季比賽 → classification_extra；任何欄位不同 → classification_mismatch。"""
    expected = {}
    for kind, rows in sourced_games:
        src = game_class.source_file(kind, season)
        for g in rows:
            try:
                expected[g['game_id']] = game_class.as_csv(game_class.row(g, src))
            except Exception as e:
                raise AuditIntegrityError('classification_mismatch', f"{g.get('game_id')}: 無法重新分類：{e}") from e
    table = {gid: r for gid, r in classification.items() if r.get('season') == str(season)}
    missing = sorted(set(expected) - set(table))
    if missing:
        raise AuditIntegrityError('classification_missing', f'{season}: 分類表缺少比賽 {missing[:5]}（或球季欄位錯誤）')
    extra = sorted(set(table) - set(expected))
    if extra:
        raise AuditIntegrityError('classification_extra', f'{season}: 分類表多出原始資料沒有的比賽 {extra[:5]}')
    for gid in sorted(expected):
        got = {k: table[gid].get(k) for k in game_class.FIELDS}
        if got != expected[gid] or set(table[gid]) != set(game_class.FIELDS):
            diff = sorted(k for k in game_class.FIELDS if got[k] != expected[gid][k]) or ['欄位集合']
            raise AuditIntegrityError('classification_mismatch', f'{season}: {gid} 的分類與重新分類結果不同（{diff}）；'
                                                                 '必須以 game_class 重建分類表')
    return {gid: table[gid] for gid in expected}


def _season_has_any_data(season, root, classification):
    files = [paths(season, root)['teambox'], paths(season, root)['games'], *playin_paths(season, root).values()]
    return (any(os.path.exists(f) for f in files)
            or any(str(r.get('season')) == str(season) for r in classification.values()))


def load_snapshot(season, root='.', classification_rows=()):
    """F1 唯一的原始資料來源：一次讀入 espn 與 espn_playin 的 games／team boxes，完成稽核完整性驗證
    （指紋、範圍、重新稽核）、唯一性、來源隔離與分類表一致性（重新分類、逐筆逐欄位比對）後，
    回傳 (不可變 Snapshot, 預期內容指紋)。預期指紋由呼叫端（DataAccess）保存在快照外部。
    任何失敗 → AuditIntegrityError，整份拒絕。

    沒有任何資料（espn、espn_playin 原始檔都不存在，分類表也沒有該季比賽）：只有 NO_DATA_SEASONS 回傳
    status = no_raw_data 的空快照，其他球季 → season_no_data。只要有任何一份資料存在，就走完整驗證（缺檔 → raw_missing）。"""
    classification = classification_index(classification_rows)
    if not _season_has_any_data(season, root, classification):
        if season in NO_DATA_SEASONS:
            snap = Snapshot.build(season, 'no_raw_data')
            return snap, snap.content_digest()
        raise AuditIntegrityError('season_no_data', f'{season}: 沒有任何原始資料也沒有分類資料，且不在空資料 allowlist '
                                                    f'{NO_DATA_SEASONS} 內（可能是整季資料遺失或分類表重建錯誤）')
    m, flags, game_rows, box_rows = _verify(season, root)
    pp = playin_paths(season, root)
    pi = {}
    for k, path in pp.items():
        pi[k] = (_parse_gz(_read_bytes(path, 'raw_missing', k), 'raw_unreadable', f'{k} 原始檔')
                 if os.path.isfile(path) else [])
    games, boxes = integrity.merge_sources(
        [('espn', game_rows), ('espn_playin', pi['espn_playin_games'])],
        [('espn', box_rows), ('espn_playin', pi['espn_playin']), ('espn_playin_bbref', pi['espn_playin_bbref'])],
        classification)
    cls = verify_classification(season, [('espn', game_rows), ('espn_playin', pi['espn_playin_games'])], classification)
    snap = Snapshot.build(season, 'verified', games, boxes, flags, cls, m)
    return snap, snap.content_digest()


def main():
    for s in sorted(int(x) for x in os.listdir(box_audit.RAW) if x.isdigit()):
        m = build_manifest(s)
        print(s, m['expected_game_count'], m['audited_game_count'], m['raw_boxscore_file_hash'][:12])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
