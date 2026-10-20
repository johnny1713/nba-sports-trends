"""
探路用：抓 Odds Shark 的 NBA 頁面，確認它的趨勢有沒有「星期幾」這類條件、句型長什麼樣。
雲端 session 的 proxy 擋外部網站，所以只能在 GitHub Actions 上跑（probe.yml）。
結果存到 samples/oddsshark/，並把摘要印在日誌。

（covers 的探路版本見 git 歷史 7ca3852）
"""
import os
import re
import time
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
OUT = 'samples/oddsshark'
BASE = 'https://www.oddsshark.com'
WEEKDAY = re.compile(r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\b')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.geturl(), r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'  [失敗] {url}: {e}')
        return None, None
    finally:
        time.sleep(2)


def text(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()


def save(name, body):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
        f.write(body)


def summarize(name, body):
    plain = text(re.sub(r'<script.*?</script>|<style.*?</style>', ' ', body, flags=re.S))
    # 趨勢句通常長這樣："The Cavaliers are 6-14 ATS in their last 20 games played on a Tuesday."
    sents = set(re.findall(r'[A-Z][^.]{0,160}?\b\d+-\d+(?:-\d+)?\b[^.]{0,160}\.', plain))
    trendish = [s for s in sents if re.search(r'\b(ATS|SU|OVER|UNDER|Over|Under|last \d+)\b', s)]
    wk = [s for s in trendish if WEEKDAY.search(s)]
    print(f'  {name}: {len(body)} 字元，像趨勢的句子 {len(trendish)} 條，含星期幾 {len(wk)} 條')
    for s in sorted(trendish)[:15]:
        print('     ', s[:200])
    for s in wk[:15]:
        print('   [星期]', s[:200])
    return trendish, wk


def main():
    os.makedirs(OUT, exist_ok=True)
    pages = {}
    for path in ('/nba/odds', '/nba/scores', '/nba/trends', '/nba/computer-picks', '/nba/consensus-picks'):
        url, body = fetch(BASE + path)
        if body:
            name = path.strip('/').replace('/', '_') + '.html'
            save(name, body)
            pages[name] = body
            print(f'[{path}] → {url}，{len(body)} 字元')
            summarize(name, body)

    # 從列表頁找單場頁連結（Odds Shark 的單場網址通常是 /nba/<客>-<主>-odds-<月>-<日>-<年>-<id>）
    links = set()
    for body in pages.values():
        for href in re.findall(r'href="(/nba/[a-z0-9-]+-odds-[a-z]+-\d+-\d{4}-\d+)"', body):
            links.add(href)
        for href in re.findall(r'href="(https://www\.oddsshark\.com/nba/[a-z0-9-]+-odds-[a-z]+-\d+-\d{4}-\d+)"', body):
            links.add(href.replace(BASE, ''))
    print(f'找到單場連結 {len(links)} 個:', sorted(links)[:10])
    if not links:
        # 沒有就把頁面裡所有 /nba/ 開頭的連結印出來，方便下一輪調整
        allnba = set()
        for body in pages.values():
            allnba.update(re.findall(r'href="((?:https://www\.oddsshark\.com)?/nba/[^"#?]+)"', body))
        print('頁面上的 /nba/ 連結樣本:', sorted(allnba)[:60])

    total_wk = 0
    for href in sorted(links)[:4]:
        for suffix in ('', '/trends'):
            url, body = fetch(BASE + href + suffix)
            if not body:
                continue
            name = 'game_' + href.strip('/').split('/')[-1][-40:] + suffix.replace('/', '_') + '.html'
            save(name, body)
            _, wk = summarize(name, body)
            total_wk += len(wk)
    print(f'=== 單場頁含星期幾的趨勢合計 {total_wk} 條 ===')


if __name__ == '__main__':
    main()
