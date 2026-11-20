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
    with open(p, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as f:
        f.write(b)
    print(name, st, len(b))
    return b


def main():
    os.makedirs(OUT, exist_ok=True)
    save('bbref_box_201410280NOP', 'https://www.basketball-reference.com/boxscores/201410280NOP.html')
    time.sleep(4)
    save('bbref_box_202401150PHI', 'https://www.basketball-reference.com/boxscores/202401150PHI.html')


if __name__ == '__main__':
    main()
