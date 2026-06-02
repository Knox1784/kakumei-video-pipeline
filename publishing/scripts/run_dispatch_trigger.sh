#!/bin/zsh
# 手動トリガ / 参照用スクリプト: auto_post workflow を workflow_dispatch で起動する。
#
# ⚠️ launchd の自動発火 (com.kakumei.autopost, 22:00/23:00 JST) は **このスクリプトを呼ばない**。
#    ~/Documents は TCC 保護で launchd から読めず "/bin/zsh: can't open input file" になるため、
#    plist (~/Library/LaunchAgents/com.kakumei.autopost.plist) は gh を直接 ProgramArguments で
#    起動する (publishing/scripts/com.kakumei.autopost.plist が参照コピー)。
#    本スクリプトは「スロット窓内で手動即投稿したい」時などに自分で打つ用。
#
# 役割: GitHub Actions の auto_post workflow を workflow_dispatch で起動するだけ。
#       投稿の実体 (queue 消化 + YouTube 投稿) は GHA 側 dispatch_queue.py が行う
#       = 100-500アカ運用にスケールする実行基盤は GHA のまま維持。
#
# なぜ launchd トリガ: GHA の schedule(cron) はベストエフォートで遅延/ドロップする
#       (2026-06-01 に当日投稿ゼロを観測)。launchd は定刻に確実発火し、スリープ時も
#       起床時に追いつく。workflow_dispatch の実行自体は GHA で確実 (実証済)。
# 二重防御: GHA の schedule cron (22:11-22:51 / 23:11-23:51) は予備として残す
#       (Mac off の日のフォールバック)。二重投稿は dispatcher の投稿済み判定で防止。
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGDIR="$ROOT/publishing/scripts/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/autopost_trigger_$(date +%Y-%m-%d).log"
cd "$ROOT" || exit 1
{
  echo "=== $(date -Iseconds) trigger start ==="
  gh workflow run auto_post.yml --ref main
  rc=$?
  echo "gh workflow run exit=$rc"
  echo "=== $(date -Iseconds) trigger end ==="
} >> "$LOG" 2>&1
exit 0
