"""Own the run lock in one process; never pass its descriptor to children."""
import fcntl
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
PID_FILE = RUNTIME / 'worker.pid'


def worker_pid():
    try:
        pid = int(PID_FILE.read_text().strip())
        if pid <= 1:
            return None
        os.kill(pid, 0)
        command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True,
                                          stderr=subprocess.DEVNULL).strip()
        parts = shlex.split(command)
        if len(parts) < 2 or Path(parts[0]).name != 'bash' or Path(parts[1]).name != 'start.sh':
            return None
        cwd = subprocess.check_output(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], text=True,
                                      stderr=subprocess.DEVNULL)
        if ('n' + str(ROOT)) in cwd.splitlines():
            return pid
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def clear_stale():
    if worker_pid() is not None:
        return False
    PID_FILE.unlink(missing_ok=True)
    directory = RUNTIME / 'run.lock'
    if directory.exists():
        directory.rmdir()
    return True


def acquire(handle):
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def terminate(pid):
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
        else:
            subprocess.run(['pkill', '-TERM', '-P', str(pid)], capture_output=True)
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def stop(handle):
    locked = acquire(handle)
    pid = worker_pid()
    if pid is not None:
        terminate(pid)
    deadline = time.monotonic() + 20
    while not locked or worker_pid() is not None:
        if pid is None:
            pid = worker_pid()
            if pid is not None:
                terminate(pid)
        if time.monotonic() >= deadline:
            print('終了処理が続いています。少し待って bash stop.sh を再実行してください。', file=sys.stderr)
            return 1
        time.sleep(.1)
        if not locked:
            locked = acquire(handle)
    clear_stale()
    print('自動操作を停止し、起動ロックを解除しました。ゲーム内のオート対戦は続きます。'
          if pid else '実行中の自動操作はありません。残っていた起動記録を片付けました。')
    return 0


def start(handle, args):
    if not acquire(handle):
        print('自動操作は実行中、または終了処理中です。停止する場合は bash stop.sh を実行してください。', file=sys.stderr)
        return 1
    if not clear_stale():
        print('自動操作は既に実行中です。停止する場合は bash stop.sh を実行してください。', file=sys.stderr)
        return 1
    env = {**os.environ, 'POKEPOKE_LOCK_HELD': '1'}
    child = subprocess.Popen(['bash', str(ROOT / 'start.sh'), *args], cwd=ROOT,
                             env=env, start_new_session=True, close_fds=True)

    def interrupt(*_):
        if child.poll() is None:
            terminate(child.pid)

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        deadline = time.monotonic() + 5
        while True:
            try:
                os.killpg(child.pid, 0)
                if time.monotonic() >= deadline:
                    os.killpg(child.pid, signal.SIGKILL)
                    break
                time.sleep(.1)
            except ProcessLookupError:
                break
        clear_stale()


def main():
    RUNTIME.mkdir(exist_ok=True)
    with (RUNTIME / 'run.guard').open('a+') as handle:
        args = sys.argv[1:]
        return stop(handle) if args == ['--stop'] else start(handle, args[1:] if args[:1] == ['--'] else args)


if __name__ == '__main__':
    raise SystemExit(main())
