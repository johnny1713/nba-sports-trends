# 特徵依賴關係與資料可用性（v1）

由 `nba_quant/feature_deps.py` 產生。可用性沿依賴鏈傳遞（含跨球季收縮先驗）；不可用的基礎欄位不補值、不以 BBRef 覆蓋。
2024-25 只做資料品質檢查；2025-26 不讀取。

## 1. 依賴鏈

| 特徵 | 範圍欄位 | 直接依賴 | 基礎欄位（遞迴）| 跨球季 |
|---|---|---|---|---|
| ELO.rating | use_elo | game_result | game_result |  |
| F1.drtg | use_team_stats | drtg | fga, fta, opp_fga, opp_fta, opp_oreb, opp_pts, opp_tov, oreb, tov | prior |
| F1.net_rating | use_team_stats | net_rating | fga, fta, opp_fga, opp_fta, opp_oreb, opp_pts, opp_tov, oreb, pts, tov | prior |
| F1.ortg | use_team_stats | ortg | fga, fta, opp_fga, opp_fta, opp_oreb, opp_tov, oreb, pts, tov | prior |
| F1.pace | use_team_stats | pace | fga, fta, opp_fga, opp_fta, opp_oreb, opp_tov, oreb, tov | prior |
| F2.ewm_net_rating | use_team_stats | net_rating | fga, fta, opp_fga, opp_fta, opp_oreb, opp_pts, opp_tov, oreb, pts, tov | window |
| F2.last10_net_rating | use_team_stats | net_rating | fga, fta, opp_fga, opp_fta, opp_oreb, opp_pts, opp_tov, oreb, pts, tov | window |
| F2.last5_net_rating | use_team_stats | net_rating | fga, fta, opp_fga, opp_fta, opp_oreb, opp_pts, opp_tov, oreb, pts, tov | window |
| F3.efg_def | use_team_stats | efg_def | opp_fg3m, opp_fga, opp_fgm |  |
| F3.efg_off | use_team_stats | efg_off | fg3m, fga, fgm |  |
| F3.ft_rate_def | use_team_stats | ft_rate_def | opp_fga, opp_ftm |  |
| F3.ft_rate_off | use_team_stats | ft_rate_off | fga, ftm |  |
| F3.orb_rate_def | use_team_stats | orb_rate_def | dreb, opp_oreb |  |
| F3.orb_rate_off | use_team_stats | orb_rate_off | opp_dreb, oreb |  |
| F3.tov_rate_def | use_team_stats | tov_rate_def | opp_fga, opp_fta, opp_tov |  |
| F3.tov_rate_off | use_team_stats | tov_rate_off | fga, fta, tov |  |
| F4.srs_margin | use_team_stats | margin | opp_score, score |  |
| F4.srs_net_rating | use_team_stats | net_rating | fga, fta, opp_fga, opp_fta, opp_oreb, opp_pts, opp_tov, oreb, pts, tov |  |
| F5.back_to_back | use_fatigue | game_date | game_date |  |
| F5.games_last_7_days | use_fatigue | game_date | game_date |  |
| F5.rest_days | use_fatigue | game_date | game_date |  |
| F5.road_trip_length | use_fatigue | game_date | game_date |  |
| F5.three_in_four | use_fatigue | game_date | game_date |  |
| F7.league_recent_points | use_team_stats | total_points | opp_score, score | window |
| F7.pace_sum | use_team_stats | pace | fga, fta, opp_fga, opp_fta, opp_oreb, opp_tov, oreb, tov | prior |

## 2. 每季可用性（不是 available 的才列出）

| 球季 | 特徵 | 狀態 | 原因（依賴路徑）|
|---|---|---|---|
| 2017-18 | F1.drtg | unavailable | 2018: F1.drtg -> drtg -> possessions -> opp_tov 不可用 |
| 2017-18 | F1.net_rating | unavailable | 2018: F1.net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用 |
| 2017-18 | F1.ortg | unavailable | 2018: F1.ortg -> ortg -> possessions -> opp_tov 不可用 |
| 2017-18 | F1.pace | unavailable | 2018: F1.pace -> pace -> possessions -> opp_tov 不可用 |
| 2017-18 | F2.ewm_net_rating | unavailable | 2018: F2.ewm_net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用 |
| 2017-18 | F2.last10_net_rating | unavailable | 2018: F2.last10_net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用 |
| 2017-18 | F2.last5_net_rating | unavailable | 2018: F2.last5_net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用 |
| 2017-18 | F3.tov_rate_def | unavailable | 2018: F3.tov_rate_def -> tov_rate_def -> opp_tov 不可用 |
| 2017-18 | F3.tov_rate_off | unavailable | 2018: F3.tov_rate_off -> tov_rate_off -> tov 不可用 |
| 2017-18 | F4.srs_net_rating | unavailable | 2018: F4.srs_net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用 |
| 2017-18 | F7.pace_sum | unavailable | 2018: F7.pace_sum -> pace -> possessions -> opp_tov 不可用 |
| 2018-19 | F1.drtg | available_prior_excluded | 上季 2018 的 F1.drtg -> drtg -> possessions -> opp_tov 不可用：收縮先驗不得使用該季的值，只能退回其他可用來源，並記錄 |
| 2018-19 | F1.net_rating | available_prior_excluded | 上季 2018 的 F1.net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用：收縮先驗不得使用該季的值，只能退回其他可用來源，並記錄 |
| 2018-19 | F1.ortg | available_prior_excluded | 上季 2018 的 F1.ortg -> ortg -> possessions -> opp_tov 不可用：收縮先驗不得使用該季的值，只能退回其他可用來源，並記錄 |
| 2018-19 | F1.pace | available_prior_excluded | 上季 2018 的 F1.pace -> pace -> possessions -> opp_tov 不可用：收縮先驗不得使用該季的值，只能退回其他可用來源，並記錄 |
| 2018-19 | F2.ewm_net_rating | available_prior_excluded | 上季 2018 的 F2.ewm_net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用：季初視窗不得往回數到該季的比賽（跳過、不補值），並記錄 |
| 2018-19 | F2.last10_net_rating | available_prior_excluded | 上季 2018 的 F2.last10_net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用：季初視窗不得往回數到該季的比賽（跳過、不補值），並記錄 |
| 2018-19 | F2.last5_net_rating | available_prior_excluded | 上季 2018 的 F2.last5_net_rating -> net_rating -> ortg -> possessions -> opp_tov 不可用：季初視窗不得往回數到該季的比賽（跳過、不補值），並記錄 |
| 2018-19 | F7.pace_sum | available_prior_excluded | 上季 2018 的 F7.pace_sum -> pace -> possessions -> opp_tov 不可用：收縮先驗不得使用該季的值，只能退回其他可用來源，並記錄 |

## 3. 資料層檢查（F1～F4、F7 範圍 `use_team_stats` 內的球隊 box）

| 球季 | 球隊 box | pts | fgm | fga | fg3m | fg3a | ftm | fta | oreb | dreb | tov |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2014-15 | 2460 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2015-16 | 2460 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2016-17 | 2460 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2017-18 | 2460 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | **0/2460** |
| 2018-19 | 2460 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2019-20 | 2118 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2020-21 | 2160 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2021-22 | 2460 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2022-23 | 2460 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2023-24 | 2462 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
| 2024-25 | 2462 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |
