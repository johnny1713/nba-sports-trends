"""
F1 球季累計效率（第一階段 stage 2；使用者 2026-11-20 第八輪核准開始 F1）。

定義（每隊、每場預測，只用該場**美東日期之前**、同一球季、`use_team_stats` 範圍內已完賽的比賽）：

    回合數（每隊每場）  poss_T = FGA − OREB + TOV + 0.44 × FTA
    該場回合數          game_poss = (poss_T + poss_O) / 2
    時間係數            minutes_factor = (48 + 5 × OT) / 48
    ORtg_raw = 100 × Σ 得分 / Σ game_poss
    DRtg_raw = 100 × Σ 失分 / Σ game_poss
    Net_raw  = ORtg_raw − DRtg_raw
    Pace_raw = Σ game_poss / Σ minutes_factor         （每 48 分鐘回合數）

收縮（n = 本季至今場數，M = SHRINK_GAMES）：  F1 = (n × raw + M × prior) / (n + M)
先驗（來源由資料存取層的 f1_prior_source 規則決定，本模組在批次計算時以相同規則重現並有測試比對）：
    team_previous_season                   prior = W × 該隊上季全季值 + (1 − W) × 上季聯盟平均
    league_average_current_season_to_date  prior = 本季至今聯盟平均（上季不可用，且本季至今 ≥ 100 場）
    league_average_latest_available_season prior = 最近一個可用完整球季的聯盟平均（上季不可用、本季至今 < 100 場）
    上季沒有資料（2014-15 開季）            prior = 本季至今聯盟平均（≥ 100 場），否則 status = missing（不補值）
聯盟平均：ORtg 與 DRtg 的聯盟平均相同（每一分同時是某隊得分與另一隊失分），Net 的聯盟平均為 0。

參數 SHRINK_GAMES = 10、PRIOR_TEAM_WEIGHT = 0.5 是預先登記的預設值，**沒有用任何資料調整**；
未來若要調整，只能用開發期資料（config.DEV_SEASONS）。

可用性：由 feature_deps 判定。2017-18：F1 全部 unavailable（回合數依賴失誤），不輸出數值；
2018-19：available_prior_excluded，先驗不得使用 2017-18。
資料只透過 DataAccess 讀取；盤口、box score 以外的資料一律不用。
"""
from __future__ import annotations

from collections import defaultdict

from .. import asof, feature_deps
from ..data_access import MIN_LEAGUE_GAMES_F1, DataAccess

SHRINK_GAMES = 10.0
PRIOR_TEAM_WEIGHT = 0.5
FEATURES = ('F1.ortg', 'F1.drtg', 'F1.net_rating', 'F1.pace')
FIELDS = ('pts', 'fga', 'fta', 'oreb', 'tov', 'overtimes')
SCOPE = 'use_team_stats'


def team_poss(b):
    return b['fga'] - b['oreb'] + b['tov'] + 0.44 * b['fta']


def game_rows(boxes):
    """把球隊 box 配成每隊每場一列：team、opp、得分、失分、該場回合數、時間係數。"""
    by = defaultdict(list)
    for b in boxes:
        by[b['game_id']].append(b)
    rows = []
    for gid, bs in by.items():
        if len(bs) != 2:
            continue                        # 只有一隊的 box（被排除）→ 整場不用，不補值
        a, b = bs
        gp = (team_poss(a) + team_poss(b)) / 2.0
        mf = (48 + 5 * a['overtimes']) / 48.0
        for t, o in ((a, b), (b, a)):
            rows.append({'game_id': gid, 'start_utc': t['start_utc'], 'et_date': asof.et_date(t['start_utc']),
                         'team': t['team'], 'opp': o['team'], 'pf': t['pts'], 'pa': o['pts'], 'poss': gp, 'mf': mf})
    return rows


class Acc:
    __slots__ = ('n', 'pf', 'pa', 'poss', 'mf', 'first', 'last')

    def __init__(self):
        self.n, self.pf, self.pa, self.poss, self.mf, self.first, self.last = 0, 0.0, 0.0, 0.0, 0.0, None, None

    def add(self, r):
        self.n += 1
        self.pf += r['pf']
        self.pa += r['pa']
        self.poss += r['poss']
        self.mf += r['mf']
        d = r['start_utc'][:10]
        self.first = d if self.first is None or d < self.first else self.first
        self.last = d if self.last is None or d > self.last else self.last

    def values(self):
        if not self.n or not self.poss:
            return None
        o, d = 100 * self.pf / self.poss, 100 * self.pa / self.poss
        return {'ortg': o, 'drtg': d, 'net_rating': o - d, 'pace': self.poss / self.mf}


def league_values(acc):
    """聯盟平均（每場每隊各算一次，所以 pf 與 pa 總和相同；Net = 0）。"""
    v = acc.values()
    if v is None:
        return None
    return {'ortg': v['ortg'], 'drtg': v['ortg'], 'net_rating': 0.0, 'pace': v['pace']}


def season_totals(da, season):
    """某季全季（完整球季，用於下一季的先驗）：每隊與聯盟的累計。"""
    rows = game_rows(da.team_boxes(season, SCOPE, list(FIELDS)))
    teams, league = defaultdict(Acc), Acc()
    for r in rows:
        teams[r['team']].add(r)
        league.add(r)
    return teams, league


def prev_available(season):
    return not (feature_deps.closure('F1.net_rating') & feature_deps.unavailable_bases(season))


def latest_available_before(season):
    s = season - 1
    while not prev_available(s):
        s -= 1
    return s


def compute_season(season, purpose='feature_computation', root='.', da=None):
    """批次計算某季每一場（use_team_stats 範圍）兩隊的賽前 F1。回傳每隊每場一列。"""
    da = da or DataAccess(purpose, root=root)
    status = feature_deps.availability('F1.net_rating', season)[0]
    games = da.games(season, SCOPE)
    if status == 'unavailable':
        return [{'game_id': g['game_id'], 'team': t, 'season': season, 'as_of': g['start_utc'], 'status': 'unavailable',
                 'n_games': None, 'raw': None, 'prior_source': None, 'prior_seasons': [],
                 'reason': feature_deps.availability('F1.net_rating', season)[1], **{f: None for f in FEATURES}}
                for g in games for t in (g['home'], g['away'])]
    rows = game_rows(da.team_boxes(season, SCOPE, list(FIELDS)))
    by_date = defaultdict(list)
    for r in rows:
        by_date[r['et_date']].append(r)

    prev = season - 1
    prev_teams = prev_league = None
    if prev_available(prev):
        try:
            prev_teams, prev_league = season_totals(da, prev)
        except FileNotFoundError:
            prev_teams = None
        if prev_teams is not None and not prev_league.n:
            prev_teams = prev_league = None          # 上季沒有資料（例如 2014-15 的上一季）
    fallback_season = None if prev_available(prev) else latest_available_before(prev)
    fallback_league = league_values(season_totals(da, fallback_season)[1]) if fallback_season else None

    cur_teams, cur_league = defaultdict(Acc), Acc()
    out = []
    by_game = {g['game_id']: g for g in games}
    for d in sorted(by_date):
        todays = by_date[d]
        lg = league_values(cur_league)
        for r in todays:
            g = by_game[r['game_id']]
            acc = cur_teams[r['team']]
            prior, src, seasons = _prior(r['team'], prev, prev_teams, prev_league, cur_league, lg,
                                         fallback_season, fallback_league)
            raw = acc.values()
            rec = {'game_id': r['game_id'], 'team': r['team'], 'opp': r['opp'], 'season': season, 'as_of': g['start_utc'],
                   'n_games': acc.n, 'period': [acc.first, acc.last] if acc.n else None, 'prior_source': src,
                   'prior_seasons': seasons, 'shrink_games': SHRINK_GAMES, 'prior_team_weight': PRIOR_TEAM_WEIGHT,
                   'status': status, 'raw': raw}
            if prior is None:
                rec.update({'status': 'missing', **{f: None for f in FEATURES}})
            else:
                for k in ('ortg', 'drtg', 'net_rating', 'pace'):
                    x = raw[k] if raw else 0.0
                    rec[f'F1.{k}'] = (acc.n * x + SHRINK_GAMES * prior[k]) / (acc.n + SHRINK_GAMES)
            out.append(rec)
        for r in todays:                            # 當天的比賽要到隔天才加入累計
            cur_teams[r['team']].add(r)
            cur_league.add(r)
    return out


def _prior(team, prev, prev_teams, prev_league, cur_league, cur_lg_values, fallback_season, fallback_league):
    if prev_teams is not None and team in prev_teams:
        tv, lv = prev_teams[team].values(), league_values(prev_league)
        return ({k: PRIOR_TEAM_WEIGHT * tv[k] + (1 - PRIOR_TEAM_WEIGHT) * lv[k] for k in tv}, 'team_previous_season', [prev])
    if cur_league.n >= MIN_LEAGUE_GAMES_F1 * 2:      # cur_league 以「隊場」計，每場兩列
        return cur_lg_values, 'league_average_current_season_to_date', [prev + 1]
    if fallback_league is not None:
        return fallback_league, 'league_average_latest_available_season', [fallback_season]
    return None, 'missing', []


def f1_reference(da, team, as_of):
    """逐場參考實作（測試用）：直接以 DataAccess(as_of) 讀資料重算單一隊伍的 F1，用來比對批次結果。"""
    season = da._season_of(as_of)
    rows = [r for r in game_rows(da.team_boxes(season, SCOPE, list(FIELDS), as_of)) if r['team'] == team]
    acc = Acc()
    for r in rows:
        acc.add(r)
    src = da.f1_prior_source(team, as_of, 'F1.net_rating')
    return acc, src
