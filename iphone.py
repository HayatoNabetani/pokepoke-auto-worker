#!/usr/bin/env python3
"""Small WebDriverAgent client for inspecting the connected iPhone."""
import argparse
import base64
import json
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
SESSION_FILE = ROOT / '.wda-session'


def request(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(os.getenv('WDA_URL', 'http://127.0.0.1:8100') + path,
                                 data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=45) as response:
        result = json.load(response)
    if isinstance(result.get('value'), dict) and result['value'].get('error'):
        raise RuntimeError(json.dumps(result['value'], ensure_ascii=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('session')
    shot = sub.add_parser('screenshot')
    shot.add_argument('path', nargs='?', default=str(ROOT / 'screen.png'))
    sub.add_parser('source')
    tap = sub.add_parser('tap')
    tap.add_argument('x', type=float)
    tap.add_argument('y', type=float)
    swipe = sub.add_parser('swipe')
    for name in ('x1', 'y1', 'x2', 'y2'):
        swipe.add_argument(name, type=float)
    sub.add_parser('activate')
    args = parser.parse_args()
    if args.command == 'status':
        result = request('GET', '/status')
    elif args.command == 'session':
        result = request('POST', '/session', {'capabilities': {'alwaysMatch': {
            'bundleId': 'jp.pokemon.pokemontcgp', 'shouldWaitForQuiescence': False}}})
        session = result.get('sessionId') or result.get('value', {}).get('sessionId')
        if not session:
            raise RuntimeError('WebDriverAgent did not return a session ID')
        SESSION_FILE.write_text(session)
    elif args.command == 'screenshot':
        result = request('GET', '/screenshot')
        Path(args.path).write_bytes(base64.b64decode(result['value']))
        print(Path(args.path).resolve())
        return
    else:
        session = SESSION_FILE.read_text().strip()
        prefix = '/session/' + session
        if args.command == 'source':
            result = request('GET', prefix + '/source')
        elif args.command == 'tap':
            result = request('POST', prefix + '/wda/tap', {'x': args.x, 'y': args.y})
        elif args.command == 'swipe':
            result = request('POST', prefix + '/actions', {'actions': [{
                'type': 'pointer', 'id': 'finger', 'parameters': {'pointerType': 'touch'},
                'actions': [
                    {'type': 'pointerMove', 'duration': 0, 'x': args.x1, 'y': args.y1},
                    {'type': 'pointerDown', 'button': 0},
                    {'type': 'pause', 'duration': 100},
                    {'type': 'pointerMove', 'duration': 500, 'x': args.x2, 'y': args.y2},
                    {'type': 'pointerUp', 'button': 0}]}]})
        else:
            result = request('POST', prefix + '/wda/apps/activate',
                             {'bundleId': 'jp.pokemon.pokemontcgp'})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
