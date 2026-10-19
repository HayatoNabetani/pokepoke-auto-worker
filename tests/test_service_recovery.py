"""Exercise the real shell supervisor with fake services, never an iPhone."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ServiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy(Path(__file__).parents[1] / 'start.sh', self.root)
        shutil.copy(Path(__file__).parents[1] / 'run_lock.py', self.root)
        (self.root / '.runtime').mkdir()
        (self.root / '.runtime/ocr').touch(mode=0o755)
        (self.root / 'wda.xctestrun').touch()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.command('lsof', 'exit 0')
        self.command('nc', 'exit 0')
        self.command('curl', 'if [ -f "$TEST_ROOT/worker-count" ] && [ ! -f "$TEST_ROOT/wda-starts" ]; then exit 1; fi\nexit 0')
        self.command('xcodebuild', 'echo started >> "$TEST_ROOT/wda-starts"\nexec /bin/sleep 30')
        self.command('uv', f'''exec {sys.executable!r} "$TEST_ROOT/fake_uv.py" "$@"''')
        (self.root / 'fake_uv.py').write_text('''
import json, os, pathlib, sys
root = pathlib.Path(os.environ['TEST_ROOT'])
args = sys.argv[1:]
if args[0] == 'sync':
    raise SystemExit(0)
if 'run_lock.py' in args:
    index = args.index('run_lock.py')
    os.execv(sys.executable, [sys.executable, str(root / 'run_lock.py'), *args[index + 1:]])
if '-c' in args:
    print(0 if 'bool' in args[args.index('-c') + 1] or '--reset-progress' in args else 100)
    raise SystemExit(0)
script = 'worker.py' if 'worker.py' in args else 'device.py'
with (root / 'calls.jsonl').open('a') as handle:
    handle.write(json.dumps({'script': script, 'args': args,
                             'baseline': os.getenv('POKEPOKE_RUN_BASELINE')}) + '\\n')
if script == 'device.py':
    raise SystemExit(int(os.getenv('TEST_PREPARE_EXIT', '0')))
counter = root / 'worker-count'
n = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(n))
# This checkpoint must survive service restarts.
(root / '.runtime/progress.json').write_text(json.dumps({'total_battles': int(os.environ['POKEPOKE_RUN_BASELINE']) + n}))
raise SystemExit(75 if os.getenv('TEST_ALWAYS_FAIL') == '1' or n == 1
                 else int(os.getenv('TEST_WORKER_EXIT', '0')))
''')
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'UV_BIN': str(self.bin / 'uv'), 'TEST_ROOT': str(self.root),
                    'IPHONE_UDID': 'fake-device', 'WDA_TESTRUN': str(self.root / 'wda.xctestrun')}
        self.env.pop('IPHONE_PASSCODE', None)

    def command(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)

    def run_start(self, *args):
        return subprocess.run(['bash', 'start.sh', *args], cwd=self.root, env=self.env,
                              text=True, capture_output=True, timeout=30)

    def calls(self, script):
        path = self.root / 'calls.jsonl'
        return [row for row in map(json.loads, path.read_text().splitlines()) if row['script'] == script]

    def test_transport_failure_restarts_service_and_retains_budget_and_checkpoint(self):
        result = self.run_start('--max-battles', '10', '--reset-progress')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workers = self.calls('worker.py')
        self.assertEqual(len(workers), 2)
        self.assertIn('--reset-progress', workers[0]['args'])
        self.assertNotIn('--reset-progress', workers[1]['args'])
        self.assertEqual([row['baseline'] for row in workers], ['0', '0'])
        self.assertIn('--max-battles', workers[1]['args'])
        self.assertEqual(len(self.calls('device.py')), 2)
        self.assertIn('wda_service_restart', result.stdout)
        self.assertTrue((self.root / 'wda-starts').exists())
        self.assertEqual(json.loads((self.root / '.runtime/progress.json').read_text())['total_battles'], 2)
        self.assertFalse((self.root / '.runtime/run.lock').exists())

    def test_restarts_are_bounded(self):
        self.env['TEST_ALWAYS_FAIL'] = '1'
        result = self.run_start()
        self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
        self.assertEqual(len(self.calls('worker.py')), 4)
        self.assertEqual(result.stdout.count('wda_service_restart'), 3)
        self.assertFalse((self.root / '.runtime/run.lock').exists())

    def test_ordinary_worker_error_does_not_restart_services(self):
        self.env['TEST_PREPARE_EXIT'] = '1'
        result = self.run_start()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.calls('device.py')), 1)
        self.assertNotIn('wda_service_restart', result.stdout)
