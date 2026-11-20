# 原始資料與既有報告 SHA256 前後比對（2026-11-20 第五輪）

基準：本輪開始時的 commit 50389de。方法：逐檔比較工作目錄 sha256 與 `git show 50389de:<path> | sha256sum`。

- data/raw/（含附加賽）、data/audit/source_compare/、既有盤口品質與稽核報告：共 257 個檔案，**0 個變動**
- data/derived/：不存在
- 本輪沒有抓取任何資料；新增 docs/reports/model_data/v1/feature_availability.md（新路徑）
