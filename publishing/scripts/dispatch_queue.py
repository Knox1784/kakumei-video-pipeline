#!/usr/bin/env python3
"""
GitHub Actions YouTube 自動投稿ディスパッチャ (+ X クロスポスト)

責務:
  1. publishing/posting_schedule.yaml からスロット定義を読む
  2. 現在時刻 (JST) がどのスロットの ±slot_window_min 内かを判定
  3. このスロットで既に投稿済みなら exit 0 (二重投稿防止)
  4. publishing/queue/*/ をディレクトリ名昇順 sort、先頭の meta.json を読む
  5. account_id に対応するトークンで external_skills/youtube-uploader/scripts/upload.py を起動
  6. 成功: queue ディレクトリ削除 + publishing-state JSON 生成
  6b. X クロスポスト (x_enabled=true デフォルト): external_skills/x-uploader を起動。
      ⚠️ X 失敗は state に記録 + x_failure.json marker を書くのみで exit code を絶対に汚さない
      (exit 1 にすると state 未push → 次 cron で YouTube 二重投稿になるため)
  7. 失敗 (YouTube 投稿前のみ): stderr 出力後 sys.exit(1) → GHA で Issue 化

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

# --- X (Twitter) クロスポスト ---
X_TOKENS_DIR = ROOT / "publishing/tokens/x"
X_UPLOADER = ROOT / "external_skills/x-uploader/scripts/upload.py"
# YouTube 成功 + X 失敗の時のみ書かれる marker。GHA の "Report X failure" ステップが
# これを見て Issue 化する (repo root = GITHUB_WORKSPACE 直下。.gitignore 済)
X_FAILURE_MARKER = ROOT / "x_failure.json"
X_SUBPROCESS_TIMEOUT = 300  # 秒。X ハングが 23:00 スロットを潰さないための上限


def load_schedule() -> dict:
    return yaml.safe_load(SCHEDULE_FILE.read_text())


def find_active_slot(now: datetime, slots: list[str], window_min: int) -> str | None:
    """now が ±window_min 内にあるスロットを返す。**過去スロットを優先**。

    GHA cron は 30-50min 遅延することがあり、22:37 で発火したとき
    abs() で「最近」を選ぶと 23:00 (23min ahead) が選ばれてしまうバグがあった。
    過去 (now >= slot_dt) を優先することで「22:00 cron が遅延発火した」を
    正しく 22:00 スロットとして扱う。
    """
    today = now.date()
    candidates = []  # list of (diff_min, slot_str)
    for slot_str in slots:
        h, m = map(int, slot_str.split(":"))
        slot_dt = datetime.combine(today, time(h, m), tzinfo=now.tzinfo)
        diff_min = (now - slot_dt).total_seconds() / 60.0  # 符号付き: 正=過去
        if abs(diff_min) <= window_min:
            candidates.append((diff_min, slot_str))
    if not candidates:
        return None
    past = [(d, s) for d, s in candidates if d >= 0]
    if past:
        past.sort(key=lambda x: x[0])  # 最も最近の過去 (小さい正)
        return past[0][1]
    candidates.sort(key=lambda x: -x[0])  # 過去なし → 最も近い未来 (-diff 最小)
    return candidates[0][1]


def already_posted_in_slot(slot_str: str, now: datetime, window_min: int) -> bool:
    """同スロット時刻に投稿済みかチェック (publishing-state を見る)。

    優先: `posted_slot` フィールド (新形式) で本日同スロット exact match。
    後方互換: `posted_slot` がない旧 publishing-state は時刻 ±window_min 範囲で判定。

    旧時刻ベースは隣接スロット (60min 間隔 + 60min ウィンドウ) で重複が起きた。
    posted_slot を使えば exact match で重複なし。
    """
    today_iso = now.date().isoformat()
    if not STATE_DIR.exists():
        return False

    # 時刻ベース fallback 用 (posted_slot 無い旧 state 用、ただし窓を半分=30min に絞り重複回避)
    today = now.date()
    h, m = map(int, slot_str.split(":"))
    slot_dt = datetime.combine(today, time(h, m), tzinfo=now.tzinfo)
    fallback_window = min(window_min, 29)  # 隣接スロット境界に届かないよう 29min
    earliest = slot_dt - timedelta(minutes=fallback_window)
    latest = slot_dt + timedelta(minutes=fallback_window)

    for f in STATE_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        # 1) 優先: posted_slot exact match (新形式)
        if d.get("posted_slot") == slot_str:
            posted_date = (d.get("posted_at") or d.get("posted_at_iso") or "")[:10]
            if posted_date == today_iso:
                return True
            continue  # posted_slot あるが別日 → 無視

        # 2) 旧形式: 時刻ベース (狭い窓で fallback)
        if d.get("posted_slot") is not None:
            continue  # posted_slot 有れば 1) で判定済、それ以外はここに来ない
        ts = d.get("posted_at_iso") or d.get("made_public_at") or d.get("posted_at")
        if not ts:
            continue
        try:
            if "T" in ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(ts, "%Y-%m-%d").replace(
                    tzinfo=ZoneInfo("Asia/Tokyo"), hour=0
                )
        except Exception:
            continue
        dt = dt.astimezone(now.tzinfo)
        if earliest <= dt <= latest:
            return True
    return False


def pick_queue_head(now: datetime | None = None, current_slot: str | None = None) -> Path | None:
    """Pick first queue dir whose meta.not_before is null or <= now AND target_slot matches current_slot.

    Gates (in order):
      1. `target_slot` (optional, e.g. "21:00"): if set, must EXACTLY match current_slot.
         Otherwise the item is skipped (= 朝7時/22時など他スロットでの誤消化を防止).
      2. `not_before` (optional ISO 8601 datetime): if in the future, item is skipped.

    Items without these fields fall back to FIFO behavior (backward compatible).
    """
    if not QUEUE_DIR.exists():
        return None
    dirs = sorted(
        d for d in QUEUE_DIR.iterdir()
        if d.is_dir() and (d / "meta.json").exists() and (d / "short.mp4").exists()
    )
    for d in dirs:
        try:
            meta = json.loads((d / "meta.json").read_text())
        except Exception:
            continue

        # 1) target_slot ゲート (新規、 backward compat: 未指定なら無視)
        target_slot = meta.get("target_slot")
        if target_slot and current_slot and target_slot != current_slot:
            print(f"  🎯 {d.name} target_slot={target_slot} != current={current_slot} → 次へ", flush=True)
            continue

        # 2) not_before ゲート (既存)
        nb = meta.get("not_before")
        if nb and now is not None:
            try:
                nb_dt = datetime.fromisoformat(nb.replace("Z", "+00:00"))
                if nb_dt.tzinfo is None:
                    nb_dt = nb_dt.replace(tzinfo=now.tzinfo)
                if now < nb_dt:
                    print(f"  ⏰ {d.name} not_before={nb} 未到達 → 次へ", flush=True)
                    continue
            except Exception as e:
                print(f"  ⚠️ {d.name} not_before parse 失敗 ({nb}): {e}、ゲート無視で投稿", flush=True)
        return d
    return None


def extract_json_block(out: str) -> dict:
    """stdout 末尾の JSON ブロックを抽出 (整形済 multi-line)。

    youtube-uploader / x-uploader 共通の出力契約。
    ⚠️ 既存 YouTube パスの load-bearing ロジックの純粋切出し — 挙動変更禁止。
    """
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
    return extract_json_block(r.stdout)


def _write_x_failure_marker(clip_id: str, error: str, now: datetime):
    """GHA "Report X failure" ステップ用の marker (.gitignore 済・commit されない)。"""
    try:
        X_FAILURE_MARKER.write_text(json.dumps(
            {"clip_id": clip_id, "error": error[-2000:], "at": now.isoformat()},
            ensure_ascii=False, indent=2,
        ) + "\n")
    except Exception as e:  # marker 書込み失敗すら exit code を汚さない
        print(f"  ⚠️ x_failure marker 書込み失敗: {e}", flush=True)


def post_to_x(video_path: Path, meta: dict, now: datetime) -> dict | None:
    """YouTube 投稿成功後の X クロスポスト。

    戻り値: x_post dict (成功 or {"status":"failed",...}) / None (skip)。
    ⚠️ 不変条件: この関数は絶対に raise しない。X の失敗で exit code が汚れると
    state 未push → 次 cron で YouTube 二重投稿になる (呼び出し側にも二重ガードあり)。
    """
    clip_id = meta.get("clip_id", "?")
    try:
        # ゲート 1: クリップ単位 opt-out (デフォルト ON)
        if not meta.get("x_enabled", True):
            print("  ⏭ X: x_enabled=false → skip", flush=True)
            return None
        # ゲート 2: X に限定公開は無い → public のみクロスポスト
        if meta.get("privacy", "public") != "public":
            print(f"  ⏭ X: privacy={meta.get('privacy')} (≠public) → skip", flush=True)
            return None
        # ゲート 3: トークン存在
        x_account_id = meta.get("x_account_id") or meta.get("account_id", "kakumei_ikka")
        token_path = X_TOKENS_DIR / f"{x_account_id}.json"
        if not token_path.exists():
            if meta.get("x_account_id"):
                # meta が明示指定したアカのトークンが無い = 設定ミス疑い → Issue 化
                msg = f"x_account_id={x_account_id} のトークンが無い: {token_path}"
                print(f"  ⚠️ X: {msg}", flush=True)
                _write_x_failure_marker(clip_id, msg, now)
                return {"status": "failed", "error": msg, "account_id": x_account_id}
            # デフォルトアカのトークン不在 = X 未セットアップの正常状態 → 静かに skip
            print(f"  ⏭ X: token not found ({token_path.name}) → skip (X 未セットアップ)", flush=True)
            return None

        # 本文: x_text 優先、無ければ title から "#Shorts" 除去
        text = (meta.get("x_text") or meta["title"].replace("#Shorts", "")).strip()

        cmd = [
            sys.executable, str(X_UPLOADER),
            "--video", str(video_path),
            "--text", text,
            "--token", str(token_path),
        ]
        print(f"  $ x-uploader/upload.py {text!r}", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=X_SUBPROCESS_TIMEOUT)
        if r.returncode != 0:
            raise RuntimeError(f"x-uploader failed: {r.stderr.strip()[-2000:]}")
        result = extract_json_block(r.stdout)
        print(f"  ✅ X posted: {result.get('url')}", flush=True)
        return {
            "tweet_id": result["tweet_id"],
            "url": result["url"],
            "text": result.get("text", text),
            "posted_at_iso": now.isoformat(),
            "account_id": x_account_id,
        }
    except BaseException as e:  # TimeoutExpired 含む全例外を吸収
        err = str(e)
        print(f"  ❌ X post failed (YouTube は成功済・処理続行): {err[-500:]}", flush=True)
        _write_x_failure_marker(clip_id, err, now)
        return {"status": "failed", "error": err[-2000:]}


def append_x_post_to_state(clip_id: str, x_post: dict):
    """投稿済み state JSON に x_post キーを追記 (state 本体は YouTube 成功時に書込み済)。"""
    path = STATE_DIR / f"{clip_id}.json"
    state = json.loads(path.read_text())
    state["x_post"] = x_post
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(f"  → x_post appended: {path.relative_to(ROOT)}", flush=True)


def write_state(meta: dict, upload_result: dict, now: datetime, slot_str: str | None = None):
    """publishing-state JSON を生成 (= 自動モニター対象化)。
    slot_str: 投稿が紐付くスケジュールスロット (例 "22:00") — already_posted_in_slot の exact match に使用。
    """
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
        "posted_slot": slot_str,
        "source_video": meta.get("source_video"),
        "source_range_summary": meta.get("source_range_summary"),
        "duration_s": meta.get("duration_s"),
        "tags": meta.get("tags", []),
        "experiment_arm": meta.get("experiment_arm"),
        "edit_style": meta.get("edit_style"),
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

    # 3. queue 先頭取得 (target_slot ゲートに current slot を渡す)
    target = pick_queue_head(now, current_slot=slot)
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
    video_path = target / "short.mp4"
    result = upload_video(video_path, meta, token_path)
    print(f"  ✅ uploaded: {result['url']}", flush=True)

    # 6. state 生成 (posted_slot 含む) → queue 削除
    #    ⚠️ X より先に YouTube の記録と queue 削除を完結させる
    #    (X がどう失敗/ハングしても二重投稿防止の3層が成立した状態を保つ)
    write_state(meta, result, now, slot_str=slot)

    # 6b. X クロスポスト (queue 削除前 = short.mp4 がまだ存在するうちに実行)
    #     post_to_x は内部で全例外を吸収するが、呼び出し側でも二重ガード
    #     (どんな例外でも exit 0 を守る — 汚すと次 cron で YouTube 二重投稿)
    try:
        x_post = post_to_x(video_path, meta, now)
    except BaseException as e:
        print(f"  ❌ X post failed (outer guard): {e}", flush=True)
        _write_x_failure_marker(meta.get("clip_id", "?"), str(e), now)
        x_post = {"status": "failed", "error": str(e)[-2000:]}
    if x_post is not None:
        try:
            append_x_post_to_state(meta["clip_id"], x_post)
        except BaseException as e:
            print(f"  ⚠️ x_post state 追記失敗 (続行): {e}", flush=True)

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
