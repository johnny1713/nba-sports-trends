# 稽核涵蓋清單：版本驗證與可重現性最終審查（2026-11-21）

基準：commit ddd1b82（F1 數值基準 20db020）。只修改稽核完整性驗證（`nba_quant/audit_coverage.py`）與其測試；
沒有修改 F1 公式、先驗方案 A、M = 10、W = 0.5、100 場門檻；沒有開始 F2～F7，沒有訓練、調參、選模、回測或驗證。

## 審查發現（ddd1b82）

| # | 項目 | ddd1b82 | 修正後 |
|---|---|---|---|
| 1a | 讀取時比較 `audit_code_sha256` 與目前執行的稽核程式 | **FAIL**：只寫入、從未比較 | PASS：`verify` 以目前 `box_audit.py` 的 sha256 比對，不符 → `audit_code_hash` |
| 1b | 只檢查 `audit_version` 字串 | **FAIL**：是 | PASS：版本字串與程式指紋都檢查 |
| 1c | 程式改了但版本忘記更新 | **FAIL**：會放行 | PASS：拒絕（`audit_code_hash`）|
| 1d | 版本升級但舊清單仍在 | PASS：拒絕（`version`）| PASS |
| 2a | 序列化固定欄位順序與格式 | PASS：`store.write_json` 鍵排序、indent 1、UTF-8、結尾換行 | PASS |
| 2b | `audit_timestamp` 讓相同資料重跑的檔案 SHA256 不同 | **是**（實測同資料不同時間重建，檔案 sha256 不同）| 仍是（刻意：時間是事件 metadata）|
| 2c | 能區分稽核事件時間與稽核內容指紋 | **FAIL**：沒有內容指紋 | PASS：新增 `content_sha256` |

## 修正

- `verify` 在版本檢查後比較 `audit_code_sha256` 與目前實際執行的稽核程式指紋。代價：`box_audit.py` 任何改動（含註解）
  都會讓 11 份清單失效，必須重跑 `python -m nba_quant.box_audit` 與 `python -m nba_quant.audit_coverage`——這是 fail closed 的預期行為。
- 內容指紋 `content_sha256` = sha256（清單排除 `audit_timestamp`、`content_sha256` 後，鍵排序、無空白的 UTF-8 JSON）。
  排除的欄位記在清單的 `content_excluded_fields`。讀取時重算，不符或缺漏 → `content_hash`（同時擋下手動竄改與舊格式清單）。
- 11 份清單以 `build_manifest` 重建（重跑稽核、結果與既有 flag 檔逐筆相同），**保留原稽核事件時間**；
  原有欄位逐一比對全部相同，只新增 `content_excluded_fields` 與 `content_sha256`。

| 球季 | 已稽核場數 | 內容指紋 content_sha256 | 檔案 sha256 |
|---|---|---|---|
| 2014-15 | 1,311 | `888bfe79715d6074` | `7a50bfeaa307043a` |
| 2015-16 | 1,316 | `624798e03d8e4870` | `e7036acf5c9d2b6f` |
| 2016-17 | 1,309 | `18df88aeb4df416b` | `f52f2a32cf744ae1` |
| 2017-18 | 1,312 | `4ff0f06eaad96d38` | `f4cf8e85e8434c9b` |
| 2018-19 | 1,312 | `983ee02242746572` | `cf0ae72710b3996d` |
| 2019-20 | 1,142 | `63faa34dd7740347` | `e3d944c43a10726d` |
| 2020-21 | 1,165 | `65077c4318cc3cf6` | `a41548174142aab8` |
| 2021-22 | 1,317 | `259f4f302c67418f` | `a7dec853aec0b75d` |
| 2022-23 | 1,314 | `fe3c9b1f2bc533ca` | `3f57212bc38e74c6` |
| 2023-24 | 1,313 | `09f9f6fc6a24c199` | `a4be8f19ccedb9c7` |
| 2024-25 | 1,315 | `7ff637fd0ea0ca33` | `b485cdc23af1e114` |

## 新增測試（7 項，`tests/test_audit_integrity.py`）

| 測試 | 驗證 |
|---|---|
| test_08c | 稽核程式指紋改變、版本字串未更新、保留舊清單 → 拒絕 `audit_code_hash` |
| test_08d | 不用 mock 指紋函式：實際換一份多一行註解的稽核程式檔 → 拒絕 |
| test_08e | 程式要求版本升為 v2、舊 v1 清單仍在 → 拒絕 `version` |
| test_08f | 程式與清單完全相符 → 通過 |
| test_08g | 改清單內容未更新內容指紋、或移除內容指紋 → 拒絕 `content_hash` |
| test_content_fingerprint_independent_of_timestamp | 不同時間重建：內容指紋相同，唯一差異欄位是 `audit_timestamp` |
| test_content_fingerprint_changes_with_content | flag 改變 → 內容指紋改變 |

既有的真實資料測試另加：coverage 目錄恰為 2015～2025 共 11 份，且每份的程式指紋 = 目前程式。

## 最終驗收

| 項目 | 結果 |
|---|---|
| 測試 | PASS：325 項（ddd1b82 的 318 項 + 7 項）|
| 11 份清單完整且驗證通過 | PASS |
| 2013-14 無資料例外（賽程空且原始檔都不存在才回傳空集合）| PASS（test_season_without_any_raw_data_needs_no_audit）|
| 2017-18 隔離 | PASS |
| 2023-24～2025-26 鎖定 | PASS |
| 原始資料、既有 flag、盤口品質模組、既有報告（283 檔，相對 20db020）| PASS：0 變動 |
| F1 開發期 9 季完整輸出 vs 20db020 | PASS：sha256 全部相同 |
