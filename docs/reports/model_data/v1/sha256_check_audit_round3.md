# 原始資料與既有報告 SHA256 前後比對（2026-11-21：稽核完整性第三輪）

基準：a922bcd 與 20db020（兩者結果相同）。方法：逐檔比較 `git show <基準>:<path> | sha256sum` 與目前檔案。

| 範圍 | 檔案數 | 變動 |
|---|---|---|
| data/raw/（不含 flag）| 195 | 0 |
| 既有 flag 檔（box 稽核 v1 11 檔、盤口 odds_flags 11 檔）| 22 | 0 |
| data/audit/ 其他既有檔（來源比對、summary 等，不含 coverage 清單）| 36 | 0 |
| quality.py、odds_flags.py、clv.py、price_time.py | 4 | 0 |
| docs/reports/（model_data 以外，含盤口品質報告）| 26 | 0 |

- 重建：`data/audit/box_quality/v1/coverage/2015.json`～`2025.json`（只有 audit_code_files、audit_code_sha256、content_sha256 不同）。
- F1 開發期九季完整輸出 sha256 與 a922bcd、20db020 相同；data/derived/、data/ops/ 不存在。
