# F1 資料一致性與稽核完整性修正（2026-11-21，問題 1、問題 2）

基準 commit：20db020。本輪**只**修正有效資料一致性與稽核完整性：
**沒有修改 F1 公式、先驗方案 A、M = 10、W = 0.5、100 場門檻或任何特徵定義**；沒有開始 F2～F7，
沒有訓練、調參、選模、回測或驗證。開發期 2014-15～2022-23 的 F1 完整輸出（列、排除、警告）與 20db020 **逐位相同**
（9 季 sha256 全部一致）。

## 問題 1：唯一有效比賽入口

`nba_quant/features/f1.py::get_valid_f1_games(da, season, as_of=None, exclude_team=None)`，依序：
F1 用途檢查 → 2017-18 不可用（回傳 unavailable，不讀任何資料）→ as-of（美東日期嚴格早於 as_of）→ 完賽且 `use_team_stats`
→ 兩隊 box 齊全 → 稽核 ERROR 排除（先驗證涵蓋清單，fail closed）→ 回合數有效 → leave-one-team-out → WARNING 記錄。
回傳 `rows`、`game_ids`、`excluded`、`loto_excluded`、`warnings`、`status`。

實際呼叫路徑：

| 用途 | 路徑 |
|---|---|
| F1 球隊累計、`league_games_asof` | `compute()` → `get_valid_f1_games(da, season)`，逐日累計（當日比賽隔日才加入）|
| `league_games_asof_excl_team`、100 場門檻、當季 LOTO 聯盟先驗 | `compute()` 同一份有效列，扣除目標隊參與的有效列 → `_prior()` |
| 上季 ORtg/DRtg/Pace 先驗（隊與聯盟）、後備球季聯盟平均 | `prior_context()` → `season_totals()` → `get_valid_f1_games(da, prev)` |
| `DataAccess.f1_prior_source()` | 委派 `f1.prior_source()` → `get_valid_f1_games(da, season, as_of, exclude_team=team)` + `prior_context()` → 同一個 `_prior()` |
| `build_history()` | 相容名稱，直接回傳 `get_valid_f1_games(da, season)` |

資料存取層已沒有任何自行計數的程式碼。`compute()` 為效能以逐日累計使用整季有效集合；
測試逐列證明它與「每列各自呼叫 `get_valid_f1_games(as_of, exclude_team)`」的場數、ID 集合與先驗來源完全相同（T42）。

## 問題 2：稽核 fail closed

新模組 `nba_quant/audit_coverage.py`，清單存放於獨立路徑 `data/audit/box_quality/v1/coverage/<季>.json`
（排序鍵 JSON，可重現）。**沒有修改原始 box、既有 flag 檔或盤口品質模組。**
`box_audit.py` 只新增 `audit_scope()`（稽核範圍的唯一定義，清單也用它）與 `root` 參數；
重新稽核 2014-15～2024-25 的結果與既有 flag 檔逐筆相同。

產生（`build_manifest`）時會重跑稽核，結果必須與既有 flag 檔逐筆相同，否則拒絕（`stale_audit`）。
讀取（`verify`，`DataAccess.box_audit_flags` 每次呼叫）檢查，任一不符即拋出 `AuditIntegrityError`：

| 代碼 | 檢查 |
|---|---|
| flags_missing / manifest_missing | flag 檔、清單存在 |
| version | `audit_version` = `box_quality_v1` |
| season | 清單球季相符 |
| raw_boxscore_hash / raw_games_hash | 原始 teambox、賽程檔指紋 |
| flags_hash | flag 檔指紋 |
| duplicate_ids / count | 無重複、數量欄位 = ID 數 |
| not_all_audited | 應稽核 = 已稽核 |
| scope_mismatch | 清單 = 目前原始資料推得的比賽（沒有未稽核、沒有多餘）|
| flag_outside_scope | flag 只出現在已稽核比賽 |

唯一例外：某季賽程為空**且**原始 games／teambox 檔都不存在（完全沒有資料；實際只有 2014-15 的上一季 2013-14）→ 空集合。

清單範例（2022-23，ID 清單截斷顯示）：

```json
{
 "audit_code_sha256": "0961c3de73c49dfd4956c341df85a3e8cc6228c890f4cfa5075b9fb77bc98e24",
 "audit_timestamp": "2026-11-21T08:55:36+00:00",
 "audit_version": "box_quality_v1",
 "audited_game_count": 1314,
 "audited_game_ids": ["401468016", "401468017", "401468018", "…(共 1314)"],
 "audited_team_box_count": 2628,
 "expected_game_count": 1314,
 "expected_game_ids": ["401468016", "401468017", "401468018", "…(共 1314)"],
 "flags_file_hash": "7718ea631cb7a98b1351c120caaa3ed8edf80ac9ca2218ddaf5df87e78a14419",
 "raw_boxscore_file": "data/raw/espn/2023/teambox.jsonl.gz",
 "raw_boxscore_file_hash": "32e89bebe2607f436b42a89dc3d9b2e28d80fea467b101dc523d5eb02a2fec64",
 "raw_games_file_hash": "aa38dbe9660a969e59d01ddc33eb63b27cb93729b480b55dbee56b88fc7f296a",
 "season": 2023
}
```

每季涵蓋與原始指紋比對（清單內 vs 目前檔案）：

| 球季 | 應稽核 | 已稽核 | 球隊 box | 清單內指紋 | 目前檔案指紋 | 結果 |
|---|---|---|---|---|---|---|
| 2014-15 | 1,311 | 1,311 | 2,622 | `954505ef8233` | `954505ef8233` | 相符 |
| 2015-16 | 1,316 | 1,316 | 2,632 | `7afcb574d136` | `7afcb574d136` | 相符 |
| 2016-17 | 1,309 | 1,309 | 2,618 | `b7a0c5d81d0f` | `b7a0c5d81d0f` | 相符 |
| 2017-18 | 1,312 | 1,312 | 2,624 | `407fc235e76d` | `407fc235e76d` | 相符 |
| 2018-19 | 1,312 | 1,312 | 2,624 | `3daf67a87faa` | `3daf67a87faa` | 相符 |
| 2019-20 | 1,142 | 1,142 | 2,284 | `800c3c9d25db` | `800c3c9d25db` | 相符 |
| 2020-21 | 1,165 | 1,165 | 2,330 | `aac98e427b1a` | `aac98e427b1a` | 相符 |
| 2021-22 | 1,317 | 1,317 | 2,634 | `32b371c6e4cd` | `32b371c6e4cd` | 相符 |
| 2022-23 | 1,314 | 1,314 | 2,628 | `32e89bebe260` | `32e89bebe260` | 相符 |
| 2023-24 | 1,313 | 1,313 | 2,626 | `61e32d19d177` | `61e32d19d177` | 相符 |
| 2024-25 | 1,315 | 1,315 | 2,630 | `b83e5ee825ef` | `b83e5ee825ef` | 相符 |

2023-24、2024-25 的清單只做資料品質用途（重跑稽核、計算指紋），F1 對這兩季仍在讀稽核之前就被鎖定拒絕；2025-26 沒有原始資料。

## 三場已知 ERROR

| game_id | 球季 | 原因 | 結果 |
|---|---|---|---|
| 401161297 | 2019-20 | DET tov = 0（box 稽核 v1 ERROR）| 排除於雙方累計，`excluded` reason = box_audit_error |
| 401468217 | 2022-23 | 同上 | 同上 |
| 401468616 | 2022-23 | 同上 | 同上 |

由 `get_valid_f1_games` 排除（T42 真實資料測試）；把三場 box 改成極端值後，原清單失效、F1 拒絕計算（`raw_boxscore_hash`），
以原稽核判定重建清單後 2019-20、2020-21、2022-23 F1 逐位不變（T40 已更新）。

## 測試

全部 **318 項通過**（基準 292 項 + 新增 26 項 `tests/test_audit_integrity.py`）。要求的 13 項對應：

| # | 要求 | 測試 |
|---|---|---|
| 1 | audit 檔缺失 | test_01_flag_file_missing_refused |
| 2 | 空 audit 檔且無清單 | test_02_empty_flag_file_without_manifest_refused |
| 3 | 缺一筆 audited_game_id | test_03_one_audited_id_missing_refused、test_03b |
| 4 | 多一筆不存在的 ID | test_04_extra_nonexistent_id_refused、test_04b |
| 5 | 重複 game ID | test_05_duplicate_id_refused（另 test_05b 數量欄位）|
| 6 | 改一個原始 box 欄位 | test_06_one_raw_box_field_changed_refused |
| 7 | 新增一場比賽 | test_07_new_game_invalidates_old_manifest（含只偽造指紋仍拒絕）|
| 8 | 稽核版本不符 | test_08_audit_version_incompatible_refused |
| 9 | 完整稽核、無 ERROR 的季通過 | test_09_fully_audited_season_without_error_passes |
| 10 | 有 ERROR 的季仍排除 | test_10_error_missing_and_invalid_poss_excluded_consistently、RealData.test_10_real_error_games_excluded |
| 11 | f1_prior_source 與 F1 集合相同 | test_11_prior_source_and_f1_use_identical_valid_set、RealData.test_11、test_threshold_99_fails_100_passes |
| 12 | 2017-18 隔離 | RealData.test_12_2017_18_isolated（另既有隔離測試）|
| 13 | 2023-24～2025-26 鎖定 | RealData.test_13_locked_seasons_refused_before_audit（另既有鎖定測試）|

既有測試的調整：合成資料根目錄改由 `test_f1.seal()` 寫入空 flag 檔並產生清單（修改原始檔或注入 flag 後重新封存）；
直接改原始 box 的兩項真實資料測試改為先斷言拒絕、再以原稽核判定重建清單；`test_f1_fixes` 的模擬改為 patch `get_valid_f1_games`。
沒有放寬任何既有斷言。
