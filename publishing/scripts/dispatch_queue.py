#!/usr/bin/env python3
"""
GitHub Actions YouTube 自動投稿ディスパッチャ

責務:
  1. publishing/posting_schedule.yaml からスロット定義を読む
  2. 現在時刻 (JST) がどのスロットの ±slot_window_min 内かを判定
  3. このスロットで既に投稿済みなら exit 0 (二重投稿防止)
  4. publishing/queue/*/ をディレクトリ名昇順 sort、先頭の meta.json を読む
  5. account_id に対応するトークンで external_skills/youtube-uploader/scripts/upload.py を起動
  6. 成功: queue ディレクトリ削除 + publishing-state JSON 生成
  7. 失敗: stderr 出力後 sys.exit(1) → GHA で Issue 化

呼び出し: GitHub Actions cron (4スロット時刻に発火) または手動 (workflow_dispatch)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE_FILE = ROOT / "publishing/posting_schedule.yaml"
QUEUE_DIR = ROOT / "publishing/queue"
STATE_DIR = ROOT / "publishing/publishing-state/source-podcast"
TOKENS_DIR = ROOT / "publishing/tokens/youtube"
UPLOADER = ROOT / "external_skills/youtube-uploader/scripts/upload.py"


def load_schedule() -> dict:
    return yaml.safe_load(SCHEDULE_FILE.read_text())


def find_active_slot(now: datetime, slots: list[str], window_min: int) -> str | None:
    """now が ±window_min 内にあるスロットを返す。複数該当なら最も近いもの。"""
    today = now.date()
    candidates = []
    for slot_str in slots:
        h, m = map(int, slot_str.split(":"))
        slot_dt = datetime.combine(today, time(h, m), tzinfo=now.tzinfo)
        diff = abs((now - slot_dt).total_seconds()) / 60.0
        if diff <= window_min:
            candidates.append((diff, slot_str))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def already_posted_in_slot(slot_str: str, now: datetime, window_min: int) -> bool:
    """同スロット時刻 ±window_min 内に投稿済みかチェック (publishing-state を見る)"""
    today = now.date()
    h, m = map(int, slot_str.split(":"))
    slot_dt = datetime.combine(today, time(h, m), tzinfo=now.tzinfo)
    earliest = slot_dt - timedelta(minutes=window_min)
    latest = slot_dt + timedelta(minutes=window_min)

    if not STATE_DIR.exists():
        return False
    for f in STATE_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        ts = d.get("posted_at_iso") or d.get("made_public_at") or d.get("posted_at")
        if not ts:
            continue
        try:
            if "T" in ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                # date only — 9:00 AM JST 仮定 (古い記録は除外したいだけなので大雑把でOK)
                dt = datetime.strptime(ts, "%Y-%m-%d").replace(
                    tzinfo=ZoneInfo("Asia/Tokyo"), hour=0
                )
        except Exception:
            continue
        dt = dt.astimezone(now.tzinfo)
        if earliest <= dt <= latest:
            return True
    return False


def pick_queue_head() -> Path | None:
    if not QUEUE_DIR.exists():
        return None
    dirs = sorted(
        d for d in QUEUE_DIR.iterdir()
        if d.is_dir() and (d / "meta.json").exists() and (d / "short.mp4").exists()
    )
    return dirs[0] if dirs else None


def upload_video(video_path: Path, meta: dict, token_path: Path) -> dict:
    """upload.py をサブプロセス起動。stdout の JSON を返す。"""
    cmd = [
        sys.executable, str(UPLOADER),
        "--video", str(video_path),
        "--title", meta["title"],
        "--description", meta.get("description", ""),
        "--tags", ",".join(meta.get("tags", [])),
        "--privacy", meta.get("privacy", "public"),
        "--token", str(token_path),
    ]
    print(f"  $ upload.py {meta['title']!r} ({meta.get('privacy', 'public')})", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"upload.py failed: {r.stderr.strip()[-2000:]}")
    # upload.py の出力末尾にある JSON ブロックを抽出 (整形済 multi-line)
    out = r.stdout
    end = out.rfind("}")
    if end == -1:
        raise RuntimeError(f"upload.py 出力に '}}' がない: {out[-500:]}")
    # 対応する '{' を depth カウントで探す
    depth = 0
    start = -1
    for i in range(end, -1, -1):
        if out[i] == "}":
            depth += 1
        elif out[i] == "{":
            depth -= 1
            if depth == 0:
                start = i
                break
    if start == -1:
        raise RuntimeError(f"upload.py 出力に対応する '{{' がない: {out[-500:]}")
    return json.loads(out[start:end + 1])


def write_state(meta: dict, upload_result: dict, now: datetime):
    """publishing-state JSON を生成 (= 自動モニター対象化)"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    clip_id = meta["clip_id"]
    state = {
        "clip_id": clip_id,
        "title": meta["title"],
        "channel": meta.get("channel", "革命一家"),
        "channel_id": meta.get("channel_id"),
        "video_id": upload_result["video_id"],
        "url": upload_result["url"],
        "privacy": upload_result["privacy"],
        "posted_at": now.date().isoformat(),
        "made_public_at": now.date().isoformat(),
        "posted_at_iso": now.isoformat(),
        "source_video": meta.get("source_video"),
        "source_range_summary": meta.get("source_range_summary"),
        "duration_s": meta.get("duration_s"),
        "tags": meta.get("tags", []),
        "posted_via": "github-actions",
    }
    out = STATE_DIR / f"{clip_id}.json"
    out.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(f"  → state written: {out.relative_to(ROOT)}", flush=True)


def main():
    cfg = load_schedule()
    tz = ZoneInfo(cfg.get("timezone", "Asia/Tokyo"))
    now = datetime.now(tz=tz)
    window = cfg.get("slot_window_min", 30)
    print(f"=== dispatch_queue start (now={now.isoformat()}) ===", flush=True)

    # 1. 現在のスロット判定
    slot = find_active_slot(now, cfg["slots"], window)
    if not slot:
        print(f"  no active slot at {now.strftime('%H:%M')} (slots={cfg['slots']}) → skip", flush=True)
        return 0
    print(f"  active slot: {slot}", flush=True)

    # 2. 二重投稿防止
    if already_posted_in_slot(slot, now, window):
        print(f"  already posted within slot {slot} window → skip", flush=True)
        return 0

    # 3. queue 先頭取得
    target = pick_queue_head()
    if not target:
        print(f"  queue empty → skip", flush=True)
        return 0
    print(f"  target: {target.name}", flush=True)

    # 4. meta + token 解決
    meta = json.loads((target / "meta.json").read_text())
    account_id = meta.get("account_id", "kakumei_ikka")
    token_path = TOKENS_DIR / f"{account_id}.json"
    if not token_path.exists():
        raise RuntimeError(f"token not found: {token_path}")
    if not UPLOADER.exists():
        raise RuntimeError(f"uploader not found: {UPLOADER}")

    # 5. アップロード
    result = upload_video(target / "short.mp4", meta, token_path)
    print(f"  ✅ uploaded: {result['url']}", flush=True)

    # 6. state 生成 → queue 削除
    write_state(meta, result, now)
    shutil.rmtree(target)
    print(f"  → queue dir removed: {target.relative_to(ROOT)}", flush=True)
    print(f"=== dispatch_queue end (success) ===", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"❌ FAILED: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
