#!/usr/bin/env python3
"""Run the manual Wizard acceptance suite against a live HocusPocus API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def read_json(url: str) -> dict:
    with urlopen(url, timeout=10) as response:  # noqa: S310 - explicit local acceptance URL
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default=os.environ.get('HOCUSPOCUS_BASE_URL'))
    parser.add_argument('--profile', choices=('plan', 'simulate', 'real'), default='simulate')
    parser.add_argument('--scenario', choices=('smoke', 'full', 'studio', 'language', 'music-video', 'comic', 'series', 'failure', 'cancel', 'workspace'), default='smoke')
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Run only tests that failed in the previous Playwright invocation')
    parser.add_argument('--confirm-real', action='store_true')
    args = parser.parse_args()

    if not args.base_url:
        print(
            'Pass --base-url with the URL shown by Pinokio, or set HOCUSPOCUS_BASE_URL.',
            file=sys.stderr,
        )
        return 2
    base_url = args.base_url.rstrip('/')
    try:
        config = read_json(f'{base_url}/api/v1/system-config')
    except (OSError, URLError, ValueError) as exc:
        print(f'HocusPocus is not reachable at {base_url}: {exc}', file=sys.stderr)
        return 2
    actual = config.get('execution_mode', 'real')
    if actual != args.profile:
        print(
            f'Backend mode is {actual!r}, requested {args.profile!r}. Restart HocusPocus with '
            f'HOCUSPOCUS_EXECUTION_MODE={args.profile} before running this suite.',
            file=sys.stderr,
        )
        return 2
    if args.profile == 'real' and not args.confirm_real:
        print('Real generation requires --confirm-real.', file=sys.stderr)
        return 2

    environment = os.environ.copy()
    environment.update({
        'HOCUSPOCUS_BASE_URL': base_url,
        'HOCUSPOCUS_E2E_PROFILE': args.profile,
        'HOCUSPOCUS_E2E_SCENARIO': args.scenario,
        'HOCUSPOCUS_E2E_CONFIRM_REAL': 'YES' if args.confirm_real else '',
    })
    command = ['npm', 'run', 'test:e2e:wizard', '--']
    if args.headed:
        command.append('--headed')
    if args.resume:
        command.append('--last-failed')
    return subprocess.run(command, cwd=ROOT / 'ui', env=environment, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
