# 原始資料與既有報告 SHA256 前後比對（2026-11-20 第六輪）

基準：本輪開始時的 commit d62cb81。方法：逐檔比較工作目錄 sha256 與 `git show d62cb81:<path> | sha256sum`。

- data/raw/（含附加賽）、data/audit/（含 model_data）、既有盤口品質與稽核報告：共 271 個檔案，**0 個變動**
- nba_quant/quality.py：未變動
- data/derived/：不存在
- 本輪沒有抓取任何資料，也沒有讀取 2025-26；2024-25 只在 data_quality 用途的測試中讀取（確認附加賽 6 場可讀）
