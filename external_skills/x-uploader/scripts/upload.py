#!/usr/bin/env python3
"""
X (Twitter) ショート動画アップローダー — youtube-uploader と同じ CLI 契約

認証: OAuth 1.0a user context (4キー・無期限)。トークン JSON:
  {api_key, api_key_secret, access_token, access_token_secret}

使用例:
  # 認証テスト (read のみ・課金最小)
  python3 upload.py --verify --token publishing/tokens/x/kakumei_ikka.json

  # 動画投稿 (長辺>1280px は自動で 720x1280 に縮小)
  python3 upload.py \
    --video path/to/short_final.mp4 \
    --text "ツイート本文" \
    --token publishing/tokens/x/kakumei_ikka.json

  # テスト投稿の削除
  python3 upload.py --delete 1234567890 --token publishing/tokens/x/kakumei_ikka.json

制約 (2026-06 時点):
  - 動画: H.264+AAC / 0.5〜140s / ≤512MB / 解像度 32x32〜1280x1024 (長辺1280)
  - 本文: weighted 280 (CJK・絵文字=2 → 日本語実質140字)。超過は自動切詰め
  - 課金: pay-per-use (~$0.015/投稿)。URL入りは $0.20 → 本文に URL を入れない
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unicodedata

import requests
from requests_oauthlib import OAuth1

API_BASE = "https://api.x.com"
MEDIA_UPLOAD_URL = f"{API_BASE}/2/media/upload"  # command= 形式の単一エンドポイント
TWEETS_URL = f"{API_BASE}/2/tweets"
USERS_ME_URL = f"{API_BASE}/2/users/me"

CHUNK_SIZE = 4 * 1024 * 1024  # 4MB
REQUEST_TIMEOUT = 30          # 秒 (per-request)
PROCESSING_DEADLINE = 240     # 秒 (STATUS poll の hard deadline)
MAX_DURATION_S = 140
MAX_BYTES = 512 * 1024 * 1024
MAX_LONG_EDGE = 1280
MAX_SHORT_EDGE = 1024
MAX_WEIGHTED_LEN = 280        # CJK は 2 カウント (twitter-text v3)

REQUIRED_KEYS = ("api_key", "api_key_secret", "access_token", "access_token_secret")


# ---------------------------------------------------------------------------
# 認証
# ---------------------------------------------------------------------------

def load_auth(token_path: str) -> OAuth1:
    """トークン JSON を読み 4キーを検証して OAuth1 を返す。"""
    token_path = os.path.expanduser(token_path)
    if not os.path.isfile(token_path):
        print(f"Error: トークンファイルが見つかりません: {token_path}", file=sys.stderr)
        sys.exit(1)
    try:
        d = json.loads(open(token_path).read())
    except Exception as e:
        print(f"Error: トークン JSON が不正です: {e}", file=sys.stderr)
        sys.exit(1)
    missing = [k for k in REQUIRED_KEYS if not d.get(k)]
    if missing:
        print(
            f"Error: トークン JSON に必須キーが欠落: {missing}\n"
            f"必須: {list(REQUIRED_KEYS)} (developer.x.com で再生成して保存)",
            file=sys.stderr,
        )
        sys.exit(1)
    return OAuth1(
        d["api_key"], d["api_key_secret"],
        d["access_token"], d["access_token_secret"],
    )


# ---------------------------------------------------------------------------
# 文字数 (twitter-text v3 weighted length: CJK・絵文字=2)
# ---------------------------------------------------------------------------

_WEIGHT1_RANGES = [(0, 4351), (8192, 8205), (8208, 8223), (8242, 8247)]


def _char_weight(ch: str) -> int:
    cp = ord(ch)
    for lo, hi in _WEIGHT1_RANGES:
        if lo <= cp <= hi:
            return 1
    return 2


def weighted_len(text: str) -> int:
    return sum(_char_weight(c) for c in unicodedata.normalize("NFC", text))


def truncate_weighted(text: str, limit: int = MAX_WEIGHTED_LEN) -> str:
    """weighted length が limit を超える場合、末尾を '…' (weight 2) で切詰める。"""
    text = unicodedata.normalize("NFC", text)
    if weighted_len(text) <= limit:
        return text
    acc, out = 0, []
    for ch in text:
        w = _char_weight(ch)
        if acc + w > limit - 2:  # '…' の分を確保
            break
        acc += w
        out.append(ch)
    return "".join(out).rstrip() + "…"


# ---------------------------------------------------------------------------
# 動画前処理 (検査 + 必要なら 720x1280 へ縮小)
# ---------------------------------------------------------------------------

def probe_video(path: str) -> dict:
    """ffprobe で width/height/duration を取得。"""
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-show_entries", "format=duration",
            "-of", "json", path,
        ],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()[-500:]}")
    d = json.loads(r.stdout)
    stream = d["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "duration": float(d["format"]["duration"]),
    }


def prepare_video(path: str) -> tuple[str, bool]:
    """検査して必要なら縮小。(アップロードすべきパス, 一時ファイルか) を返す。

    X の解像度上限 = 長辺 1280 / 短辺 1024。1080x1920 マスターは 720x1280 に縮小。
    非 Premium の再生上限は 720p なので画質ロスは実質無し。
    """
    info = probe_video(path)
    w, h, dur = info["width"], info["height"], info["duration"]
    size = os.path.getsize(path)
    print(f"動画: {w}x{h}, {dur:.1f}s, {size / 1e6:.1f}MB", flush=True)

    if dur > MAX_DURATION_S:
        raise RuntimeError(f"動画が長すぎます: {dur:.1f}s > {MAX_DURATION_S}s (X standard 上限)")
    if size > MAX_BYTES:
        raise RuntimeError(f"ファイルが大きすぎます: {size} bytes > {MAX_BYTES}")

    long_edge, short_edge = max(w, h), min(w, h)
    if long_edge <= MAX_LONG_EDGE and short_edge <= MAX_SHORT_EDGE:
        return path, False

    # 縮小倍率: 長辺・短辺の両上限を満たす最大スケール
    scale = min(MAX_LONG_EDGE / long_edge, MAX_SHORT_EDGE / short_edge)
    nw = int(math.floor(w * scale / 2) * 2)  # 偶数化
    nh = int(math.floor(h * scale / 2) * 2)
    fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="x_upload_")
    os.close(fd)
    print(f"X 解像度上限超過 → {nw}x{nh} に縮小中 (ffmpeg)...", flush=True)
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-i", path,
            "-vf", f"scale={nw}:{nh}",
            "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            tmp,
        ],
        capture_output=True, text=True, timeout=180,
    )
    if r.returncode != 0:
        os.unlink(tmp)
        raise RuntimeError(f"ffmpeg 縮小失敗: {r.stderr.strip()[-500:]}")
    print(f"縮小完了: {os.path.getsize(tmp) / 1e6:.1f}MB", flush=True)
    return tmp, True


# ---------------------------------------------------------------------------
# HTTP ヘルパー (429/403/401 の原因別メッセージ + 5xx バックオフ)
# ---------------------------------------------------------------------------

def _explain_and_exit(resp: requests.Response, ctx: str):
    body = resp.text[:1000]
    if resp.status_code == 401:
        print(
            f"Error: 401 認証エラー ({ctx})。4キーが無効です。\n"
            "→ developer.x.com でキー再生成 → publishing/tokens/x/*.json 更新 "
            "→ gh secret set X_TOKEN_<ID> で再登録\n" + body,
            file=sys.stderr,
        )
    elif resp.status_code == 403:
        print(
            f"Error: 403 Forbidden ({ctx})。最頻原因:\n"
            "  1. アプリ権限が Read-only (Developer Console で Read and Write に変更)\n"
            "  2. 権限変更後に Access Token を再生成していない (再生成必須)\n"
            "  3. pay-per-use クレジット残高ゼロ (Console → 請求書作成 → クレジット)\n" + body,
            file=sys.stderr,
        )
    elif resp.status_code == 429:
        reset = resp.headers.get("x-rate-limit-reset") or resp.headers.get(
            "x-user-limit-24hour-reset", "?"
        )
        print(
            f"Error: 429 レート上限 ({ctx})。24h キャップ到達の可能性。reset={reset}\n" + body,
            file=sys.stderr,
        )
    else:
        print(f"Error: HTTP {resp.status_code} ({ctx})\n{body}", file=sys.stderr)
    sys.exit(1)


def _request_with_retry(method: str, url: str, auth: OAuth1, ctx: str, max_retries: int = 3, **kw):
    """5xx は指数バックオフでリトライ。4xx は原因別メッセージで exit 1。"""
    kw.setdefault("timeout", REQUEST_TIMEOUT)
    for attempt in range(max_retries + 1):
        try:
            resp = requests.request(method, url, auth=auth, **kw)
        except requests.RequestException as e:
            if attempt >= max_retries:
                print(f"Error: ネットワークエラー ({ctx}): {e}", file=sys.stderr)
                sys.exit(1)
            wait = 2 ** (attempt + 1)
            print(f"ネットワークエラー ({ctx})。{wait}秒後リトライ...", flush=True)
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            if attempt >= max_retries:
                _explain_and_exit(resp, ctx)
            wait = 2 ** (attempt + 1)
            print(f"サーバーエラー {resp.status_code} ({ctx})。{wait}秒後リトライ...", flush=True)
            time.sleep(wait)
            continue
        if resp.status_code >= 400:
            _explain_and_exit(resp, ctx)
        return resp
    raise AssertionError("unreachable")


def _media_id_from(resp_json: dict) -> str:
    """v2/v1.1 双方のレスポンス形に対応して media_id を取り出す。"""
    if isinstance(resp_json.get("data"), dict):
        d = resp_json["data"]
        return str(d.get("id") or d.get("media_id_string") or d.get("media_id"))
    return str(resp_json.get("media_id_string") or resp_json.get("media_id"))


# ---------------------------------------------------------------------------
# v2 chunked media upload — 専用パス形式 (2026-06 現行仕様。実機+docs.x.com で確認済み)
#   initialize: POST /2/media/upload/initialize  (application/json)
#   append:     POST /2/media/upload/{id}/append (multipart/form-data)
#   finalize:   POST /2/media/upload/{id}/finalize
#   status:     GET  /2/media/upload?media_id={id}
# ⚠️ 旧 command=INIT/APPEND/FINALIZE 単一エンドポイント形式は廃止済み
#   (POST /2/media/upload は画像/字幕専用に変更され tweet_video を受け付けない)
# ---------------------------------------------------------------------------

def upload_media(video_path: str, auth: OAuth1) -> str:
    total_bytes = os.path.getsize(video_path)

    # INITIALIZE (JSON body)
    r = _request_with_retry(
        "POST", f"{MEDIA_UPLOAD_URL}/initialize", auth, "media initialize",
        json={
            "media_type": "video/mp4",
            "total_bytes": total_bytes,
            "media_category": "tweet_video",
        },
    )
    media_id = _media_id_from(r.json())
    print(f"media initialize ok: media_id={media_id}", flush=True)

    # APPEND (4MB チャンク, multipart)
    with open(video_path, "rb") as f:
        segment_index = 0
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            _request_with_retry(
                "POST", f"{MEDIA_UPLOAD_URL}/{media_id}/append", auth,
                f"media append seg{segment_index}",
                files={
                    "segment_index": (None, str(segment_index)),
                    "media": chunk,
                },
            )
            segment_index += 1
    print(f"media append ok: {segment_index} segments", flush=True)

    # FINALIZE (body 無し)
    r = _request_with_retry(
        "POST", f"{MEDIA_UPLOAD_URL}/{media_id}/finalize", auth, "media finalize",
    )
    info = r.json()
    processing = (info.get("data") or info).get("processing_info")

    # STATUS poll (hard deadline 付き — ハングで GHA スロットを潰さない)
    deadline = time.time() + PROCESSING_DEADLINE
    while processing and processing.get("state") in ("pending", "in_progress"):
        if time.time() > deadline:
            raise RuntimeError(
                f"動画処理が {PROCESSING_DEADLINE}s 以内に完了しませんでした (state={processing.get('state')})"
            )
        wait = int(processing.get("check_after_secs", 3))
        print(f"動画処理中 (state={processing['state']})... {wait}s 待機", flush=True)
        time.sleep(min(wait, 15))
        r = _request_with_retry(
            "GET", MEDIA_UPLOAD_URL, auth, "media STATUS",
            params={"media_id": media_id},
        )
        info = r.json()
        processing = (info.get("data") or info).get("processing_info")

    if processing and processing.get("state") == "failed":
        raise RuntimeError(f"動画処理失敗: {json.dumps(processing, ensure_ascii=False)}")
    print("media 処理完了 (succeeded)", flush=True)
    return media_id


# ---------------------------------------------------------------------------
# 投稿 / 検証 / 削除
# ---------------------------------------------------------------------------

def create_tweet(text: str, media_id: str, auth: OAuth1) -> dict:
    r = _request_with_retry(
        "POST", TWEETS_URL, auth, "POST /2/tweets",
        json={"text": text, "media": {"media_ids": [media_id]}},
    )
    data = r.json()["data"]
    # 残量ヘッダを結果に同梱 (pay-per-use / 24h キャップの可視化)
    limits = {
        k: v for k, v in r.headers.items()
        if k.lower().startswith(("x-rate-limit", "x-app-limit", "x-user-limit"))
    }
    return {"tweet": data, "limits": limits}


def verify(auth: OAuth1):
    r = _request_with_retry("GET", USERS_ME_URL, auth, "GET /2/users/me")
    d = r.json()["data"]
    print(json.dumps(
        {"verified": True, "user_id": d["id"], "username": d["username"], "name": d["name"]},
        ensure_ascii=False, indent=2,
    ))


def delete_tweet(tweet_id: str, auth: OAuth1):
    r = _request_with_retry("DELETE", f"{TWEETS_URL}/{tweet_id}", auth, "DELETE /2/tweets/:id")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="X (Twitter) 動画アップローダー")
    parser.add_argument("--video", help="アップロードする MP4 ファイルパス")
    parser.add_argument("--text", default="", help="ツイート本文 (weighted 280 で自動切詰め)")
    parser.add_argument("--token", required=True, help="トークン JSON パス (4キー)")
    parser.add_argument("--verify", action="store_true", help="認証テストのみ (read)")
    parser.add_argument("--delete", metavar="TWEET_ID", help="指定 tweet を削除")
    args = parser.parse_args()

    auth = load_auth(args.token)

    if args.verify:
        verify(auth)
        return

    if args.delete:
        delete_tweet(args.delete, auth)
        return

    if not args.video:
        print("Error: --video でアップロードするファイルを指定してください", file=sys.stderr)
        sys.exit(1)
    video_path = os.path.expanduser(args.video)
    if not os.path.isfile(video_path):
        print(f"Error: ファイルが見つかりません: {video_path}", file=sys.stderr)
        sys.exit(1)

    text = truncate_weighted(args.text.strip())
    if "http://" in text or "https://" in text:
        # URL 入りは $0.20/投稿 (13倍課金) + リーチ低下 → 設計上使わない
        print("⚠️ 本文に URL が含まれています (高額課金 $0.20/投稿 + リーチ低下)", flush=True)

    upload_path, is_tmp = prepare_video(video_path)
    try:
        media_id = upload_media(upload_path, auth)
        result = create_tweet(text, media_id, auth)
    finally:
        if is_tmp:
            os.unlink(upload_path)

    tweet = result["tweet"]
    out = {
        "tweet_id": tweet["id"],
        "url": f"https://x.com/i/status/{tweet['id']}",
        "text": tweet.get("text", text),
        "limits": result["limits"],
    }
    # dispatch_queue.py は stdout 末尾の JSON ブロックを抽出する (youtube-uploader と同契約)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
