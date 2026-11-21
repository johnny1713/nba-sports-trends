# 稽核完整性第四輪：單一資料快照、espn_playin 來源隔離、2013-14 allowlist（2026-11-21，基準 572a58f）

範圍只限稽核完整性、資料來源隔離與空資料例外。F1 公式與特徵定義、先驗方案 A、M = 10、W = 0.5、100 場門檻都沒有修改；
F1 九季完整輸出與 572a58f、a922bcd 逐位相同；F5／Elo 使用的一般資料存取路徑（11 季 × 4 種用途的賽程與 box）與 572a58f 逐位相同。
沒有開始 F2～F7，沒有訓練、調參、選模、回測或驗證。

## 修改檔案

| 檔案 | 修改 | 原因 |
|---|---|---|
| nba_quant/integrity.py（新）| 唯一性檢查、來源隔離合併規則 `merge_sources`、`Snapshot`（含內容指紋 `check`）、`AuditIntegrityError` | FAIL-1、重複資料防護 |
| nba_quant/audit_coverage.py | `load_snapshot`：一次讀入 espn 與 espn_playin 的 games／boxes，完成稽核驗證與來源隔離後回傳快照；`NO_DATA_SEASONS = (2014,)`；程式指紋納入 integrity.py | FAIL-1、FAIL-2 |
| nba_quant/box_audit.py | `scope_from_records` 稽核前檢查 game_id 與 (game_id, team) 唯一性 | 稽核前確認唯一性 |
| nba_quant/data_access.py | `verified_snapshot`；`games`／`team_boxes`／`box_audit_flags` 可接收快照（給定時不讀原始檔）；一般路徑的 espn／espn_playin 合併改用 `merge_sources`（不再「後讀覆蓋」）| FAIL-1、來源隔離 |
| nba_quant/features/f1.py | `get_valid_f1_games`、`compute`（預測目標賽程）、`f1_reference` 只用 `verified_snapshot`，使用後再核對快照指紋；移除舊的無資料例外判斷（移到 `load_snapshot`）| FAIL-1、FAIL-2 |
| data/audit/box_quality/v1/coverage/*.json | 11 份重建（程式指紋多了 integrity.py；其餘欄位與 572a58f 相同）| 指紋集合改變 |
| tests/test_f1.py | 合成資料的附加賽改放 espn_playin（與真實佈局相同）；合成球季的前三季建立「已稽核、0 場」的空球季 | 新規則下合成資料的正確佈局 |
| tests/test_audit_integrity.py、tests/test_source_isolation.py（新）| 測試 | 決策 5 |

## 資料流

```
F1（get_valid_f1_games / compute / f1_reference / prior_source / season_totals）
  └─ DataAccess.verified_snapshot(season, as_of)        先做球季鎖定檢查（鎖定期在讀任何資料前就拒絕）
       └─ audit_coverage.load_snapshot(season, root, 分類表)
            1. 沒有任何資料？（espn 兩檔、espn_playin 三檔都不存在，且分類表沒有該季）
                 season ∈ NO_DATA_SEASONS (2014) → 空快照 no_raw_data；否則 → season_no_data
            2. _verify：清單、版本、程式指紋、內容指紋 → 一次讀入 espn games／teambox 位元組
                 → 唯一性（duplicate_game／duplicate_box）→ 指紋 → 範圍 → flag 指紋 → 用同一份紀錄重新稽核、逐筆比對
            3. 一次讀入 espn_playin games／teambox／teambox_bbref
            4. integrity.merge_sources：來源隔離與跨來源唯一性
            5. Snapshot(games, boxes, flags) 封存內容指紋
  └─ DataAccess.games / team_boxes / box_audit_flags(..., snapshot=snap)   只取快照內的紀錄，不讀原始檔
  └─ snap.check()                                        使用後重算指紋，驗證後被改動 → snapshot_mismatch
```

同一個 DataAccess 實例內，每季只建一次快照（之後每次使用都重算指紋）；驗證後即使磁碟上的原始檔被改，
這個實例仍用驗證過的快照，新的 DataAccess 則會因指紋不符拒絕。

F5／Elo 等其他使用者走一般路徑 `DataAccess.games／team_boxes`（不帶快照），讀檔後同樣經過 `merge_sources` 的
來源隔離與唯一性檢查；它們不做稽核驗證，這與本輪之前相同（稽核只對 F1 的球隊統計是必要條件）。

## espn_playin 來源隔離規則（`integrity.merge_sources`，依分類表 game_type）

| 來源 | 只能提供 |
|---|---|
| espn（data/raw/espn/<季>/）| PLAY_IN 以外：例行賽、季中錦標賽（含冠軍戰）、季後賽 |
| espn_playin（data/raw/espn_playin/<季>/，含 teambox_bbref）| 分類表明確為 PLAY_IN 的比賽 |

- 同一來源內 game_id 重複、同一場同一隊 box 重複 → 拒絕。
- 同一 game_id 出現在兩個來源、同一場同一隊 box 出現在兩個檔案（含 espn_playin 的 teambox 與 teambox_bbref）→ 拒絕，不依讀取順序覆蓋。
- espn_playin 的比賽不在分類表或不是 PLAY_IN → source_mismatch；espn 提供 PLAY_IN 比賽 → source_mismatch。
- espn_playin 的 box 只能屬於 espn_playin 的比賽；espn 的 box 不得屬於附加賽。
- 比賽用途仍只由分類表的 use_* 欄位決定：F1 不含附加賽與季後賽；F5／Elo 含附加賽與季後賽（用途矩陣不變，
  一般路徑輸出與 572a58f 逐位相同：2020～2025 附加賽 1／6／6／6／6／6 場照常提供給 F5／Elo）。
- 真實資料：espn 沒有任何 PLAY_IN 比賽；espn_playin 全部是 PLAY_IN；兩來源之間、teambox 與 teambox_bbref 之間零重疊。

## 2013-14 allowlist

`audit_coverage.NO_DATA_SEASONS = (2014,)`。season key 與 data/raw/espn/<季>/ 及分類表 season 欄相同，以球季結束年份表示
（2015 = 2014-15），所以 2014 = 2013-14，也就是第一個資料季 2014-15 的上一季（有測試確認 = 最早資料季 − 1）。
只有在「espn 兩檔、espn_playin 三檔都不存在，且分類表沒有該季比賽」時才放行；其他球季同樣情況 → season_no_data；
只要有任何一份資料（含 allowlist 球季）就走完整驗證，缺檔 → raw_missing、損毀 → raw_unreadable。
原始檔存在但季賽尚未開始（as_of 早於開季）→ 完整驗證後回傳合法空集合。

## 重新稽核逐筆比對（11 季）

| 球季 | flag 筆數 | 重新稽核 | 清單與 572a58f 差異 |
|---|---|---|---|
| 2014-15～2024-25 | 14、15、10、1,010、28、9、7、12、9、14、15 | 全部逐筆相同 | 只有 audit_code_files、audit_code_sha256、content_sha256 |

## 測試

**369 項全部通過**（572a58f 為 344 項）。新增 `tests/test_source_isolation.py` 25 項：

| # | 要求 | 測試 |
|---|---|---|
| 1 | espn_playin 注入例行賽 box → F1 拒絕 | InjectionRefused.test_01（F1 與 F5／Elo 路徑都拒絕 source_mismatch）|
| 2 | 與 ESPN 重複的 box | test_02（duplicate_box）、test_02b（teambox 與 bbref 重疊）、test_02c（例行賽 game 出現在 espn_playin）、test_02d（附加賽改由 espn 提供）、test_02e（espn_playin 出現非 PLAY_IN 比賽）|
| 3 | 同一來源 game ID 重複 | Duplicates.test_03（espn；產生清單與 box 稽核本身也拒絕）、test_03b（espn_playin）|
| 4 | 同一場同一隊 box 重複 | Duplicates.test_04（兩種順序都拒絕）|
| 5 | 附加賽仍提供給 F5／Elo | PlayInStillServesAllowedUses.test_05、RealData.test_real_play_in_counts_unchanged_for_elo_and_f1_excludes、test_real_snapshot_equals_general_path |
| 6 | F1 使用的 box 與驗證快照不一致 → 拒絕 | SnapshotIsTheOnlySource.test_06（驗證後竄改 → snapshot_mismatch）、test_06b、test_06c（F1 每筆 box = 快照）|
| 7 | 驗證後無法透過重讀或合併替換 | test_07（一般讀檔路徑被替換成會失敗的函式時 F1 照常計算；改磁碟檔不影響已驗證快照；新實例拒絕）、F1SourceStructure（F1 每個讀取呼叫都帶 snapshot）|
| 8 | 2013-14 例外通過 | NoDataAllowlist.test_08、RealData.test_real_2013_14_allowed_others_refused |
| 9 | 其他球季無資料 → 拒絕 | test_09（2019、2013、2010、2030；以及因上一季無資料而拒絕計算 F1）、test_09b（整季含分類表消失）|
| 10 | 有原始檔、季賽未開始 → 空集合 | test_10 |
| 11 | 原始檔缺一份或損毀 → 拒絕 | test_11（espn teambox／games 缺失、espn 與 espn_playin 損毀；有／無 as_of）、test_11b（allowlist 球季只要有資料就完整驗證）|

## 變更檢查（相對 572a58f）

data/raw/espn 70 檔、data/raw/espn_playin 125 檔、盤口 odds_flags 11 檔（以上合計 data/raw 全部 206 檔）、
box 稽核 flag 11 檔、data/audit 其他 36 檔、盤口品質模組 4 檔、既有報告 26 檔，共 283 檔：0 變動。
