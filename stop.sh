#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f config.local.sh ]; then source config.local.sh; fi
UV_BIN="${UV_BIN:-uv}"
exec "$UV_BIN" run --locked python run_lock.py --stop
