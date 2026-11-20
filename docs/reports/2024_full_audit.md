# 2023-24 完整資料品質報告（ESPN season 2024）

## 判定：**PASS**

- 通過
- 門檻（未修改）：盤口 error 比例 < 1%；開盤／收盤各市場可用覆蓋率 ≥ 95%；完賽資料完整率 ≥ 99%

## 1. 場次與完整度

| 項目 | 例行賽 | 季後賽 |
|---|---|---|
| 場次（含延賽） | 1233 | 82 |
| 完賽 | 1231 | 82 |
| 資料完整 | 1231 | 82 |
| 完整率 % | 100.0 | 100.0 |
| ESPN box score 缺漏 | 0 | 0 |
| BBRef 補值 | 0 | 0 |
| 補值後仍不完整 | 0 | 0 |
| 盤口缺漏場次 | 0 | 0 |
| 每場莊家數中位數 | 10 | 1.0 |

- 狀態：例行賽 {'final': 1231, 'postponed': 2}；季後賽 {'final': 82}
- 每隊例行賽 82～83 場（30 隊；83 場者為 NBA 盃冠軍賽兩隊，ESPN 列為例行賽）
- 資料來源標記不一致：0 場；box score 合理性問題：0；重複 game_id：0

## 2. 盤口階段分類

- 筆數：{'close': 76930, 'open': 75722}
- 時間性質：{'PROVIDER_LABELED_CLOSE': 76930, 'PROVIDER_LABELED_OPEN': 75722}
- **賽後快照（POSTGAME_SNAPSHOT）：0 筆**——本季沒有任何賽後快照，開盤／收盤全部來自 ESPN 明確標記的欄位
- 收盤時間戳驗證比例：0.0%（ESPN 不提供時間戳；只能依供應商標記使用）

## 3. 各市場開盤／收盤可用覆蓋率（排除被標記紀錄後，至少一家雙邊齊全）

| 階段/市場 | 例行賽 % | 季後賽 % |
|---|---|---|
| open/spread | 99.59 | 96.34 |
| open/total | 99.92 | 100.0 |
| open/ml | 99.84 | 100.0 |
| close/spread | 100.0 | 100.0 |
| close/total | 100.0 | 100.0 |
| close/ml | 100.0 | 100.0 |

- 品質門檻計算（全季合併）：{'close/ml': 100.0, 'close/spread': 100.0, 'close/total': 100.0, 'open/ml': 99.85, 'open/spread': 99.62, 'open/total': 99.92}

## 4. 各博彩公司逐家覆蓋率（雙邊齊全且有價格；未排除標記）

| 博彩公司 | 階段/市場 | 例行賽 % | 季後賽 % |
|---|---|---|---|
| MGM | close/ml | 99.92 | 24.39 |
| MGM | close/spread | 99.92 | 24.39 |
| MGM | close/total | 99.92 | 24.39 |
| MGM | open/ml | 99.76 | 24.39 |
| MGM | open/spread | 98.29 | 24.39 |
| MGM | open/total | 99.76 | 24.39 |
| BetfairSportsbook | close/ml | 99.84 | 24.39 |
| BetfairSportsbook | close/spread | 99.84 | 24.39 |
| BetfairSportsbook | close/total | 99.84 | 24.39 |
| BetfairSportsbook | open/ml | 98.13 | 24.39 |
| BetfairSportsbook | open/spread | 98.13 | 24.39 |
| BetfairSportsbook | open/total | 99.68 | 24.39 |
| DraftKings | close/ml | 99.84 | 24.39 |
| DraftKings | close/spread | 99.84 | 24.39 |
| DraftKings | close/total | 99.84 | 24.39 |
| DraftKings | open/ml | 92.28 | 24.39 |
| DraftKings | open/spread | 92.28 | 24.39 |
| DraftKings | open/total | 99.68 | 24.39 |
| Unibet | close/ml | 99.84 | 24.39 |
| Unibet | close/spread | 99.84 | 24.39 |
| Unibet | close/total | 99.84 | 24.39 |
| Unibet | open/ml | 98.29 | 24.39 |
| Unibet | open/spread | 98.29 | 24.39 |
| Unibet | open/total | 99.68 | 24.39 |
| ESPN BET | close/ml | 99.59 | 100.0 |
| ESPN BET | close/spread | 99.68 | 100.0 |
| ESPN BET | close/total | 99.68 | 100.0 |
| ESPN BET | open/ml | 98.62 | 100.0 |
| ESPN BET | open/spread | 98.54 | 100.0 |
| ESPN BET | open/total | 99.51 | 100.0 |
| Titanbets | close/ml | 98.86 | 24.39 |
| Titanbets | close/spread | 98.86 | 24.39 |
| Titanbets | close/total | 98.86 | 24.39 |
| Titanbets | open/ml | 97.64 | 24.39 |
| Titanbets | open/spread | 97.24 | 24.39 |
| Titanbets | open/total | 98.29 | 24.39 |
| Caesars Sportsbook (New Jersey) | close/ml | 98.46 | 24.39 |
| Caesars Sportsbook (New Jersey) | close/spread | 98.7 | 24.39 |
| Caesars Sportsbook (New Jersey) | close/total | 98.7 | 24.39 |
| Caesars Sportsbook (New Jersey) | open/ml | 96.67 | 24.39 |
| Caesars Sportsbook (New Jersey) | open/spread | 96.91 | 24.39 |
| Caesars Sportsbook (New Jersey) | open/total | 98.13 | 24.39 |
| Caesars Sportsbook (Colorado) | close/ml | 96.99 | 24.39 |
| Caesars Sportsbook (Colorado) | close/spread | 98.62 | 24.39 |
| Caesars Sportsbook (Colorado) | close/total | 98.62 | 24.39 |
| Caesars Sportsbook (Colorado) | open/ml | 95.21 | 24.39 |
| Caesars Sportsbook (Colorado) | open/spread | 96.83 | 24.39 |
| Caesars Sportsbook (Colorado) | open/total | 98.05 | 24.39 |
| Caesars Sportsbook (Tennessee) | close/ml | 97.81 | 24.39 |
| Caesars Sportsbook (Tennessee) | close/spread | 98.54 | 24.39 |
| Caesars Sportsbook (Tennessee) | close/total | 98.54 | 24.39 |
| Caesars Sportsbook (Tennessee) | open/ml | 96.1 | 24.39 |
| Caesars Sportsbook (Tennessee) | open/spread | 96.83 | 24.39 |
| Caesars Sportsbook (Tennessee) | open/total | 98.05 | 24.39 |
| SugarHouse | close/ml | 96.75 | 24.39 |
| SugarHouse | close/spread | 96.75 | 24.39 |
| SugarHouse | close/total | 96.75 | 24.39 |
| SugarHouse | open/ml | 95.21 | 24.39 |
| SugarHouse | open/spread | 95.21 | 24.39 |
| SugarHouse | open/total | 96.59 | 24.39 |
| PointsBet | close/ml | 28.27 | 0.0 |
| PointsBet | close/spread | 28.27 | 0.0 |
| PointsBet | close/total | 28.27 | 0.0 |
| PointsBet | open/ml | 28.11 | 0.0 |
| PointsBet | open/spread | 28.11 | 0.0 |
| PointsBet | open/total | 28.11 | 0.0 |
| betegy | close/ml | 1.62 | 0.0 |
| betegy | close/spread | 1.62 | 0.0 |
| betegy | close/total | 0.16 | 0.0 |
| Caesars Sportsbook | close/ml | 0.65 | 0.0 |
| Caesars Sportsbook | close/spread | 1.46 | 0.0 |
| Caesars Sportsbook | close/total | 1.46 | 0.0 |
| Caesars Sportsbook | open/ml | 0.65 | 0.0 |
| Caesars Sportsbook | open/spread | 1.46 | 0.0 |
| Caesars Sportsbook | open/total | 1.46 | 0.0 |

## 5. 異常盤口（單筆紀錄；原始資料不動）

- 檢核 403698 項：error 860（0.213%）、warning 455、缺失值 0

| 市場/類型/嚴重度 | 筆數 |
|---|---|
| ml/line_deviates_from_market/error | 76 |
| ml/ml_deviates_from_market/error | 28 |
| ml/overround_high/warning | 18 |
| ml/price_extreme/warning | 8 |
| ml/spread_ml_direction_conflict/error | 10 |
| spread/line_deviates_from_market/error | 290 |
| spread/overround_high/warning | 10 |
| spread/price_extreme/warning | 131 |
| spread/spread_deviates_from_market/error | 94 |
| spread/spread_ml_direction_conflict/error | 10 |
| total/line_deviates_from_market/error | 346 |
| total/price_extreme/warning | 288 |
| total/total_out_of_range/error | 6 |

依博彩公司（error）：

| 博彩公司 | error 筆數 | 該公司盤口筆數 | 比例 % |
|---|---|---|---|
| ESPN BET | 256 | 15648 | 1.64 |
| Unibet | 232 | 14908 | 1.56 |
| SugarHouse | 140 | 14452 | 0.97 |
| BetfairSportsbook | 52 | 14900 | 0.35 |
| DraftKings | 52 | 14612 | 0.36 |
| Titanbets | 34 | 14760 | 0.23 |
| Caesars Sportsbook (Colorado) | 32 | 14626 | 0.22 |
| Caesars Sportsbook (Tennessee) | 24 | 14664 | 0.16 |
| Caesars Sportsbook (New Jersey) | 20 | 14706 | 0.14 |
| MGM | 12 | 14952 | 0.08 |
| PointsBet | 4 | 4164 | 0.1 |
| Caesars Sportsbook | 2 | 176 | 1.14 |

## 6. ESPN BET 系統性錯誤檢查

**結論：無系統性錯誤**

| 階段/市場 | 紀錄數 | error 筆數 | error % | 類型 |
|---|---|---|---|---|
| open/spread | 2590 | 106 | 4.09 | {'line_deviates_from_market': 88, 'spread_deviates_from_market': 18} |
| open/total | 2614 | 124 | 4.74 | {'line_deviates_from_market': 124} |
| open/ml | 2592 | 22 | 0.85 | {'line_deviates_from_market': 20, 'ml_deviates_from_market': 2} |
| close/spread | 2618 | 2 | 0.08 | {'line_deviates_from_market': 2} |
| close/total | 2618 | 2 | 0.08 | {'line_deviates_from_market': 2} |
| close/ml | 2616 | 0 | 0.0 | {} |

與同場同階段其他莊家中位數的差距（只算有 ≥ 3 家其他莊家的場次）：

| 階段/市場 | 場次 | 差距中位數（分）| 差 ≤ 1 分比例 % | 差 > 4 分比例 % |
|---|---|---|---|---|
| close/spread | 1246 | 0.5 | 96.71 | 0.08 |
| close/total | 1246 | 0.5 | 91.97 | 0.08 |
| open/total | 1243 | 1.0 | 62.19 | 9.81 |
| open/spread | 1223 | 0.5 | 79.64 | 3.68 |

## 7. CLV 配對（同一家、同市場、同方向；不補值）

- 有效配對 74750 筆，涵蓋 1312 場（例行賽 1230、季後賽 82）；考慮 1313 場，沒有任何有效配對的場次 1
- 依市場有效配對：{'ml': 24916, 'spread': 24712, 'total': 25122}
- 收盤時間性質：{'PROVIDER_LABELED_CLOSE': 74750}
- 排除 2182 筆，依原因：{'missing_open': 1210, 'flagged_record': 915, 'missing_same_book_other_side_for_devig': 55, 'missing_close': 2}

| 市場/排除原因 | 筆數 |
|---|---|
| ml/flagged_record | 136 |
| ml/missing_close | 2 |
| ml/missing_open | 538 |
| ml/missing_same_book_other_side_for_devig | 8 |
| spread/flagged_record | 365 |
| spread/missing_open | 586 |
| spread/missing_same_book_other_side_for_devig | 21 |
| total/flagged_record | 414 |
| total/missing_open | 86 |
| total/missing_same_book_other_side_for_devig | 26 |

## 8. Line CLV 與 Price CLV（分開；此處只報有效筆數與排除原因，不做任何模型評估）

| 市場 | 配對 | Line CLV 有效 | Price CLV 有效 | 未計算原因 |
|---|---|---|---|---|
| spread | 24712 | 24712 | 5666 | {'price:line_moved_price_not_comparable': 19046} |
| total | 25122 | 25122 | 3362 | {'price:line_moved_price_not_comparable': 21760} |
| ml | 24916 | 0 | 24916 | {'line:not_applicable_moneyline_has_no_line': 24916} |

## 9. CLV 驗證項目

| 驗證 | 結果 |
|---|---|
| every_pair_same_book | ✅ |
| every_pair_same_market_and_side | ✅ |
| devig_uses_same_book_opposite_side | ✅ |
| no_flagged_record_in_any_pair | ✅ |
| no_postgame_snapshot_in_any_pair | ✅ |
| price_clv_not_computed_when_lines_differ | ✅ |
| ml_has_no_line_clv | ✅ |
| trace_samples_found_in_raw | ✅ |

追溯抽樣（正規化值 ↔ odds_raw 原始報價）：

- `401584089` BetfairSportsbook ml/away：開盤 [None, 1.6494] ← {"favorite": true, "moneyLine": {"alternateDisplayValue": "-154", "american": "-154", "decimal": 1.65, "displayValue": "50/77", "fraction": "50/77", "value": 1.
  收盤 [None, 1.7246] ← {"moneyLine": {"alternateDisplayValue": "-138", "american": "-138", "decimal": 1.72, "displayValue": "50/69", "fraction": "50/69", "value": 1.72}, "pointSpread"
- `401584870` ESPN BET ml/away：開盤 [None, 2.6] ← {"favorite": false, "moneyLine": {"alternateDisplayValue": "+160", "american": "+160", "decimal": 2.6, "displayValue": "8/5", "fraction": "8/5", "value": 2.6}, 
  收盤 [None, 2.45] ← {"moneyLine": {"alternateDisplayValue": "+145", "american": "+145", "decimal": 2.45, "displayValue": "29/20", "fraction": "29/20", "value": 2.45}, "pointSpread"
- `401585120` Caesars Sportsbook (New Jersey) ml/away：開盤 [None, 2.58] ← {"favorite": false, "moneyLine": {"alternateDisplayValue": "+158", "american": "+158", "decimal": 2.58, "displayValue": "79/50", "fraction": "79/50", "value": 2
  收盤 [None, 2.7] ← {"moneyLine": {"alternateDisplayValue": "+170", "american": "+170", "decimal": 2.7, "displayValue": "17/10", "fraction": "17/10", "value": 2.7}, "pointSpread": 
- `401585376` DraftKings spread/away：開盤 [-1.0, 1.9091] ← {"favorite": true, "moneyLine": {"alternateDisplayValue": "-115", "american": "-115", "decimal": 1.87, "displayValue": "20/23", "fraction": "20/23", "value": 1.
  收盤 [-1.0, 1.9091] ← {"moneyLine": {"alternateDisplayValue": "-115", "american": "-115", "decimal": 1.87, "displayValue": "20/23", "fraction": "20/23", "value": 1.87}, "pointSpread"
- `401585633` Unibet ml/away：開盤 [None, 1.1786] ← {"favorite": true, "moneyLine": {"alternateDisplayValue": "-560", "american": "-560", "decimal": 1.18, "displayValue": "5/28", "fraction": "5/28", "value": 1.18
  收盤 [None, 1.1786] ← {"moneyLine": {"alternateDisplayValue": "-560", "american": "-560", "decimal": 1.18, "displayValue": "5/28", "fraction": "5/28", "value": 1.18}, "pointSpread": 

## 10. 追溯資訊

- 程式版本：`6345212b8d7d570533918584efae1c875a436659`
- 輸入檔 sha256：
  - `games.jsonl.gz`：`ffed87d310462d90668ae97cf91127943927635de387111e9a6fbc089e1303d5`
  - `teambox.jsonl.gz`：`61e32d19d1771ae2d2e4329e0572552be0508e50524aef0765b53c8ad39dc4d2`
  - `odds.jsonl.gz`：`90ef799ab089882765d1b8140f82009d6df0eca44f95c30bd50ecf1270efc8f5`
  - `odds_raw.jsonl.gz`：`3e3cbeadeb4735c08e10a1d6273fd12cd0e72358b94f0c542dc4773d7f51d0e3`
  - `odds_flags.jsonl.gz`：`10ca5d9cb5d817700fc40d931dca0c32c96fb09caf92be64f02cbf0a6227e25b`
- 重算：`PYTHONPATH=. python tools/season_audit.py 2024`
