# NBA 量化推薦系統 V2：架構與資料模型（Phase 2）

> 舊版（`scrape.py` + 根目錄 `index.html`）在 V2 完成樣本外驗證之前**照常運作、不更動**。
> V2 所有檔案都是新增的，部署在 `/v2/`。

## 0. 驗收標準（優先於一切）

V2 的成敗只看一件事：**在嚴格的樣本外測試中，是否比「單純跟市場」更好**。
衡量指標見第 6 節。若證明不了優勢，網站如實顯示，不調降標準產生明牌。

## 1. 目錄結構

```
nba_quant/              # V2 程式（純邏輯，不碰 HTML）
  schema.py             # 資料模型與驗證
  store.py              # JSONL.gz 讀寫、sha256、原子寫入
  asof.py               # 防資料洩漏：依時間點與用途過濾資料
  sources/              # 資料取得（只負責抓與正規化，不做預測）
    espn.py             #   賽程、比分、box score、盤口、傷兵
    taiwan.py           #   台灣運彩盤口（手動 CSV／玩運彩）
  features/             # 特徵工程（只吃 asof 過濾後的資料）
  models/               # 各模型：market、elo、logistic、ridge、gbm、blend
  market.py             # 賠率換算、去水、EV、結算規則
  backtest/             # walk-forward、指標、報表
  render/               # 產生 v2/ 頁面（只讀預測結果 JSON）
  daily.py              # 每日流程進入點
  backfill.py           # 歷史資料回補進入點
tests/                  # 單元／API／回測測試
data/
  raw/espn/<季>/        # 歷史原始資料（每季一組 .jsonl.gz，完成的球季不再變動）
  snapshots/<日期>/     # 每次預測當下的輸入快照（重現用）
  predictions/<日期>.json
  taiwan/manual/<日期>.csv   # 手動輸入的台灣運彩盤口
  taiwan/scraped/<日期>.json # 自動取得的台灣盤口（若可行）
  ops/                  # 抓取日誌、API 錯誤紀錄（監控頁用）
models_store/<版本>/    # 模型參數（JSON，不用 pickle）＋ manifest
v2/                     # GitHub Pages 發佈的新版網站
docs/
```

## 2. 資料模型

所有紀錄都帶 `source`（來源）與 `fetched_at`（我們抓到的 UTC 時間）。

### 2.1 Game
| 欄位 | 說明 |
|---|---|
| `game_id` | ESPN event id |
| `season` | 結束年份（2025-26 季 = 2026）|
| `season_type` | 2 = 例行賽，3 = 季後賽（季前賽不收）|
| `start_utc` | 開賽時間（UTC，ISO 8601）|
| `home` / `away` | ESPN 隊伍縮寫 |
| `home_pts` / `away_pts` | 完賽比分，未完賽為 null |
| `status` | `scheduled` / `final` / `postponed` / `canceled` |
| `neutral` | 中立場 |

### 2.2 TeamBox（每場每隊一筆，**只能用於該場之後的預測**）
投籃、三分、罰球命中/出手、進攻/防守籃板、失誤、得分、延長賽次數，
以及球員列表（id、姓名、上場分鐘、得分、是否先發、未上場原因）。
回合數以 `FGA − OREB + TOV + 0.44 × FTA` 估算（兩隊平均），再算每 100 回合效率。

### 2.3 OddsQuote（**最容易洩漏的一張表**）
| 欄位 | 說明 |
|---|---|
| `game_id`, `provider` | |
| `stage` | `open` / `close` / `snapshot` / `current_postgame` |
| `market` | `ml` / `spread` / `total` |
| `side` | `home` / `away` / `over` / `under` |
| `line` | 讓分（主隊視角）或總分；獨贏為 null |
| `price_decimal` | 小數賠率；缺就 null，**絕不補值** |
| `observed_at` | 我們親眼看到的時間：`snapshot` 有，`open`/`close` 為 null（ESPN 沒給確切時間）|

`stage` 的規則：
- `open`：開盤，視為賽前可得 → 可用於預測與回測下注。
- `snapshot`：我們每輪自己抓的即時盤，帶 `observed_at` → 只有 `observed_at < 預測時間` 才可用。
- `close`：收盤 → **只能用於 CLV 與評估**，`asof.py` 拒絕把它交給預測用途。
- `current_postgame`：賽後才抓到的「current」，等同收盤，規則同 `close`。

### 2.4 InjuryReport（只有上線後的即時快照）
`team, player_id, player, status (Out/Doubtful/Questionable/Probable/Day-To-Day), comment, reported_at, fetched_at`。
**歷史傷兵不回補**（ESPN 過去比賽頁的傷兵清單不保證是賽前狀態）。
回測中的「傷兵」只用賽前已知的代理變數：「前 N 場缺陣」（由前幾場 box score 判定），並標示為代理值。

### 2.5 TaiwanQuote
`date_tw, home, away, market, side, line, price_decimal, source (manual|playsport), observed_at, note`。
沒有這筆資料時，畫面顯示「缺少台灣盤口，無法計算實際 EV」。**美國盤口絕不填入此表。**

### 2.6 Prediction（每筆推薦一筆，永久保存）
`game_id, market, side, line, p_model, p_market_devig, p_blend, price_tw, ev_tw, price_us, ev_us, tier,
reasons[], risks[], model_version, snapshot_path, snapshot_sha256, predicted_at`。

## 3. 防資料洩漏（要求 A）

1. 預測時間點 `T`：回測為「開賽當日美東 00:00」；上線為實際執行時間。
2. 球隊數據：只用 `start_utc` 在**比賽日之前**的比賽（同一天較早開打的也不用，避免時區邊界誤判）。
3. 盤口：只透過 `asof.quotes_for_prediction(quotes, T)` 取得，該函式只放行 `open` 與 `observed_at < T` 的 `snapshot`。
   `close` / `current_postgame` 只能經 `asof.quotes_for_evaluation()` 取得。
4. 傷兵：見 2.4，回測不假裝有賽前傷兵資料。
5. 特徵函式的輸入一律是已過濾的資料，測試會刻意塞入未來資料，確認輸出不變。

## 3.1 資料品質規則（Phase 3 補充要求）

- **例行賽與季後賽分開**：`season_type` 2／3 分開標記；品質報告、建模、回測一律分開評估，不得混合計算。
- **盤口品質標記另存**：`odds_flags.jsonl.gz`（`nba_quant/odds_flags.py`）。`error`（明顯錯誤）一律排除；
  `warning`（極端但可能真實，例如 −13000 的獨贏）預設排除，人工放行才可用。原始 `odds.jsonl.gz` 永不修改。
- **讓分方向唯一定義**：`nba_quant/lines.py`——以被押注那一隊的角度，負數 = 讓分、正數 = 受讓，
  主客兩邊一定相反；過盤 = 該隊淨勝分 + line > 0。ESPN 與玩運彩都已用測試確認符合此定義。
- **資料來源標記**：每場比賽 `box_source`（espn／bbref）、每筆 box score `source`、BBRef 球員 id 帶 `bbref:` 前綴；
  品質報告與測試都檢查三者一致。
- **模型訓練前必做：補值敏感度測試**。同一套 walk-forward 流程跑兩次——
  (A) 只用 ESPN 原生 box score 的比賽（BBRef 補值的比賽在特徵計算中視為缺漏），
  (B) ESPN + BBRef 補值。比較兩者的 Brier、Log Loss、預測分差的 MAE，以及逐場預測差異的分佈；
  差異的信賴區間若排除 0，就先調查原因，不進入正式訓練。結果寫入 docs/reports/。
- **盤口異常以單筆紀錄為單位排除**：只排除被標記的那一筆（某家、某階段、某盤口、某一邊），
  同場其他莊家、其他盤口、同組另一邊全部保留；只有整場資料都有問題時才會整場不可用。
- **讓分×獨贏方向矛盾的歸因**（2026-11-20 使用者決定）：同場同階段有 ≥ 3 家其他有效莊家時，以讓分中位數（±1 分）
  與獨贏熱門方向（≥ 2/3 一致）判斷錯在哪個市場，只排除錯的那個市場（兩邊都排除，讓分線雙邊共用）；
  無法歸因或不足 3 家時，兩個市場都排除。
- **抽水分級**（同一家、同一階段的雙邊價格；只適用美國莊家，台灣運彩不套用）：
  1.00～1.10 一般；1.10～1.25 或 0.98～1.00 偏高（warning，待確認）；> 1.25 或 < 0.98 錯誤。
- **盤口偏離市場**（2019-20 實測發現）：ESPN 的「賽後 current」對部分莊家其實是**比賽中最後的滾球盤**，
  數字接近最終結果，是資料洩漏。同場同階段 ≥ 4 家莊家、且 ≥ 2/3 的其他莊家落在共識範圍內時，
  偏離全體中位數（讓分 > 4、總分 > 6、獨贏去水勝率 > 0.15）判為錯誤，並註明是否比市場更接近實際結果。
  **評估用的「市場基準」一律取多家莊家的中位數，不用單一莊家**——單家的小幅污染（< 門檻）才不會影響結論。
  2024-25 起只有一家莊家，無法交叉比對：那段期間只用 ESPN 明確標記的 open／close 欄位。
- **ESPN 總分 ≤ 0（實測 -1）是缺失值佔位符**：視同沒有這筆盤口，計入缺漏、不計入異常。
- **各博彩公司原始盤口分開保存**；市場共識（中位數盤口、平均去水機率）只能另外計算、另存，不覆蓋原始資料。

## 4. 模型對照組（要求 B）

| 代號 | 模型 | 輸出 |
|---|---|---|
| M0 | 市場基準：去水後的市場機率 | 勝率、過盤率 |
| M1 | Elo（含主場、休息、分差修正）| 勝率、預期分差 |
| M2 | Logistic Regression | 勝率 |
| M3 | Ridge Regression | 預期分差、預期總分 → 以常態分佈轉過盤率 |
| M4 | Gradient Boosting（sklearn HistGradientBoosting）| 勝率／分差 |
| M5 | 市場與自主模型融合（logit 線性組合，權重由 walk-forward 決定）| 最終機率 |

所有機率都要經過校準（Platt／Isotonic，只用訓練期資料擬合）。

## 5. Walk-forward 與保留測試期（要求 D、F）

依 `docs/reports/2026-11-20_espn_odds_coverage.md` 的實測覆蓋率決定：

| 期間 | 球季 | 盤口狀況 | 用途 |
|---|---|---|---|
| 暖身 | 2014-15 | 只有收盤 | 只用來累積球隊數據，不評估 |
| 開發期 | 2015-16 ～ 2022-23 | 只有收盤 | 自主模型（M1～M4）逐季 walk-forward 訓練；**以收盤去水機率當評估基準**（Brier、Log Loss）。不做下注回測：沒有賽前價格 |
| 調參期 | 2023-24 | 開盤＋收盤，多家莊家 | 選融合權重、推薦門檻；以開盤價下注、收盤算 CLV |
| **鎖定測試期** | **2024-25、2025-26** | 開盤＋收盤，單一莊家 | 只在全部設計定案後評估一次；評估紀錄寫入 `data/ops/holdout_log.jsonl` |
| 上線期 | 2026-27 起 | 開盤＋收盤＋我們自己的即時快照 | 每天實際預測；台灣盤口另計 |

- 鎖定由程式強制（`HOLDOUT_SEASONS`）：一般回測指令遇到這兩季直接拒絕；必須加 `--final`。
- 融合模型（M5）需要市場機率當輸入，只能用**開盤**，所以 M5 的一切調整只在 2023-24 進行。
- 開發期用收盤當評估基準符合規則 A（收盤只用於評估）。

## 6. 評估指標（要求 C）

ROI、命中率、平均賠率、總投注、總獲利、平均 EV、Brier、Log Loss、CLV、最大連敗、最大回撤、
校準曲線（分箱）、依賠率區間的績效、依市場與推薦等級的績效。
**每張報表都附 M0（市場基準）的同期數字。** 期間：全季、近 30／60／90 天。

## 7. 版本與重現（要求 E）

- 模型版本 `v2.<major>.<minor>+<git sha>`；參數存 JSON（`models_store/<版本>/params.json`）。
- `manifest.json`：訓練區間、特徵清單、超參數、訓練資料檔的 sha256、程式碼 git sha、套件版本。
- 每次預測把當下用到的輸入寫成快照（`data/snapshots/`），預測紀錄存快照路徑與 sha256。
  重現方法：checkout 該 git sha，載入同一份快照與參數，輸出應逐位元組相同。

## 8. 部署

- 新增 workflow（token 沒有 workflow 權限，需由使用者手動加入，檔案放在 `setup/`）：
  - `v2-daily.yml`：每天抓資料、預測、產生 `/v2/`、跑測試。
  - `v2-backfill.yml`：手動觸發，分季回補歷史資料。
- 套件：`requirements-v2.txt`（numpy、pandas、scikit-learn、pytest），只在 Actions 安裝。
- API key 一律放 GitHub Secrets → 環境變數，程式碼不寫死。
- 舊版 `scrape.yml` 與每日 21:30 回報不變。
