# 中立場資料表（獨立檔案 `data/reference/neutral_sites.csv`）

不改 `games.jsonl.gz` 的 `neutral` 欄位。未列入的比賽沿用 ESPN 主客場。

| 類別 | 賽段 | 狀態 | 場數 |
|---|---|---|---|
| bubble_postseason | postseason | neutral | 83 |
| bubble_regular | regular | neutral | 88 |
| cup_knockout | regular | neutral | 4 |
| espn_flag_only | regular | unknown | 6 |
| international | regular | neutral | 16 |
| ist_knockout | regular | neutral | 2 |

## 非泡泡區明細

| game_id | 美東日期 | 對戰 | 狀態 | 類別 | ESPN 場館（現名） | BBRef 場館 | 判定理由 |
|---|---|---|---|---|---|---|---|
| 400578409 | 2014-11-12 | HOU @ MIN | unknown | espn_flag_only | Mexico City Arena, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 標記中立場但無備註；依使用者指示維持無法確認，不推測（BBRef 場館「Mexico City Arena, Mexico City, Mexico」僅為輔助證據，不單獨作判定） |
| 400578877 | 2015-01-15 | NY @ MIL | unknown | espn_flag_only | O2 Arena (ENG), London | The O2 Arena, London, United Kingdom | ESPN 標記中立場但無備註；依使用者指示維持無法確認，不推測（BBRef 場館「The O2 Arena, London, United Kingdom」僅為輔助證據，不單獨作判定） |
| 400828169 | 2015-12-03 | BOS @ SAC | unknown | espn_flag_only | Mexico City Arena, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 標記中立場但無備註；依使用者指示維持無法確認，不推測（BBRef 場館「Mexico City Arena, Mexico City, Mexico」僅為輔助證據，不單獨作判定） |
| 400828475 | 2016-01-14 | TOR @ ORL | neutral | international | O2 Arena (ENG), London | The O2 Arena, London, United Kingdom | ESPN 備註「AT LONDON」與 BBRef 場館「The O2 Arena, London, United Kingdom」一致 |
| 400900010 | 2017-01-12 | IND @ DEN | unknown | espn_flag_only | O2 Arena (ENG), London | The O2 Arena, London, United Kingdom | ESPN 標記中立場但無備註；依使用者指示維持無法確認，不推測（BBRef 場館「The O2 Arena, London, United Kingdom」僅為輔助證據，不單獨作判定） |
| 400900012 | 2017-01-12 | DAL @ PHX | unknown | espn_flag_only | Mexico City Arena, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 標記中立場但無備註；依使用者指示維持無法確認，不推測（BBRef 場館「Mexico City Arena, Mexico City, Mexico」僅為輔助證據，不單獨作判定） |
| 400900026 | 2017-01-14 | SA @ PHX | unknown | espn_flag_only | Mexico City Arena, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 標記中立場但無備註；依使用者指示維持無法確認，不推測（BBRef 場館「Mexico City Arena, Mexico City, Mexico」僅為輔助證據，不單獨作判定） |
| 400975116 | 2017-12-07 | OKC @ BKN | neutral | international | Mexico City Arena, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA MEXICO CITY GAMES」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 400975127 | 2017-12-09 | MIA @ BKN | neutral | international | Mexico City Arena, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA MEXICO CITY GAMES」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 400975360 | 2018-01-11 | BOS @ PHI | neutral | international | O2 Arena (ENG), London | The O2 Arena, London, United Kingdom | ESPN 備註「NBA LONDON GAME」與 BBRef 場館「The O2 Arena, London, United Kingdom」一致 |
| 401071099 | 2018-12-13 | CHI @ ORL | neutral | international | Arena CDMX, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA MEXICO CITY GAMES」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 401071110 | 2018-12-15 | UTAH @ ORL | neutral | international | Arena CDMX, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA MEXICO CITY GAMES」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 401071341 | 2019-01-17 | NY @ WSH | neutral | international | O2 Arena (ENG), London | The O2 Arena, London, United Kingdom | ESPN 備註「NBA LONDON GAME」與 BBRef 場館「The O2 Arena, London, United Kingdom」一致 |
| 401161011 | 2019-12-12 | DAL @ DET | neutral | international | Arena CDMX, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA MEXICO CITY GAMES」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 401161022 | 2019-12-14 | SA @ PHX | neutral | international | Arena CDMX, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA MEXICO CITY GAMES」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 401161311 | 2020-01-24 | MIL @ CHA | neutral | international | Bercy Arena, Paris | AccorHotels Arena, Paris, France | ESPN 備註「NBA PARIS GAME」與 BBRef 場館「AccorHotels Arena, Paris, France」一致 |
| 401468833 | 2023-01-19 | CHI @ DET | neutral | international | Bercy Arena, Paris | Accor Arena, Paris, France | ESPN 備註「NBA Paris Game 2023」與 BBRef 場館「Accor Arena, Paris, France」一致 |
| 401584800 | 2023-11-09 | ATL @ ORL | neutral | international | Mexico City Arena, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA Mexico City Game」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 401607494 | 2023-12-07 | IND @ MIL | neutral | ist_knockout | T-Mobile Arena, Las Vegas, NV | T-Mobile Arena, Las Vegas, Nevada | 2023-24 季中錦標賽拉斯維加斯準決賽（使用者指定） |
| 401607493 | 2023-12-07 | NO @ LAL | neutral | ist_knockout | T-Mobile Arena, Las Vegas, NV | T-Mobile Arena, Las Vegas, Nevada | 2023-24 季中錦標賽拉斯維加斯準決賽（使用者指定） |
| 401607495 | 2023-12-09 | IND @ LAL | neutral | cup_knockout | T-Mobile Arena, Las Vegas, NV | T-Mobile Arena, Las Vegas, Nevada | ESPN 備註「NBA In-Season Tournament Championship」與 BBRef 場館「T-Mobile Arena, Las Vegas, Nevada」一致 |
| 401585155 | 2024-01-11 | BKN @ CLE | neutral | international | Bercy Arena, Paris | Accor Arena, Paris, France | ESPN 備註「NBA Paris Game」與 BBRef 場館「Accor Arena, Paris, France」一致 |
| 401704713 | 2024-11-02 | MIA @ WSH | neutral | international | Arena CDMX, Mexico City | Mexico City Arena, Mexico City, Mexico | ESPN 備註「NBA Mexico City Game 2024」與 BBRef 場館「Mexico City Arena, Mexico City, Mexico」一致 |
| 401734906 | 2024-12-14 | ATL @ MIL | neutral | cup_knockout | T-Mobile Arena, Las Vegas, NV | T-Mobile Arena, Las Vegas, Nevada | ESPN 備註「NBA Cup - Semifinals」與 BBRef 場館「T-Mobile Arena, Las Vegas, Nevada」一致 |
| 401734907 | 2024-12-14 | HOU @ OKC | neutral | cup_knockout | T-Mobile Arena, Las Vegas, NV | T-Mobile Arena, Las Vegas, Nevada | ESPN 備註「NBA Cup - Semifinals」與 BBRef 場館「T-Mobile Arena, Las Vegas, Nevada」一致 |
| 401734908 | 2024-12-17 | MIL @ OKC | neutral | cup_knockout | T-Mobile Arena, Las Vegas, NV | T-Mobile Arena, Las Vegas, Nevada | ESPN 備註「NBA Cup Championship」與 BBRef 場館「T-Mobile Arena, Las Vegas, Nevada」一致 |
| 401705187 | 2025-01-23 | SA @ IND | neutral | international | Accor Arena, Paris | Accor Arena, Paris, France | ESPN 備註「NBA Paris Games 2025」與 BBRef 場館「Accor Arena, Paris, France」一致 |
| 401705199 | 2025-01-25 | IND @ SA | neutral | international | Accor Arena, Paris | Accor Arena, Paris, France | ESPN 備註「NBA Paris Games 2025」與 BBRef 場館「Accor Arena, Paris, France」一致 |
