# 原始資料與既有報告 SHA256 前後比對（2026-11-20 第七輪：鎖定規則修訂 + Elo stage 1）

基準：本輪開始時的 commit 3feeacc。方法：逐檔比較工作目錄 sha256 與 `git show 3feeacc:<path> | sha256sum`。

- data/raw/（含附加賽）、data/audit/、既有盤口品質與稽核報告：共 271 個檔案，**0 個變動**
- nba_quant/quality.py：未變動；data/derived/、data/ops/（holdout log）：不存在（沒有任何凍結或正式測試登記）
- 本輪沒有抓取任何資料；新增 data/reference/start_time_flags.csv（4 場時間異常的登記，不修改原始資料）
