"""
資料存取層（使用者 2026-11-20 第六輪：模型實作前必須完成的防護）。

所有特徵、模型、回測程式**只能**透過這裡讀資料；不得直接讀 data/raw（有結構測試）。這一層強制：

1. 用途（purpose）：每次存取都要宣告用途。（2026-11-20 第七輪修訂）
   模型凍結前：
   - 2024-25：只有 data_quality 可讀；其他所有用途拒絕。
   - 2025-26：任何用途都拒絕（包含 data_quality）。
   模型凍結後（config.freeze_model → 每季分別 holdout_begin）：
   - 兩季都只能以 final_evaluation 用途、帶著**該季**已登記且尚未出結果的 run_id 讀取；每季一次。
   - training、feature_computation、feature_selection、tuning、model_selection、evaluation（開發期 walk-forward）、
     backtest 永遠不能讀這兩季。
2. 時間：as_of（預測場次的開賽時間）之前的**前一個美東日期（含）以前**已完賽的比賽才回傳；同日較早場次也不回傳。
3. 範圍：依分類表的用途欄位（use_team_stats、use_fatigue、use_elo、counts_for_standings、train_sample）篩選。
4. 欄位：要求某季不可用的基礎欄位（2017-18 tov）直接報錯；需要 tov 時排除 tov_usable = False 的 box（2020-21 附加賽）。
5. 盤口隔離：本模組不 import 任何盤口模組；回傳的比賽只含白名單欄位（沒有 odds_*）。
6. 特徵輸入：require_features() 經 feature_deps 依賴檢查；未登記或不可用的特徵拒絕。

這一層只做「選哪些資料」，不計算任何特徵值。
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from . import asof, config, feature_deps, store
from .model_data_stats import tov_definition

PURPOSES = ('data_quality', 'feature_computation', 'training', 'feature_selection', 'tuning', 'model_selection',
            'evaluation', 'backtest', 'final_evaluation', 'validation', 'history_features')
VALIDATION = tuple(config.VALIDATION_SEASONS)   # 2023-24
NO_METRICS = ('history_features',)
DATA_QUALITY_ONLY = (2025,)          # 2024-25
FULLY_LOCKED = (2026,)               # 2025-26
SCOPES = ('use_team_stats', 'use_fatigue', 'use_elo', 'counts_for_standings', 'train_sample')
GAME_FIELDS = ('game_id', 'season', 'start_utc', 'home', 'away', 'home_abbr', 'away_abbr', 'home_pts', 'away_pts',
               'game_type', 'box_source')
# 預先登記的資料可用性門檻（使用者 2026-11-20 第七輪接受）。不是模型最佳化結果；
# 未來若要調整，只能用開發期資料評估，不得查看鎖定測試期結果（有測試鎖住數值，改動會讓測試失敗、需經核准）。
MIN_SAMPLE_F2 = 3                    # F2 近 N 場：可用場次少於此數 → missing（不補值）
MIN_LEAGUE_GAMES_F1 = 100            # F1 先驗用「當季至今聯盟平均」所需的最少場次；不足時退回最近的可用球季


class FieldUnavailable(LookupError):
    pass


class FeatureRejected(LookupError):
    pass


def _parse_ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(timezone.utc)


class DataAccess:
    def __init__(self, purpose, run_id=None, root='.'):
        if purpose not in PURPOSES:
            raise ValueError(f'未知的用途：{purpose}（允許：{PURPOSES}）')
        self.purpose, self.run_id, self.root = purpose, run_id, root
        self._cls = None
        self.log = []          # 每次存取的紀錄（用途、球季、範圍、as_of、回傳筆數、排除原因）

    # ------------------------------------------------------------ 鎖定
    def check_season(self, season, as_of=None):
        if self.purpose == 'history_features':
            return self._check_history(season, as_of)
        if self.purpose == 'validation':
            if season in config.HOLDOUT_SEASONS:
                raise config.HoldoutLocked('validation 不得讀取 2024-25、2025-26')
            if season in VALIDATION:
                config.check_validation(self.run_id)          # 凍結後、已登記、尚未完成的唯一一次驗證
            return
        if self.purpose == 'final_evaluation':
            if season not in config.HOLDOUT_SEASONS:
                raise config.HoldoutLocked('final_evaluation 只用於鎖定測試期的正式最終評估')
            if not self.run_id:
                raise config.HoldoutLocked('final_evaluation 必須帶著該季已登記的 run_id（模型凍結後 holdout_begin）')
            config.check_seasons([season], self.run_id)       # 該季已登記、尚未出結果
            return
        if season in FULLY_LOCKED:
            raise config.HoldoutLocked(f'{season}（2025-26）模型凍結前完全鎖定：任何用途都不得讀取（用途 {self.purpose}）')
        if season in DATA_QUALITY_ONLY and self.purpose != 'data_quality':
            raise config.HoldoutLocked(f'{season}（2024-25）鎖定測試期：用途 {self.purpose} 不得讀取，只允許 data_quality'
                                       '（模型凍結後的正式評估須用 final_evaluation + run_id）')
        if season in VALIDATION and self.purpose != 'data_quality':
            raise config.HoldoutLocked(f'{season}（2023-24）驗證期：用途 {self.purpose} 不得讀取，只允許 data_quality'
                                       '（模型凍結後以 validation + run_id 驗證一次）')

    def _check_history(self, season, as_of):
        """歷史特徵生成（第八輪）：不是自由讀整季的權限。
        - 必須給 as_of（預測場次的開賽時間），只回傳 as_of 美東日期之前已完賽的比賽。
        - 不得讀取預測目標球季之後的球季。
        - 預測目標球季本身必須已被授權：開發期 → 放行；2023-24 → 已登記的驗證 run；2024-25／2025-26 → 該季已登記的
          正式最終測試 run；之後的球季尚未定義 → 拒絕。所以凍結前，任何 2023-24 以後的歷史都讀不到。
        - 不得輸出評估指標（assert_metrics_allowed）。"""
        if not as_of:
            raise config.HoldoutLocked('history_features 必須指定 as_of（預測時間點）')
        target = self._season_of(as_of)
        if season > target:
            raise config.HoldoutLocked(f'history_features：不得讀取預測目標球季 {target} 之後的 {season}')
        if target in VALIDATION:
            config.check_validation(self.run_id)
        elif target in config.HOLDOUT_SEASONS:
            config.check_seasons([target], self.run_id)
        elif target >= config.LIVE_SEASON:
            raise config.HoldoutLocked(f'{target} 的歷史特徵規則尚未定義')

    def assert_metrics_allowed(self, seasons):
        """輸出整體評估指標前必須呼叫：歷史特徵用途永遠不能輸出指標；2023-24 只能在登記的驗證 run、
        2024-25／2025-26 只能在該季登記的正式最終測試 run 中輸出。"""
        if self.purpose in NO_METRICS:
            raise config.HoldoutLocked('history_features 用途不得輸出任何評估指標')
        for s in seasons:
            if s in VALIDATION:
                if self.purpose != 'validation':
                    raise config.HoldoutLocked(f'{s}（2023-24）的評估指標只能在正式驗證中輸出')
                config.check_validation(self.run_id)
            elif s in config.HOLDOUT_SEASONS:
                if self.purpose != 'final_evaluation':
                    raise config.HoldoutLocked(f'{s} 的評估指標只能在正式最終測試中輸出')
                config.check_seasons([s], self.run_id)

    # ------------------------------------------------------------ 讀檔（只在這裡）
    def _path(self, *p):
        return os.path.join(self.root, *p)

    def _classification(self):
        if self._cls is None:
            self._cls = {r['game_id']: r for r in csv.DictReader(open(self._path('data', 'reference', 'game_classification.csv'),
                                                                        encoding='utf-8'))}
        return self._cls

    def _raw_games(self, season):
        out = []
        for p in (self._path('data', 'raw', 'espn', str(season), 'games.jsonl.gz'),
                  self._path('data', 'raw', 'espn_playin', str(season), 'games.jsonl.gz')):
            if os.path.exists(p):
                out += list(store.read_jsonl_gz(p))
        return out

    def _raw_boxes(self, season):
        out = {}
        for p in (self._path('data', 'raw', 'espn', str(season), 'teambox.jsonl.gz'),
                  self._path('data', 'raw', 'espn_playin', str(season), 'teambox.jsonl.gz'),
                  self._path('data', 'raw', 'espn_playin', str(season), 'teambox_bbref.jsonl.gz')):
            if os.path.exists(p):
                for b in store.read_jsonl_gz(p):
                    out[(b['game_id'], b['team'])] = b
        return out

    # ------------------------------------------------------------ 公開介面
    def games(self, season, scope, as_of=None):
        """完賽、資料完整、在 scope 內、且（若給 as_of）在 as_of 的美東日期之前的比賽。"""
        self.check_season(season, as_of)
        if scope not in SCOPES:
            raise ValueError(f'未知的資料範圍：{scope}（允許：{SCOPES}）')
        cls = self._classification()
        boxes = None
        out = []
        cutoff = asof.et_date(as_of) if as_of else None
        for g in self._raw_games(season):
            if g['status'] != 'final':
                continue
            c = cls.get(g['game_id'])
            if c is None:
                raise ValueError(f"{g['game_id']} 不在分類表中")
            if c[scope] != 'True':
                continue
            if g.get('complete') is not True:
                if c['game_type'] != 'PLAY_IN':
                    continue
                boxes = boxes if boxes is not None else self._raw_boxes(season)
                if not ((g['game_id'], g['home']) in boxes and (g['game_id'], g['away']) in boxes):
                    continue
            if cutoff and asof.et_date(g['start_utc']) >= cutoff:
                continue
            d = {k: g.get(k) for k in GAME_FIELDS}
            d['game_type'] = c['game_type']
            out.append(d)
        out.sort(key=lambda g: (g['start_utc'], g['game_id']))
        self.log.append({'call': 'games', 'purpose': self.purpose, 'season': season, 'scope': scope, 'as_of': as_of,
                         'returned': len(out)})
        return out

    def team_boxes(self, season, scope, fields, as_of=None):
        """回傳 [{game_id, team, <fields>}]。要求不可用的欄位直接報錯；需要 tov 時排除 tov_usable = False 的 box。"""
        bad = set(fields) & feature_deps.unavailable_bases(season)
        if bad:
            raise FieldUnavailable(f'{season}: 欄位 {sorted(bad)} 整季不可用（不補值、不以 BBRef 覆蓋）')
        unknown = set(fields) - set(feature_deps.BOX_FIELDS) - set(feature_deps.GAME_BOX_FIELDS)
        if unknown:
            raise ValueError(f'未知的 box 欄位：{sorted(unknown)}')
        games = self.games(season, scope, as_of)
        boxes = self._raw_boxes(season)
        out, excluded = [], []
        for g in games:
            for t in (g['home'], g['away']):
                b = boxes.get((g['game_id'], t))
                if b is None:
                    excluded.append((g['game_id'], t, 'missing_box'))
                    continue
                if 'tov' in fields and not tov_definition(b, g['game_type'], season)[1]:
                    excluded.append((g['game_id'], t, tov_definition(b, g['game_type'], season)[0]))
                    continue
                if any(b.get(f) is None for f in fields):
                    excluded.append((g['game_id'], t, 'missing_field'))
                    continue
                out.append({'game_id': g['game_id'], 'team': t, 'start_utc': g['start_utc'], 'game_type': g['game_type'],
                            **{f: b[f] for f in fields}})
        self.log.append({'call': 'team_boxes', 'purpose': self.purpose, 'season': season, 'scope': scope,
                         'fields': sorted(fields), 'as_of': as_of, 'returned': len(out), 'excluded': excluded})
        return out

    def neutral_status(self, game_ids):
        """中立場狀態（data/reference/neutral_sites.csv）：'neutral' / 'unknown' / 'home'（未列入 = 一般主場）。"""
        if not hasattr(self, '_neutral'):
            p = self._path('data', 'reference', 'neutral_sites.csv')
            self._neutral = ({r['game_id']: r['status'] for r in csv.DictReader(open(p, encoding='utf-8'))}
                             if os.path.exists(p) else {})
        return {g: self._neutral.get(g, 'home') for g in game_ids}

    def require_features(self, features, season, as_of=None):
        """模型輸入檢查：未登記 → KeyError；不可用 → FeatureRejected；回傳每個特徵的狀態。"""
        self.check_season(season, as_of)
        res = feature_deps.check_model_inputs(features, season)
        bad = {f: why for f, (st, why) in res.items() if st == 'unavailable'}
        if bad:
            raise FeatureRejected(f'{season} 不可用的特徵不得進入模型：{bad}')
        return res

    # ------------------------------------------------------------ 跨球季 fallback（只選資料，不算數值）
    def f2_window(self, team, as_of, n, feature='F2.last5_net_rating'):
        """F2 近 N 場：只用可用的比賽；當季不足時，只有上一季同一特徵可用才往回數，
        絕不跳過不可用的球季（2017-18）去湊場數；少於 MIN_SAMPLE_F2 → missing。"""
        season = self._season_of(as_of)
        if feature_deps.availability(feature, season)[0] == 'unavailable':
            return {'feature': feature, 'status': 'unavailable', 'games': [], 'n_used': 0, 'seasons': []}
        picked, seasons, stopped = [], [], None
        s = season
        while len(picked) < n:
            if feature_deps.availability(feature, s)[0] == 'unavailable':
                stopped = f'{s} 不可用，停止往回數（不跳過）'
                break
            try:
                gs = [g for g in self.games(s, 'use_team_stats', as_of) if team in (g['home'], g['away'])]
            except config.HoldoutLocked:
                stopped = f'{s} 鎖定，停止'
                break
            if not gs and s != season:
                stopped = f'{s} 沒有資料，停止'
                break
            take = gs[::-1][:n - len(picked)]
            if take:
                seasons.append(s)
            picked += take
            s -= 1
        n_used = len(picked)
        status = 'ok' if n_used == n else ('partial' if n_used >= MIN_SAMPLE_F2 else 'missing')
        # complete = 真的湊滿 N 場；partial 的平均只能以「近 n_used 場」使用，不可當成完整近 N 場
        return {'feature': feature, 'team': team, 'as_of': as_of, 'n_requested': n, 'n_used': n_used, 'status': status,
                'complete': n_used == n,
                'seasons': seasons, 'games': [g['game_id'] for g in picked],
                'period': [picked[-1]['start_utc'][:10], picked[0]['start_utc'][:10]] if picked else None,
                'stopped': stopped}

    def f1_prior_source(self, team, as_of, feature='F1.net_rating'):
        """F1 收縮先驗的來源：上季同一特徵可用 → 該隊上季值；不可用 → 當時可取得的聯盟平均
        （當季至今 ≥ MIN_LEAGUE_GAMES_F1 場則用當季至今；否則用最近一個可用的完整球季），不得使用不可用的球季。"""
        season = self._season_of(as_of)
        if feature_deps.availability(feature, season)[0] == 'unavailable':
            return {'feature': feature, 'status': 'unavailable'}
        prev = season - 1
        prev_ok = not (feature_deps.closure(feature) & feature_deps.unavailable_bases(prev))
        if prev_ok:
            gs = [g for g in self.games(prev, 'use_team_stats') if team in (g['home'], g['away'])]
            if gs:
                return {'feature': feature, 'team': team, 'as_of': as_of, 'source': 'team_previous_season', 'seasons': [prev],
                        'n_games': len(gs), 'period': [gs[0]['start_utc'][:10], gs[-1]['start_utc'][:10]]}
        cur = self.games(season, 'use_team_stats', as_of)
        if len(cur) >= MIN_LEAGUE_GAMES_F1:
            return {'feature': feature, 'team': team, 'as_of': as_of, 'source': 'league_average_current_season_to_date',
                    'seasons': [season], 'n_games': len(cur), 'period': [cur[0]['start_utc'][:10], cur[-1]['start_utc'][:10]],
                    'excluded_seasons': [] if prev_ok else [prev]}
        if prev_ok:                                   # 上季可用但沒有資料（2014-15 的上一季）：不補值
            return {'feature': feature, 'team': team, 'as_of': as_of, 'source': 'missing', 'seasons': [],
                    'n_games': 0, 'period': None, 'current_season_games_to_date': len(cur)}
        s = prev - 1
        while s in feature_deps.SEASON_UNAVAILABLE and feature_deps.closure(feature) & feature_deps.unavailable_bases(s):
            s -= 1
        gs = self.games(s, 'use_team_stats')
        return {'feature': feature, 'team': team, 'as_of': as_of, 'source': 'league_average_latest_available_season',
                'seasons': [s], 'n_games': len(gs), 'period': [gs[0]['start_utc'][:10], gs[-1]['start_utc'][:10]] if gs else None,
                'excluded_seasons': [prev], 'current_season_games_to_date': len(cur)}

    def _season_of(self, as_of):
        """以分類表找 as_of 所屬球季（as_of 為某場比賽的開賽時間）。"""
        t = _parse_ts(as_of)
        best = None
        for r in self._classification().values():
            if _parse_ts(r['start_utc']) <= t and (best is None or r['start_utc'] > best['start_utc']):
                best = r
        if best is None:
            raise ValueError(f'{as_of} 早於所有資料')
        return int(best['season'])
