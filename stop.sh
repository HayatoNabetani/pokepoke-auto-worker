#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .runtime/worker.pid ]; then
  echo "起動中の自動操作はありません。"
  exit 0
fi
worker_pid="$(cat .runtime/worker.pid)"
if ! [[ "$worker_pid" =~ ^[0-9]+$ ]]; then
  echo "PIDファイルの形式が不正です。" >&2
  exit 1
fi
worker_command="$(ps -p "$worker_pid" -o command= || true)"
case "$worker_command" in
  *"bash start.sh"*|*"bash "*"/pokepoke-auto-worker/start.sh"*) ;;
  *) echo "実行中のプロセスがstart.shではないため、停止操作を中止しました。" >&2; exit 1 ;;
esac
pkill -TERM -P "$worker_pid" 2>/dev/null || true
kill -TERM "$worker_pid" 2>/dev/null || true
echo "自動操作の停止を指示しました。ゲーム内のオート対戦は続きます。"
