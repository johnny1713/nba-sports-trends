# 模型資料統計 v1

依 `data/reference/game_classification.csv` 計算。**不使用、不修改** `quality.py` 與盤口品質報告（凍結的盤口品質 v1）。
2024-25 標記為 data_quality_only：只做資料品質統計，不得用於特徵選擇、調參、選模、評估或回測。2025-26 不讀取。

## 1. 各用途的場數（完賽）

| 球季 | 狀態 | 例行賽戰績 | F1/F2 | F5 疲勞 | Elo | 訓練樣本 | 戰績每隊場數 | 戰績檢查 |
|---|---|---|---|---|---|---|---|---|
| 2014-15 | open | 1230 | 1230 | 1311 | 1311 | 1230 | 82～82 | OK |
| 2015-16 | open | 1230 | 1230 | 1316 | 1316 | 1230 | 82～82 | OK |
| 2016-17 | open | 1230 | 1230 | 1309 | 1309 | 1230 | 82～82 | OK |
| 2017-18 | open | 1230 | 1230 | 1312 | 1312 | 1230 | 82～82 | OK |
| 2018-19 | open | 1230 | 1230 | 1312 | 1312 | 1230 | 82～82 | OK |
| 2019-20 | open | 1059 | 1059 | 1143 | 1143 | 1059 | 64～75 | OK |
| 2020-21 | open | 1080 | 1080 | 1171 | 1171 | 1080 | 72～72 | OK |
| 2021-22 | open | 1230 | 1230 | 1323 | 1323 | 1230 | 82～82 | OK |
| 2022-23 | open | 1230 | 1230 | 1320 | 1320 | 1230 | 82～82 | OK |
| 2023-24 | open | 1230 | 1231 | 1319 | 1319 | 1231 | 82～82 | OK |
| 2024-25 | data_quality_only | 1230 | 1231 | 1321 | 1321 | 1231 | 82～82 | OK |

## 2. box score 覆蓋率與失誤可用性

| 球季 | 用途 | 場數 | 兩隊 box 完整 | 覆蓋率 | 失誤可用（球隊 box）| 失誤定義 |
|---|---|---|---|---|---|---|
| 2014-15 | F1/F2 | 1230 | 1230 | 100.00% | 2460 | bbref_team_total 324, espn_total_incl_team 2136 |
| 2014-15 | F5 疲勞 | 1311 | 1311 | 100.00% | 2622 | bbref_team_total 356, espn_total_incl_team 2266 |
| 2014-15 | Elo | 1311 | 1311 | 100.00% | 2622 | bbref_team_total 356, espn_total_incl_team 2266 |
| 2015-16 | F1/F2 | 1230 | 1230 | 100.00% | 2460 | bbref_team_total 322, espn_total_incl_team 2138 |
| 2015-16 | F5 疲勞 | 1316 | 1316 | 100.00% | 2632 | bbref_team_total 322, espn_total_incl_team 2310 |
| 2015-16 | Elo | 1316 | 1316 | 100.00% | 2632 | bbref_team_total 322, espn_total_incl_team 2310 |
| 2016-17 | F1/F2 | 1230 | 1230 | 100.00% | 2460 | bbref_team_total 326, espn_total_incl_team 2134 |
| 2016-17 | F5 疲勞 | 1309 | 1309 | 100.00% | 2618 | bbref_team_total 336, espn_total_incl_team 2282 |
| 2016-17 | Elo | 1309 | 1309 | 100.00% | 2618 | bbref_team_total 336, espn_total_incl_team 2282 |
| 2017-18 | F1/F2 | 1230 | 1230 | 100.00% | 0 | bbref_team_total_season_disabled 326, espn_2017_18_field_shift 2134 |
| 2017-18 | F5 疲勞 | 1312 | 1312 | 100.00% | 0 | bbref_team_total_season_disabled 344, espn_2017_18_field_shift 2280 |
| 2017-18 | Elo | 1312 | 1312 | 100.00% | 0 | bbref_team_total_season_disabled 344, espn_2017_18_field_shift 2280 |
| 2018-19 | F1/F2 | 1230 | 1230 | 100.00% | 2460 | espn_total_incl_team 2460 |
| 2018-19 | F5 疲勞 | 1312 | 1312 | 100.00% | 2624 | espn_total_incl_team 2624 |
| 2018-19 | Elo | 1312 | 1312 | 100.00% | 2624 | espn_total_incl_team 2624 |
| 2019-20 | F1/F2 | 1059 | 1059 | 100.00% | 2118 | espn_total_incl_team 2118 |
| 2019-20 | F5 疲勞 | 1143 | 1143 | 100.00% | 2286 | espn_total_incl_team 2286 |
| 2019-20 | Elo | 1143 | 1143 | 100.00% | 2286 | espn_total_incl_team 2286 |
| 2020-21 | F1/F2 | 1080 | 1080 | 100.00% | 2160 | espn_total_incl_team 2160 |
| 2020-21 | F5 疲勞 | 1171 | 1171 | 100.00% | 2330 | bbref_player_only 12, espn_total_incl_team 2330 |
| 2020-21 | Elo | 1171 | 1171 | 100.00% | 2330 | bbref_player_only 12, espn_total_incl_team 2330 |
| 2021-22 | F1/F2 | 1230 | 1230 | 100.00% | 2460 | espn_total_incl_team 2460 |
| 2021-22 | F5 疲勞 | 1323 | 1323 | 100.00% | 2646 | espn_total_incl_team 2646 |
| 2021-22 | Elo | 1323 | 1323 | 100.00% | 2646 | espn_total_incl_team 2646 |
| 2022-23 | F1/F2 | 1230 | 1230 | 100.00% | 2460 | espn_total_incl_team 2460 |
| 2022-23 | F5 疲勞 | 1320 | 1320 | 100.00% | 2640 | espn_total_incl_team 2640 |
| 2022-23 | Elo | 1320 | 1320 | 100.00% | 2640 | espn_total_incl_team 2640 |
| 2023-24 | F1/F2 | 1231 | 1231 | 100.00% | 2462 | espn_total_incl_team 2462 |
| 2023-24 | F5 疲勞 | 1319 | 1319 | 100.00% | 2638 | espn_total_incl_team 2638 |
| 2023-24 | Elo | 1319 | 1319 | 100.00% | 2638 | espn_total_incl_team 2638 |
| 2024-25 | F1/F2 | 1231 | 1231 | 100.00% | 2462 | bbref_team_total 2, espn_total_incl_team 2460 |
| 2024-25 | F5 疲勞 | 1321 | 1321 | 100.00% | 2642 | bbref_team_total 2, espn_total_incl_team 2640 |
| 2024-25 | Elo | 1321 | 1321 | 100.00% | 2642 | bbref_team_total 2, espn_total_incl_team 2640 |

## 3. 各用途包含的比賽類型

| 球季 | 用途 | game_type |
|---|---|---|
| 2014-15 | 例行賽戰績 | REGULAR_SEASON 1230 |
| 2014-15 | F1/F2 | REGULAR_SEASON 1230 |
| 2014-15 | F5 疲勞 | POSTSEASON 81, REGULAR_SEASON 1230 |
| 2014-15 | Elo | POSTSEASON 81, REGULAR_SEASON 1230 |
| 2014-15 | 訓練樣本 | REGULAR_SEASON 1230 |
| 2015-16 | 例行賽戰績 | REGULAR_SEASON 1230 |
| 2015-16 | F1/F2 | REGULAR_SEASON 1230 |
| 2015-16 | F5 疲勞 | POSTSEASON 86, REGULAR_SEASON 1230 |
| 2015-16 | Elo | POSTSEASON 86, REGULAR_SEASON 1230 |
| 2015-16 | 訓練樣本 | REGULAR_SEASON 1230 |
| 2016-17 | 例行賽戰績 | REGULAR_SEASON 1230 |
| 2016-17 | F1/F2 | REGULAR_SEASON 1230 |
| 2016-17 | F5 疲勞 | POSTSEASON 79, REGULAR_SEASON 1230 |
| 2016-17 | Elo | POSTSEASON 79, REGULAR_SEASON 1230 |
| 2016-17 | 訓練樣本 | REGULAR_SEASON 1230 |
| 2017-18 | 例行賽戰績 | REGULAR_SEASON 1230 |
| 2017-18 | F1/F2 | REGULAR_SEASON 1230 |
| 2017-18 | F5 疲勞 | POSTSEASON 82, REGULAR_SEASON 1230 |
| 2017-18 | Elo | POSTSEASON 82, REGULAR_SEASON 1230 |
| 2017-18 | 訓練樣本 | REGULAR_SEASON 1230 |
| 2018-19 | 例行賽戰績 | REGULAR_SEASON 1230 |
| 2018-19 | F1/F2 | REGULAR_SEASON 1230 |
| 2018-19 | F5 疲勞 | POSTSEASON 82, REGULAR_SEASON 1230 |
| 2018-19 | Elo | POSTSEASON 82, REGULAR_SEASON 1230 |
| 2018-19 | 訓練樣本 | REGULAR_SEASON 1230 |
| 2019-20 | 例行賽戰績 | REGULAR_SEASON 1059 |
| 2019-20 | F1/F2 | REGULAR_SEASON 1059 |
| 2019-20 | F5 疲勞 | PLAY_IN 1, POSTSEASON 83, REGULAR_SEASON 1059 |
| 2019-20 | Elo | PLAY_IN 1, POSTSEASON 83, REGULAR_SEASON 1059 |
| 2019-20 | 訓練樣本 | REGULAR_SEASON 1059 |
| 2020-21 | 例行賽戰績 | REGULAR_SEASON 1080 |
| 2020-21 | F1/F2 | REGULAR_SEASON 1080 |
| 2020-21 | F5 疲勞 | PLAY_IN 6, POSTSEASON 85, REGULAR_SEASON 1080 |
| 2020-21 | Elo | PLAY_IN 6, POSTSEASON 85, REGULAR_SEASON 1080 |
| 2020-21 | 訓練樣本 | REGULAR_SEASON 1080 |
| 2021-22 | 例行賽戰績 | REGULAR_SEASON 1230 |
| 2021-22 | F1/F2 | REGULAR_SEASON 1230 |
| 2021-22 | F5 疲勞 | PLAY_IN 6, POSTSEASON 87, REGULAR_SEASON 1230 |
| 2021-22 | Elo | PLAY_IN 6, POSTSEASON 87, REGULAR_SEASON 1230 |
| 2021-22 | 訓練樣本 | REGULAR_SEASON 1230 |
| 2022-23 | 例行賽戰績 | REGULAR_SEASON 1230 |
| 2022-23 | F1/F2 | REGULAR_SEASON 1230 |
| 2022-23 | F5 疲勞 | PLAY_IN 6, POSTSEASON 84, REGULAR_SEASON 1230 |
| 2022-23 | Elo | PLAY_IN 6, POSTSEASON 84, REGULAR_SEASON 1230 |
| 2022-23 | 訓練樣本 | REGULAR_SEASON 1230 |
| 2023-24 | 例行賽戰績 | CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, REGULAR_SEASON 1164 |
| 2023-24 | F1/F2 | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, REGULAR_SEASON 1164 |
| 2023-24 | F5 疲勞 | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, PLAY_IN 6, POSTSEASON 82, REGULAR_SEASON 1164 |
| 2023-24 | Elo | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, PLAY_IN 6, POSTSEASON 82, REGULAR_SEASON 1164 |
| 2023-24 | 訓練樣本 | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, REGULAR_SEASON 1164 |
| 2024-25 | 例行賽戰績 | CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, REGULAR_SEASON 1164 |
| 2024-25 | F1/F2 | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, REGULAR_SEASON 1164 |
| 2024-25 | F5 疲勞 | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, PLAY_IN 6, POSTSEASON 84, REGULAR_SEASON 1164 |
| 2024-25 | Elo | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, PLAY_IN 6, POSTSEASON 84, REGULAR_SEASON 1164 |
| 2024-25 | 訓練樣本 | CUP_FINAL 1, CUP_GROUP 60, CUP_QUARTERFINAL 4, CUP_SEMIFINAL 2, REGULAR_SEASON 1164 |
