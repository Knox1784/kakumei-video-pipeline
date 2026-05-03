#!/bin/zsh
# launchd から毎日呼ばれる薄いラッパ。
# monitor_runner.py を実行し、ログを日次ファイルに append する。
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGDIR="$ROOT/publishing/scripts/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/monitor_$(date +%Y-%m-%d).log"

# Python interpreter resolution: prefer $PYTHON env var, fall back to PATH `python3`.
# launchd's PATH is minimal — install_launchd.sh writes EnvironmentVariables.PYTHON
# pointing to the right interpreter (eg. pyenv shim) when registering the plist.
PYTHON="${PYTHON:-python3}"

{
  echo "=== $(date -Iseconds) launcher start ==="
  "$PYTHON" "$ROOT/publishing/scripts/monitor_runner.py" "$@"
  echo "=== $(date -Iseconds) launcher end ==="
} >> "$LOG" 2>&1
