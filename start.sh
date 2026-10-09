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
UV_BIN="${UV_BIN:-uv}"
if ! command -v "$UV_BIN" >/dev/null 2>&1; then
  echo "uvをインストールしてください。README.mdを確認してください。" >&2
  exit 1
fi
uv_args=(run --locked)
if [ -f .env ]; then
  chmod 600 .env
  uv_args+=(--env-file .env)
fi
run_python() { "$UV_BIN" "${uv_args[@]}" python "$@"; }
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
"$UV_BIN" sync --locked
wda_log="logs/wda.log"
if [ "$(run_python -c 'import os; print(int(bool(os.getenv("IPHONE_PASSCODE"))))')" = 1 ]; then
  # XCTest logs taps, so discard low-level logs when unlocking is configured.
  wda_log="/dev/null"
fi
if [ ! -x "$POKEPOKE_OCR" ] || [ ocr.swift -nt "$POKEPOKE_OCR" ]; then
  xcrun swiftc -module-cache-path "$PWD/.runtime/swift-cache" ocr.swift -o "$POKEPOKE_OCR"
fi
# Refresh a leftover forwarder from this checkout so code updates take effect.
# Never terminate an unrelated service using the same port.
for bridge_pid in $(lsof -nP -iTCP:8100 -sTCP:LISTEN -t 2>/dev/null | sort -u); do
  bridge_command="$(ps -p "$bridge_pid" -o command= || true)"
  bridge_cwd="$(lsof -a -p "$bridge_pid" -d cwd -Fn 2>/dev/null || true)"
  if [[ "$bridge_command" == *"usb-forward.cjs"* ]] && [[ "$bridge_cwd" == *$'\n'"n$PWD" ]]; then
    kill -TERM "$bridge_pid" 2>/dev/null || true
    for attempt in $(seq 1 10); do
      if ! kill -0 "$bridge_pid" 2>/dev/null; then break; fi
      sleep .2
    done
  fi
done
if ! nc -z 127.0.0.1 8100 >/dev/null 2>&1; then
  "$NODE_BIN" usb-forward.cjs >logs/usb-forward.log 2>&1 &
  forward_pid=$!
fi
if ! curl --max-time 3 -fsS http://127.0.0.1:8100/status >/dev/null 2>&1; then
  if [ ! -f "$WDA_TESTRUN" ]; then
    echo "WebDriverAgentのxctestrunがありません。WDA_TESTRUNを指定してください。" >&2
    exit 1
  fi
  xcodebuild test-without-building -xctestrun "$WDA_TESTRUN" \
    -destination "id=$IPHONE_UDID" \
    -resultBundlePath "$PWD/logs/wda-$(date +%Y%m%d-%H%M%S).xcresult" \
    >"$wda_log" 2>&1 &
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
run_python device.py
run_python worker.py "$@"
