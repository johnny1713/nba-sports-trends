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

**核心規則（v1.4，使用者 2026-10-20 逐條確認）：兩隊的紀錄要「條件相對應」才配成一對。**

| 對應方式 | 例子 |
|---|---|
| 主↔客對調 | 全場：A 主場 8/10 配 B 客場 1/10 |
| 熱門↔冷門對調 | 情境：A 主場當熱門 5-0 配 B 客場當冷門 0-5 |
| 其他條件相同 | 情境：A 前一場輸球後 配 B 前一場輸球後 |
| **休息天數不論幾天都算同一類** | A 休 1 天 9-1 配 B 休 2 天 1-9（使用者明確要求）|
| 星期幾算同一類 | 至今 MLB 400 版／NBA 樣本都沒出現過星期幾的趨勢，程式已預先支援 |

- 只用今天**確定成立**的紀錄（全場趨勢的主客場也要符合今天）。
- **全場只配全場、情境只配情境**，不跨來源。
- **兩隊交手紀錄只顯示、不計分**（使用者：要兩邊各自都有紀錄）。
- **方向檢查（v1.8）**：配成對的兩組，**原始**過盤率都要偏向押注這邊才算——勝負盤「A >50% ＋ B <50%」，
  大小分兩隊都 >50% 同方向。v1.7 只取平均，開幕日尼克 30/40 配 76 人 24/45（76 人自己 53%）
  被平均成 51.4 上榜，使用者指出「理論上要一邊大於 50% 另一邊小於 50% 才會推吧」。
- 每對分數 = (A 那組平均 + B 那組平均) / 2，每條換算成「對押注這邊有利」的 Wilson 下界；
  兩邊都是自己贏的話（A 當冷門 6-0、B 當熱門 4-0）會互相抵銷到 50 以下。
- **推薦分數 = 所有配對（全場＋情境）的平均，權重相同**。配不成對的紀錄只顯示。

`build_recommendations` 另外算「只用全場配對」（趨勢分）與「只用情境配對」（情境分），
三種各自選邊、都寫進 history.json，戰績區比較表靠它驗證，不要拿掉。

演變：v1.0 平均兩種分數、情境一條就算 → v1.1 情境要兩隊都有 → v1.2 兩種來源混在一起 →
v1.3 拿掉 8 場樣本下限 → **v1.4 條件要相對應**。都是 2026-10-20 開幕日前與使用者來回確認的結果。

全場趨勢與 MLB 的差異：
- **沒有 8 場樣本下限**（v1.3，使用者 2026-10-20）：兩種紀錄平等，情境 4-0 算、全場 7-0 不算說不過去；
  小樣本交給 Wilson 下界打折。
- Low 的趨勢也換算成反向支持（`only hit Over 12 of 40` = 小分 28/40），
因為 NBA 全場趨勢太少，只認 High 幾乎湊不出推薦。

⚠️ **已知現象（2026-10-13 離線測試，v1.0）**：一條今天適用的 4-0 情境趨勢，下界就有 70.9；
5-0 是 75.3。全場趨勢最好的也才 60 出頭。所以 Top 5 會被情境分主導（v1.1 加了雙方佐證後緩和很多）——
這是使用者知情的選擇（他相信 NBA 情境趨勢準），由戰績表驗證，不要私下調權重。
若戰績顯示情境分沒有優勢，把證據攤給使用者看，讓他決定。

### 其他實作重點

- **季前賽**：列表 gamebox 標頭寫 `Pre Season`。預設整場跳過，頁面顯示「目前是季前賽」。
  `--include-preseason` 只給測試用，開了也不會寫 history。
- ⚠️ **趨勢區兩隊是兩個巢狀 `<section>`**（away-team-section／home-team-section）。v1.6 以前取「到第一個
  `</section>` 為止」，**第二隊（通常是主隊）的全場趨勢整個漏掉**，開幕日每場都只有客隊有趨勢——
  使用者一眼看出「怎麼每場都只有一隊」，我卻解釋成「covers 還沒發佈」。v1.7 改成取到下一個
  `<section class="cardWrapper` 為止。**又是「解析壞掉和沒發佈長得一樣」**（MLB CLAUDE.md 第 10 點），
  下結論前先去原始頁面數 `team-section` 有幾個。MLB 是整頁找 h4，沒有這個問題。
  另外 covers 發佈是**分隊陸續**的：同一場可能先只有一隊的 section。
- **頁面驗證**：賽前頁比對 schema.org 的 homeTeam/awayTeam，已完賽頁（沒有 schema）改比 og:title。
  兩者對不上就當抓取失敗（實測有網址被導到 Odds Shark 通用頁）。
- **盤口**：取列表 gamebox 的共識盤口（`team-consensus` 兩欄、`team-overunder`）。
  ⚠️ **例行賽的 `team-consensus` 裡多了下注比例 `<strong>38%</strong>`，季前賽沒有**（2026-10-20 開幕前發現）。
  v1.4 以前要求 span 內沒有標籤，例行賽會**每一場都讀不到讓分 → 讓分市場整個被靜默跳過**。
  現在先拿掉 `<strong>` 再取數字，讀不到時印警告。用季前賽頁面測試抓不到這種差異——**開季要用開季的頁面驗證**。
  開打後列表就沒有盤口了，`known_lines()` 會沿用同一天上一輪 index.html 的值。
  沒有盤口時整個讓分／大小分市場跳過，不出沒有數字的推薦。
- **讓分的包含關係**一般化成 `margin_needed`：獨贏 1 分、盤口 s 需要 `floor(-s)+1` 分。
  同隊去重留最容易中的（與 MLB 相同，理由見 MLB CLAUDE.md）。
- **計分板的「誰過了讓分」**來自 gamebox 的 `summary-box`（"Brooklyn covered the spread of +3.5"），
  `following a ATS loss` 這類條件靠它判斷。
- 前一場是季前賽 → 情境條件回 None（無法確認），所以**例行賽第一週的前一場類條件都不會計分**，正常。
  **連「休息天數」也不拿季前賽來算**（使用者 2026-10-20 明確決定：只用例行賽，季前賽不能算）。
  我曾建議休息天數例外，被否決，別再改。

### 驗證方式

    python scrape.py --offline samples --date 2026-10-13 --include-preseason --out /tmp/t.html
    cp /tmp/t.html /tmp/t2.html && python scrape.py --replay --out /tmp/t2.html && cmp /tmp/t.html /tmp/t2.html

離線模式讀 `samples/`（`_offline_file` 對應網址→檔名），不寫 history／scores。
`--replay` 必須位元組相同。UI 改動另用 390px 檢查 `scrollWidth - clientWidth == 0`。

### 星期幾的趨勢：covers 沒有、Odds Shark 已併入 covers（2026-10-20 查證）

使用者記得以前有「週三 18 場過 16 場」這種趨勢——**是真的**，2023 年 Odds Shark 還獨立時有
（例：「Cavaliers are 6-14 ATS in their last 20 on a Tuesday」）。但現在 oddsshark.com 的
NBA 網址全部導回 covers（`samples/oddsshark/`），句型與 covers Recent Form 相同，112 句零星期幾；
MLB 400 個歷史版本也零。`cond_key`／`condition_applies` 已預先支援星期幾，出現了會自動配對。

唯一的路是自己用 covers 計分板（`summary-box` 有誰過讓分）回填整季算週X戰績。
**使用者決定先不做**：自己切 7 天 × 30 隊 = 210 個切片必然長出巧合的「18 過 16」。
等戰績表證明情境趨勢有用再說。

### 為什麼幾乎沒有讓分推薦（2026-10-30 查證，使用者決定維持現狀）

開幕 11 天 81 場，讓分推薦（連候選）一筆都沒有：全場趨勢的讓分只有 11 條（獨贏 111、大小分 107）；
情境的讓分雖有 96 條今天適用，但兩隊都有的只 7 場、條件對應的 2 對、一高一低的 0 對。
曾提議「冷門隊獨贏改推受讓」（受讓 ⊇ 獨贏，命中率只會更高），**使用者回「不用，自己判斷」**——
別再自動加這個轉換。

## 待辦

- **workflow 檔 Claude 無法推送**（token 沒有 workflow scope，git push 與 API 都被拒）。
  排程版放在 `setup/scrape.yml`，例行賽開打時請使用者複製到 `.github/workflows/scrape.yml`，
  並在 Settings → Pages 開啟（Deploy from branch: main / root）。
- 例行賽開打後：量趨勢發佈時間調整排程；確認 `Pre Season` 以外的標頭字樣（例如 NBA Cup）不影響判斷；
  跑一次不變式掃描（分數可由紀錄重算、盤口數字合理範圍要從實際分佈訂）。
- `samples/` 只是開發用，已由 `_config.yml` 排除在 Pages 之外。
