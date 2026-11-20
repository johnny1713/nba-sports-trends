"""V2 Phase 3 準備：抓真實原始資料當解析器測試樣本，存到 samples/v2probe/（會被 probe.yml commit 到 main）。"""
import gzip, json, os, re, signal, time, urllib.request, urllib.error, functools
print = functools.partial(print, flush=True)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
OUT = 'samples/v2probe'


def _alarm(*_):
    raise TimeoutError('hard')


signal.signal(signal.SIGALRM, _alarm)


def get(url):
    signal.alarm(30)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Encoding': 'gzip', 'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8'})
        with urllib.request.urlopen(req, timeout=20) as r:
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return r.status, b
    except urllib.error.HTTPError as e:
        return e.code, b''
    except Exception as e:
        return str(e), b''
    finally:
        signal.alarm(0)
        time.sleep(0.5)


def save(name, url):
    st, b = get(url)
    p = os.path.join(OUT, name + '.gz')
    with gzip.open(p, 'wb', mtime=0) as f:
        f.write(b)
    print(name, st, len(b))
    return b


def main():
    os.makedirs(OUT, exist_ok=True)
    SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='
    SUM = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='
    ODDS = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{0}/competitions/{0}/odds'
    picks = {}
    for tag, d in [('s2016', '20160115'), ('s2023', '20230115'), ('s2024', '20240115'), ('s2025', '20250115'), ('s2027', '20261118')]:
        b = save(f'scoreboard_{tag}', SB + d)
        ev = json.loads(b)['events']
        picks[tag] = ev[0]['id']
    # 季後賽 / play-in / 延賽 例子
    for tag, d in [('playin2024', '20240416'), ('post2024', '20240421')]:
        save(f'scoreboard_{tag}', SB + d)
    for tag, eid in picks.items():
        save(f'summary_{tag}_{eid}', SUM + eid)
        save(f'odds_{tag}_{eid}', ODDS.format(eid))
    # 今天未開打的一場（盤口 snapshot 格式）
    b = save('scoreboard_today', SB + time.strftime('%Y%m%d', time.gmtime(time.time() - 5 * 3600)))
    ev = json.loads(b).get('events', [])
    if ev:
        save(f'odds_today_{ev[-1]["id"]}', ODDS.format(ev[-1]['id']))
        save(f'summary_today_{ev[-1]["id"]}', SUM + ev[-1]['id'])
    # 玩運彩：預設頁 + 明天
    tw = time.gmtime(time.time() + 8 * 3600)
    save('playsport_default', 'https://www.playsport.cc/predict/games?allianceid=3')
    save('playsport_tomorrow', 'https://www.playsport.cc/predict/games?allianceid=3&gametime=' + time.strftime('%Y%m%d', time.gmtime(time.time() + 32 * 3600)))
    html = gzip.decompress(open(os.path.join(OUT, 'playsport_default.gz'), 'rb').read()).decode('utf-8', 'replace')
    print('tabs:', re.findall(r'<[^>]+>\s*(國際盤|運彩盤)\s*<', html)[:10])
    for m in re.finditer(r'(國際盤|運彩盤)', html):
        print('  ctx:', re.sub(r'\s+', ' ', html[max(0, m.start() - 300):m.end() + 300])[:600])
        break


if __name__ == '__main__':
    main()
