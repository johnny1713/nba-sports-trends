"""
原始資料完整性：唯一性、來源隔離、已驗證資料快照（使用者 2026-11-21 核准）。

來源隔離規則（依分類表 data/reference/game_classification.csv 的 game_type）：

| 來源 | 檔案 | 只能提供 |
|---|---|---|
| espn | data/raw/espn/<季>/games.jsonl.gz、teambox.jsonl.gz | PLAY_IN 以外的比賽：例行賽、季中錦標賽（含冠軍戰）、季後賽 |
| espn_playin | data/raw/espn_playin/<季>/games.jsonl.gz、teambox.jsonl.gz、teambox_bbref.jsonl.gz | 分類表明確標記為 PLAY_IN 的比賽 |

- 同一個來源內 game_id 重複、同一場同一隊 box 重複 → 拒絕（duplicate_game／duplicate_box）。
- 同一個 game_id 出現在兩個來源、同一場同一隊 box 出現在兩個檔案 → 拒絕；**不依讀取順序決定採用哪一筆**。
- espn_playin 的比賽必須在分類表中且為 PLAY_IN；espn 不得提供分類為 PLAY_IN 的比賽 → 否則 source_mismatch。
- espn_playin 的 box 只能屬於 espn_playin 的比賽；espn 的 box 不得屬於 espn_playin 的比賽或分類為 PLAY_IN 的比賽。
比賽「用途」（F1／F5／Elo 是否納入）仍完全由分類表的 use_* 欄位決定，本模組不改變用途矩陣。

已驗證資料快照（Snapshot）：一次讀入原始 games 與 team boxes，通過稽核完整性驗證（audit_coverage.load_snapshot）後
交給 F1；建立時記錄內容指紋，使用時重算比對（check），快照內容在驗證後被改動 → snapshot_mismatch。
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

from . import store

PLAY_IN = 'PLAY_IN'
GAME_SOURCES = ('espn', 'espn_playin')
BOX_SOURCE_OF = {'espn': 'espn', 'espn_playin': 'espn_playin', 'espn_playin_bbref': 'espn_playin'}


class AuditIntegrityError(RuntimeError):
    """稽核完整性／資料來源完整性錯誤，帶可辨識的錯誤代碼（code）。"""

    def __init__(self, code, detail):
        super().__init__(f'[{code}] {detail}')
        self.code = code


def check_unique_games(rows, source):
    dup = sorted(g for g, c in Counter(r['game_id'] for r in rows).items() if c > 1)
    if dup:
        raise AuditIntegrityError('duplicate_game', f'{source}: game_id 重複 {dup[:5]}')


def check_unique_boxes(rows, source):
    dup = sorted(k for k, c in Counter((r['game_id'], r['team']) for r in rows).items() if c > 1)
    if dup:
        raise AuditIntegrityError('duplicate_box', f'{source}: 同一場同一隊的 box 重複 {dup[:5]}')


def merge_sources(game_sources, box_sources, classification):
    """依來源隔離規則合併。game_sources: [(來源, games 紀錄)]；box_sources: [(來源, box 紀錄)]；
    classification: {game_id: 分類列}。回傳 (games 紀錄清單, {(game_id, team): box})。任何違規 → AuditIntegrityError。"""
    owner = {}
    games = []
    for src, rows in game_sources:
        if src not in GAME_SOURCES:
            raise AuditIntegrityError('source_mismatch', f'未知的賽程來源 {src}')
        check_unique_games(rows, src)
        for g in rows:
            gid = g['game_id']
            if gid in owner:
                raise AuditIntegrityError('duplicate_game', f'{gid} 同時出現在 {owner[gid]} 與 {src}')
            gt = (classification.get(gid) or {}).get('game_type')
            if src == 'espn_playin' and gt != PLAY_IN:
                raise AuditIntegrityError('source_mismatch', f'{gid} 來自 espn_playin，但分類為 {gt}（只允許 PLAY_IN）')
            if src == 'espn' and gt == PLAY_IN:
                raise AuditIntegrityError('source_mismatch', f'{gid} 分類為 PLAY_IN，不得來自 espn')
            owner[gid] = src
            games.append(g)
    boxes, box_owner = {}, {}
    for src, rows in box_sources:
        if src not in BOX_SOURCE_OF:
            raise AuditIntegrityError('source_mismatch', f'未知的 box 來源 {src}')
        check_unique_boxes(rows, src)
        gsrc = BOX_SOURCE_OF[src]
        for b in rows:
            k = (b['game_id'], b['team'])
            if k in boxes:
                raise AuditIntegrityError('duplicate_box', f'{k} 同時出現在 {box_owner[k]} 與 {src}（不依讀取順序覆蓋）')
            gt = (classification.get(b['game_id']) or {}).get('game_type')
            if gsrc == 'espn_playin' and owner.get(b['game_id']) != 'espn_playin':
                raise AuditIntegrityError('source_mismatch', f'{k} 來自 {src}，但該場不是 espn_playin 的附加賽')
            if gsrc == 'espn' and (owner.get(b['game_id']) == 'espn_playin' or gt == PLAY_IN):
                raise AuditIntegrityError('source_mismatch', f'{k} 是附加賽，不得來自 espn')
            boxes[k] = b
            box_owner[k] = src
    return games, boxes


def _digest(games, boxes, flags):
    return hashlib.sha256(store.dumps([games, sorted(([k[0], k[1]], v) for k, v in boxes.items()), flags])
                          .encode('utf-8')).hexdigest()


@dataclass
class Snapshot:
    """一季已驗證的原始資料快照。status：verified（通過完整驗證）或 no_raw_data（只限 allowlist 球季）。"""
    season: int
    status: str
    manifest: dict | None = None
    flags: list = field(default_factory=list)
    games: list = field(default_factory=list)
    boxes: dict = field(default_factory=dict)
    digest: str = ''

    def seal(self):
        self.digest = _digest(self.games, self.boxes, self.flags)
        return self

    def check(self):
        """使用前重算內容指紋：驗證後快照被改動（或不是驗證流程產生的快照）→ 拒絕。"""
        if not self.digest or _digest(self.games, self.boxes, self.flags) != self.digest:
            raise AuditIntegrityError('snapshot_mismatch', f'{self.season}: 資料快照與驗證時的內容不一致')
        return self
