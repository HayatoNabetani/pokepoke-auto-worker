import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class RunLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy(Path(__file__).parents[1] / 'run_lock.py', self.root)
        self.runtime = self.root / '.runtime'
        self.runtime.mkdir()
        (self.runtime / 'progress.json').write_text('progress must survive')
        (self.root / 'start.sh').write_text('''#!/bin/bash
set -eu
mkdir .runtime/run.lock
echo $$ > .runtime/worker.pid
trap 'rm -f .runtime/worker.pid; rmdir .runtime/run.lock' EXIT
trap 'exit 0' TERM INT
touch ready
if [ "${1:-}" = hold ]; then sleep 30; fi
''')

    def run_guard(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'run_lock.py'), *args],
                              text=True, capture_output=True, timeout=25)

    def hold(self):
        process = subprocess.Popen([sys.executable, str(self.root / 'run_lock.py'), 'hold'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def finish():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=15)
        self.addCleanup(finish)
        deadline = time.monotonic() + 5
        while not (self.root / 'ready').exists():
            if process.poll() is not None or time.monotonic() > deadline:
                self.fail('guard did not start')
            time.sleep(.02)
        return process

    def test_stale_pid_and_directory_do_not_prevent_restart(self):
        (self.runtime / 'worker.pid').write_text('99999999')
        (self.runtime / 'run.lock').mkdir()
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.runtime / 'run.lock').exists())
        self.assertEqual((self.runtime / 'progress.json').read_text(), 'progress must survive')

    def test_reused_pid_does_not_kill_unrelated_process(self):
        (self.runtime / 'worker.pid').write_text(str(os.getpid()))
        (self.runtime / 'run.lock').mkdir()
        self.assertEqual(self.run_guard().returncode, 0)
        os.kill(os.getpid(), 0)

    def test_double_start_is_blocked_and_stop_allows_immediate_restart(self):
        process = self.hold()
        duplicate = self.run_guard()
        self.assertEqual(duplicate.returncode, 1)
        self.assertIsNone(process.poll())
        stopped = self.run_guard('--stop')
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        process.wait(timeout=5)
        self.assertFalse((self.runtime / 'run.lock').exists())
        self.assertEqual(self.run_guard().returncode, 0)

    def test_stop_cleans_stale_record_without_touching_progress(self):
        (self.runtime / 'worker.pid').write_text('99999999')
        (self.runtime / 'run.lock').mkdir()
        self.assertEqual(self.run_guard('--stop').returncode, 0)
        self.assertFalse((self.runtime / 'worker.pid').exists())
        self.assertTrue((self.runtime / 'progress.json').exists())

    def test_ctrl_c_releases_guard_for_next_start(self):
        process = self.hold()
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=15)
        self.assertFalse((self.runtime / 'run.lock').exists())
        self.assertEqual(self.run_guard().returncode, 0)
