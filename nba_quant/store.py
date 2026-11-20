"""JSONL.gz 讀寫、sha256、原子寫入。資料檔以 git 版控，所以輸出要穩定（鍵排序、固定 gzip mtime）。"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tempfile
from typing import Iterable, Iterator


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def write_jsonl_gz(path: str, records: Iterable[dict]) -> str:
    """原子寫入；gzip mtime 固定為 0，相同內容 → 相同位元組（git 才不會產生假變更）。回傳 sha256。"""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0) as gz:
        for r in records:
            gz.write((dumps(r) + '\n').encode('utf-8'))
    data = buf.getvalue()
    _atomic_write(path, data)
    return hashlib.sha256(data).hexdigest()


def read_jsonl_gz(path: str) -> Iterator[dict]:
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_json(path: str, obj) -> str:
    data = (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + '\n').encode('utf-8')
    _atomic_write(path, data)
    return hashlib.sha256(data).hexdigest()


def read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: str, data: bytes):
    d = os.path.dirname(path) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.tmp-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
