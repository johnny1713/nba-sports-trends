"""共用 HTTP：重試、退避、硬性逾時、禮貌間隔。所有錯誤都回報給呼叫端記錄，不吞掉。"""
from __future__ import annotations

import gzip
import json
import signal
import threading
import time
import urllib.error
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


class FetchError(RuntimeError):
    def __init__(self, url, status, msg=''):
        super().__init__(f'{status} {url} {msg}')
        self.url, self.status = url, status


class Fetcher:
    def __init__(self, min_interval=0.35, retries=3, timeout=20, hard_timeout=40):
        self.min_interval, self.retries, self.timeout, self.hard = min_interval, retries, timeout, hard_timeout
        self._last = 0.0
        self.calls = 0
        self.errors = []          # [(url, status, message)]，寫進資料品質報告

    def _wait(self):
        dt = time.time() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.time()

    def get_bytes(self, url, headers=None) -> bytes:
        last = None
        for attempt in range(self.retries):
            self._wait()
            self.calls += 1
            h = {'User-Agent': UA, 'Accept-Encoding': 'gzip', 'Accept-Language': 'en-US,en;q=0.9,zh-TW;q=0.8'}
            h.update(headers or {})
            use_alarm = threading.current_thread() is threading.main_thread() and hasattr(signal, 'SIGALRM')
            if use_alarm:
                signal.signal(signal.SIGALRM, _raise_timeout)
                signal.alarm(self.hard)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=self.timeout) as r:
                    b = r.read()
                    if r.headers.get('Content-Encoding') == 'gzip':
                        b = gzip.decompress(b)
                    return b
            except urllib.error.HTTPError as e:
                last = (e.code, str(e))
                if e.code in (400, 401, 403, 404):
                    break                              # 不會因重試而改變
            except Exception as e:                     # 逾時、連線中斷
                last = (type(e).__name__, str(e)[:120])
            finally:
                if use_alarm:
                    signal.alarm(0)
            time.sleep(3 ** (attempt + 1))
        self.errors.append((url, last[0], last[1]))
        raise FetchError(url, last[0], last[1])

    def get_json(self, url):
        return json.loads(self.get_bytes(url))


def _raise_timeout(*_):
    raise TimeoutError('hard timeout')
