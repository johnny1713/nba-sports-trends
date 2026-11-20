"""
V2 workflow 的單一進入點：python -m nba_quant.jobs <job> [args]

各階段完成後才接上對應模組；尚未完成的 job 直接報錯，不假裝成功。
daily 在 V2 啟用（存在 data/V2_ENABLED）之前一律略過——排程先裝好也不會產生任何輸出。
"""
from __future__ import annotations

import argparse
import os
import sys

ENABLE_FLAG = os.path.join('data', 'V2_ENABLED')


def main(argv=None):
    p = argparse.ArgumentParser(prog='nba_quant.jobs')
    p.add_argument('job', choices=['test', 'backfill', 'backtest', 'daily'])
    p.add_argument('--season', type=int)
    a, rest = p.parse_known_args(argv)

    if a.job == 'test':
        print('tests are run by the workflow step; nothing to do')
        return 0
    if a.job == 'daily':
        if not os.path.exists(ENABLE_FLAG):
            print('V2 not enabled yet (data/V2_ENABLED missing) — skipping')
            return 0
        from . import daily
        return daily.main(rest)
    if a.job == 'backfill':
        from . import backfill
        return backfill.main(a.season, rest)
    if a.job == 'backtest':
        from .backtest import run
        return run.main(rest)
    return 2


if __name__ == '__main__':
    sys.exit(main())
