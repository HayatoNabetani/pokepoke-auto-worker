import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from device import APP_ID, Device, passcode_buttons


def keypad(label='パスコードを入力'):
    return '<App label="' + label + '">' + ''.join(
        f'<XCUIElementTypeButton label="{digit}" x="{digit * 10}" y="100" width="10" height="10"/>'
        for digit in range(10)) + '</App>'


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.marker = Path(self.tmp.name) / 'unlock-attempted'
        self.addCleanup(patch.stopall)
        patch('device.ATTEMPT_FILE', self.marker).start()
        patch('device.time.sleep').start()
        patch.dict(os.environ, {'IPHONE_PASSCODE': '012345'}).start()
        self.device = Device('test')
        self.calls = []
        self.locked_values = iter([True, True, False])

        def request(method, path, payload=None):
            self.calls.append((method, path, payload))
            if path == '/wda/locked':
                return {'value': next(self.locked_values)}
            if path == '/wda/activeAppInfo':
                return {'value': {'bundleId': 'com.apple.springboard'}}
            if path == '/source':
                return {'value': keypad()}
            return {'value': None}

        self.request = patch('device.request', side_effect=request).start()

    def test_successful_unlock_uses_digit_buttons_without_secret_payload(self):
        self.assertTrue(self.device.unlock())
        taps = [c[2] for c in self.calls if c[1].endswith('/wda/tap')]
        self.assertEqual([tap['x'] for tap in taps], [5, 15, 25, 35, 45, 55])
        self.assertNotIn('012345', repr(self.calls))
        self.assertNotIn('IPHONE_PASSCODE', os.environ)
        self.assertFalse(self.marker.exists())

    def test_unlocked_device_never_enters_passcode(self):
        self.locked_values = iter([False])
        self.marker.write_text('pending')
        self.assertFalse(self.device.unlock())
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.marker.exists())

    def test_missing_passcode_does_not_tap(self):
        self.device._passcode = ''
        with self.assertRaisesRegex(RuntimeError, 'IPHONE_PASSCODE'):
            self.device.unlock()
        self.assertEqual(len(self.calls), 1)

    def test_wrong_passcode_is_not_retried_even_after_restart(self):
        self.locked_values = iter([True] * 7)
        with self.assertRaisesRegex(RuntimeError, '自動解除を確認できない'):
            self.device.unlock()
        self.assertTrue(self.marker.exists())
        calls_before = len(self.calls)
        self.locked_values = iter([True])
        with self.assertRaisesRegex(RuntimeError, '再入力しません'):
            Device('new-session').unlock()
        self.assertEqual(len(self.calls), calls_before + 1)

    def test_wda_error_body_does_not_leak_secret(self):
        self.request.side_effect = RuntimeError('request contained 012345')
        # Errors before entering any secret cannot echo a secret request; check
        # an error during the actual unlock operation is replaced as well.
        with patch.object(self.device, 'locked', return_value=True):
            with self.assertRaises(RuntimeError) as caught:
                self.device.unlock()
        self.assertNotIn('012345', str(caught.exception))

    def test_non_passcode_screen_is_not_tapped(self):
        self.request.side_effect = lambda method, path, payload=None: {
            'value': True if path == '/wda/locked' else
            {'bundleId': 'com.apple.springboard'} if path == '/wda/activeAppInfo' else
            keypad('ホーム画面') if path == '/source' else None}
        with self.assertRaisesRegex(RuntimeError, '自動解除を確認できない'):
            self.device.unlock()
        self.assertFalse(self.marker.exists())

    def test_keypad_requires_all_digits(self):
        with self.assertRaises(RuntimeError):
            passcode_buttons('<App label="パスコード"/>')

    def test_game_mode_overlay_waits_until_target_is_detected(self):
        self.request.side_effect = [{'value': {'bundleId': 'com.apple.springboard'}},
                                    {'value': 4}, {'value': {'bundleId': APP_ID}}]
        self.assertTrue(self.device.wait_foreground())
        self.assertEqual(self.request.call_args_list[0].args, ('GET', '/wda/activeAppInfo'))
        self.assertFalse(any(call.args[1].endswith('/wda/tap')
                             for call in self.request.call_args_list))

    def test_real_other_app_is_not_accepted_even_if_game_reports_foreground(self):
        self.request.side_effect = [{'value': {'bundleId': 'other.app'}}, {'value': 4}]
        with self.assertRaisesRegex(RuntimeError, 'other.app'):
            self.device.wait_foreground()

    def test_home_screen_does_not_count_as_game_overlay(self):
        self.request.side_effect = [{'value': {'bundleId': 'com.apple.springboard'}}, {'value': 2}]
        with self.assertRaisesRegex(RuntimeError, 'ポケポケ以外'):
            self.device.wait_foreground()

    def test_overlay_wait_has_a_timeout(self):
        self.request.side_effect = [{'value': {'bundleId': 'com.apple.springboard'}}, {'value': 4}]
        with self.assertRaisesRegex(RuntimeError, '前面表示を確認できません'):
            self.device.wait_foreground(timeout=0)

    def test_activate_does_not_finish_until_foreground_is_verified(self):
        self.request.side_effect = [{'value': None}, {'value': {'bundleId': 'com.apple.springboard'}},
                                    {'value': 2}, {'value': {'bundleId': APP_ID}}]
        self.device.activate()
        self.assertEqual(self.request.call_args_list[0].args[1], '/session/test/wda/apps/activate')
        self.assertEqual(self.request.call_count, 4)


if __name__ == '__main__':
    unittest.main()
