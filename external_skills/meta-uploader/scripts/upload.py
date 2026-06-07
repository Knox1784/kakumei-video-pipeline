#!/usr/bin/env python3
"""
Meta (Facebook Page Reels / Instagram Reels / Threads) アップローダー
— youtube-uploader / x-uploader と同じ CLI 契約 (stdout 末尾に結果 JSON ブロック)

認証:
  - facebook / instagram: App A (Business type) の無期限 Page アクセストークン
      → publishing/tokens/meta/{account_id}.json
  - threads: App B (Threads use case) の 60日トークン (refresh_threads_token.py が自動更新)
      → publishing/tokens/threads/{account_id}.json

使用例:
  # 認証テスト (read のみ・投稿しない)
  python3 upload.py --verify --platform facebook  --token publishing/tokens/meta/kakumei_ikka.json
  python3 upload.py --verify --platform instagram --token publishing/tokens/meta/kakumei_ikka.json
  python3 upload.py --verify --platform threads   --token publishing/tokens/threads/kakumei_ikka.json

  # Facebook Page に Reel 投稿 (バイナリ直アップロード)
  python3 upload.py --platform facebook --video short.mp4 --text "説明文" \
    --token publishing/tokens/meta/kakumei_ikka.json

  # Instagram に Reel 投稿 (resumable バイナリ直アップロード)
  python3 upload.py --platform instagram --video short.mp4 --text "キャプション" \
    --token publishing/tokens/meta/kakumei_ikka.json

  # Threads に動画投稿 (⚠️ バイナリ不可 — 公開 URL 必須。GHA では SHA 固定 raw URL を渡す)
  python3 upload.py --platform threads --video-url "https://raw.githubusercontent.com/..." \
    --text "本文" --token publishing/tokens/threads/kakumei_ikka.json

  # テスト投稿の削除 (facebook / threads のみ。instagram は API 削除不可 → アプリから手動)
  python3 upload.py --delete <POST_ID> --platform facebook --token ...

制約 (2026-06 時点・公式 docs 確認済):
  - FB Reels : 9:16 / 3〜90s / 24-60fps / H.264+AAC。レート 30投稿/24h/Page
  - IG Reels : 9:16 / 3s〜15min / ≤300MB / **音声 AAC ≤128kbps 必須** (超過は確定リジェクト)。100投稿/24h
  - Threads  : 9:16 推奨 / ≤300s / ≤1GB / 本文 ≤500字。250投稿/24h
  - ⚠️ トークンは絶対に URL クエリに入れない (Authorization ヘッダのみ)。
    repo/Issue が public のため、全出力はスクラバー (scrub) を通してから print する
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import requests

GRAPH = "https://graph.facebook.com/v25.0"
RUPLOAD_FB = "https://rupload.facebook.com/video-upload/v25.0"
RUPLOAD_IG = "https://rupload.facebook.com/ig-api-upload/v25.0"
THREADS_GRAPH = "https://graph.threads.net/v1.0"

REQUEST_TIMEOUT = 30           # 秒 (per-request)
BINARY_UPLOAD_TIMEOUT = 180    # 秒 (rupload は 1 リクエストで全 bytes 送信。~10MB なら数秒)
FB_PROCESSING_DEADLINE = 150   # 秒 (finish 後の status poll。超過は "processing" 扱いで成功)
IG_PROCESSING_DEADLINE = 300   # 秒 (公式推奨: 1分毎・最大5分)
THREADS_PROCESSING_DEADLINE = 300
IG_MAX_CONTAINER_ATTEMPTS = 2  # 9004/2207052 (fetch/処理の一過性失敗) は新コンテナで1回だけ再試行

FB_REEL_MIN_S, FB_REEL_MAX_S = 3.0, 90.0
# IG の音声上限 = 128kbps (公式スペック + 実リジェクト報告あり)。
# ffmpeg -b:a 128k の実出力は ~131kbps のため判定閾値は 136k
# (prepare_queue_clip.py と同期。128_000 にすると正規化済ファイルを毎回再エンコードする)
COMPLIANT_AUDIO_BPS = 136_000
THREADS_TEXT_LIMIT = 500
IG_CAPTION_LIMIT = 2200


# ---------------------------------------------------------------------------
# トークン漏洩スクラバー — repo/Issue が public のため全出力に適用する
# ---------------------------------------------------------------------------

_SCRUB_PATTERNS = [
    re.compile(r"access_token=[^&\s\"']+"),
    re.compile(r"\bEAA[0-9A-Za-z]{20,}"),      # FB/Page トークン (EAA... プレフィクス)
    re.compile(r"\bTH[A-Z][0-9A-Za-z_\-]{20,}"),  # Threads トークン (THQVJ... プレフィクス)
    re.compile(r"\bIGQ[0-9A-Za-z_\-]{20,}"),   # IG (Instagram Login 系) トークン
]


def scrub(text: str) -> str:
    """トークンらしき文字列を全て *** に置換。print / エラー / marker 書込み前に必ず通す。"""
    for pat in _SCRUB_PATTERNS:
        text = pat.sub("***TOKEN***", text)
    return text


def log(msg: str):
    print(scrub(msg), flush=True)


def err_exit(msg: str, code: int = 1):
    print(scrub(msg), file=sys.stderr, flush=True)
    sys.exit(code)


# ---------------------------------------------------------------------------
# トークンファイル
# ---------------------------------------------------------------------------

def load_token(token_path: str) -> dict:
    token_path = os.path.expanduser(token_path)
    if not os.path.isfile(token_path):
        err_exit(f"Error: トークンファイルが見つかりません: {token_path}")
    try:
        return json.loads(open(token_path).read())
    except Exception as e:
        err_exit(f"Error: トークン JSON が不正です: {e}")


def require_keys(tok: dict, platform: str) -> dict:
    """platform に必要なキーを検証して使う部分を返す。欠落は原因別メッセージで exit 1。"""
    if platform == "facebook":
        fb = tok.get("fb") or {}
        if not (fb.get("page_id") and fb.get("page_access_token")):
            err_exit(
                "Error: トークン JSON に fb.page_id / fb.page_access_token がありません。\n"
                "→ external_skills/meta-uploader/scripts/authorize.py を実行して再取得"
            )
        return fb
    if platform == "instagram":
        fb = tok.get("fb") or {}
        ig = tok.get("ig") or {}
        if not fb.get("page_access_token"):
            err_exit("Error: fb.page_access_token がありません (IG は Page トークンで投稿します)")
        if not ig.get("ig_user_id"):
            err_exit(
                "Error: ig.ig_user_id がありません。\n"
                "→ IG アカウントが Professional 化 + FB Page 連携済みか確認して authorize.py 再実行"
            )
        return {"ig_user_id": ig["ig_user_id"], "page_access_token": fb["page_access_token"]}
    if platform == "threads":
        if not (tok.get("user_id") and tok.get("access_token")):
            err_exit(
                "Error: threads トークン JSON に user_id / access_token がありません。\n"
                "→ authorize.py の Threads セクションを実行して再取得"
            )
        return tok
    err_exit(f"Error: 未知の platform: {platform}")


# ---------------------------------------------------------------------------
# 動画 preflight (facebook / instagram のバイナリ経路のみ)
#   ⚠️ Threads は committed bytes を URL fetch するためここでは直せない
#     → queue 配置時の prepare_queue_clip.py が本質対応。これは安全網
# ---------------------------------------------------------------------------

def probe_video(path: str) -> dict:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height,bit_rate,sample_rate",
            "-show_entries", "format=duration",
            "-of", "json", path,
        ],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()[-500:]}")
    d = json.loads(r.stdout)
    info = {"duration": float(d["format"]["duration"])}
    for s in d.get("streams", []):
        if s.get("codec_type") == "video":
            info.update(vcodec=s.get("codec_name"), width=int(s.get("width", 0)),
                        height=int(s.get("height", 0)))
        elif s.get("codec_type") == "audio":
            info.update(acodec=s.get("codec_name"),
                        abr=int(s.get("bit_rate") or 0),
                        asr=int(s.get("sample_rate") or 0))
    return info


def prepare_video(path: str, platform: str) -> tuple[str, bool]:
    """検査して必要なら音声のみ再エンコード。(アップロードすべきパス, 一時ファイルか) を返す。"""
    info = probe_video(path)
    dur = info["duration"]
    log(f"動画: {info.get('width')}x{info.get('height')}, {dur:.1f}s, "
        f"audio={info.get('acodec')}@{info.get('abr', 0)//1000}kbps")

    if platform == "facebook" and not (FB_REEL_MIN_S <= dur <= FB_REEL_MAX_S):
        raise RuntimeError(
            f"FB Reels の長さ制限外: {dur:.1f}s (許容 {FB_REEL_MIN_S:.0f}-{FB_REEL_MAX_S:.0f}s)。"
            "meta.json に \"fb_enabled\": false を設定して FB のみ skip 可"
        )
    if info.get("vcodec") not in ("h264", "hevc"):
        raise RuntimeError(f"非対応 video codec: {info.get('vcodec')} (H.264/HEVC のみ)")

    # 音声が仕様内ならそのまま
    if info.get("acodec") == "aac" and 0 < info.get("abr", 0) <= COMPLIANT_AUDIO_BPS and info.get("asr", 0) <= 48000:
        return path, False

    # 音声のみ再エンコード (映像は無劣化 copy) — IG は >128kbps を確定リジェクトする
    fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="meta_upload_")
    os.close(fd)
    log(f"音声が仕様外 ({info.get('acodec')}@{info.get('abr', 0)//1000}kbps) → 128kbps AAC に再エンコード (映像 copy)...")
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-i", path,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-movflags", "+faststart",
                tmp,
            ],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 音声再エンコード失敗: {r.stderr.strip()[-500:]}")
    except BaseException:
        # TimeoutExpired / ffmpeg 不在 (OSError) 含む全失敗で temp をリークさせない
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    log(f"再エンコード完了: {os.path.getsize(tmp) / 1e6:.1f}MB")
    return tmp, True


# ---------------------------------------------------------------------------
# HTTP ヘルパー — トークンは Authorization ヘッダのみ (URL/クエリ厳禁)
# ---------------------------------------------------------------------------

class GraphError(RuntimeError):
    """4xx Graph API エラー。原因別メッセージ化と IG リトライ判定に使う。"""

    def __init__(self, status: int, body: dict | str, ctx: str):
        self.status = status
        self.body = body if isinstance(body, dict) else {}
        self.raw = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        err = self.body.get("error", {}) if isinstance(self.body, dict) else {}
        self.code = err.get("code")
        self.subcode = err.get("error_subcode")
        self.message = err.get("message", "")
        self.ctx = ctx
        super().__init__(f"HTTP {status} ({ctx}) code={self.code} subcode={self.subcode}: "
                         f"{scrub(str(self.message))[:300]}")


def _request_with_retry(method: str, url: str, ctx: str, *, token: str,
                        token_scheme: str = "Bearer", headers: dict | None = None,
                        params: dict | None = None, data: dict | None = None,
                        body_bytes: bytes | None = None, max_retries: int = 3,
                        timeout: int = REQUEST_TIMEOUT,
                        deadline: float | None = None) -> requests.Response:
    """5xx/ネットワークは指数バックオフ。4xx は GraphError raise (呼び出し側で原因別処理)。

    deadline (time.time() 基準): リトライ込みの worst case が subprocess timeout を
    突き破ると、FB finish=PUBLISHED **後**に SIGKILL → 成功投稿が「失敗」記録 →
    手動再投稿で二重投稿になり得る。deadline 超過時はリトライせず即 raise し、
    per-attempt timeout も残り時間でキャップする。
    """
    h = dict(headers or {})
    h["Authorization"] = f"{token_scheme} {token}"
    for attempt in range(max_retries + 1):
        attempt_timeout = timeout
        if deadline is not None:
            rem = deadline - time.time()
            if rem <= 1:
                raise RuntimeError(f"deadline 超過のためリトライ中断 ({ctx})")
            attempt_timeout = min(timeout, max(int(rem), 1))
        try:
            resp = requests.request(method, url, headers=h, params=params,
                                    data=body_bytes if body_bytes is not None else data,
                                    timeout=attempt_timeout)
        except requests.RequestException as e:
            if attempt >= max_retries or (deadline is not None and deadline - time.time() < 5):
                raise RuntimeError(f"ネットワークエラー ({ctx}): {scrub(str(e))[:300]}")
            wait = 2 ** (attempt + 1)
            log(f"ネットワークエラー ({ctx})。{wait}秒後リトライ...")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            if attempt >= max_retries or (deadline is not None and deadline - time.time() < 5):
                raise GraphError(resp.status_code, _safe_json(resp), ctx)
            wait = 2 ** (attempt + 1)
            log(f"サーバーエラー {resp.status_code} ({ctx})。{wait}秒後リトライ...")
            time.sleep(wait)
            continue
        if resp.status_code >= 400:
            raise GraphError(resp.status_code, _safe_json(resp), ctx)
        return resp
    raise AssertionError("unreachable")


def _safe_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return resp.text[:1000]


def explain_graph_error(e: GraphError) -> str:
    """原因別の対処メッセージ (AUTO_POST_RULES.md のランブックと対応)。"""
    if e.code == 190:
        return ("190 トークン失効 (パスワード変更/期限切れ/権限剥奪)。\n"
                "→ authorize.py 再実行 → gh secret set で Secret 更新")
    if e.code in (200, 10):
        return ("権限/スコープ不足。Graph API Explorer で必要 scope を付けてトークン再取得\n"
                "(pages_show_list, pages_read_engagement, pages_manage_posts, "
                "instagram_basic, instagram_content_publish)")
    if e.code in (4, 17, 32, 613) or e.subcode == 2207042:
        return "レート上限 (FB Reels 30/24h・IG 100/24h・Threads 250/24h)。24h 窓の自然回復を待つ"
    if e.subcode == 2207026:
        return ("動画スペック違反 (音声 >128kbps / コーデック等)。\n"
                "→ prepare_queue_clip.py で正規化した mp4 か確認")
    if e.code == 9004 or e.subcode == 2207052:
        return ("メディア取得/処理失敗 (video_url が fetch 不能 or Meta 側一過性)。\n"
                "→ Threads: repo が public か・SHA URL が生きているか確認。IG: 再試行")
    return "詳細: " + scrub(e.raw)[:500]


# ---------------------------------------------------------------------------
# Facebook Page Reels — 3-phase (start → rupload binary → finish) + status poll
# ---------------------------------------------------------------------------

def post_facebook(video_path: str, text: str, fb: dict, deadline: float) -> dict:
    page_id, pt = fb["page_id"], fb["page_access_token"]
    total_bytes = os.path.getsize(video_path)

    # 1. start
    r = _request_with_retry("POST", f"{GRAPH}/{page_id}/video_reels", "fb reels start",
                            token=pt, data={"upload_phase": "start"}, deadline=deadline)
    start = r.json()
    video_id = start["video_id"]
    log(f"fb start ok: video_id={video_id}")

    # 2. rupload バイナリ (1 リクエストで全 bytes)
    with open(video_path, "rb") as f:
        _request_with_retry(
            "POST", f"{RUPLOAD_FB}/{video_id}", "fb rupload",
            token=pt, token_scheme="OAuth",
            headers={"offset": "0", "file_size": str(total_bytes)},
            body_bytes=f.read(), timeout=BINARY_UPLOAD_TIMEOUT,
            deadline=deadline,
        )
    log(f"fb rupload ok: {total_bytes / 1e6:.1f}MB")

    # 3. finish (PUBLISHED)
    _request_with_retry("POST", f"{GRAPH}/{page_id}/video_reels", "fb reels finish",
                        token=pt, data={
                            "upload_phase": "finish",
                            "video_id": video_id,
                            "video_state": "PUBLISHED",
                            "description": text,
                        }, deadline=deadline)
    log("fb finish ok (video_state=PUBLISHED)")

    # 4. status poll — finish 受理済みなので deadline 超過は "processing" 扱いで成功
    status = "processing"
    poll_deadline = min(deadline, time.time() + FB_PROCESSING_DEADLINE)
    while time.time() < poll_deadline:
        try:
            r = _request_with_retry("GET", f"{GRAPH}/{video_id}", "fb status poll",
                                    token=pt, params={"fields": "status"}, deadline=deadline)
            vs = (r.json().get("status") or {}).get("video_status", "")
            log(f"fb 処理中 (video_status={vs})...")
            if vs == "ready":
                status = "ready"
                break
            if vs == "error":
                raise RuntimeError(f"FB 動画処理失敗: {scrub(json.dumps(r.json(), ensure_ascii=False))[:500]}")
        except (GraphError, RuntimeError) as e:
            # finish=PUBLISHED は受理済み — poll の失敗 (ネットワーク枯渇含む) で
            # 公開済み投稿を「失敗」記録してはいけない。続行して deadline で "processing" 成功
            log(f"fb status poll 一過性エラー (続行): {e}")
        time.sleep(10)
    if status == "processing":
        log("⚠️ fb 処理未完了のまま deadline — finish=PUBLISHED 受理済みのため成功扱い (誤報 Issue 防止)")

    # ⚠️ result JSON に text を含めない — dispatch の extract_json_block は brace カウントの
    #    ため、本文中の {} で解析が壊れる (本文は dispatcher 側が state に記録する)
    return {
        "platform": "facebook",
        "video_id": str(video_id),
        "url": f"https://www.facebook.com/reel/{video_id}",
        "status": status,
    }


# ---------------------------------------------------------------------------
# Instagram Reels — resumable binary (container → rupload → poll → publish)
# ---------------------------------------------------------------------------

def post_instagram(video_path: str, text: str, ig: dict, deadline: float) -> dict:
    ig_user_id, pt = ig["ig_user_id"], ig["page_access_token"]
    total_bytes = os.path.getsize(video_path)
    caption = text[:IG_CAPTION_LIMIT]
    last_err: Exception | None = None

    for attempt in range(IG_MAX_CONTAINER_ATTEMPTS):
        if attempt:
            log(f"IG: 新コンテナで再試行 ({attempt + 1}/{IG_MAX_CONTAINER_ATTEMPTS})")
        try:
            # 1. resumable コンテナ作成
            r = _request_with_retry("POST", f"{GRAPH}/{ig_user_id}/media", "ig media container",
                                    token=pt, data={
                                        "media_type": "REELS",
                                        "upload_type": "resumable",
                                        "caption": caption,
                                    }, deadline=deadline)
            container_id = r.json()["id"]
            log(f"ig container ok: {container_id}")

            # 2. rupload バイナリ
            with open(video_path, "rb") as f:
                _request_with_retry(
                    "POST", f"{RUPLOAD_IG}/{container_id}", "ig rupload",
                    token=pt, token_scheme="OAuth",
                    headers={"offset": "0", "file_size": str(total_bytes)},
                    body_bytes=f.read(), timeout=BINARY_UPLOAD_TIMEOUT,
                    deadline=deadline,
                )
            log(f"ig rupload ok: {total_bytes / 1e6:.1f}MB")

            # 3. status poll (FINISHED まで)
            poll_deadline = min(deadline, time.time() + IG_PROCESSING_DEADLINE)
            while True:
                r = _request_with_retry("GET", f"{GRAPH}/{container_id}", "ig status poll",
                                        token=pt, params={"fields": "status_code,status"}, deadline=deadline)
                sc = r.json().get("status_code", "")
                if sc == "FINISHED":
                    break
                if sc in ("ERROR", "EXPIRED"):
                    raise RuntimeError(
                        f"IG コンテナ {sc}: {scrub(json.dumps(r.json(), ensure_ascii=False))[:500]}")
                if time.time() > poll_deadline:
                    raise RuntimeError(f"IG 処理が deadline 内に完了せず (status_code={sc})")
                log(f"ig 処理中 (status_code={sc})... 10s 待機")
                time.sleep(10)

            # 4. publish
            r = _request_with_retry("POST", f"{GRAPH}/{ig_user_id}/media_publish", "ig publish",
                                    token=pt, data={"creation_id": container_id}, deadline=deadline)
            media_id = r.json()["id"]
            log(f"ig published: media_id={media_id}")

            # 5. permalink (best-effort)
            permalink = None
            try:
                r = _request_with_retry("GET", f"{GRAPH}/{media_id}", "ig permalink",
                                        token=pt, params={"fields": "permalink"}, max_retries=1, deadline=deadline)
                permalink = r.json().get("permalink")
            except Exception as e:
                log(f"ig permalink 取得失敗 (無視): {e}")

            # text は result に含めない (brace カウント対策 — post_facebook 参照)
            return {
                "platform": "instagram",
                "media_id": str(media_id),
                "container_id": str(container_id),
                "permalink": permalink,
                "url": permalink or f"https://www.instagram.com/reel/{media_id}/",
            }
        except (GraphError, RuntimeError) as e:
            last_err = e
            # 再試行は「publish 前に確定した一過性失敗」のみに限定する。
            # publish 段階以降の曖昧な失敗で新コンテナを作ると二重投稿になり得るため、
            # ① fetch/処理失敗 (9004/2207052) ② コンテナ状態 ERROR、の2パターンだけ
            retriable = (isinstance(e, GraphError) and (e.code == 9004 or e.subcode == 2207052)
                         and "publish" not in e.ctx)
            retriable = retriable or "IG コンテナ ERROR" in str(e)
            if retriable and attempt + 1 < IG_MAX_CONTAINER_ATTEMPTS and time.time() < deadline:
                continue
            raise
    raise last_err  # unreachable (上で raise 済) — 型のための保険


# ---------------------------------------------------------------------------
# Threads — URL fetch のみ (container → poll → publish)
# ---------------------------------------------------------------------------

def truncate_text(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def post_threads(video_url: str, text: str, th: dict, deadline: float) -> dict:
    user_id, tt = th["user_id"], th["access_token"]
    text = truncate_text(text, THREADS_TEXT_LIMIT)

    # 1. コンテナ作成 (Meta が video_url を cURL fetch する — 公開 URL 必須)
    r = _request_with_retry("POST", f"{THREADS_GRAPH}/{user_id}/threads", "threads container",
                            token=tt, data={
                                "media_type": "VIDEO",
                                "video_url": video_url,
                                "text": text,
                            }, deadline=deadline)
    container_id = r.json()["id"]
    log(f"threads container ok: {container_id}")

    # 2. status poll (公式推奨: ~30s 待ってから 1分毎・最大5分)
    time.sleep(15)
    poll_deadline = min(deadline, time.time() + THREADS_PROCESSING_DEADLINE)
    while True:
        r = _request_with_retry("GET", f"{THREADS_GRAPH}/{container_id}", "threads status poll",
                                token=tt, params={"fields": "status,error_message"}, deadline=deadline)
        d = r.json()
        st = d.get("status", "")
        if st == "FINISHED":
            break
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(
                f"Threads コンテナ {st}: error_message={d.get('error_message')} "
                "(FAILED_DOWNLOADING_VIDEO = video_url が fetch 不能 → repo public / SHA URL を確認)")
        if time.time() > poll_deadline:
            raise RuntimeError(f"Threads 処理が deadline 内に完了せず (status={st})")
        log(f"threads 処理中 (status={st})... 20s 待機")
        time.sleep(20)

    # 3. publish
    r = _request_with_retry("POST", f"{THREADS_GRAPH}/{user_id}/threads_publish", "threads publish",
                            token=tt, data={"creation_id": container_id}, deadline=deadline)
    post_id = r.json()["id"]
    log(f"threads published: post_id={post_id}")

    # 4. permalink (best-effort)
    permalink = None
    try:
        r = _request_with_retry("GET", f"{THREADS_GRAPH}/{post_id}", "threads permalink",
                                token=tt, params={"fields": "permalink"}, max_retries=1, deadline=deadline)
        permalink = r.json().get("permalink")
    except Exception as e:
        log(f"threads permalink 取得失敗 (無視): {e}")

    # text は result に含めない (brace カウント対策 — post_facebook 参照)
    return {
        "platform": "threads",
        "post_id": str(post_id),
        "permalink": permalink,
        "url": permalink or f"https://www.threads.net/@{th.get('username', '')}",
    }


# ---------------------------------------------------------------------------
# verify / delete
# ---------------------------------------------------------------------------

def verify(platform: str, tok: dict):
    if platform == "facebook":
        fb = require_keys(tok, "facebook")
        r = _request_with_retry("GET", f"{GRAPH}/{fb['page_id']}", "fb verify",
                                token=fb["page_access_token"], params={"fields": "id,name"})
        out = {"verified": True, "platform": "facebook", **r.json()}
    elif platform == "instagram":
        ig = require_keys(tok, "instagram")
        r = _request_with_retry("GET", f"{GRAPH}/{ig['ig_user_id']}", "ig verify",
                                token=ig["page_access_token"], params={"fields": "id,username"})
        out = {"verified": True, "platform": "instagram", **r.json()}
    else:  # threads
        th = require_keys(tok, "threads")
        r = _request_with_retry("GET", f"{THREADS_GRAPH}/me", "threads verify",
                                token=th["access_token"], params={"fields": "id,username"})
        out = {"verified": True, "platform": "threads", **r.json()}
        # トークン年齢の警告 (60日寿命。7日毎自動 refresh が止まっていないかの早期検知)
        refreshed_at = tok.get("refreshed_at")
        if refreshed_at:
            try:
                from datetime import datetime, timezone
                age_days = (datetime.now(timezone.utc)
                            - datetime.fromisoformat(refreshed_at)).days
                out["token_age_days"] = age_days
                if age_days > 45:
                    out["warning"] = f"⚠️ トークン年齢 {age_days}日 (60日で失効) — refresh が止まっている可能性"
            except Exception:
                pass
    print(scrub(json.dumps(out, ensure_ascii=False, indent=2)))


def delete_post(platform: str, post_id: str, tok: dict):
    if platform == "facebook":
        fb = require_keys(tok, "facebook")
        r = _request_with_retry("DELETE", f"{GRAPH}/{post_id}", "fb delete",
                                token=fb["page_access_token"])
    elif platform == "threads":
        th = require_keys(tok, "threads")
        r = _request_with_retry("DELETE", f"{THREADS_GRAPH}/{post_id}", "threads delete",
                                token=th["access_token"])
    else:
        err_exit("Error: Instagram は API 削除不可。IG アプリから手動で削除してください")
    print(scrub(json.dumps(r.json(), ensure_ascii=False, indent=2)))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Meta (FB Reels / IG Reels / Threads) アップローダー")
    parser.add_argument("--platform", required=True,
                        choices=["facebook", "instagram", "threads"])
    parser.add_argument("--video", help="アップロードする MP4 (facebook / instagram)")
    parser.add_argument("--video-url", help="公開動画 URL (threads 専用)")
    parser.add_argument("--text", default="", help="説明文/キャプション/本文")
    parser.add_argument("--token", required=True, help="トークン JSON パス")
    parser.add_argument("--verify", action="store_true", help="認証テストのみ (read)")
    parser.add_argument("--delete", metavar="POST_ID", help="指定投稿を削除 (fb/threads)")
    parser.add_argument("--deadline-s", type=int, default=0,
                        help="全体の wall-clock 上限秒 (0=プラットフォーム既定)")
    args = parser.parse_args()

    tok = load_token(args.token)

    try:
        if args.verify:
            verify(args.platform, tok)
            return
        if args.delete:
            delete_post(args.platform, args.delete, tok)
            return

        deadline = time.time() + (args.deadline_s or 3600)

        if args.platform == "threads":
            if not args.video_url:
                err_exit("Error: threads は --video-url が必須です (バイナリアップロード非対応)")
            th = require_keys(tok, "threads")
            result = post_threads(args.video_url, args.text, th, deadline)
        else:
            if not args.video:
                err_exit("Error: --video でアップロードするファイルを指定してください")
            video_path = os.path.expanduser(args.video)
            if not os.path.isfile(video_path):
                err_exit(f"Error: ファイルが見つかりません: {video_path}")
            section = require_keys(tok, args.platform)
            upload_path, is_tmp = prepare_video(video_path, args.platform)
            try:
                if args.platform == "facebook":
                    result = post_facebook(upload_path, args.text, section, deadline)
                else:
                    result = post_instagram(upload_path, args.text, section, deadline)
            finally:
                if is_tmp:
                    os.unlink(upload_path)
    except GraphError as e:
        err_exit(f"Error: {e}\n対処: {explain_graph_error(e)}")
    except Exception as e:
        # RuntimeError 以外 (TimeoutExpired / OSError 等) も raw traceback を出さず
        # 必ずスクラブ済みメッセージで終了する (stderr は marker → public Issue に流れる)
        err_exit(f"Error: {type(e).__name__}: {scrub(str(e))[:1000]}")

    # dispatch_queue.py は stdout 末尾の JSON ブロックを抽出する (youtube/x-uploader と同契約)
    print(scrub(json.dumps(result, ensure_ascii=False, indent=2)))


if __name__ == "__main__":
    main()
