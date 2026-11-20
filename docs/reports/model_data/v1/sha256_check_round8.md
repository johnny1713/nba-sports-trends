# 原始資料與既有報告 SHA256 前後比對（2026-11-20 第八輪：2023-24 驗證期鎖定 + F1）

基準：本輪開始時的 commit eaba22f。方法：逐檔比較 `git show eaba22f:<path> | sha256sum`。

- data/raw/（含附加賽）、data/audit/、既有盤口品質與稽核報告：共 271 個檔案，**0 個變動**
- nba_quant/quality.py 未變動；data/derived/、data/ops/ 不存在（沒有任何凍結、驗證或正式測試登記）
- 本輪沒有抓取資料，沒有讀取 2023-24、2024-25、2025-26（除既有 data_quality 測試）
