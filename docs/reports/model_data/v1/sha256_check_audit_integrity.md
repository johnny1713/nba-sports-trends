# 原始資料與既有報告 SHA256 前後比對（2026-11-21：稽核完整性與 F1 有效集合修正）

基準：commit 20db020。方法：逐檔比較 `git show 20db020:<path> | sha256sum` 與目前檔案。

| 範圍 | 檔案數 | 變動 |
|---|---|---|
| data/raw/（含附加賽與 BBRef 後備檔）| 206 | 0 |
| data/audit/（既有 flag 檔、來源比對、summary）| 47 | 0 |
| quality.py、odds_flags.py、clv.py、price_time.py | 4 | 0 |
| docs/reports/（model_data 以外的既有報告，含盤口品質報告）| 26 | 0 |

- 新增（獨立路徑，不覆蓋任何既有檔）：`data/audit/box_quality/v1/coverage/2015.json`～`2025.json`（11 檔）。
- data/derived/、data/ops/ 不存在（沒有任何凍結、驗證或正式測試登記）。
- 本輪沒有抓取資料；F1 開發期 9 季完整輸出 sha256 與 20db020 相同。
