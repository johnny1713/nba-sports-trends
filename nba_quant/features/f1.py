"""
F1 球季累計效率（第一階段 stage 2；2026-11-21 修正四個程式缺口，公式與先驗規則不變）。

定義（每隊、每場預測，只用該場**美東日期之前**、同一球季、`use_team_stats` 範圍內已完賽、且**有效**的比賽）：

    回合數（每隊每場）  poss_T = FGA − OREB + TOV + 0.44 × FTA
    該場回合數          game_poss = (poss_T + poss_O) / 2
    時間係數            minutes_factor = (48 + 5 × OT) / 48
    ORtg_raw = 100 × Σ 得分 / Σ game_poss
    DRtg_raw = 100 × Σ 失分 / Σ game_poss
    Net_raw  = ORtg_raw − DRtg_raw
    Pace_raw = Σ game_poss / Σ minutes_factor         （每 48 分鐘回合數）

收縮（n = 該隊本季至今有效場數，M = SHRINK_GAMES）：  F1 = (n × raw + M × prior) / (n + M)
先驗（現行 A；B 方案待核准，見 f1_prior_B_proposal.md 審查文件）：
    team_previous_season                   prior = W × 該隊上季全季值 + (1 − W) × 上季聯盟平均
    league_average_current_season_to_date  prior = 本季至今聯盟平均（上季不可用，且本季至今 ≥ 100 場）
    league_average_latest_available_season prior = 最近一個可用完整球季的聯盟平均（上季不可用、本季至今 < 100 場）
    上季沒有資料（2014-15 開季）            prior = 本季至今聯盟平均（≥ 100 場），否則 status = missing（不補值）
聯盟平均：總量加權；ORtg 與 DRtg 的聯盟平均相同，Net 的聯盟平均為 0。

資料有效性（2026-11-21）：
- 賽程與特徵輸出分離：預測目標場次以 DataAccess.games()（賽程）為準逐場輸出，**不需要該場自己的 box**。
- 歷史比賽只有在**兩隊 box 都有效**時才進入累計：任一隊缺漏（缺 box、缺欄位、失誤不可用）→ 該場不計算共同回合數，
  雙方都不累計，記錄於 excluded（場次、球隊、原因）。不以另一隊資料推測缺漏隊伍。
- 單場回合數：每隊 poss_T > 0 且 game_poss > 0；否則 invalid_possessions，排除並保留原始數據。
- 異常值警告（只標記、不排除、不影響數值）：該季有效比賽的每 48 分鐘回合數超出「中位數 ± 6 × 1.4826 × MAD」
  （與 box 稽核 v1 相同方法；開發期 9,519 場實際 0 場超出）。
- 狀態：available、available_prior_excluded、unavailable（依賴規則不可用）、missing（沒有先驗）、
  invalid（累計回合數 ≤ 0 卻有場數，理論上不會發生，發生即不輸出數值）。

先驗方案（使用者 2026-11-21 決定）：維持 A；當季至今聯盟平均採 leave-one-team-out（排除目標球隊參與的比賽），
100 場門檻以排除後的有效比賽數判斷。B、C 方案未採用（見提案文件）。2018-19 先驗在第 100 場切換造成的不連續為已知限制。
box 稽核 v1：error → 該場不進雙方累計；warning → 保留並記錄。

用途（2026-11-21）：每個公開入口都自行檢查 DataAccess 的用途，只允許 ALLOWED_PURPOSES；data_quality 等其他用途一律拒絕，
不只靠資料存取層。

參數 SHRINK_GAMES = 10、PRIOR_TEAM_WEIGHT = 0.5 是預先登記的預設值，**沒有用任何資料調整**；
未來若要調整，只能用開發期資料（config.DEV_SEASONS）。
"""
from __future__ import annotations

import os
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .. import asof, audit_coverage, config, feature_deps
from ..data_access import MIN_LEAGUE_GAMES_F1, DataAccess

SHRINK_GAMES = 10.0
PRIOR_TEAM_WEIGHT = 0.5
FEATURES = ('F1.ortg', 'F1.drtg', 'F1.net_rating', 'F1.pace')
KEYS = ('ortg', 'drtg', 'net_rating', 'pace')
FIELDS = ('pts', 'fga', 'fta', 'oreb', 'tov', 'overtimes')
SCOPE = 'use_team_stats'
ALLOWED_PURPOSES = ('feature_computation', 'history_features', 'validation', 'final_evaluation')
WARN_MAD_K = 6.0


class PurposeNotAllowed(config.HoldoutLocked):
    pass


def check_purpose(da):
    if not isinstance(da, DataAccess):
        raise PurposeNotAllowed('F1 只接受 DataAccess')
    if da.purpose not in ALLOWED_PURPOSES:
        raise PurposeNotAllowed(f'F1 特徵計算不接受用途 {da.purpose}（只允許 {ALLOWED_PURPOSES}）')
    return da


def team_poss(b):
    return b['fga'] - b['oreb'] + b['tov'] + 0.44 * b['fta']


@dataclass
class History:
    """有效比賽（隊場列）與排除／警告紀錄。"""
    rows: list
    excluded: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    game_ids: list = field(default_factory=list)
    loto_excluded: list = field(default_factory=list)
    status: str = 'available'


def get_valid_f1_games(da, season, as_of=None, exclude_team=None):
    """F1 有效比賽的**唯一**判斷入口（2026-11-21）。F1 球隊累計、聯盟先驗、league_games_asof、
    league_games_asof_excl_team、100 場門檻、f1_prior_source 全部只透過這裡取得有效比賽。依序：
      1. as-of：只取 as_of 美東日期之前的比賽（as_of 為 None → 整季）
      2. 完賽、`use_team_stats` 範圍（DataAccess.games）
      3. 兩隊 box 都存在且欄位齊全（含失誤可用性）
      4. box 稽核 v1 ERROR 排除（稽核涵蓋清單驗證失敗 → AuditIntegrityError，不計算）
      5. 回合數有效（每隊 > 0、共同回合數 > 0）
      6. 2017-18 等 F1 不可用球季：status = unavailable，不讀取任何資料
      7. leave-one-team-out：exclude_team 參與的比賽不計入（另列 loto_excluded，不算資料問題）
    唯一不需要稽核的情況：該季賽程為空**且**原始 games／teambox 檔都不存在（完全沒有資料，status = no_raw_data）。
    回傳 History：rows（每隊每場一列）、game_ids、excluded、loto_excluded、warnings、status。"""
    check_purpose(da)
    if feature_deps.availability('F1.net_rating', season)[0] == 'unavailable':
        return History(rows=[], status='unavailable')
    schedule = da.games(season, SCOPE, as_of)
    raw = audit_coverage.paths(season, da.root)
    if not schedule and not os.path.exists(raw['teambox']) and not os.path.exists(raw['games']):
        return History(rows=[], status='no_raw_data')  # 該季完全沒有原始資料（例：2014-15 的上一季）：沒有可稽核的比賽
    boxes = da.team_boxes(season, SCOPE, list(FIELDS), as_of)
    excl_by = defaultdict(list)
    for gid, team, why in da.log[-1].get('excluded', []):
        excl_by[gid].append((team, why))
    flags = da.box_audit_flags(season, as_of)          # fail closed：涵蓋清單不符即拋出錯誤
    by = defaultdict(dict)
    for b in boxes:
        by[b['game_id']][b['team']] = b
    h = History(rows=[])
    for g in schedule:
        gid, teams = g['game_id'], (g['home'], g['away'])
        got = by.get(gid, {})
        missing = [t for t in teams if t not in got]
        if missing:
            reasons = dict(excl_by.get(gid, []))
            h.excluded.append({'game_id': gid, 'start_utc': g['start_utc'], 'teams': list(teams),
                               'missing_teams': missing, 'reason': ';'.join(sorted({reasons.get(t, 'missing_box') for t in missing})),
                               'affected': 'excluded from both teams\' F1 history'})
            continue
        fl = [f for k in ((gid, g['home']), (gid, g['away']), (gid, None)) for f in flags.get(k, [])]
        errs = [f for f in fl if f['severity'] == 'error']
        if errs:
            h.excluded.append({'game_id': gid, 'start_utc': g['start_utc'], 'teams': list(teams), 'missing_teams': [],
                               'reason': 'box_audit_error', 'audit_flags': [{k: f.get(k) for k in ('team', 'check', 'detail')}
                                                                          for f in errs],
                               'raw_boxes': {t: {k: got[t][k] for k in FIELDS} for t in teams},
                               'affected': 'excluded from both teams\' F1 history'})
            continue
        a, b = got[g['home']], got[g['away']]
        pa, pb = team_poss(a), team_poss(b)
        gp = (pa + pb) / 2.0
        if pa <= 0 or pb <= 0 or gp <= 0:
            h.excluded.append({'game_id': gid, 'start_utc': g['start_utc'], 'teams': list(teams), 'missing_teams': [],
                               'reason': 'invalid_possessions', 'poss': {g['home']: pa, g['away']: pb},
                               'raw_boxes': {t: {k: got[t][k] for k in FIELDS} for t in teams},
                               'affected': 'excluded from both teams\' F1 history'})
            continue
        if exclude_team is not None and exclude_team in teams:
            h.loto_excluded.append(gid)
            continue
        for f in fl:
            if f['severity'] == 'warning':
                h.warnings.append({'game_id': gid, 'source': 'box_audit_v1', 'team': f.get('team'), 'check': f['check'],
                                   'detail': f['detail'], 'action': 'kept_with_warning'})
        mf = (48 + 5 * a['overtimes']) / 48.0
        for t, o in ((a, b), (b, a)):
            h.rows.append({'game_id': gid, 'start_utc': g['start_utc'], 'et_date': asof.et_date(g['start_utc']),
                           'team': t['team'], 'opp': o['team'], 'pf': t['pts'], 'pa': o['pts'], 'poss': gp, 'mf': mf})
        h.game_ids.append(gid)
    paces = {r['game_id']: r['poss'] / r['mf'] for r in h.rows}
    if len(paces) >= 30:
        med = statistics.median(paces.values())
        mad = statistics.median(abs(v - med) for v in paces.values()) * 1.4826
        if mad > 0:
            lo, hi = med - WARN_MAD_K * mad, med + WARN_MAD_K * mad
            h.warnings += [{'game_id': gid, 'source': 'f1_pace_band', 'pace_per48': v, 'band': [lo, hi], 'action': 'flag_only'}
                           for gid, v in sorted(paces.items()) if v < lo or v > hi]
    return h


def build_history(da, season, schedule=None):
    """相容名稱：整季的有效比賽（= get_valid_f1_games(da, season)）。schedule 參數已不使用。"""
    return get_valid_f1_games(da, season)


def game_rows(boxes):
    """（相容用）把球隊 box 配成每隊每場一列；只收兩隊都在且回合數 > 0 的比賽。"""
    by = defaultdict(list)
    for b in boxes:
        by[b['game_id']].append(b)
    rows = []
    for gid, bs in by.items():
        if len(bs) != 2:
            continue
        a, b = bs
        pa, pb = team_poss(a), team_poss(b)
        gp = (pa + pb) / 2.0
        if pa <= 0 or pb <= 0 or gp <= 0:
            continue
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
        d = asof.et_date(r['start_utc']).isoformat()              # 期間以美東日期記錄
        self.first = d if self.first is None or d < self.first else self.first
        self.last = d if self.last is None or d > self.last else self.last

    def values(self):
        if not self.n or self.poss <= 0 or self.mf <= 0:
            return None
        o, d = 100 * self.pf / self.poss, 100 * self.pa / self.poss
        return {'ortg': o, 'drtg': d, 'net_rating': o - d, 'pace': self.poss / self.mf}


def minus(acc, other):
    """acc − other（leave-one-team-out：從聯盟累計扣掉目標球隊參與的比賽）。"""
    r = Acc()
    r.n, r.pf, r.pa, r.poss, r.mf = acc.n - other.n, acc.pf - other.pf, acc.pa - other.pa, acc.poss - other.poss, acc.mf - other.mf
    return r


def league_values(acc):
    """聯盟平均（總量加權：每場每隊各算一次，所以 pf 與 pa 總和相同；Net = 0）。"""
    v = acc.values()
    if v is None:
        return None
    return {'ortg': v['ortg'], 'drtg': v['ortg'], 'net_rating': 0.0, 'pace': v['pace']}


def season_totals(da, season):
    """某季全季（完整球季，用於下一季的先驗）：每隊與聯盟的累計。只用有效比賽。"""
    check_purpose(da)
    h = get_valid_f1_games(da, season)
    teams, league = defaultdict(Acc), Acc()
    for r in h.rows:
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


def _empty(rec):
    for k in KEYS:
        rec[f'raw_{k}'] = None
        rec[f'prior_{k}'] = None
        rec[f'F1.{k}'] = None
    return rec


@dataclass
class F1Result:
    rows: list
    excluded: list
    warnings: list


def compute(season, purpose='feature_computation', root='.', da=None):
    """批次計算某季賽程上每一場（use_team_stats 範圍）兩隊的賽前 F1。回傳 F1Result（列、排除紀錄、警告）。"""
    da = check_purpose(da or DataAccess(purpose, root=root))
    status, reason = feature_deps.availability('F1.net_rating', season)
    schedule = da.games(season, SCOPE)
    base = {'team_shrinkage_M': SHRINK_GAMES, 'prior_team_weight_W': PRIOR_TEAM_WEIGHT,
            'league_prior_K': None}                       # 方案 A 不使用 K（不適用，不虛構數值）
    if status == 'unavailable':
        rows = [_empty({'game_id': g['game_id'], 'team': t, 'opp': o, 'season': season, 'as_of': g['start_utc'],
                        'status': 'unavailable', 'reason': reason, 'n_games': None, 'period': None,
                        'prior_source': None, 'prior_season': [], 'prior_value': None, 'prior_weight': 'not_applicable',
                        'prior_weight_basis': None, 'league_games_asof': None, 'league_games_asof_excl_team': None,
                        'excluded_history_games': None, **base})
                for g in schedule for t, o in ((g['home'], g['away']), (g['away'], g['home']))]
        return F1Result(rows, [], [])
    hist = get_valid_f1_games(da, season)
    by_date = defaultdict(list)
    for r in hist.rows:
        by_date[r['et_date']].append(r)
    excl_dates = defaultdict(list)
    for e in hist.excluded:
        excl_dates[asof.et_date(e['start_utc'])].append(e)

    prev, prev_teams, prev_league, fallback_season, fallback_league = prior_context(da, season)

    cur_teams, cur_league = defaultdict(Acc), Acc()
    involved = defaultdict(Acc)                             # 每隊：其參與比賽的兩列（供 leave-one-team-out 扣除）
    excl_count = defaultdict(int)
    out = []
    sched_by_date = defaultdict(list)
    for g in schedule:
        sched_by_date[asof.et_date(g['start_utc'])].append(g)
    for d in sorted(set(sched_by_date) | set(by_date) | set(excl_dates)):
        for g in sched_by_date.get(d, []):                  # 預測目標：以賽程為準，不需要本場 box
            for t, o in ((g['home'], g['away']), (g['away'], g['home'])):
                acc = cur_teams[t]
                loto = minus(cur_league, involved[t])               # 當季聯盟平均排除目標球隊參與的比賽
                prior, src, seasons, basis, weight = _prior(t, prev, prev_teams, prev_league, loto, fallback_season,
                                                            fallback_league)
                raw = acc.values()
                rec = {'game_id': g['game_id'], 'team': t, 'opp': o, 'season': season, 'as_of': g['start_utc'],
                       'n_games': acc.n, 'period': [acc.first, acc.last] if acc.n else None,
                       'prior_source': src, 'prior_season': seasons, 'prior_value': dict(prior) if prior else None,
                       'prior_weight': weight, 'prior_weight_basis': basis,
                       'league_games_asof': cur_league.n // 2, 'league_games_asof_excl_team': loto.n // 2,
                       'excluded_history_games': excl_count[t],
                       'status': status, 'reason': reason if status != 'available' else '', **base}
                for k in KEYS:
                    rec[f'raw_{k}'] = raw[k] if raw else None
                    rec[f'prior_{k}'] = prior[k] if prior else None
                if acc.n and raw is None:                          # 有場數但累計無效：比「沒有先驗」更嚴重，優先標 invalid
                    rec.update({'status': 'invalid', 'reason': '累計回合數 ≤ 0', **{f: None for f in FEATURES}})
                elif prior is None:
                    rec.update({'status': 'missing', 'reason': '沒有可用的先驗（不補值）', **{f: None for f in FEATURES}})
                else:
                    for k in KEYS:
                        x = raw[k] if raw else 0.0                # n = 0 時權重為 0，x 不影響結果
                        rec[f'F1.{k}'] = (acc.n * x + SHRINK_GAMES * prior[k]) / (acc.n + SHRINK_GAMES)
                out.append(rec)
        for r in by_date.get(d, []):                         # 當天的有效比賽要到隔天才加入累計
            cur_teams[r['team']].add(r)
            cur_league.add(r)
            involved[r['team']].add(r)                       # 本隊列
            involved[r['opp']].add(r)                        # 對手列（同一場的另一隊也「參與」這場）
        for e in excl_dates.get(d, []):
            for t in e['teams']:
                excl_count[t] += 1
    return F1Result(out, hist.excluded, hist.warnings)


def compute_season(season, purpose='feature_computation', root='.', da=None):
    """相容介面：只回傳列。"""
    return compute(season, purpose, root, da).rows


def _prior(team, prev, prev_teams, prev_league, loto, fallback_season, fallback_league):
    """回傳 (prior, source, seasons, basis, weight)。方案 A（使用者 2026-11-21 決定維持）：
    上季可用 → W × 該隊上季值 + (1 − W) × 上季聯盟平均；
    上季不可用 → 當季至今（排除目標球隊參與的比賽）有效聯盟比賽 ≥ 100 場才用當季至今聯盟平均（LOTO），
    否則用最近可用球季的聯盟平均；2014-15 沒有上季 → 未滿 100 場為 missing。100 是預先登記的資料可用性門檻。"""
    tv = prev_teams[team].values() if prev_teams is not None and team in prev_teams else None
    lv = league_values(prev_league) if prev_league is not None else None
    if tv is not None and lv is not None:                # 上季該隊或聯盟累計無效（回合數 ≤ 0）→ 視同沒有上季值，不代入
        return ({k: PRIOR_TEAM_WEIGHT * tv[k] + (1 - PRIOR_TEAM_WEIGHT) * lv[k] for k in tv}, 'team_previous_season', [prev],
                f'{PRIOR_TEAM_WEIGHT} × 該隊 {prev} 全季值 + {1 - PRIOR_TEAM_WEIGHT} × {prev} 聯盟平均',
                {'team_previous_season': PRIOR_TEAM_WEIGHT, 'league_previous_season': 1 - PRIOR_TEAM_WEIGHT})
    g = loto.n // 2                                       # 排除目標球隊後的有效聯盟比賽數
    if g >= MIN_LEAGUE_GAMES_F1:
        return (league_values(loto), 'league_average_current_season_to_date', [prev + 1],
                f'本季至今聯盟平均，排除本隊參與的比賽（{g} 場 ≥ {MIN_LEAGUE_GAMES_F1}）', 'not_applicable')
    if fallback_league is not None:
        return (fallback_league, 'league_average_latest_available_season', [fallback_season],
                f'{fallback_season} 全季聯盟平均（本季至今排除本隊後 {g} 場 < {MIN_LEAGUE_GAMES_F1}；上季不可用）',
                'not_applicable')
    return None, 'missing', [], f'無上季資料且本季至今排除本隊後 {g} 場 < {MIN_LEAGUE_GAMES_F1}', 'not_applicable'


def prior_context(da, season):
    """某季先驗所需的上季累計與後備球季（compute 與 prior_source 共用，皆由 get_valid_f1_games 而來）。"""
    prev = season - 1
    prev_teams = prev_league = None
    if prev_available(prev):
        prev_teams, prev_league = season_totals(da, prev)
        if not prev_league.n:
            prev_teams = prev_league = None              # 上季沒有資料（例如 2014-15 的上一季）
    fallback_season = None if prev_available(prev) else latest_available_before(prev)
    fallback_league = league_values(season_totals(da, fallback_season)[1]) if fallback_season else None
    return prev, prev_teams, prev_league, fallback_season, fallback_league


def prior_source(da, team, as_of, feature='F1.net_rating'):
    """單一隊伍在 as_of 時的先驗來源（DataAccess.f1_prior_source 委派到這裡）。
    有效比賽一律取自 get_valid_f1_games(as_of, exclude_team=team)，決策一律走 compute 用的同一個 _prior，
    不另外計數。"""
    check_purpose(da)
    season = da._season_of(as_of)
    if feature_deps.availability(feature, season)[0] == 'unavailable':
        return {'feature': feature, 'status': 'unavailable'}
    prev, prev_teams, prev_league, fb_season, fb_league = prior_context(da, season)
    cur = get_valid_f1_games(da, season, as_of, exclude_team=team)
    loto = Acc()
    for r in cur.rows:
        loto.add(r)
    _, src, seasons, basis, weight = _prior(team, prev, prev_teams, prev_league, loto, fb_season, fb_league)
    out = {'feature': feature, 'team': team, 'as_of': as_of, 'source': src, 'seasons': seasons,
           'prior_weight': weight, 'prior_weight_basis': basis,
           'current_season_valid_game_ids': list(cur.game_ids),
           'current_season_games_to_date': len(cur.game_ids)}
    if src == 'team_previous_season':
        acc = prev_teams[team]
        out.update({'n_games': acc.n, 'period': [acc.first, acc.last]})
    elif src == 'league_average_current_season_to_date':
        out.update({'n_games': len(cur.game_ids), 'period': [loto.first, loto.last] if loto.n else None,
                    'excluded_seasons': [] if prev_available(prev) else [prev]})
    elif src == 'league_average_latest_available_season':
        lg = season_totals(da, fb_season)[1]
        out.update({'n_games': lg.n // 2, 'period': [lg.first, lg.last] if lg.n else None, 'excluded_seasons': [prev]})
    else:
        out.update({'n_games': 0, 'period': None})
    return out


def f1_reference(da, team, as_of):
    """逐場參考實作（測試用）：直接以 DataAccess(as_of) 讀資料重算單一隊伍的累計與先驗來源。"""
    check_purpose(da)
    season = da._season_of(as_of)
    sched = da.games(season, SCOPE, as_of)
    rows = []
    boxes = {(b['game_id'], b['team']): b for b in da.team_boxes(season, SCOPE, list(FIELDS), as_of)}
    flags = da.box_audit_flags(season, as_of)
    for g in sched:
        a, b = boxes.get((g['game_id'], g['home'])), boxes.get((g['game_id'], g['away']))
        if not a or not b:
            continue
        if any(f['severity'] == 'error' for k in ((g['game_id'], g['home']), (g['game_id'], g['away']), (g['game_id'], None))
               for f in flags.get(k, [])):
            continue
        rows += [r for r in game_rows([a, b]) if r['team'] == team]
    acc = Acc()
    for r in rows:
        acc.add(r)
    src = da.f1_prior_source(team, as_of, 'F1.net_rating')
    return acc, src
