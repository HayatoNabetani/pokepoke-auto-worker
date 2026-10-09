"""Prepare the target app and unlock a numeric passcode without logging it."""
import os
import re
import time
import xml.etree.ElementTree as ET

from iphone import ROOT, SESSION_FILE, request

APP_ID = 'jp.pokemon.pokemontcgp'
ATTEMPT_FILE = ROOT / '.runtime' / 'unlock-attempted'


def passcode_buttons(source):
    tree = ET.fromstring(source)
    labels = ' '.join(node.get('label', '') + ' ' + node.get('name', '')
                      for node in tree.iter())
    if not any(word in labels.lower() for word in ('passcode', 'パスコード')):
        raise RuntimeError('パスコード画面を確認できないため、入力せず停止しました。')
    buttons = {}
    for node in tree.iter('XCUIElementTypeButton'):
        if node.get('visible') == 'false' or node.get('enabled') == 'false':
            continue
        match = re.match(r'^([0-9])(?:\s|$)', node.get('label') or node.get('name', ''))
        if not match:
            continue
        x, y, width, height = (float(node.get(k, '0')) for k in ('x', 'y', 'width', 'height'))
        if width > 0 and height > 0:
            buttons[match[1]] = (x + width / 2, y + height / 2)
    if set(buttons) != set('0123456789'):
        raise RuntimeError('数字キーを確認できないため、入力せず停止しました。')
    return buttons


class Device:
    def __init__(self, session):
        self.prefix = '/session/' + session
        # Keep the secret out of subprocess environments and diagnostic output.
        self._passcode = os.environ.pop('IPHONE_PASSCODE', '')

    def locked(self):
        value = request('GET', '/wda/locked').get('value')
        if not isinstance(value, bool):
            raise RuntimeError('iPhoneのロック状態を確認できませんでした。')
        return value

    def unlock(self):
        if not self.locked():
            ATTEMPT_FILE.unlink(missing_ok=True)
            return False
        if ATTEMPT_FILE.exists():
            raise RuntimeError('前回の解除が確認できていないため再入力しません。iPhoneを手動で解除してから再開してください。')
        if not re.fullmatch(r'[0-9]{4}|[0-9]{6}', self._passcode):
            raise RuntimeError('iPhoneがロック中です。.envのIPHONE_PASSCODEに数字4桁または6桁を設定してください。')
        try:
            request('POST', self.prefix + '/wda/pressButton', {'name': 'home'})
            time.sleep(1)
            if not self.locked():
                return True
            # Use the SpringBoard source, regardless of the session's target app.
            active = request('GET', '/wda/activeAppInfo')['value']
            if active.get('bundleId') != 'com.apple.springboard':
                raise RuntimeError('ロック画面を確認できませんでした。')
            buttons = passcode_buttons(request('GET', '/source')['value'])
            ATTEMPT_FILE.parent.mkdir(exist_ok=True)
            # Survives process restarts: never repeatedly submit a wrong code.
            with ATTEMPT_FILE.open('x') as handle:
                handle.write('Unlock confirmation pending\n')
            for digit in self._passcode:
                x, y = buttons[digit]
                request('POST', self.prefix + '/wda/tap', {'x': x, 'y': y})
                time.sleep(.15)
            for _ in range(5):
                time.sleep(1)
                if not self.locked():
                    ATTEMPT_FILE.unlink(missing_ok=True)
                    return True
            raise RuntimeError('解除を確認できませんでした。')
        except Exception:
            # WDA errors may echo request details; do not propagate their bodies.
            raise RuntimeError('自動解除を確認できないため停止しました。パスコードを再入力せず、iPhoneを手動で確認してください。') from None

    def activate(self):
        request('POST', self.prefix + '/wda/apps/activate', {'bundleId': APP_ID})


def prepare():
    session = None
    if SESSION_FILE.exists():
        candidate = SESSION_FILE.read_text().strip()
        try:
            request('GET', '/session/' + candidate + '/wda/activeAppInfo')
            session = candidate
        except Exception:
            pass
    if session is None:
        # Do not launch the game while the device is still locked.
        result = request('POST', '/session', {'capabilities': {'alwaysMatch': {
            'shouldWaitForQuiescence': False}}})
        session = result.get('sessionId') or result.get('value', {}).get('sessionId')
        if not session:
            raise RuntimeError('WebDriverAgentのセッションを開始できませんでした。')
        SESSION_FILE.write_text(session)
    device = Device(session)
    device.unlock()
    device.activate()
    print('iPhoneのロック解除を確認し、ポケポケを前面にしました。')


if __name__ == '__main__':
    try:
        prepare()
    except Exception as error:
        # No traceback containing WDA responses or environment values.
        print('起動準備に失敗しました：' + (str(error) if isinstance(error, RuntimeError)
                                      else 'iPhoneとの接続を確認してください。'))
        raise SystemExit(1)
