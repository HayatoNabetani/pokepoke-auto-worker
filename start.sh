#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs .runtime
export POKEPOKE_OCR="$PWD/.runtime/ocr"
if [ -f config.local.sh ]; then
  source config.local.sh
fi
: "${IPHONE_UDID:?config.local.shにIPHONE_UDIDを設定してください。}"
export IPHONE_UDID
NODE_BIN="${NODE_BIN:-node}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WDA_TESTRUN="${WDA_TESTRUN:-}"
if ! mkdir .runtime/run.lock 2>/dev/null; then
  echo "自動操作は既に実行中です。.runtime/worker.pidを確認してください。" >&2
  exit 1
fi
printf '%s\n' "$$" >.runtime/worker.pid
forward_pid=""
wda_pid=""
cleanup() {
  if [ -n "$forward_pid" ]; then kill "$forward_pid" 2>/dev/null || true; fi
  if [ -n "$wda_pid" ]; then kill "$wda_pid" 2>/dev/null || true; fi
  rm -f .runtime/worker.pid
  rmdir .runtime/run.lock 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if [ ! -x "$POKEPOKE_OCR" ] || [ ocr.swift -nt "$POKEPOKE_OCR" ]; then
  xcrun swiftc -module-cache-path "$PWD/.runtime/swift-cache" ocr.swift -o "$POKEPOKE_OCR"
fi
if ! curl --max-time 3 -fsS http://127.0.0.1:8100/status >/dev/null 2>&1; then
  "$NODE_BIN" usb-forward.cjs >logs/usb-forward.log 2>&1 &
  forward_pid=$!
  if [ ! -f "$WDA_TESTRUN" ]; then
    echo "WebDriverAgentのxctestrunがありません。WDA_TESTRUNを指定してください。" >&2
    exit 1
  fi
  xcodebuild test-without-building -xctestrun "$WDA_TESTRUN" \
    -destination "id=$IPHONE_UDID" \
    -resultBundlePath "$PWD/logs/wda-$(date +%Y%m%d-%H%M%S).xcresult" \
    >logs/wda.log 2>&1 &
  wda_pid=$!
  ready=0
  for attempt in $(seq 1 60); do
    if curl --max-time 2 -fsS http://127.0.0.1:8100/status >/dev/null 2>&1; then
      ready=1
      break
    fi
    if ! kill -0 "$wda_pid" 2>/dev/null; then
      echo "WebDriverAgentの起動に失敗しました。logs/wda.logを確認してください。" >&2
      exit 1
    fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "iPhoneのロック解除と操作許可を確認してください。接続待ちがタイムアウトしました。" >&2
    exit 1
  fi
fi
if ! "$PYTHON_BIN" - <<'PY'
from iphone import SESSION_FILE, request
try:
    session = SESSION_FILE.read_text().strip()
    result = request('GET', '/session/' + session + '/wda/activeAppInfo')
    if not result.get('value', {}).get('bundleId'):
        raise RuntimeError('No active app')
except Exception:
    raise SystemExit(1)
PY
then
  "$PYTHON_BIN" iphone.py session
fi
"$PYTHON_BIN" worker.py "$@"
