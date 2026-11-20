"""資料來源探路（大改版 Phase 1）：只印日誌，不寫任何檔案、不 commit。"""
import json, time, urllib.request, urllib.error, gzip, re

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
NBA_HDR = {'Referer': 'https://www.nba.com/', 'Origin': 'https://www.nba.com',
           'x-nba-stats-origin': 'stats', 'x-nba-stats-token': 'true', 'Accept': 'application/json'}


def get(url, hdr=None, timeout=25):
    h = {'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9', 'Accept-Encoding': 'gzip'}
    h.update(hdr or {})
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return r.status, b.decode('utf-8', 'replace'), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, '', time.time() - t0
    except Exception as e:
        return type(e).__name__ + ':' + str(e)[:80], '', time.time() - t0
    finally:
        time.sleep(1.5)


def probe(name, url, hdr=None, show=None):
    st, body, dt = get(url, hdr)
    print(f'\n### {name}\n  {url}\n  status={st} size={len(body)} {dt:.1f}s')
    if body and show:
        try:
            show(body)
        except Exception as e:
            print('  [show error]', e)
    return body


def j(b):
    return json.loads(b)


def sb_show(b):
    d = j(b)
    ev = d.get('events', [])
    print(f'  events={len(ev)}')
    for e in ev[:2]:
        c = e['competitions'][0]
        print('  ', e['id'], e['name'], e['date'], 'odds:', json.dumps(c.get('odds', [])[:1])[:600])
    return ev


def main():
    # ---------- ESPN ----------
    today = time.strftime('%Y%m%d', time.gmtime(time.time() - 6 * 3600))
    b = probe('ESPN scoreboard today', f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={today}', show=sb_show)
    ev_today = j(b)['events'] if b else []
    past = {}
    for d in ('20251110', '20250115', '20240115', '20230115', '20200115', '20150115'):
        b = probe(f'ESPN scoreboard {d}', f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}', show=sb_show)
        if b:
            try:
                past[d] = j(b)['events'][0]['id']
            except Exception:
                pass
    ids = ([ev_today[0]['id']] if ev_today else []) + list(past.values())
    for eid in ids:
        def odds_show(b):
            d = j(b)
            print('  count', d.get('count'))
            for it in d.get('items', [])[:3]:
                print('   provider', it.get('provider', {}).get('name'), '| spread', it.get('spread'), '| OU', it.get('overUnder'),
                      '| keys', [k for k in it if k in ('open', 'close', 'current', 'homeTeamOdds', 'awayTeamOdds')])
                for k in ('open', 'close', 'current'):
                    if k in it:
                        print('     ', k, json.dumps(it[k])[:300])
                ht = it.get('homeTeamOdds', {})
                print('      homeTeamOdds', json.dumps({x: ht.get(x) for x in ('moneyLine', 'spreadOdds', 'open', 'close', 'current')})[:500])
        probe(f'ESPN core odds event {eid}', f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{eid}/competitions/{eid}/odds', show=odds_show)
    if ids:
        def summ(b):
            d = j(b)
            print('  keys', list(d.keys()))
            print('  pickcenter', json.dumps(d.get('pickcenter', []))[:600])
            print('  injuries', json.dumps(d.get('injuries', []))[:500])
            bx = d.get('boxscore', {}).get('teams', [])
            if bx:
                print('  team box stats', [s.get('name') for s in bx[0].get('statistics', [])][:30])
        probe('ESPN summary (today)', f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={ids[0]}', show=summ)
        if len(ids) > 1:
            probe('ESPN summary (past)', f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={ids[1]}', show=summ)
    probe('ESPN injuries', 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries',
          show=lambda b: print('  teams', len(j(b).get('injuries', [])), json.dumps(j(b).get('injuries', [])[:1])[:700]))

    # ---------- NBA official ----------
    probe('NBA cdn schedule', 'https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json',
          show=lambda b: print('  gameDates', len(j(b)['leagueSchedule']['gameDates'])))
    probe('NBA cdn today scoreboard', 'https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json',
          show=lambda b: print('  games', len(j(b)['scoreboard']['games'])))
    for name, url in [
        ('stats.nba.com team advanced', 'https://stats.nba.com/stats/leaguedashteamstats?MeasureType=Advanced&PerMode=PerGame&Season=2024-25&SeasonType=Regular%20Season&LeagueID=00&LastNGames=0&Month=0&OpponentTeamID=0&PaceAdjust=N&Period=0&PlusMinus=N&Rank=N&DateFrom=&DateTo=&GameScope=&GameSegment=&Location=&Outcome=&PORound=0&PlayerExperience=&PlayerPosition=&SeasonSegment=&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0&VsConference=&VsDivision=&Conference=&Division='),
        ('stats.nba.com team gamelog', 'https://stats.nba.com/stats/leaguegamelog?Counter=0&Direction=ASC&LeagueID=00&PlayerOrTeam=T&Season=2024-25&SeasonType=Regular%20Season&Sorter=DATE'),
    ]:
        probe(name, url, hdr=NBA_HDR, show=lambda b: print('  ', b[:300]))
    probe('NBA injury report page', 'https://official.nba.com/nba-injury-report-2025-26-season/',
          show=lambda b: print('  pdf links', len(re.findall(r'Injury-Report_[^"]+\.pdf', b)), re.findall(r'https?://[^"]+Injury-Report_[^"]+\.pdf', b)[-2:]))

    # ---------- Basketball Reference ----------
    probe('BBRef 2025 season', 'https://www.basketball-reference.com/leagues/NBA_2025.html',
          show=lambda b: print('  has advanced table', 'advanced-team' in b))
    probe('BBRef games 2025 Jan', 'https://www.basketball-reference.com/leagues/NBA_2025_games-january.html',
          show=lambda b: print('  rows', b.count('data-stat="visitor_team_name"')))

    # ---------- Odds ----------
    probe('The Odds API (no key)', 'https://api.the-odds-api.com/v4/sports')
    probe('SBR archive index', 'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba/nbaoddsarchives.htm',
          show=lambda b: print('  links', re.findall(r'href="([^"]*nba[^"]*\.(?:xlsx?|htm))"', b)[:20]))
    probe('Taiwan sportslottery home', 'https://www.sportslottery.com.tw/',
          show=lambda b: print('  title', re.findall(r'<title>(.*?)</title>', b, re.S)[:1]))
    probe('Taiwan sportslottery blob', 'https://blob.sportslottery.com.tw/apidata/Pre/ListByLeague.json',
          show=lambda b: print('  ', b[:300]))
    probe('playsport NBA', 'https://www.playsport.cc/predict/games?allianceid=3',
          show=lambda b: print('  title', re.findall(r'<title>(.*?)</title>', b, re.S)[:1]))


if __name__ == '__main__':
    main()
