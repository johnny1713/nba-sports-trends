"""V2 Phase 2：ESPN 歷史盤口覆蓋率稽核 + 玩運彩盤口探路。只印日誌，不寫檔、不 commit。"""
import json, time, urllib.request, urllib.error, gzip, re, signal, functools, datetime as dt
from collections import Counter, defaultdict
print = functools.partial(print, flush=True)

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


class Hard(Exception):
    pass


def _alarm(*_):
    raise Hard('hard timeout')


signal.signal(signal.SIGALRM, _alarm)


def get(url, timeout=20):
    h = {'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9', 'Accept-Encoding': 'gzip'}
    signal.alarm(30)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return r.status, b.decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception as e:
        return type(e).__name__, ''
    finally:
        signal.alarm(0)
        time.sleep(0.25)


# 每季：(年份標籤, 開始日, 結束日)。抽樣每 9 天一天，只算例行賽（season.type == 2）
SEASONS = [(y, dt.date(y - 1, 10, 25), dt.date(y, 4, 10)) for y in range(2015, 2027)]
SEASONS.append((2027, dt.date(2026, 10, 21), dt.date(2026, 11, 19)))


def has_price(x):
    return isinstance(x, dict) and (x.get('decimal') is not None or x.get('american') not in (None, '') or x.get('value') is not None)


def audit_item(it):
    """回傳一家莊家在一場比賽的欄位完整度。"""
    f = {}
    f['spread'] = it.get('spread') is not None
    f['total'] = it.get('overUnder') is not None
    h, a = it.get('homeTeamOdds') or {}, it.get('awayTeamOdds') or {}
    f['ml_cur'] = h.get('moneyLine') is not None and a.get('moneyLine') is not None
    f['spread_price_cur'] = h.get('spreadOdds') is not None and a.get('spreadOdds') is not None
    f['total_price_cur'] = it.get('overOdds') is not None and it.get('underOdds') is not None
    for stage in ('open', 'close'):
        ho, ao = h.get(stage) or {}, a.get(stage) or {}
        f[f'{stage}_spread'] = bool((ho.get('pointSpread') or {}).get('american') or (ho.get('pointSpread') or {}).get('alternateDisplayValue'))
        f[f'{stage}_spread_price'] = has_price(ho.get('spread')) and has_price(ao.get('spread'))
        f[f'{stage}_ml'] = has_price(ho.get('moneyLine')) and has_price(ao.get('moneyLine'))
        tot = it.get(stage) or {}
        f[f'{stage}_total'] = bool(tot.get('total'))
        f[f'{stage}_total_price'] = has_price(tot.get('over')) and has_price(tot.get('under'))
        f[f'{stage}_decimal'] = isinstance(ho.get('moneyLine'), dict) and ho['moneyLine'].get('decimal') is not None
    return f


def main():
    t_start = time.time()
    summary = {}
    for label, d0, d1 in SEASONS:
        games = 0
        any_odds = 0
        prov_counts = []
        provs = Counter()
        best = Counter()      # 每場「至少一家」具備該欄位
        first_prov = Counter()
        sample_note = None
        d = d0
        while d <= d1:
            st, b = get(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d:%Y%m%d}')
            d += dt.timedelta(days=9)
            if st != 200 or not b:
                continue
            for e in json.loads(b).get('events', []):
                if (e.get('season') or {}).get('type') != 2:
                    continue
                if not (e.get('status', {}).get('type', {}).get('completed')):
                    continue
                games += 1
                st2, b2 = get(f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{e['id']}/competitions/{e['id']}/odds")
                if st2 != 200 or not b2:
                    prov_counts.append(0)
                    continue
                items = json.loads(b2).get('items', [])
                items = [i for i in items if 'Live' not in ((i.get('provider') or {}).get('name') or '')]
                prov_counts.append(len(items))
                if items:
                    any_odds += 1
                    first_prov[(items[0].get('provider') or {}).get('name')] += 1
                agg = defaultdict(bool)
                for it in items:
                    provs[(it.get('provider') or {}).get('name')] += 1
                    for k, v in audit_item(it).items():
                        agg[k] = agg[k] or v
                for k, v in agg.items():
                    best[k] += v
        n = games or 1
        summary[label] = dict(games=games, any=any_odds, avg_prov=sum(prov_counts) / max(len(prov_counts), 1),
                              fields={k: round(100 * v / n) for k, v in sorted(best.items())},
                              providers=provs.most_common(8), primary=first_prov.most_common(3))
        s = summary[label]
        print(f"\n=== {label - 1}-{str(label)[2:]} 抽樣比賽 {games} 場，有盤口 {any_odds} ({100 * any_odds / n:.0f}%)，平均莊家 {s['avg_prov']:.1f}  [{time.time() - t_start:.0f}s]")
        print('   欄位(至少一家具備,%):', json.dumps(s['fields']))
        print('   莊家:', s['providers'])
        print('   第一順位:', s['primary'])

    # ---------- 玩運彩 ----------
    print('\n\n##### playsport #####')
    st, b = get('https://www.playsport.cc/robots.txt')
    print('robots.txt', st)
    print(b[:1500])
    for url in ('https://www.playsport.cc/predict/games?allianceid=3',
                'https://www.playsport.cc/predict/games?allianceid=3&gametime=' + time.strftime('%Y%m%d', time.gmtime(time.time() + 8 * 3600))):
        st, b = get(url)
        print('\n', url, st, len(b))
        plain = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<script.*?</script>|<style.*?</style>', ' ', b, flags=re.S)))
        for kw in ('讓分', '大小', '不讓分', '主勝', '賠率', '1.7', '1.8'):
            idx = [m.start() for m in re.finditer(re.escape(kw), plain)][:3]
            for i in idx:
                print(f'   [{kw}]', plain[max(0, i - 120):i + 160])
        print('   script data hints:', re.findall(r'(?:odds|handicap|spread|total)[A-Za-z_]*["\']?\s*[:=]', b)[:20])


if __name__ == '__main__':
    main()
