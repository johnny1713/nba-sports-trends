# 原始資料與既有報告 SHA256 前後比對（2026-11-20 第四輪）

基準：本輪開始時的 commit 2baacb3。方法：逐檔比較工作目錄 sha256 與 `git show 2baacb3:<path> | sha256sum`。

- data/raw/（含 2019-20～2024-25 附加賽）與 data/audit/source_compare/：239 個檔案，**0 個變動**
- 既有盤口品質與稽核報告（docs/reports/data_quality/ 與 docs/reports/*.md、*.csv）：18 個，**0 個變動**
- data/derived/：不存在
- 本輪沒有抓取任何資料；新增檔案只有 data/audit/model_data/v1/summary.json 與 docs/reports/model_data/v1/README.md（新路徑）
