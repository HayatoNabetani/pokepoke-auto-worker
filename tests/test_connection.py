import http.client
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from iphone import request, WDAConnectionError


def response(value):
    result = MagicMock()
    result.__enter__.return_value = io.BytesIO(json.dumps({'value': value}).encode())
    return result


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.open = patch('iphone.urllib.request.urlopen').start()
        self.sleep = patch('iphone.time.sleep').start()
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def test_disconnect_during_locked_query_reconnects(self):
        self.open.side_effect = [http.client.RemoteDisconnected('closed'), response(False)]
        self.assertFalse(request('GET', '/wda/locked')['value'])
        self.assertEqual(self.open.call_count, 2)
        self.sleep.assert_called_once_with(1)

    def test_connection_refused_is_bounded_and_explained(self):
        self.open.side_effect = urllib.error.URLError(ConnectionRefusedError('refused'))
        with self.assertRaisesRegex(WDAConnectionError, '再試行後も復旧'):
            request('GET', '/screenshot')
        self.assertEqual(self.open.call_count, 4)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [1, 2, 4])

    def test_tap_is_never_replayed_when_response_is_lost(self):
        self.open.side_effect = http.client.RemoteDisconnected('closed')
        with self.assertRaisesRegex(WDAConnectionError, '再送していません'):
            request('POST', '/session/secret-session/wda/tap', {'x': 10, 'y': 20})
        self.open.assert_called_once()
        self.sleep.assert_not_called()
        self.assertNotIn('secret-session', self.output.getvalue())
        self.assertNotIn('20', self.output.getvalue())

    def test_post_app_state_is_a_read_and_can_retry(self):
        self.open.side_effect = [TimeoutError(), response(4)]
        self.assertEqual(request('POST', '/session/test/wda/apps/state', {'bundleId': 'target'})['value'], 4)
        self.assertEqual(self.open.call_count, 2)

    def test_http_error_is_not_retried_as_usb_failure(self):
        self.open.side_effect = urllib.error.HTTPError('http://localhost', 404, 'missing session', {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            request('GET', '/session/test/source')
        self.open.assert_called_once()

    def test_wda_error_response_is_not_retried(self):
        self.open.return_value = response({'error': 'invalid session id'})
        with self.assertRaises(RuntimeError):
            request('GET', '/session/test/source')
        self.open.assert_called_once()
