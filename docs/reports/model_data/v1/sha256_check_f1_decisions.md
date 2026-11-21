# 原始資料與既有報告 SHA256 前後比對（2026-11-21：F1 決策落實——方案 A、LOTO、欄位、box 稽核 ERROR 排除）

基準：commit 12a7ea1。方法：逐檔比較 `git show 12a7ea1:<path> | sha256sum`。

- data/raw/（含附加賽）、data/audit/（含 box 稽核 v1 旗標）、既有盤口品質與稽核報告：共 271 個檔案，**0 個變動**
- quality.py、odds_flags.py、clv.py、price_time.py 未變動；data/derived/、data/ops/ 不存在
- 本輪沒有抓取資料，沒有讀取 2023-24、2024-25、2025-26 的真實資料
