# 2024-25 完整資料品質報告（ESPN season 2025）

## 判定：**PASS**

- 通過
- 門檻（未修改）：盤口 error 比例 < 1%；開盤／收盤各市場可用覆蓋率 ≥ 95%；完賽資料完整率 ≥ 99%

## 1. 場次與完整度

| 項目 | 例行賽 | 季後賽 |
|---|---|---|
| 場次（含延賽） | 1236 | 84 |
| 完賽 | 1231 | 84 |
| 資料完整 | 1231 | 84 |
| 完整率 % | 100.0 | 100.0 |
| ESPN box score 缺漏 | 1 | 0 |
| BBRef 補值 | 1 | 0 |
| 補值後仍不完整 | 0 | 0 |
| 盤口缺漏場次 | 0 | 0 |
| 每場莊家數中位數 | 1 | 1.0 |

- 狀態：例行賽 {'final': 1231, 'postponed': 5}；季後賽 {'final': 84}
- 每隊例行賽 82～83 場（30 隊；83 場者為 NBA 盃冠軍賽兩隊，ESPN 列為例行賽）
- 資料來源標記不一致：0 場；box score 合理性問題：0；重複 game_id：0

## 2. 盤口階段分類

- 筆數：{'open': 7888, 'close': 7888}
- 時間性質：{'PROVIDER_LABELED_OPEN': 7888, 'PROVIDER_LABELED_CLOSE': 7888}
- **賽後快照（POSTGAME_SNAPSHOT）：0 筆**——本季沒有任何賽後快照，開盤／收盤全部來自 ESPN 明確標記的欄位
- 收盤時間戳驗證比例：0.0%（ESPN 不提供時間戳；只能依供應商標記使用）

## 3. 各市場開盤／收盤可用覆蓋率（排除被標記紀錄後，至少一家雙邊齊全）

| 階段/市場 | 例行賽 % | 季後賽 % |
|---|---|---|
| open/spread | 95.37 | 100.0 |
| open/total | 95.37 | 100.0 |
| open/ml | 97.97 | 100.0 |
| close/spread | 99.92 | 100.0 |
| close/total | 100.0 | 100.0 |
| close/ml | 99.92 | 100.0 |

- 品質門檻計算（全季合併）：{'close/ml': 100.0, 'close/spread': 99.92, 'close/total': 100.0, 'open/ml': 98.48, 'open/spread': 98.4, 'open/total': 100.0}

## 4. 各博彩公司逐家覆蓋率（雙邊齊全且有價格；未排除標記）

| 博彩公司 | 階段/市場 | 例行賽 % | 季後賽 % |
|---|---|---|---|
| ESPN BET | close/ml | 100.0 | 100.0 |
| ESPN BET | close/spread | 99.92 | 100.0 |
| ESPN BET | close/total | 100.0 | 100.0 |
| ESPN BET | open/ml | 100.0 | 100.0 |
| ESPN BET | open/spread | 99.92 | 100.0 |
| ESPN BET | open/total | 100.0 | 100.0 |

## 5. 異常盤口（單筆紀錄；原始資料不動）

- 檢核 33871 項：error 80（0.2362%）、warning 222、缺失值 0

| 市場/類型/嚴重度 | 筆數 |
|---|---|
| ml/price_extreme/warning | 8 |
| ml/spread_ml_direction_conflict/error | 40 |
| spread/price_extreme/warning | 103 |
| spread/spread_ml_direction_conflict/error | 40 |
| total/price_extreme/warning | 111 |

依博彩公司（error）：

| 博彩公司 | error 筆數 | 該公司盤口筆數 | 比例 % |
|---|---|---|---|
| ESPN BET | 80 | 15776 | 0.51 |

## 6. ESPN BET 系統性錯誤檢查

**結論：無系統性錯誤**

| 階段/市場 | 紀錄數 | error 筆數 | error % | 類型 |
|---|---|---|---|---|
| open/spread | 2628 | 40 | 1.52 | {'spread_ml_direction_conflict': 40} |
| open/total | 2630 | 0 | 0.0 | {} |
| open/ml | 2630 | 40 | 1.52 | {'spread_ml_direction_conflict': 40} |
| close/spread | 2628 | 0 | 0.0 | {} |
| close/total | 2630 | 0 | 0.0 | {} |
| close/ml | 2630 | 0 | 0.0 | {} |

本季出現的博彩公司：1 家（ESPN BET）

### 多家交叉驗證可行性（例行賽、季後賽分開）

「可交叉驗證」= 同場、同階段、同市場至少 4 家博彩公司（偏離市場檢查的最低條件）。

| 階段/市場 | 賽段 | 總場數 | ≥4 家（可交叉驗證）| <4 家（無法交叉驗證）| 只有 1 家 | 0 家 |
|---|---|---|---|---|---|---|
| open/spread | 例行賽 | 1231 | 0（0.0%）| 1231（100.0%）| 1230 | 1 |
| open/spread | 季後賽 | 84 | 0（0.0%）| 84（100.0%）| 84 | 0 |
| open/total | 例行賽 | 1231 | 0（0.0%）| 1231（100.0%）| 1231 | 0 |
| open/total | 季後賽 | 84 | 0（0.0%）| 84（100.0%）| 84 | 0 |
| open/ml | 例行賽 | 1231 | 0（0.0%）| 1231（100.0%）| 1231 | 0 |
| open/ml | 季後賽 | 84 | 0（0.0%）| 84（100.0%）| 84 | 0 |
| close/spread | 例行賽 | 1231 | 0（0.0%）| 1231（100.0%）| 1230 | 1 |
| close/spread | 季後賽 | 84 | 0（0.0%）| 84（100.0%）| 84 | 0 |
| close/total | 例行賽 | 1231 | 0（0.0%）| 1231（100.0%）| 1231 | 0 |
| close/total | 季後賽 | 84 | 0（0.0%）| 84（100.0%）| 84 | 0 |
| close/ml | 例行賽 | 1231 | 0（0.0%）| 1231（100.0%）| 1231 | 0 |
| close/ml | 季後賽 | 84 | 0（0.0%）| 84（100.0%）| 84 | 0 |

#### 無法交叉驗證的資料：檢查範圍與使用限制

**無法執行的檢查**（需要同場其他博彩公司）：
- 盤口偏離市場（`line_deviates_from_market`）——因此**疑似滾球盤混入無法偵測**
- 讓分×獨贏方向矛盾的歸因（需 ≥ 3 家其他莊家）——發生矛盾時一律保守處理，兩個市場都排除
- 極端讓分「與市場一致／矛盾」的比對

**仍可透過內部一致性完成的檢查**（只需該家自己的報價）：
- 讓分兩邊互為相反數（`spread_sign_mismatch`）、盤口欄位填入賠率（`line_field_contains_price`）
- 讓分／總分超出合理範圍、總分兩邊不同、總分佔位符 -1
- 賠率無效（≤ 1.0）、極端賠率、抽水分級（同一家同階段雙邊）
- 同一家同階段的讓分與獨贏熱門方向是否一致（偵測得到，但無法判斷錯在哪一邊）
- 開盤／收盤欄位的時間性質分類（ESPN 一律為供應商標記、無時間戳）

**是否允許進入後續分析**：依現行規則，未被標記的紀錄仍會被 `usable_quotes()` 放行，可進入後續分析，但有以下限制：
- 這些紀錄只通過內部一致性檢查，**未經多家市場交叉驗證**；「沒有被標記」不等於「沒有異常」
- 覆蓋率達標只代表價格存在，**不代表通過多家來源驗證**
- 後續任何評估（含鎖定測試期）都必須把「可交叉驗證」與「無法交叉驗證」的場次分開報告，不得合併成單一結論
- 是否在評估中排除無法交叉驗證的場次，屬於使用者的決策；本報告不自行決定

- ⚠️ 本季無法交叉驗證的部分：open/spread（例行賽 無法交叉驗證 1231 場）、open/spread（季後賽 無法交叉驗證 84 場）、open/total（例行賽 無法交叉驗證 1231 場）、open/total（季後賽 無法交叉驗證 84 場）、open/ml（例行賽 無法交叉驗證 1231 場）、open/ml（季後賽 無法交叉驗證 84 場）、close/spread（例行賽 無法交叉驗證 1231 場）、close/spread（季後賽 無法交叉驗證 84 場）、close/total（例行賽 無法交叉驗證 1231 場）、close/total（季後賽 無法交叉驗證 84 場）、close/ml（例行賽 無法交叉驗證 1231 場）、close/ml（季後賽 無法交叉驗證 84 場）

與同場同階段其他莊家中位數的差距（只算有 ≥ 3 家其他莊家的場次）：

| 階段/市場 | 場次 | 差距中位數（分）| 差 ≤ 1 分比例 % | 差 > 4 分比例 % |
|---|---|---|---|---|

## 7. CLV 配對（同一家、同市場、同方向；不補值）

- 有效配對 7612 筆，涵蓋 1314 場（例行賽 1230、季後賽 84）；考慮 1315 場，沒有任何有效配對的場次 1
- 依市場有效配對：{'ml': 2580, 'spread': 2516, 'total': 2516}
- 收盤時間性質：{'PROVIDER_LABELED_CLOSE': 7612}
- 排除 276 筆，依原因：{'flagged_record': 268, 'missing_same_book_other_side_for_devig': 8}

| 市場/排除原因 | 筆數 |
|---|---|
| ml/flagged_record | 46 |
| ml/missing_same_book_other_side_for_devig | 4 |
| spread/flagged_record | 111 |
| spread/missing_same_book_other_side_for_devig | 1 |
| total/flagged_record | 111 |
| total/missing_same_book_other_side_for_devig | 3 |

## 8. Line CLV 與 Price CLV（分開；此處只報有效筆數與排除原因，不做任何模型評估）

| 市場 | 配對 | Line CLV 有效 | Price CLV 有效 | 未計算原因 |
|---|---|---|---|---|
| spread | 2516 | 2516 | 596 | {'price:line_moved_price_not_comparable': 1920} |
| total | 2516 | 2516 | 270 | {'price:line_moved_price_not_comparable': 2246} |
| ml | 2580 | 0 | 2580 | {'line:not_applicable_moneyline_has_no_line': 2580} |

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

- `401703370` ESPN BET ml/away：開盤 [None, 5.75] ← {"favorite": false, "moneyLine": {"alternateDisplayValue": "+475", "american": "+475", "decimal": 5.75, "displayValue": "19/4", "fraction": "19/4", "value": 5.7
  收盤 [None, 9.0] ← {"moneyLine": {"alternateDisplayValue": "+800", "american": "+800", "decimal": 9.0, "displayValue": "8/1", "fraction": "8/1", "value": 9.0}, "pointSpread": {"al
- `401704859` ESPN BET spread/away：開盤 [7.5, 1.9091] ← {"favorite": false, "moneyLine": {"alternateDisplayValue": "+270", "american": "+270", "decimal": 3.7, "displayValue": "27/10", "fraction": "27/10", "value": 3.
  收盤 [7.5, 1.9524] ← {"moneyLine": {"alternateDisplayValue": "+250", "american": "+250", "decimal": 3.5, "displayValue": "5/2", "fraction": "5/2", "value": 3.5}, "pointSpread": {"al
- `401705122` ESPN BET ml/away：開盤 [None, 1.7692] ← {"favorite": true, "moneyLine": {"alternateDisplayValue": "-130", "american": "-130", "decimal": 1.769, "displayValue": "10/13", "fraction": "10/13", "value": 1
  收盤 [None, 1.7407] ← {"moneyLine": {"alternateDisplayValue": "-135", "american": "-135", "decimal": 1.741, "displayValue": "20/27", "fraction": "20/27", "value": 1.741}, "pointSprea
- `401705376` ESPN BET total/over：開盤 [219.5, 1.9091] ← {"over": {"alternateDisplayValue": "-110", "american": "-110", "decimal": 1.909, "displayValue": "10/11", "fraction": "10/11", "value": 1.909}, "total": {"alter
  收盤 [227.5, 1.9091] ← {"over": {"alternateDisplayValue": "-110", "american": "-110", "decimal": 1.909, "displayValue": "10/11", "fraction": "10/11", "value": 1.909}, "total": {"alter
- `401705630` ESPN BET spread/away：開盤 [10.5, 1.9091] ← {"favorite": false, "moneyLine": {"alternateDisplayValue": "+380", "american": "+380", "decimal": 4.8, "displayValue": "19/5", "fraction": "19/5", "value": 4.8}
  收盤 [10.5, 1.8696] ← {"moneyLine": {"alternateDisplayValue": "+380", "american": "+380", "decimal": 4.8, "displayValue": "19/5", "fraction": "19/5", "value": 4.8}, "pointSpread": {"

## 10. 追溯資訊

- 程式版本：`7fe767d8fc9326fa0d2001d0ffafc892c2f5b31b`
- 輸入檔 sha256：
  - `games.jsonl.gz`：`630bb32349863baeef631f2d61847d312d716974b9d1b06ec1e3472ec2963133`
  - `teambox.jsonl.gz`：`b83e5ee825eff2a4557e33abd20d11e2356cf0c1e3005987ac1f36e23e119c54`
  - `odds.jsonl.gz`：`2a7df816e6df1a4cf6221ac44797605d1dd638f469776f3a5835d0ac63fcce42`
  - `odds_raw.jsonl.gz`：`5f690c0602a4c398f61d09478885b75652ed7d964ed2be8141b0f456a8650d45`
  - `odds_flags.jsonl.gz`：`67380bd704107200b0deee3512c3c0f4a9d5054ee693a219ca81609a96c40031`
- 重算：`PYTHONPATH=. python tools/season_audit.py 2025`
