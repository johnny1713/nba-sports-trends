# 附加賽（Play-In）資料品質報告

唯讀報告。附加賽獨立存放在 `data/raw/espn_playin/<季>/`，不混入 `data/raw/espn/`，也不進例行賽訓練樣本（`train_sample` = False）。2025-26 為鎖定測試期，不抓取。

## 1. 總覽

| 球季 | 預期 | 找到 | box 來源 | 兩隊 box 完整 | 得分恆等式 | 得分 = ESPN 計分板 | ESPN vs BBRef 10 欄位全一致 | 只有失誤不一致 | 原始檔 sha256 | 分類表 game_type |
|---|---|---|---|---|---|---|---|---|---|---|
| 2019-20 | 1 | 1 | espn 1 | 1/1 | 1/1 | 1/1 | 1/1 | 0 | 3/3 相符 | PLAY_IN 1 |
| 2020-21 | 6 | 6 | bbref（ESPN 無資料） 6 | 6/6 | 6/6 | 6/6 | 不適用 | — | 19/19 相符 | PLAY_IN 6 |
| 2021-22 | 6 | 6 | espn 6 | 6/6 | 6/6 | 6/6 | 1/6 | 5 | 19/19 相符 | PLAY_IN 6 |
| 2022-23 | 6 | 6 | espn 6 | 6/6 | 6/6 | 6/6 | 3/6 | 3 | 19/19 相符 | PLAY_IN 6 |
| 2023-24 | 6 | 6 | espn 6 | 6/6 | 6/6 | 6/6 | 2/6 | 4 | 19/19 相符 | PLAY_IN 6 |
| 2024-25 | 6 | 6 | espn 6 | 6/6 | 6/6 | 6/6 | 6/6 | 0 | 19/19 相符 | PLAY_IN 6 |

## 2. 失誤欄位定義（ESPN 有 box score 的場次）

| 球季 | 球隊紀錄 | ESPN total = 球員 + 全隊 | ESPN 球員加總 = BBRef 球員加總 | BBRef 球隊合計 = 球員加總（不含全隊失誤）| ESPN total = BBRef 球隊合計 |
|---|---|---|---|---|---|
| 2019-20 | 2 | 2/2 | 2/2 | 2/2 | 2/2 |
| 2021-22 | 12 | 12/12 | 12/12 | 12/12 | 6/12 |
| 2022-23 | 12 | 12/12 | 12/12 | 12/12 | 6/12 |
| 2023-24 | 12 | 12/12 | 12/12 | 12/12 | 7/12 |
| 2024-25 | 12 | 12/12 | 12/12 | 4/12 | 12/12 |

判讀：
- ESPN 內部一致（total = 球員 + 全隊）且球員失誤與 BBRef 100% 相同；ESPN 的定義與正式回補資料相同（`totalTurnovers`）。
- 2021-22～2023-24 的 BBRef 附加賽頁面，球隊合計**不含全隊失誤**（36/36 筆 = 球員加總），所以只要該隊有全隊失誤，ESPN 就比 BBRef 多。這是 BBRef 頁面的定義差異，不是 ESPN 錯誤；ESPN 球員加總與 BBRef 一致可佐證。
- 2024-25 的 BBRef 頁面含全隊失誤，與 ESPN 12/12 相同。2019-20 那場兩隊全隊失誤都是 0，無法判斷 BBRef 當時的定義。
- **2020-21 只有 BBRef**（ESPN 球隊統計空白、球員數字全 0）。BBRef 球隊合計 12/12 = 球員加總，**不含全隊失誤**，與正式資料的失誤定義不同，且沒有來源可以補上。使用該季附加賽失誤時須標註此限制。

## 3. 逐場

| 球季 | Game ID | 開賽 UTC | 對戰 | 比分 | ESPN 備註 | game_type | box 來源 |
|---|---|---|---|---|---|---|---|
| 2019-20 | 401236333 | 2020-08-15T18:30:00Z | MEM @ POR | 122–126 | WEST PLAY-IN - GAME 1 | PLAY_IN | espn |
| 2020-21 | 401326988 | 2021-05-18T22:30:00Z | CHA @ IND | 117–144 | NBA Play-In - East - 9th Place vs 10th Place | PLAY_IN | bbref |
| 2020-21 | 401326989 | 2021-05-19T01:00:00Z | WSH @ BOS | 100–118 | NBA Play-In - East - 7th Place vs 8th Place | PLAY_IN | bbref |
| 2020-21 | 401326990 | 2021-05-19T23:30:00Z | SA @ MEM | 96–100 | NBA Play-In - West - 9th Place vs 10th Place | PLAY_IN | bbref |
| 2020-21 | 401326991 | 2021-05-20T02:00:00Z | GS @ LAL | 100–103 | NBA Play-In - West - 7th Place vs 8th Place | PLAY_IN | bbref |
| 2020-21 | 401326993 | 2021-05-21T00:00:00Z | IND @ WSH | 115–142 | NBA Play-In - East - 8th Seed Game | PLAY_IN | bbref |
| 2020-21 | 401326994 | 2021-05-22T01:00:00Z | MEM @ GS | 117–112 | NBA Play-In - West - 8th Seed Game | PLAY_IN | bbref |
| 2021-22 | 401428070 | 2022-04-12T23:00:00Z | CLE @ BKN | 108–115 | NBA Play-In - East - 7th Place vs 8th Place | PLAY_IN | espn |
| 2021-22 | 401428071 | 2022-04-13T01:30:00Z | LAC @ MIN | 104–109 | NBA Play-In - West - 7th Place vs 8th Place | PLAY_IN | espn |
| 2021-22 | 401428072 | 2022-04-13T23:00:00Z | CHA @ ATL | 103–132 | NBA Play-In - East - 9th Place vs 10th Place | PLAY_IN | espn |
| 2021-22 | 401428073 | 2022-04-14T01:30:00Z | SA @ NO | 103–113 | NBA Play-In - West - 9th Place vs 10th Place | PLAY_IN | espn |
| 2021-22 | 401428074 | 2022-04-15T23:30:00Z | ATL @ CLE | 107–101 | NBA Play-In - East - 8th Seed Game | PLAY_IN | espn |
| 2021-22 | 401428075 | 2022-04-16T02:00:00Z | NO @ LAC | 105–101 | NBA Play-In - West - 8th Seed Game | PLAY_IN | espn |
| 2022-23 | 401539671 | 2023-04-11T23:30:00Z | ATL @ MIA | 116–105 | NBA Play-In - East - 7th Place vs 8th Place | PLAY_IN | espn |
| 2022-23 | 401539672 | 2023-04-12T02:00:00Z | MIN @ LAL | 102–108 | NBA Play-In - West - 7th Place vs 8th Place | PLAY_IN | espn |
| 2022-23 | 401539673 | 2023-04-12T23:00:00Z | CHI @ TOR | 109–105 | NBA Play-In - East - 9th Place vs 10th Place | PLAY_IN | espn |
| 2022-23 | 401539674 | 2023-04-13T01:50:00Z | OKC @ NO | 123–118 | NBA Play-In - West - 9th Place vs 10th Place | PLAY_IN | espn |
| 2022-23 | 401539675 | 2023-04-14T23:00:00Z | CHI @ MIA | 91–102 | NBA Play-In - East - 8th Seed Game | PLAY_IN | espn |
| 2022-23 | 401539676 | 2023-04-15T01:50:00Z | OKC @ MIN | 95–120 | NBA Play-In - West - 8th Seed Game | PLAY_IN | espn |
| 2023-24 | 401654655 | 2024-04-16T23:30:00Z | LAL @ NO | 110–106 | NBA Play-In - West - 7th Place vs 8th Place | PLAY_IN | espn |
| 2023-24 | 401654656 | 2024-04-17T02:00:00Z | GS @ SAC | 94–118 | NBA Play-In - West - 9th Place vs 10th Place | PLAY_IN | espn |
| 2023-24 | 401654659 | 2024-04-17T23:00:00Z | MIA @ PHI | 104–105 | NBA Play-In - East - 7th Place vs 8th Place | PLAY_IN | espn |
| 2023-24 | 401654658 | 2024-04-18T01:48:00Z | ATL @ CHI | 116–131 | NBA Play-In - East - 9th Place vs 10th Place | PLAY_IN | espn |
| 2023-24 | 401654660 | 2024-04-19T23:00:00Z | CHI @ MIA | 91–112 | NBA Play-In - East - 8th Seed Game | PLAY_IN | espn |
| 2023-24 | 401654661 | 2024-04-20T01:30:00Z | SAC @ NO | 98–105 | NBA Play-In - West - 8th Seed Game | PLAY_IN | espn |
| 2024-25 | 401766458 | 2025-04-15T23:30:00Z | ATL @ ORL | 95–120 | NBA Play-In - East - 7th Place vs 8th Place | PLAY_IN | espn |
| 2024-25 | 401766459 | 2025-04-16T02:00:00Z | MEM @ GS | 116–121 | NBA Play-In - West - 7th Place vs 8th Place | PLAY_IN | espn |
| 2024-25 | 401766460 | 2025-04-16T23:30:00Z | MIA @ CHI | 109–90 | NBA Play-In - East - 9th Place vs 10th Place | PLAY_IN | espn |
| 2024-25 | 401766461 | 2025-04-17T02:00:00Z | DAL @ SAC | 120–106 | NBA Play-In - West - 9th Place vs 10th Place | PLAY_IN | espn |
| 2024-25 | 401766462 | 2025-04-18T23:00:00Z | MIA @ ATL | 123–114 | NBA Play-In - East - 8th Seed Game | PLAY_IN | espn |
| 2024-25 | 401766463 | 2025-04-19T01:30:00Z | DAL @ MEM | 106–120 | NBA Play-In - West - 8th Seed Game | PLAY_IN | espn |
