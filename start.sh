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
if [ "${POKEPOKE_LOCK_HELD:-}" != 1 ]; then
  exec "$UV_BIN" run --locked python run_lock.py -- "$@"
fi
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
stop_child() {
  local child_pid="${1:-}"
  if [ -n "$child_pid" ] && [ "$(ps -p "$child_pid" -o ppid= 2>/dev/null | tr -d ' ')" = "$$" ]; then
    kill -TERM "$child_pid" 2>/dev/null || true
    for attempt in $(seq 1 10); do
      if ! kill -0 "$child_pid" 2>/dev/null; then break; fi
      sleep .2
    done
    if [ "$(ps -p "$child_pid" -o ppid= 2>/dev/null | tr -d ' ')" = "$$" ]; then
      kill -KILL "$child_pid" 2>/dev/null || true
    fi
    wait "$child_pid" 2>/dev/null || true
  fi
}
cleanup() {
  stop_child "$forward_pid"
  stop_child "$wda_pid"
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
ensure_services() {
local force="${1:-0}"
if [ "$force" = 1 ]; then
  stop_child "$forward_pid"
  forward_pid=""
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
  stop_child "$wda_pid"
  wda_pid=""
  if [ ! -f "$WDA_TESTRUN" ]; then
    echo "WebDriverAgentのxctestrunがありません。WDA_TESTRUNを指定してください。" >&2
    exit 1
  fi
  echo '{"event":"wda_runner_start"}'
  xcodebuild test-without-building -xctestrun "$WDA_TESTRUN" \
    -destination "id=$IPHONE_UDID" \
    -resultBundlePath "$PWD/logs/wda-$(date +%Y%m%d-%H%M%S)-${recovery_attempt:-0}.xcresult" \
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
}

# Preserve one battle budget across child restarts; reset only on the first run.
export POKEPOKE_RUN_BASELINE
POKEPOKE_RUN_BASELINE="$(run_python -c 'import sys; from iphone import ROOT; from progress import ProgressFile; data = None if "--reset-progress" in sys.argv[1:] else ProgressFile(ROOT / ".runtime/progress.json").load(); print((data or {}).get("total_battles", 0))' "$@")"
worker_args=("$@")
ensure_services 0
for recovery_attempt in 0 1 2 3; do
  if run_python device.py && run_python worker.py "${worker_args[@]}"; then
    exit 0
  else
    worker_status=$?
  fi
  if [ "$worker_status" -ne 75 ]; then exit "$worker_status"; fi
  if [ "$recovery_attempt" -eq 3 ]; then
    echo '接続サービスの再起動を3回試みましたが復旧できません。USB接続とiPhoneの許可を確認してください。進捗は保持しています。' >&2
    exit 75
  fi
  echo "{\"event\":\"wda_service_restart\",\"attempt\":$((recovery_attempt + 1))}"
  # Do not repeatedly reset a checkpoint the worker has just saved.
  retained_args=()
  for arg in "${worker_args[@]}"; do
    if [ "$arg" != '--reset-progress' ]; then retained_args+=("$arg"); fi
  done
  worker_args=("${retained_args[@]}")
  rm -f .wda-session
  ensure_services 1
done
