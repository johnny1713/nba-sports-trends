"""
探路用：抓 covers.com 的 NBA 賽事列表與幾場單場頁，存成 samples/ 供分析頁面結構。
雲端 session 的 proxy 擋 covers.com，所以只能在 GitHub Actions 上跑。
"""
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
OUT = 'samples'


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'  [失敗] {url}: {e}')
        return None
    finally:
        time.sleep(1.5)


def save(name, text):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
        f.write(text)


def summarize(html):
    sec = re.search(r'<section[^>]*id="trends"[^>]*>(.*?)</section>', html, re.S)
    trends = sec.group(1) if sec else ''
    form = re.search(r'<section[^>]*id="form_trends"[^>]*>(.*?)</section>', html, re.S)
    h4 = re.findall(r'<h4[^>]*class="[^"]*\b(High|Low)\b[^"]*"[^>]*>(.*?)</h4>', trends, re.S)
    print(f'    trends 段落 {len(trends)} 字元 / Check back shortly: {"Check back shortly" in trends}'
          f' / 趨勢標題 {len(h4)} 條 / form_trends 段落: {bool(form)}'
          f' / single-form-trend {html.count("single-form-trend")} 次')
    for _cls, t in h4[:6]:
        print('      ', re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', t)).strip()[:160])
    labels = re.findall(r'other-odds-label[^>]*>\s*([^<]+)<', html)
    print('    盤口標籤:', sorted(set(l.strip() for l in labels))[:15])


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo('America/New_York')).date()
    except Exception:
        today = (datetime.now(timezone.utc) - timedelta(hours=4)).date()

    # 往前看 3 天（已完賽頁的趨勢會保留，可驗證解析）、往後看 14 天（找第一個有比賽的日子）
    found = []
    for delta in list(range(-3, 15)):
        d = (today + timedelta(days=delta)).isoformat()
        html = fetch(f'https://www.covers.com/sports/nba/matchups?selectedDate={d}')
        if not html:
            continue
        arts = re.findall(r'<article\s+[^>]*class="[^"]*gamebox[^"]*"[^>]*>.*?</article>', html, re.S | re.I)
        ids = [m for a in arts for m in re.findall(r'data-url=["\']?/sports/game/(\d+)', a)]
        print(f'[{d}] gamebox {len(arts)} 個, game id {len(ids)} 個')
        if arts and not any(x[0] == d for x in found):
            save(f'list_{d}.html', html)
            found.append((d, ids))
        if len([f for f in found if f[0] >= today.isoformat()]) >= 1 and delta >= 0 and len(found) >= 2:
            break

    for d, ids in found:
        for gid in ids[:3]:
            for suffix in ('/picks', ''):
                url = f'https://www.covers.com/sport/basketball/nba/matchup/{gid}{suffix}'
                html = fetch(url)
                if not html:
                    continue
                name = f'matchup_{d}_{gid}{suffix.replace("/", "_")}.html'
                save(name, html)
                print(f'  {name}: {len(html)} 字元')
                summarize(html)
    if not found:
        print('[!] 這段期間的 NBA 賽事列表都沒有 gamebox，可能網址或版面不同')
        html = fetch('https://www.covers.com/sports/nba/matchups')
        if html:
            save('list_default.html', html)
            print('  預設頁', len(html), '字元，連結樣本:', re.findall(r'href="(/sport[^"]*nba[^"]*)"', html)[:10])


if __name__ == '__main__':
    sys.exit(main())
