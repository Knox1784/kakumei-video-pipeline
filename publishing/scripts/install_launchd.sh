#!/bin/zsh
# Install / reinstall the post-monitor launchd job.
#
# Reads the plist template, substitutes __ROOT__ and __PYTHON__ with this
# checkout's absolute path and the python interpreter found on $PATH (or
# overridden via $PYTHON), writes to ~/Library/LaunchAgents/, and loads it.
#
# Usage:
#   bash publishing/scripts/install_launchd.sh        # install + load
#   bash publishing/scripts/install_launchd.sh stop   # unload (uninstall)
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEMPLATE="$ROOT/publishing/scripts/launchd/com.kakumei.postmonitor.plist.template"
DEST="$HOME/Library/LaunchAgents/com.kakumei.postmonitor.plist"
LABEL="com.kakumei.postmonitor"

if [[ "$1" == "stop" || "$1" == "uninstall" ]]; then
  launchctl unload "$DEST" 2>/dev/null || true
  rm -f "$DEST"
  echo "✅ Uninstalled $LABEL"
  exit 0
fi

PYTHON_BIN="${PYTHON:-$(command -v python3)}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "❌ python3 not found on PATH. Install Python 3.10+ or set \$PYTHON." >&2
  exit 1
fi

mkdir -p "$ROOT/publishing/scripts/logs"
mkdir -p "$HOME/Library/LaunchAgents"

# Substitute placeholders
sed -e "s|__ROOT__|$ROOT|g" -e "s|__PYTHON__|$PYTHON_BIN|g" "$TEMPLATE" > "$DEST"

# Validate generated plist
if ! plutil -lint "$DEST" >/dev/null; then
  echo "❌ Generated plist failed plutil -lint. Check $DEST" >&2
  exit 1
fi

# Reload (unload first if already loaded)
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"

echo "✅ Installed $LABEL"
echo "   plist: $DEST"
echo "   ROOT:  $ROOT"
echo "   PYTHON: $PYTHON_BIN"
echo ""
echo "Daily run: 08:00 local time"
echo "Manual trigger: launchctl start $LABEL"
echo "Uninstall:      bash publishing/scripts/install_launchd.sh stop"
