# NBA Trends 專案筆記

NBA 每日賽事趨勢爬蟲 + GitHub Pages 儀表板，是 `johnny1713/mlb-sports-trends` 的姊妹專案。
**MLB 那份 CLAUDE.md 記了大量 covers.com 的坑與統計教訓，改這裡之前先讀那份。**
本檔只記 NBA 獨有的事。

## 使用情境（與 MLB 相同）

- 使用者在台灣，每天約 22:00 看網站，在 playsport.cc 下注，只在意命中率、不看 ROI。
- 手機瀏覽為主。回覆使用者一律用繁體中文。
- NBA 多在美東晚上 7~10 點開打＝台灣隔天早上 7~10 點，看盤時間比 MLB 寬鬆。

## 已確定的設計決定（2026-10-13 與使用者確認）

- **只做全場盤**（獨贏、全場讓分、全場大小分）。使用者在 playsport **不下半場／單節盤**。
- **季前賽不計分、不上線**。使用者明確表示季前賽不準；季前賽頁面的趨勢也混了季前賽紀錄
  （實測出現籃網「當熱門 6-0 ATS」這種不合理切片）。等例行賽開打才正式計分。
- **情境趨勢（covers 的 Recent Form）要參與判斷**——使用者的明確要求，理由是他過去的經驗。
  ⚠️ MLB 這類趨勢實測沒有加分效果（同向 80/156 = 51.3%，全部 235/441 = 53.3%），
  所以這裡的做法是：**每筆推薦同時記下「有加情境」與「沒加情境」兩種分數**，
  兩者的戰績都自動統計，讓資料決定。不要偷偷拿掉，也不要在沒有戰績前加重權重。

## covers.com NBA 頁面結構（2026-10-13 實測，samples/ 內有原始頁面）

與 MLB **幾乎相同**，MLB 的解析邏輯大多可沿用：

- 列表 `https://www.covers.com/sports/nba/matchups?selectedDate=YYYY-MM-DD`，`gamebox` article、
  `data-url=/sports/game/<id>`。
- 單場 `https://www.covers.com/sport/basketball/nba/matchup/<id>/picks`。
  ⚠️ 不帶 `/picks` 的頁面**沒有趨勢**（trends 段落 0 字元）。
- `<section id="trends">` 內 `<h4 class="... High|Low ...">`，未發佈時是 `Check back shortly`、約 600 字元。
- `single-form-trend` 一場 8 條（Recent Form／情境趨勢）。
- schema.org `startDate` 有兩種格式：`10/14/2026 00:00:00 +00:00` 與 ISO `2026-10-13T23:00:00+00:00`，兩種都要能解析。
- 2026-10-10 那幾場的 `/picks` 被導到一個 Odds Shark 的通用頁（三場內容相同），原因不明。
  正式爬蟲要偵測「頁面不是該場比賽」並跳過。

### ROI 趨勢（計分用）：絕大多數是單節／半場盤

實測 8 場 84 條，**全場盤只有 13 條**（獨贏 4、大小分 8、全場讓分 **1**），其餘是
1Q/2Q/3Q/4Q/1H/2H 與 Team Total。只做全場的話，每天可計分的趨勢很少，推薦會偏少——
這是使用者知情後選擇的取捨，不要為了「推薦太少」偷偷把半場盤加回來。
盤口名比對必須**完全比對**（`Moneyline`／`Spread`／`Game Total Over|Under`），
否則 `1Q Spread` 會被 `Spread` 吃掉。

### 情境趨勢：和 MLB 的三個差異

1. **有讓分（ATS）**：72 條裡 23 條（MLB 是 0 條）。句型：
   `Knicks are 6-0 ATS in their last 6 games as an underdog.`、
   `Over is 7-2 in Mavericks last 9 games playing on 1 days rest.`、
   `Over is 15-3 in the last 18 meetings.`（交手）、`Wizards are 0-5 ATS ...`（反向訊號）。
2. 樣本 4~18 場、平均 5.6；72 條裡 43 條 0 敗；9 場裡 5 場同時有大分與小分的高勝紀錄——與 MLB 同樣的選擇偏誤特徵。
3. ⚠️ **covers 會列出今天不成立的條件**。同一頁同時有
   `Bucks ... as a road favorite` 與 `Bucks ... as a road underdog`，公鹿今天不可能兩者皆是。
   **計分前必須先確認條件今天成立**，否則等於拿別種比賽的紀錄下注：

   | 條件 | 確認方式 |
   |---|---|
   | home / road | 賽事列表 |
   | favorite / underdog | 今天全場讓分的正負號 |
   | N days rest、following a loss/win、double-digit loss | 自己累積的賽程與比分 |
   | 對手上一場得失分等 | 第一版無法確認 → **只顯示不計分** |

## 程式架構（scrape.py v1.0，2026-10-13）

單檔、純標準庫。頁面在 Python 端直接產生 HTML（不像 MLB 用大段 JS 渲染），
所有資料另存在 `<script id="page-data">`，供 `--replay` 與下一輪沿用盤口。

| 輸出 | 用途 |
|---|---|
| `index.html` | 網站本體 |
| `history.json` | 每天的推薦（三種算法）與賽果，算戰績用 |
| `scores.json` | 近 7 天的計分板快取：算情境條件（休息天數、前一場勝負／得失分／有沒有過盤）與回填賽果 |

### 三種分數（核心設計，別合併）

每個市場（獨贏、讓分、大小分）、每一邊都算：
- **趨勢分**：ROI 全場趨勢，沿用 MLB「兩隊各自佐證」原則（押注隊有支持紀錄**且**對手有反向紀錄；
  大小分要兩隊都指向同方向），各取下界最高那條平均。單邊有資料不算。
  與 MLB 的差異：Low 的趨勢也換算成反向支持（`only hit Over 12 of 40` = 小分 28/40），
  因為 NBA 全場趨勢太少，只認 High 幾乎湊不出推薦。
- **情境分**：今天**確定成立**（`condition_applies` 回 True）的情境趨勢，換算成對這一邊有利的下界。
  **也要兩隊各自有佐證**（2026-10-20 使用者選擇，v1.1）：兩隊都要有今天適用的紀錄，缺一隊就不算；
  分數＝每隊紀錄下界的平均，再對兩隊（及交手紀錄）取平均，所以同隊反向紀錄會拉低分數。
  v1.0 只要一條適用就算，單一條 4-0 切片就有 70.9 分；改完後離線樣本 3 天的推薦從 5 筆降到 0 筆
  （尼克受讓那筆因暴龍「當熱門 4-0」反而支持暴龍，掉到 38.5）。**推薦會很少，這是使用者知情的取捨。**
- **綜合分**＝兩者平均（只有一個就用那個）。**畫面上的推薦一律是綜合分。**

`build_recommendations` 對 combined／trend／sit 三種算法**各自選邊**，三種都寫進 history.json，
戰績區有「兩種算法比較」表。這是驗證「情境趨勢到底有沒有用」的唯一方法，不要拿掉。

⚠️ **已知現象（2026-10-13 離線測試，v1.0）**：一條今天適用的 4-0 情境趨勢，下界就有 70.9；
5-0 是 75.3。全場趨勢最好的也才 60 出頭。所以 Top 5 會被情境分主導（v1.1 加了雙方佐證後緩和很多）——
這是使用者知情的選擇（他相信 NBA 情境趨勢準），由戰績表驗證，不要私下調權重。
若戰績顯示情境分沒有優勢，把證據攤給使用者看，讓他決定。

### 其他實作重點

- **季前賽**：列表 gamebox 標頭寫 `Pre Season`。預設整場跳過，頁面顯示「目前是季前賽」。
  `--include-preseason` 只給測試用，開了也不會寫 history。
- **頁面驗證**：賽前頁比對 schema.org 的 homeTeam/awayTeam，已完賽頁（沒有 schema）改比 og:title。
  兩者對不上就當抓取失敗（實測有網址被導到 Odds Shark 通用頁）。
- **盤口**：取列表 gamebox 的共識盤口（`team-consensus` 兩欄、`team-overunder`）。
  開打後列表就沒有盤口了，`known_lines()` 會沿用同一天上一輪 index.html 的值。
  沒有盤口時整個讓分／大小分市場跳過，不出沒有數字的推薦。
- **讓分的包含關係**一般化成 `margin_needed`：獨贏 1 分、盤口 s 需要 `floor(-s)+1` 分。
  同隊去重留最容易中的（與 MLB 相同，理由見 MLB CLAUDE.md）。
- **計分板的「誰過了讓分」**來自 gamebox 的 `summary-box`（"Brooklyn covered the spread of +3.5"），
  `following a ATS loss` 這類條件靠它判斷。
- 前一場是季前賽 → 情境條件回 None（無法確認），所以**例行賽第一週的前一場類條件都不會計分**，正常。

### 驗證方式

    python scrape.py --offline samples --date 2026-10-13 --include-preseason --out /tmp/t.html
    cp /tmp/t.html /tmp/t2.html && python scrape.py --replay --out /tmp/t2.html && cmp /tmp/t.html /tmp/t2.html

離線模式讀 `samples/`（`_offline_file` 對應網址→檔名），不寫 history／scores。
`--replay` 必須位元組相同。UI 改動另用 390px 檢查 `scrollWidth - clientWidth == 0`。

## 待辦

- **workflow 檔 Claude 無法推送**（token 沒有 workflow scope，git push 與 API 都被拒）。
  排程版放在 `setup/scrape.yml`，例行賽開打時請使用者複製到 `.github/workflows/scrape.yml`，
  並在 Settings → Pages 開啟（Deploy from branch: main / root）。
- 例行賽開打後：量趨勢發佈時間調整排程；確認 `Pre Season` 以外的標頭字樣（例如 NBA Cup）不影響判斷；
  跑一次不變式掃描（分數可由紀錄重算、盤口數字合理範圍要從實際分佈訂）。
- `samples/` 只是開發用，已由 `_config.yml` 排除在 Pages 之外。
