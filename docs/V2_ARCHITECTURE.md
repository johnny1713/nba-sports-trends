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
  raw/espn_playin/<季>/ # 附加賽（Play-In）獨立存放：原始回應 + 解析 + 來源紀錄；不混入 raw/espn/（2020～2025；2026 鎖定）
  reference/            # 分類表（不修改原始資料）：neutral_sites.csv、game_classification.csv
  audit/                # 唯讀稽核輸出：source_compare/（ESPN vs BBRef）、box_quality/v1/、model_data/v1/
  derived/              # 經使用者核准的修正版（目前沒有；2017-18 失誤修正版未核准）
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
| `season_type` | ESPN 賽事類型：2 = 例行賽，3 = 季後賽，5 = 附加賽（只在獨立的 play-in 目錄出現；正式回補只收 2、3）。**不可單獨用來判斷資料用途**，見 2.7 |
| `start_utc` | 開賽時間（UTC，ISO 8601）|
| `home` / `away` | ESPN 隊伍縮寫 |
| `home_pts` / `away_pts` | 完賽比分，未完賽為 null |
| `status` | `scheduled` / `final` / `postponed` / `canceled` |
| `neutral` | 中立場 |

### 2.7 比賽分類（`data/reference/game_classification.csv`，2026-11-20 使用者決策）

| 欄位 | 說明 |
|---|---|
| `game_type` | REGULAR_SEASON／CUP_GROUP／CUP_QUARTERFINAL／CUP_SEMIFINAL／CUP_FINAL／PLAY_IN／POSTSEASON |
| `counts_for_standings` | **只**表示是否計入官方例行賽勝敗紀錄。CUP_FINAL、PLAY_IN、POSTSEASON 為 False |
| `use_team_stats` | F1 球季累計效率、F2 近期狀態：一般例行賽＋盃賽冠軍戰 True；PLAY_IN、POSTSEASON False |
| `use_fatigue` | F5 賽程疲勞特徵（休息天數、背靠背、四天三賽）：所有實際出賽皆 True |
| `use_elo` | Elo 歷史更新：所有比賽皆 True，依開賽時間順序 |
| `train_sample` | 第一版訓練樣本：例行賽（含盃賽各階段與冠軍戰）True；PLAY_IN、POSTSEASON False |
| `eval_group` | regular / play_in / postseason |

規則：
- 戰績類計算一律用 `counts_for_standings`，不可用 `season_type == 2`（盃賽冠軍戰 ESPN 仍標為 2）。
- `counts_for_standings` 不可用來決定其他特徵或樣本；每種用途讀自己的欄位。
- Elo 預測只用開打前已知的評分；Elo 更新清單與訓練樣本清單分開。
- 賽事類型只有 `game_type` 一個來源；其他表格（如中立場表）不得自設賽事類型名稱。
- 盃賽冠軍戰的比賽數據可用於效率、近期狀態、模型訓練；Elo 可納入但必須保留 `game_type`。
- PLAY_IN 不混入例行賽訓練資料；保留完整 box score 供獨立分析。
- 用途矩陣見 `docs/V2_MODEL_STAGE1_DESIGN.md` 3.2。

### 2.7.1 品質統計的兩套程式（2026-11-20 第四輪，方案 A）

| 程式 | 用途 | 狀態 |
|---|---|---|
| `nba_quant/quality.py` | 盤口品質 v1（PASS／FAILED、盤口覆蓋率）| **凍結**：不修改；既有報告不重新產生（含 .md 同分列順序不固定的既有問題）|
| `nba_quant/model_data_stats.py` | 模型資料統計 v1：依分類表計算各用途場數、box 覆蓋率、失誤可用性 | 新增；輸出到 `data/audit/model_data/v1/`、`docs/reports/model_data/v1/` |

- 新產生的報告一律使用固定的次要排序鍵（例如 game_id、provider 名稱），相同資料重跑輸出位元組相同。
- 失誤可用性：`tov_definition` 與 `tov_usable` 由 model_data_stats 判定；2017-18 整季與 2020-21 附加賽（BBRef 不含全隊失誤）不可用於需要總失誤的特徵。

### 2.7.2 特徵依賴與可用性（第五輪，`nba_quant/feature_deps.py`）

- 每個特徵登記依賴（基礎欄位 → 中間量 → 特徵）與跨球季方式（prior／window）；可用性只由這裡判定，沿依賴鏈遞迴傳遞。
- 2017-18 `tov` 整季不可用 → 回合數、Pace、ORtg／DRtg／淨值、失誤率不可用；eFG%、進攻籃板率、罰球率、比分類特徵可用。
- 2018-19 依賴上季先驗或季初視窗的特徵不得使用 2017-18 的值或比賽。
- 模型輸入以 `check_model_inputs()` 檢查；未登記特徵報錯。
- Elo：同一美東日期所有比賽都用前一日結束時的評分；game_id 只作同時開賽的排序鍵。

### 2.7.3 資料存取層（第六輪，`nba_quant/data_access.py`）

- 特徵、模型、回測、頁面程式只能透過 `DataAccess(purpose)` 讀資料；直接讀原始資料會被結構測試擋下。
- 模型凍結前：2024-25 只有 data_quality 可讀；2025-26 任何用途都拒絕。模型凍結後：每季分別登記、每季一次、只限 final_evaluation，結果分開保存；看過結果後改模型 → 永久標記失去獨立性（`config.holdout_independence()`）。
- 2023-24 驗證期（第八輪）：凍結前只限 data_quality；凍結後登記一次 validation。歷史特徵生成 `history_features` 必須帶 as_of，且目標球季須已授權，不得輸出指標。
- 時間（前一美東日期）、範圍（分類表用途欄位）、欄位可用性（2017-18 tov、tov_usable）、盤口隔離、特徵依賴檢查都在這一層強制。
- 跨球季 fallback：F2 不跳過不可用球季、不足標 missing；F1 先驗改用當時可取得的聯盟平均（見設計文件 3.5）。

### 2.8 中立場（`data/reference/neutral_sites.csv`）

- 不修改 games.jsonl.gz 的 `neutral` 欄位；ESPN 的 `neutral` 旗標本身不算證據。
- 判定需要兩個獨立來源（例：ESPN 賽事備註或 ESPN 場館 + BBRef 場館），或使用者明確指定；BBRef 場館不能單獨作判定依據。
- 證據不足一律 unknown，不推測。每列保留證據來源與判定理由。

### 2.9 Box score 來源規則（2026-11-20）

- 2017-18 ESPN 失誤欄位錯位：該季所有依賴失誤的特徵停用；候選公式只列為 high-agreement candidate；
  不產生 derived 修正版、不以 BBRef 整季覆蓋 ESPN（核准前）。
- 來源比對結果須標示範圍：2017-18 為全季逐場，其他季為抽樣（每季 30 場），抽樣結果不可宣稱全季驗證。
- box score 合理性稽核 `box_quality/v1` 與盤口品質報告分開保存，不影響盤口 PASS 狀態。
- 稽核 fail closed（2026-11-21）：每季獨立的稽核涵蓋清單 `box_quality/v1/coverage/<季>.json`（`nba_quant/audit_coverage.py`），
  記錄原始檔指紋、逐場已稽核清單與稽核程式指紋（box_audit.py、audit_coverage.py、store.py）；`DataAccess.box_audit_flags` 讀取前驗證並**重新稽核逐筆比對**，任何不符一律以帶代碼的 AuditIntegrityError 拒絕。
  重新回補原始資料後必須重跑 `python -m nba_quant.box_audit` 與 `python -m nba_quant.audit_coverage`。

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

`stage` 的規則（每筆價格另由 `nba_quant/price_time.py` 依**實際存在的時間欄位**判定時間性質）：

| 時間性質 | 條件 | 用途 |
|---|---|---|
| PROVIDER_LABELED_OPEN / CLOSE | 供應商欄位標示為開盤／收盤，**沒有時間戳**（ESPN 全部屬於此類）| 可依標記使用，但不能宣稱已獨立驗證取得時間 |
| TIMESTAMP_VERIFIED_OPEN / CLOSE | 有供應商時間戳 `provider_timestamp`，且早於開賽 | 可確認是賽前價格 |
| PREGAME_SNAPSHOT | 我們自己在開賽前抓到（`observed_at` < 開賽）| 賽前價格 |
| POSTGAME_SNAPSHOT | 賽後取得的 current | **不是收盤**；只供品質稽核 |
| INVALID_AFTER_START | 時間戳或抓取時間 ≥ 開賽 | 不可當賽前價格 |

- **不推測、不補造時間**：開盤／收盤只看 `provider_timestamp`；`fetched_at`（我們的抓取時間）不是價格時間。
- **CLV 的收盤只能是 PROVIDER_LABELED_CLOSE 或 TIMESTAMP_VERIFIED_CLOSE**（`price_time.clv_closing_quotes()`、入口 `assert_clv_close()`）。
- 每季品質報告揭露各類別筆數與「收盤時間戳驗證比例」（ESPN 目前為 0%）。
- 未來若改用有時間戳的來源，`classify()` 會自動把早於開賽的收盤升級為 TIMESTAMP_VERIFIED_CLOSE，晚於開賽的判為無效。

原有規則：
- `open`：開盤，視為賽前可得 → 可用於預測與回測下注。
- `snapshot`：我們每輪自己抓的即時盤，帶 `observed_at` → 只有 `observed_at < 預測時間` 才可用。
- `close`：真正的收盤（CLOSING，ESPN 明確標記）→ **只能用於 CLV 與賽前市場基準的評估**，透過 `asof.closing_quotes()` 取得。
- `current_postgame`：**POSTGAME_SNAPSHOT（賽後快照）——不是收盤**。賽後才抓到，部分莊家已證實混入比賽中盤口。
  不得用於賽前模型訓練、賽前市場基準、CLV 或任何需要賽前資訊的回測評估；只能透過
  `asof.postgame_snapshots_for_audit()` 做資料品質稽核。評估函式入口一律呼叫 `asof.assert_no_postgame()`。
  （2026-11-20 使用者決定；早期設計曾寫「等同收盤」，已更正。）

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
  **評估用的「市場基準」只能用真正的收盤（CLOSING），一律取多家莊家的中位數，不用單一莊家**——單家的小幅污染（< 門檻）才不會影響結論。
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
| 暖身 | 2014-15 | 開盤線（無價格）＋賽後快照 | 只用來累積球隊數據，不評估 |
| 開發期 | 2015-16 ～ 2022-23 | 開盤線（無價格）＋**賽後快照（POSTGAME_SNAPSHOT，非收盤）** | 自主模型（M1～M4）逐季 walk-forward 訓練與機率評估（對實際結果的 Brier、Log Loss）。**沒有可用的賽前市場基準，不做「模型 vs 市場」比較，也不做下注回測或 CLV** |
| 調參期 | 2023-24 | 開盤＋收盤（CLOSING），多家莊家 | 選融合權重、推薦門檻；以開盤價下注、收盤算 CLV；第一次「模型 vs 市場」比較 |
| **鎖定測試期** | **2024-25、2025-26** | 開盤＋收盤，單一莊家 | 只在全部設計定案後評估一次；評估紀錄寫入 `data/ops/holdout_log.jsonl` |
| 上線期 | 2026-27 起 | 開盤＋收盤＋我們自己的即時快照 | 每天實際預測；台灣盤口另計 |

- 鎖定由程式強制（`HOLDOUT_SEASONS`）：一般回測指令遇到這兩季直接拒絕；必須加 `--final`。
- 融合模型（M5）需要市場機率當輸入，只能用**開盤**，所以 M5 的一切調整只在 2023-24 進行。
- **2022-23 品質狀態 FAILED**（ESPN BET 收盤讓分／總分欄位系統性填入賠率；其他 11 家只有賽後快照，沒有同階段替代）。
  使用者 2026-11-20 以獨立的「人工繼續回補授權」允許繼續 2023-24；授權不改變該季狀態、不套用到其他球季。
- **2023-24 起開盤／收盤嚴格覆蓋**：每個市場的可用開盤與收盤都須覆蓋 ≥ 95% 完賽比賽，賽後快照不能替代；
  單一莊家年份出錯時沒有替代來源，維持不通過（人工有條件放行也不可能成立）。

### 待檢查項目（賽後快照曾被當成收盤）

| 位置 | 狀態 |
|---|---|
| `asof.quotes_for_evaluation()` 把 close 與 current_postgame 一起回傳（原設計會用來算 CLV）| 已移除，改為 `closing_quotes()`／`postgame_snapshots_for_audit()`／`assert_no_postgame()` |
| 本文件期間表：開發期「以收盤去水機率當評估基準」 | 已更正：開發期沒有賽前市場基準 |
| `config.py` 期間註解「只有收盤」 | 已更正 |
| 品質報告覆蓋率表 | 已標示為 POSTGAME_SNAPSHOT（非收盤） |
| 模型、市場融合、回測程式 | 尚未撰寫；撰寫時入口必須呼叫 `assert_no_postgame()`，並有測試 |
| 品質稽核用到賽後快照的地方（偏離市場檢查、Opening 提供者一致性） | 只用於資料品質判定，不影響模型；保留 |

## 6. 評估指標（要求 C）

ROI、命中率、平均賠率、總投注、總獲利、平均 EV、Brier、Log Loss、CLV、最大連敗、最大回撤、
校準曲線（分箱）、依賠率區間的績效、依市場與推薦等級的績效。
**每張報表都附 M0（市場基準）的同期數字。** 期間：全季、近 30／60／90 天。

## 6.1 CLV 規範（2026-11-20 使用者決定，`nba_quant/clv.py`）

CLV 的任何計算都只能使用 `clv.pair_open_close()` 產生的配對：

1. 同一場比賽的開盤與收盤，必須來自**同一家**博彩公司。
2. 必須是**相同市場**（讓分／總分／獨贏）且**相同方向**（主／客、大／小）。
3. 不允許跨博彩公司、跨市場、跨方向配對：配對鍵是 (game_id, provider, market, side)，結構上無法混配；計算入口另有 `assert_valid_pair()` 逐筆檢查。
4. 缺開盤或缺收盤時，該筆不計入 CLV；**不得**用賽後快照、其他莊家或其他階段的價格補值。
5. 開盤須為 PROVIDER_LABELED_OPEN／TIMESTAMP_VERIFIED_OPEN；收盤須為 PROVIDER_LABELED_CLOSE／TIMESTAMP_VERIFIED_CLOSE。
6. 被品質標記排除的單筆紀錄不參與配對。
7. 去水所需的另一邊價格，也必須是**同一家、同一市場、同一階段**的報價，不得借用其他莊家。
8. CLV 報告必附 `clv.pairing_report()`：有效配對數、有效場次、排除數、依原因與市場的排除明細、收盤的時間性質（是否經時間戳驗證）。

### Line CLV 與 Price CLV（兩個獨立指標，分開呈現）

| 指標 | 市場 | 定義（正值 = 下注時比收盤更有利）| 不計算的情況 |
|---|---|---|---|
| **Line CLV**（分）| 讓分 | 以押注那隊角度：下注線 − 收盤線（押 −5.5、收 −7.5 → +2）| 獨贏：不適用（`not_applicable_moneyline_has_no_line`）|
| | 總分 | 大分：收盤線 − 下注線；小分：下注線 − 收盤線 | |
| **Price CLV**（機率）| 全部 | 同一家去水後隱含機率：收盤 − 下注時 | 讓分／總分的下注線 ≠ 收盤線：不可比（`line_moved_price_not_comparable`），不把線位變動混進價格 |

- **不可因為 Line CLV 為正就認定 Price CLV 也為正**：兩者各自報告有效筆數、平均值、正值比例（`clv.clv_metrics_report()`）。
- **獨贏另外處理**：只有 Price CLV，不套用讓分的線位算法。
- 舊介面 `clv_prob()` 等同 Price CLV，不可比時直接報錯。

排除原因代碼：`missing_open`、`missing_close`、`open_not_pregame`、`close_not_clv_eligible`、`missing_price`、`flagged_record`、`missing_same_book_other_side_for_devig`。

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
