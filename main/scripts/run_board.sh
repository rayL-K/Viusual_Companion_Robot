#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
export DISPLAY="${DISPLAY:-:0}"
python3 app.py

