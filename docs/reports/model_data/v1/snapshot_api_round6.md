# 快照 API 權限（方案 B，2026-11-21 第六輪，基準 7db80cc）

只修改快照的存取權限與檢查時機。F1 公式與特徵定義、先驗方案 A、M = 10、W = 0.5、100 場門檻、分類表、來源隔離與快照設計都沒有修改；
F1 九季完整輸出與 F5／Elo 一般讀取路徑與 7db80cc 逐位相同。沒有開始 F2～F7，沒有訓練、調參、選模、回測或驗證。

## 修改檔案

| 檔案 | 修改 |
|---|---|
| nba_quant/data_access.py | 權限由 API 區分：公開入口回傳前完整比對；新增 F1 專用私有讀取 `_f1_*`（只做身分檢查）；拿掉 `check_snapshot(full=…)` 參數；實作抽成 `_games_impl`／`_team_boxes_impl`／`_flags_impl`（共用、不做檢查）|
| nba_quant/features/f1.py | 讀取全部改用 `_f1_*`；2013-14 空資料與 2017-18 不可用回傳前完整比對；`compute` 結尾完整比對；`season_of` 拆成內部 `_season_of`（身分）與公開 `season_of`（完整）|
| tests/test_snapshot_api.py（新）、tests/test_source_isolation.py | 測試 |

## API

| 公開（回傳前完整比對）| F1 專用私有（只做身分檢查）|
|---|---|
| `verified_snapshot(season, as_of)` | `_f1_snapshot(season, as_of)` |
| `check_snapshot(snapshot)`（只有這一個參數）| `_f1_games(snap, season, scope, as_of)` |
| `games(..., snapshot=snap)` | `_f1_team_boxes(snap, season, scope, fields, as_of)` |
| `team_boxes(..., snapshot=snap)` | `_f1_flags(snap, season, as_of)` |
| `box_audit_flags(season, as_of, snapshot=None)` | |
| `f1_prior_source`（轉給 F1 `prior_source`）| |

身分檢查 = 是本實例驗證產生的那一個快照物件、欄位物件未被替換、球季相符。完整比對 = 身分檢查 + 重算內容指紋與 DataAccess 私有保存的預期值比對。
`games`／`team_boxes` 不帶快照時是 F5／Elo 的一般路徑，不涉及快照。其他公開方法都不接觸快照（有測試掃描）。

## F1 回傳入口的完整比對點

| 入口 | 完整比對 |
|---|---|
| `get_valid_f1_games` | 結尾（f1.py，回傳前）；2013-14 空資料回傳前；2017-18 依規則直接隔離、不載入快照（不需要）|
| `build_history`、`season_totals`、`prior_context` | 經由 `get_valid_f1_games` 結尾（之後只用複製出的數值）|
| `compute`／`compute_season` | 當季：`get_valid_f1_games` 結尾 + `compute` 結尾回傳前；上季／後備季：`prior_context` 內 `get_valid_f1_games` 結尾；2017-18 不可用：回傳前 |
| `season_of`（公開）| 回傳前 |
| `prior_source`、`DataAccess.f1_prior_source` | 當季與上季／後備季都在各自 `get_valid_f1_games` 結尾（在最後一次讀取之後）|
| `f1_reference` | 讀取之後呼叫的 `f1_prior_source` → `get_valid_f1_games` 結尾，對同一份快照完整比對 |

插樁測試確認：16 條回傳路徑，每一季快照最後一次讀取之後都有完整比對。反向驗證：把 `check_snapshot` 弱化成只做身分檢查，
16 條路徑與公開入口測試全部失敗。

## 效能

同一台機器依序執行：7db80cc 全套 390 項 147 秒；本版 405 項 153 秒（+4%）。完整比對次數：`get_valid_f1_games` 1 次、
`prior_source` 2 次、`f1_reference` 2 次、`compute` 3 次（有測試設上限）。

## 驗證

405 項全部通過。F1 九季輸出與 F5／Elo 一般路徑與 7db80cc 相同；11 季 flags 與重新稽核逐筆一致；分類表 14,228 列與重新分類逐筆一致；
原始資料、既有 flags、分類表、盤口模組、既有報告與稽核程式檔（audit_coverage／box_audit／game_class／integrity／store）都未變動，
所以 11 份 coverage 清單不需要重建。
