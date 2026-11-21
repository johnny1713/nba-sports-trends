# 稽核完整性最小修正（2026-11-21 第三輪，基準 a922bcd）

範圍只限稽核完整性。F1 公式、先驗方案 A、M = 10、W = 0.5、100 場門檻、特徵定義都沒有修改；
F1 開發期九季完整輸出與 a922bcd、20db020 逐位相同。沒有開始 F2～F7，沒有訓練、調參、選模、回測或驗證。

## 修改檔案

| 檔案 | 修改 | 原因 |
|---|---|---|
| nba_quant/audit_coverage.py | 程式指紋改為三檔集合（各檔 sha + 組合）、CRLF→LF；讀取時強制重新稽核並逐筆比對；交叉驗證 `audited_team_box_count`、`raw_boxscore_file`；欄位結構檢查；統一錯誤代碼；原始檔與 flag 檔一次讀入（指紋、解析、重新稽核用同一份位元組）；新增 `verify_and_load` | 決策 1～4 |
| nba_quant/box_audit.py | 新增 `scope_from_records`；`audit_season` 可接收已讀取的範圍（`scope=`）。稽核規則未變（11 季重新稽核結果與既有 flag 檔逐筆相同）| 重新稽核不重複讀檔 |
| nba_quant/store.py | 新增 `parse_jsonl_gz_bytes`（與 `read_jsonl_gz` 規則相同，11 季 22 個原始檔實測解析結果相同）| 同上 |
| nba_quant/data_access.py | `box_audit_flags` 改用 `verify_and_load` 回傳的 flag，不再另外讀檔 | 驗證與使用同一份位元組 |
| nba_quant/features/f1.py | 只改兩處讀取順序／條件，不碰計算：先驗證稽核再讀 box；「無資料」例外另要求分類表沒有該季比賽 | 讓原始檔缺失得到 `raw_missing`；堵住下述缺口 |
| data/audit/box_quality/v1/coverage/*.json | 11 份重建 | 新欄位 `audit_code_files` |
| tests/conftest.py（新）| 測試期間的宣告稽核（見下）| 合成 F1 測試 |
| tests/test_f1.py、test_f1_loto_audit.py、test_f1_final_audit.py、test_audit_integrity.py | 測試更新與新增 | 決策 5 |

**本輪新發現並修正的缺口**：`da.games` 的賽程來自原始 games 檔，所以一季的兩個原始檔都被刪掉時賽程也會變空，
原本的例外條件（賽程空且兩個原始檔都不存在）會把它當成「沒有資料」而略過稽核；F1 隨之把上一季當成無資料，
先驗來源會被靜默換掉。現在例外還要求**分類表沒有該季任何比賽**，否則照常驗證並以 `raw_missing` 拒絕。
真實資料中符合例外的只有 2013-14（分類表 2015～2025 才有比賽）。

## 稽核程式指紋涵蓋範圍

| 檔案 | 理由 |
|---|---|
| nba_quant/box_audit.py | 稽核規則、稽核範圍定義 |
| nba_quant/audit_coverage.py | 清單產生與驗證規則 |
| nba_quant/store.py | 原始資料與 flag 檔的解析 |

三者的專案內 import 只有彼此，其餘為 Python 標準函式庫。`data_access.py` 與 F1 是 flag 的使用端，
不影響稽核結果或清單驗證，不納入（由 F1 測試與九季輸出比對把關），避免無關修改讓清單失效。
`audit_code_sha256` = sha256（依路徑排序，逐行「路徑:sha256」）；各檔 sha256 先把 CRLF 統一成 LF。

## 重新稽核逐筆比對

`verify` 每次以目前程式重新執行 `box_audit.audit_season`，與 flag 檔做**整筆、全部欄位、含順序**的比較：
`game_id`、`team`、`check`、`severity`、`level`、`source`、`detail`。F1 排除判定實際用到的是
`game_id`、`team`、`severity`，全部包含在內。任何差異 → `stale_audit`。
`build_manifest(verify_flags=False)` 可以寫出清單，但只要 flag 與重新稽核不一致，正式 `verify` 一律拒絕。
重新稽核使用計算指紋時已讀入的同一份原始位元組，不重複讀檔；每季約 0.1～0.2 秒。

**測試的宣告稽核**：F1 的合成測試需要指定稽核結果（例如同場層級 ERROR，v1 規則不會產生），
`tests/conftest.py` 只在測試期間、只對有 `synthetic_audit/<季>.json` 的暫存根目錄，把稽核結果換成宣告內容；
flag 檔仍須與它逐筆相同。稽核完整性測試與真實資料不使用宣告稽核；有測試確認正式程式沒有任何這種開關。

## 錯誤代碼

flags_missing、manifest_missing、manifest_unreadable（JSON 錯誤、空檔）、manifest_invalid（非物件、欄位缺漏或多出、型別錯）、
version、audit_code_mismatch（缺欄位、缺檔指紋、組合不一致、任何檔案變動、程式檔不存在）、content_hash、season、
raw_file_mismatch、raw_missing、raw_unreadable、raw_boxscore_hash、raw_games_hash、flags_hash、flags_unreadable、
duplicate_ids、count、not_all_audited、scope_mismatch（ID 或球隊 box 數不符）、flag_outside_scope、stale_audit。
所有例外都轉成帶代碼的 `AuditIntegrityError` 後拋出，不吞例外、不降級。

## 11 份清單重建（保留原稽核事件時間）

與 a922bcd 的清單逐欄比較，只有 `audit_code_files`（新增）、`audit_code_sha256`、`content_sha256` 不同，其餘欄位完全相同。

| 球季 | 已稽核場數 | 球隊 box | flag 筆數 | flag vs 重新稽核 | content_sha256 | 檔案 sha256 |
|---|---|---|---|---|---|---|
| 2014-15 | 1,311 | 2,622 | 14 | 逐筆相同 | `3933afe3e7dcecf7` | `4cf83d8bff2fe81c` |
| 2015-16 | 1,316 | 2,632 | 15 | 逐筆相同 | `d49bf267e0c4bb06` | `cac4b3bb5edc1fbc` |
| 2016-17 | 1,309 | 2,618 | 10 | 逐筆相同 | `ec766bcea3ecbfd5` | `2c384d6792ad6890` |
| 2017-18 | 1,312 | 2,624 | 1,010 | 逐筆相同 | `5f7e3241a2610099` | `44781084ef0c5869` |
| 2018-19 | 1,312 | 2,624 | 28 | 逐筆相同 | `d29868aaec868fcd` | `7858507be28ee498` |
| 2019-20 | 1,142 | 2,284 | 9 | 逐筆相同 | `8c191dab9c3eaa90` | `eec033aabf8b1379` |
| 2020-21 | 1,165 | 2,330 | 7 | 逐筆相同 | `34d688e6d60e28e3` | `e61fd5f09a52fadd` |
| 2021-22 | 1,317 | 2,634 | 12 | 逐筆相同 | `2b07891b2eb9f9c7` | `c0e13c9f0d04cf42` |
| 2022-23 | 1,314 | 2,628 | 9 | 逐筆相同 | `f7a794873c444895` | `991a3015f46aeb56` |
| 2023-24 | 1,313 | 2,626 | 14 | 逐筆相同 | `d92da3cd0f4780cc` | `f29758c68951e3fd` |
| 2024-25 | 1,315 | 2,630 | 15 | 逐筆相同 | `c1f0ee769efdd98f` | `beb51ef0810fe73f` |

## 測試

**344 項全部通過**（a922bcd 為 325 項）。`test_audit_integrity.py` 由 33 項增為 52 項。對應決策 5：

| # | 要求 | 測試 |
|---|---|---|
| 1～3 | 改 box_audit.py／audit_coverage.py／store.py，舊清單拒絕 | test_code_01_03_any_code_file_changed_refused（三檔各一，複製到暫存目錄實際修改）|
| 4 | CRLF 與 LF 指紋一致 | test_code_04_crlf_and_lf_checkout_same_fingerprint |
| 5 | 缺 audit_code_sha256 | test_code_05_missing_audit_code_sha256_refused |
| 6 | 缺單一程式檔指紋 | test_code_06（另 06b 偽造單檔、06c 組合不一致、06d 程式檔不存在）|
| 7 | 改重要欄位並重算 content_sha256 仍拒絕 | test_07_important_fields_with_recomputed_content_refused（7 個欄位）；其餘竄改測試也一律重算 |
| 8 | verify_flags=False 的不一致 flag | test_08_verify_flags_false_inconsistent_flags_refused、test_08b（少一筆；改 severity／team／check／detail）|
| 9 | 重新稽核一致時通過 | test_09_reaudit_matches_flags_passes、RealData.test_all_seasons_coverage_verified |
| 10 | 格式錯誤／空檔／非物件／原始檔不存在 | test_10a～10g |
| 11 | 2013-14 例外正反向 | NoRawDataException（正向 1、反向 3）|

## 變更檢查（相對 a922bcd 與 20db020）

原始資料 195 檔、既有 flag（box 稽核 11、盤口 11）、其他稽核檔 36、盤口品質模組 4、既有報告 26，共 283 檔：**0 變動**。
F1 開發期九季完整輸出 sha256：與 a922bcd、20db020 **全部相同**。
