#!/usr/bin/env python3
"""
post-monitor 自動巡回ランナー

publishing-state/source-podcast/*.json を走査し、
public 投稿済の動画について made_public_at から 24h/72h 経過判定を行い、
~/.claude/skills/post-monitor/scripts/monitor.py をサブプロセス起動して
結果を元の JSON の monitor_results 配列に追記する。

毎日 launchd から呼ばれる前提。冪等 (同種 check_type は1回だけ追記)。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "publishing/publishing-state/source-podcast"
TOKEN = ROOT / "publishing/tokens/youtube/kakumei_ikka.json"
# Vendored skill (under external_skills/), with fallback to ~/.claude/skills/
MONITOR = ROOT / "external_skills/post-monitor/scripts/monitor.py"
if not MONITOR.exists():
    MONITOR = Path.home() / ".claude/skills/post-monitor/scripts/monitor.py"

CHECK_24H = "health_24h"
CHECK_72H = "full_72h"

WINDOW_24H = (20.0, 48.0)  # 20〜48h で 24h check 実施
WINDOW_72H = (60.0, 168.0)  # 60〜168h (1週間) で 72h check 実施


def parse_posted_at(s: str) -> datetime:
    """made_public_at / posted_at を datetime(UTC) に。
    "YYYY-MM-DD" は 00:00 UTC として扱う。"""
    if "T" in s:
        # ISO 8601
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    # date only
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def already_done(state: dict, check_type: str) -> bool:
    return any(r.get("check_type") == check_type for r in state.get("monitor_results", []))


def map_alert_level(status_level: str) -> str:
    return {
        "CRITICAL": "critical",
        "ERROR": "critical",
        "WARNING": "warning",
        "PENDING": "ok",
        "OK": "ok",
        "GOOD": "ok",
        "EXCELLENT": "ok",
    }.get(status_level, "ok")


def run_monitor(video_id: str, mode: str) -> dict:
    """monitor.py をサブプロセス起動。mode: 'health' | 'full'."""
    flag = "--health-check" if mode == "health" else "--full-report"
    cmd = [sys.executable, str(MONITOR), flag, video_id, "--token", str(TOKEN)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"monitor.py failed (exit {r.returncode}): {r.stderr.strip()}")
    return json.loads(r.stdout)


def derive_alert(check_type: str, payload: dict) -> tuple[str, str | None]:
    """alert_level と alert_reason を判定。
    payload: --health-check は list、--full-report は dict (status_level 含む)。"""
    if check_type == CHECK_24H:
        # health は list of {video_id, upload_status, views, ...}
        item = payload[0] if isinstance(payload, list) and payload else {}
        status = item.get("upload_status")
        if status in {"DELETED", "rejected", "failed"}:
            return "critical", f"upload_status={status}"
        if item.get("views", 0) == 0:
            return "warning", "views=0 at 24h"
        return "ok", None
    else:
        # full-report は dict with status_level + analytics
        level = payload.get("status_level", "OK")
        msg = payload.get("status_message")
        avg = (payload.get("analytics") or {}).get("averageViewPercentage")
        if isinstance(avg, (int, float)) and avg < 50:
            return "improvement_signal", f"averageViewPercentage={avg:.1f}%"
        return map_alert_level(level), msg


def append_result(state_path: Path, state: dict, entry: dict, dry_run: bool):
    state.setdefault("monitor_results", []).append(entry)
    if dry_run:
        print(f"  [dry-run] would append to {state_path.name}: {entry['check_type']} alert={entry['alert_level']}")
        return
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(f"  → appended {entry['check_type']} (alert={entry['alert_level']}) to {state_path.name}")


def process_one(state_path: Path, force: bool, dry_run: bool):
    state = json.loads(state_path.read_text())

    if state.get("privacy") != "public":
        print(f"  skip {state_path.name}: privacy={state.get('privacy')!r} (not public)")
        return

    posted_str = state.get("made_public_at") or state.get("posted_at")
    if not posted_str:
        print(f"  skip {state_path.name}: no made_public_at/posted_at", file=sys.stderr)
        return

    video_id = state.get("video_id")
    if not video_id:
        print(f"  skip {state_path.name}: no video_id", file=sys.stderr)
        return

    posted = parse_posted_at(posted_str)
    now = datetime.now(timezone.utc)
    hours = (now - posted).total_seconds() / 3600.0
    print(f"\n{state_path.name} ({video_id}) elapsed={hours:.1f}h")

    plans = []  # [(check_type, mode), ...]
    if force:
        if not already_done(state, CHECK_24H):
            plans.append((CHECK_24H, "health"))
        if not already_done(state, CHECK_72H):
            plans.append((CHECK_72H, "full"))
    else:
        if (WINDOW_24H[0] <= hours <= WINDOW_24H[1]) and not already_done(state, CHECK_24H):
            plans.append((CHECK_24H, "health"))
        if (WINDOW_72H[0] <= hours <= WINDOW_72H[1]) and not already_done(state, CHECK_72H):
            plans.append((CHECK_72H, "full"))

    if not plans:
        print(f"  no checks due (force={force})")
        return

    for check_type, mode in plans:
        try:
            payload = run_monitor(video_id, mode)
        except Exception as e:
            print(f"  ❌ {check_type} failed: {e}", file=sys.stderr)
            continue
        alert_level, alert_reason = derive_alert(check_type, payload)
        entry = {
            "checked_at": now.isoformat(),
            "hours_since_post": round(hours, 2),
            "check_type": check_type,
            "data": payload,
            "alert_level": alert_level,
            "alert_reason": alert_reason,
        }
        append_result(state_path, state, entry, dry_run)
        if alert_level in {"critical", "warning"}:
            print(f"  ⚠️  ALERT [{alert_level}] {video_id} {check_type}: {alert_reason}",
                  file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="経過時間判定をバイパスし、未実施の check を全て即時実行")
    p.add_argument("--dry-run", action="store_true", help="JSON書き込みをせず動作確認のみ")
    p.add_argument("--only", help="特定の clip_id (ファイル名 stem) だけ対象")
    args = p.parse_args()

    if not MONITOR.exists():
        print(f"Error: monitor.py not found at {MONITOR}", file=sys.stderr)
        sys.exit(1)
    if not TOKEN.exists():
        print(f"Error: token not found at {TOKEN}", file=sys.stderr)
        sys.exit(1)

    files = sorted(STATE_DIR.glob("*.json"))
    if args.only:
        files = [f for f in files if f.stem == args.only]
        if not files:
            print(f"No state file matched --only {args.only}", file=sys.stderr)
            sys.exit(1)

    print(f"=== monitor_runner start ({datetime.now(timezone.utc).isoformat()}) ===")
    print(f"  state files: {len(files)} | force={args.force} dry_run={args.dry_run}")
    for f in files:
        try:
            process_one(f, args.force, args.dry_run)
        except Exception as e:
            print(f"  ❌ {f.name} unexpected error: {e}", file=sys.stderr)
    print(f"=== monitor_runner end ===")


if __name__ == "__main__":
    main()
