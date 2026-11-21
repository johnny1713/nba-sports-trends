"""
box score 稽核涵蓋清單（audit coverage manifest；使用者 2026-11-21 核准，fail closed）。

    PYTHONPATH=. python -m nba_quant.audit_coverage            # 為每一季產生清單

產生（build_manifest）：
- 重新執行 box 稽核 v1（box_audit.audit_season，唯讀、不寫 flag 檔），結果必須與既有 flag 檔**逐筆相同**，
  才代表既有稽核對應目前的原始資料；不同 → 拒絕產生，必須重新執行資料稽核。
- 記錄：原始 teambox／games 檔的 sha256、flag 檔的 sha256、應稽核與已稽核的 game_id（排序、不重複）、數量、稽核版本、
  稽核程式（box_audit.py）的 sha256、產生時間。輸出到獨立路徑 data/audit/box_quality/v1/coverage/<季>.json，
  以排序鍵的 JSON 序列化（deterministic）。不修改原始資料、不修改既有 flag 檔。

讀取（verify）：資料存取層讀 audit flag 前呼叫；任何一項不符就拋出 AuditIntegrityError，F1 不得計算：
flag 檔存在、清單存在、稽核版本相符、**稽核程式指紋與目前執行的 box_audit.py 相符**（版本字串忘記更新也會被擋）、原始 box／games 指紋相符、flag 檔指紋相符、清單內無重複、數量相符、
應稽核 = 已稽核、清單與目前原始資料推得的應稽核比賽完全相同（沒有未稽核、沒有多餘）、flag 只出現在已稽核的比賽。
原始資料新增、刪除、修改任何內容 → 指紋不符 → 舊清單失效，必須重新稽核；不會自動沿用。
清單內容指紋 content_sha256：排除 audit_timestamp（稽核事件時間，只是 metadata）後以固定序列化計算；
相同原始資料、相同 flag、相同稽核程式 → 相同內容指紋，重新產生的時間不同不影響。讀取時重算比對，不符 → 拒絕。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from . import box_audit, store

AUDIT_VERSION = 'box_quality_v1'
REQUIRED_AUDIT_VERSION = AUDIT_VERSION
# 內容指紋排除的欄位：audit_timestamp 是「稽核事件時間」metadata，不屬於稽核內容；content_sha256 是指紋本身
CONTENT_EXCLUDED_FIELDS = ('audit_timestamp', 'content_sha256')


class AuditIntegrityError(RuntimeError):
    def __init__(self, code, detail):
        super().__init__(f'[{code}] {detail}')
        self.code = code


def paths(season, root='.'):
    raw = os.path.join(root, box_audit.RAW, str(season))
    base = os.path.join(root, 'data', 'audit', 'box_quality', 'v1')
    return {'teambox': os.path.join(raw, 'teambox.jsonl.gz'), 'games': os.path.join(raw, 'games.jsonl.gz'),
            'flags': os.path.join(base, f'{season}_flags.jsonl.gz'),
            'manifest': os.path.join(base, 'coverage', f'{season}.json')}


def expected_game_ids(season, root='.'):
    """由目前原始資料推得「應稽核」的比賽：完賽且有球隊 box（與 box_audit.audit_scope 同一個範圍定義）。"""
    _, boxes = box_audit.audit_scope(season, root)
    return sorted({b['game_id'] for b in boxes})


def _code_sha():
    """目前實際執行的稽核程式（box_audit.py）的 sha256。"""
    with open(box_audit.__file__, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def canonical_content(m):
    """內容指紋的固定序列化：排除 CONTENT_EXCLUDED_FIELDS、鍵排序、無空白、UTF-8。與檔案的排版格式無關。"""
    body = {k: v for k, v in m.items() if k not in CONTENT_EXCLUDED_FIELDS}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def content_sha(m):
    return hashlib.sha256(canonical_content(m)).hexdigest()


def build_manifest(season, root='.', verify_flags=True, now=None):
    p = paths(season, root)
    if not os.path.exists(p['flags']):
        raise AuditIntegrityError('flags_missing', f'{p["flags"]} 不存在：必須先執行 box 稽核')
    games, boxes = box_audit.audit_scope(season, root)
    if verify_flags:
        flags, _ = box_audit.audit_season(season, root)
        if flags != list(store.read_jsonl_gz(p['flags'])):
            raise AuditIntegrityError('stale_audit', f'{season}: 重新稽核結果與既有 flag 檔不同；必須重新執行資料稽核')
    audited = sorted({b['game_id'] for b in boxes})
    expected = expected_game_ids(season, root)
    m = {'season': season, 'audit_version': AUDIT_VERSION, 'audit_code_sha256': _code_sha(),
         'raw_boxscore_file': os.path.relpath(p['teambox'], root).replace(os.sep, '/'),
         'raw_boxscore_file_hash': store.sha256_file(p['teambox']),
         'raw_games_file_hash': store.sha256_file(p['games']),
         'flags_file_hash': store.sha256_file(p['flags']),
         'expected_game_ids': expected, 'audited_game_ids': audited,
         'expected_game_count': len(expected), 'audited_game_count': len(audited),
         'audited_team_box_count': len(boxes),
         'content_excluded_fields': list(CONTENT_EXCLUDED_FIELDS),
         'audit_timestamp': now or datetime.now(timezone.utc).isoformat(timespec='seconds')}
    m['content_sha256'] = content_sha(m)       # 相同原始資料 + 相同 flag + 相同稽核程式 → 相同內容指紋（與時間無關）
    os.makedirs(os.path.dirname(p['manifest']), exist_ok=True)
    store.write_json(p['manifest'], m)
    return m


def verify(season, root='.'):
    """讀取前的完整性檢查；全部通過才回傳清單，否則拋出 AuditIntegrityError（fail closed）。"""
    p = paths(season, root)
    if not os.path.exists(p['flags']):
        raise AuditIntegrityError('flags_missing', f'{season}: audit flag 檔不存在')
    if not os.path.exists(p['manifest']):
        raise AuditIntegrityError('manifest_missing', f'{season}: 稽核涵蓋清單不存在')
    m = store.read_json(p['manifest'])
    if m.get('audit_version') != REQUIRED_AUDIT_VERSION:
        raise AuditIntegrityError('version', f'{season}: 稽核版本 {m.get("audit_version")} ≠ {REQUIRED_AUDIT_VERSION}')
    if m.get('audit_code_sha256') != _code_sha():
        raise AuditIntegrityError('audit_code_hash', f'{season}: 稽核程式指紋不符（程式已變更，即使 audit_version 未更新）；'
                                                     f'必須重新稽核並重建清單')
    if m.get('season') != season:
        raise AuditIntegrityError('season', f'清單球季 {m.get("season")} ≠ {season}')
    if store.sha256_file(p['teambox']) != m.get('raw_boxscore_file_hash'):
        raise AuditIntegrityError('raw_boxscore_hash', f'{season}: 原始 box score 指紋不符，清單失效，必須重新稽核')
    if store.sha256_file(p['games']) != m.get('raw_games_file_hash'):
        raise AuditIntegrityError('raw_games_hash', f'{season}: 原始賽程指紋不符，清單失效，必須重新稽核')
    if store.sha256_file(p['flags']) != m.get('flags_file_hash'):
        raise AuditIntegrityError('flags_hash', f'{season}: flag 檔指紋不符')
    exp, aud = m.get('expected_game_ids') or [], m.get('audited_game_ids') or []
    if len(exp) != len(set(exp)) or len(aud) != len(set(aud)):
        raise AuditIntegrityError('duplicate_ids', f'{season}: 清單中有重複的 game_id')
    if m.get('expected_game_count') != len(exp) or m.get('audited_game_count') != len(aud):
        raise AuditIntegrityError('count', f'{season}: 清單數量欄位與 ID 清單不符')
    if set(exp) != set(aud):
        raise AuditIntegrityError('not_all_audited', f'{season}: 應稽核與已稽核不同（未稽核 {sorted(set(exp) - set(aud))[:5]}，'
                                                     f'多餘 {sorted(set(aud) - set(exp))[:5]}）')
    cur = expected_game_ids(season, root)
    if cur != sorted(exp):
        raise AuditIntegrityError('scope_mismatch', f'{season}: 目前原始資料的比賽與清單不同（新增 {sorted(set(cur) - set(exp))[:5]}，'
                                                    f'不存在 {sorted(set(exp) - set(cur))[:5]}）')
    flag_ids = {f['game_id'] for f in store.read_jsonl_gz(p['flags'])}
    if not flag_ids <= set(aud):
        raise AuditIntegrityError('flag_outside_scope', f'{season}: flag 出現在未稽核的比賽 {sorted(flag_ids - set(aud))[:5]}')
    if not m.get('content_sha256') or m['content_sha256'] != content_sha(m):
        raise AuditIntegrityError('content_hash', f'{season}: 清單內容指紋不符或缺漏（清單被修改或為舊格式）')
    return m


def main():
    out = []
    for s in sorted(int(x) for x in os.listdir(box_audit.RAW) if x.isdigit()):
        m = build_manifest(s)
        out.append((s, m['expected_game_count'], m['audited_game_count'], m['audited_team_box_count']))
        print(s, m['expected_game_count'], m['audited_game_count'], m['raw_boxscore_file_hash'][:12])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
