# 資料快照完整性修正（2026-11-21 第五輪，基準 97bbf1a）

範圍只限資料完整性與快照保護。F1 公式與特徵定義、先驗方案 A、M = 10、W = 0.5、100 場門檻、espn／espn_playin 來源隔離規則都沒有修改；
F1 九季完整輸出與 97bbf1a 逐位相同；F5／Elo 一般讀取路徑（11 季 × 4 種用途）與 97bbf1a 逐位相同。
沒有開始 F2～F7，沒有訓練、調參、選模、回測或驗證。

## 修改檔案

| 檔案 | 修改 | 原因 |
|---|---|---|
| nba_quant/game_class.py | 抽出 `row()`（單場分類列的唯一定義）、`source_file()`、`as_csv()`；`build()` 改用 `row()`，產出與既有分類表逐位元組相同 | 快照驗證與分類表產生共用同一套規則 |
| nba_quant/integrity.py | `Snapshot` 改為 frozen dataclass、內容深層凍結（`freeze`／`thaw`）；新增 `classifications` 欄位；`content_digest()` 涵蓋 season、status、games、boxes、flags、classifications；移除 `seal()`、`check()`、`digest` | 修正 seal 信任問題、status／season 不在指紋內、分類表不在快照內 |
| nba_quant/audit_coverage.py | `verify_classification`（重新分類、逐筆逐欄位比對）、`classification_index`（重複檢查）；`load_snapshot` 回傳（不可變快照, 預期指紋）；程式指紋納入 game_class.py | 分類表一致性、分類規則改變需重新驗證 |
| nba_quant/data_access.py | 預期指紋保存在 DataAccess 私有狀態；`check_snapshot`（身分 + 欄位物件身分，full 時重算指紋）；`games(snapshot=…)` 用快照內的分類；`box_audit_flags` 回傳獨立複本；分類表 game_id 重複 → 拒絕；`_season_row_of` | 外部保存預期指紋、可變引用洩漏、分類表唯一性 |
| nba_quant/features/f1.py | 結束時改呼叫 `da.check_snapshot(snap)`（完整指紋比對）；新增 `season_of`：判定球季用的分類列必須與已驗證快照相同 | 預期指紋在外部；先驗來源的球季判定也受分類一致性保護 |
| data/audit/box_quality/v1/coverage/*.json | 11 份重建（程式指紋多 game_class.py；其他欄位與 97bbf1a 相同）| 指紋集合改變 |
| tests/test_f1.py | 合成資料的分類表改由 `game_class.row` 從合成原始賽程產生（盃賽帶備註、季後賽／附加賽帶 season_type）| 與真實分類表的產生方式一致 |
| tests/test_f1_final_audit.py | 暫存根目錄同時複製 espn_playin | 分類表含附加賽，原始資料必須完整 |
| tests/test_source_isolation.py | test_06 改用底層替換（快照已不可原地修改）| 快照不可變 |
| tests/test_snapshot_integrity.py（新）、tests/test_audit_integrity.py | 測試 | 決策 5 |

## Snapshot 欄位與指紋涵蓋範圍

| 欄位 | 內容 | 內容指紋 |
|---|---|---|
| season | 球季 key | 涵蓋 |
| status | verified／no_raw_data | 涵蓋 |
| games | 該季全部原始賽程紀錄（espn + espn_playin，全部欄位，含巢狀 notes 等）| 涵蓋 |
| boxes | {(game_id, team): box}（全部欄位，含巢狀 players）| 涵蓋 |
| flags | box 稽核 v1 旗標（全部欄位）| 涵蓋 |
| classifications | {game_id: 分類表列}（game_class.FIELDS 全部 16 欄），已與重新分類比對通過 | 涵蓋 |
| manifest | 稽核涵蓋清單 | **不涵蓋**：metadata，只寫入存取紀錄，不影響任何數值 |

序列化：鍵排序、無空白、UTF-8 的 JSON；boxes 依 (game_id, team) 排序、classifications 依 game_id 排序。同一份資料兩次載入指紋相同。

## 分類表重新分類與逐筆比對

用快照讀入的同一份原始賽程（espn 與 espn_playin 分別帶各自的 source_file）執行 `game_class.row`，轉成 CSV 字串後
與分類表該季的列逐筆比對 16 個欄位：game_id、season、start_utc、away、home、status、espn_season_type、game_type、
counts_for_standings、use_team_stats、use_fatigue、use_elo、train_sample、eval_group、source_file、basis。
錯誤代碼：classification_missing（原始資料有、分類表該季沒有）、classification_extra（分類表該季多出）、
classification_mismatch（任一欄位不同）、classification_duplicate（同一 game_id 多列）。

真實資料 2014-15～2024-25：11 季原始賽程 14,228 場，分類表 14,228 列，**全部逐筆逐欄位相同**。

## 不可變性與預期指紋

- `Snapshot` 是 frozen dataclass；dict 轉成包住新 dict 的 MappingProxyType、list 轉成 tuple，遞迴到最內層（真實 box 的 players、賽程的 notes 都是）。
  一般 Python 操作無法修改；以 `object.__setattr__` 這類底層手段替換欄位會被下述檢查拒絕。
- 沒有任何重新封存方法（`seal`、`check`、`digest` 都已移除）。
- 預期指紋在 `load_snapshot` 建立快照當下計算，由 `DataAccess.verified_snapshot` 存在 DataAccess 的私有狀態（name-mangled），
  同時記錄快照物件與各欄位物件的身分；沒有任何方法可以更新它。
- `DataAccess.check_snapshot`：快照必須是本實例驗證產生的那一個物件、欄位物件未被替換；`full=True` 時重算內容指紋與預期值比對。
  中間步驟（取快照、games／team_boxes／box_audit_flags）做身分檢查；F1 `get_valid_f1_games` 結束時做完整比對。
  （快照深層不可變，中間步驟改用輕量檢查；完整比對每次約 0.1 秒。）
- `box_audit_flags` 回傳獨立可變複本；`games`、`team_boxes` 本來就回傳新建的 dict；classifications 只在 DataAccess 內部使用。

## 測試

**390 項全部通過**（97bbf1a 為 369 項）。新增 `tests/test_snapshot_integrity.py` 21 項，對應決策 5：

| # | 要求 | 測試 |
|---|---|---|
| 1 | 改 use_team_stats → 拒絕 | test_01（含季後賽被偷偷納入 F1）|
| 2 | 改 game_type 或其他用途旗標 → 拒絕 | test_02（13 個欄位逐一）|
| 3 | 缺列、多列 → 拒絕 | test_03（另含重複列、球季欄位錯）|
| 4 | 一致時通過 | test_04、RealData.test_real_classification_matches_reclassification_all_seasons |
| 5 | 改 status → 拒絕 | test_05、test_05b |
| 6 | 改 season → 拒絕 | test_06 |
| 7 | 巢狀資料無法修改 | test_07、test_nested_lists_are_frozen、RealData.test_real_snapshot_is_immutable |
| 8 | 沒有公開重新封存方法 | test_08 |
| 9 | 改資料後重新封存仍無法通過 | test_09（另含自組快照被拒）、test_09b |
| 10 | box_audit_flags 回傳值被改不影響快照 | test_10、test_returned_games_boxes_are_copies |
| 11 | 指紋 deterministic | test_11 |
| 12 | 分類表變動被拒絕 | test_12、test_games_use_snapshot_classification_not_dataaccess_cache、test_digest_covers_all_numeric_inputs |

所有拒絕測試都經過 F1 實際資料流（compute、get_valid_f1_games、f1_prior_source）確認整個計算被拒絕。

## 變更檢查（相對 97bbf1a）

data/raw 206 檔（espn 70、espn_playin 125、odds_flags 11）、box 稽核 flag 11 檔、data/audit 其他 36 檔、
data/reference（含分類表）、盤口品質模組 4 檔、既有報告 26 檔：0 變動。只有 11 份 coverage 清單重建。
11 季 flags 與重新稽核逐筆一致。
