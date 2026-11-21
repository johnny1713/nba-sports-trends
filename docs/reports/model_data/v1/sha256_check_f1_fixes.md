# 原始資料與既有報告 SHA256 前後比對（2026-11-21：F1 缺口修正）

基準：commit aff54ca。方法：逐檔比較 `git show aff54ca:<path> | sha256sum`。

- data/raw/（含附加賽）、data/audit/、既有盤口品質與稽核報告：共 271 個檔案，**0 個變動**
- 盤口品質與盤口相關模組（quality.py、odds_flags.py、clv.py、price_time.py）未變動
- data/derived/、data/ops/ 不存在；本輪沒有抓取資料，沒有讀取 2023-24、2024-25、2025-26 的真實資料（鎖定期相關測試使用合成資料）
- F1 開發期（2014-15～2022-23）所有特徵值與狀態與 aff54ca 逐位相同
