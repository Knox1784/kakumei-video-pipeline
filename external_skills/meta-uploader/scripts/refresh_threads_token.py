#!/usr/bin/env python3
"""
Threads 60日トークンの自動更新 — auto_post.yml が毎 run 実行する

ロジック:
  - threads トークン JSON の refreshed_at が --max-age-days (既定7日) 以内 → 何もしない (exit 0)
  - 7日超 → GET graph.threads.net/refresh_access_token (grant_type=th_refresh_token)
    → token JSON を書換え → --update-gh-secret なら gh secret set で Secret にも反映 (exit 0)
  - 失敗 → meta_failure.json の failures[] に追記して exit 1 (Report Meta failure が Issue 化)

安全性の根拠:
  - Meta の refresh は**旧トークンを失効させない** (新旧並存) → gh secret set が失敗しても
    Secret には有効な旧トークンが残り、次 run で丸ごとリトライされる。トークン喪失ウィンドウ無し
  - refreshed_at <24h は Meta 側が refresh を拒否するため --force でも no-op
  - 7日閾値 × 60日寿命 = 8倍マージン (auto_post は launchd 経由で毎日確実に発火)

使用例:
  # GHA (auto_post.yml から):
  python3 refresh_threads_token.py --token publishing/tokens/threads/kakumei_ikka.json --update-gh-secret
  # 手動で今すぐ更新:
  python3 refresh_threads_token.py --token publishing/tokens/threads/kakumei_ikka.json --force --update-gh-secret
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

THREADS_GRAPH = "https://graph.threads.net"
JST = timezone(timedelta(hours=9))
ESCALATE_AGE_DAYS = 50  # 60日失効の10日前から警告をエスカレート

# トークン漏洩スクラバー (upload.py と同一) — refresh の例外メッセージには
# `Max retries exceeded with url: ...access_token=TH...` のように**トークン入り URL** が
# 埋まることがあり、それが marker → public Issue / GHA ログに流れるのを遮断する
_SCRUB_PATTERNS = [
    re.compile(r"access_token=[^&\s\"']+"),
    re.compile(r"\bEAA[0-9A-Za-z]{20,}"),
    re.compile(r"\bTH[A-Z][0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bIGQ[0-9A-Za-z_\-]{20,}"),
]


def scrub(text: str) -> str:
    for pat in _SCRUB_PATTERNS:
        text = pat.sub("***TOKEN***", text)
    return text


def append_failure_marker(marker_path: str, error: str, token_age_days: float | None):
    """meta_failure.json の failures[] に追記。絶対に raise しない。エラー文は必ず scrub。"""
    try:
        doc = {"clip_id": None, "at": datetime.now(JST).isoformat(), "failures": []}
        if os.path.exists(marker_path):
            try:
                doc = json.loads(open(marker_path).read())
                doc.setdefault("failures", [])
            except Exception:
                pass
        msg = scrub(error)[-2000:]
        if token_age_days is not None and token_age_days > ESCALATE_AGE_DAYS:
            msg = (f"🚨 緊急: Threads トークン年齢 {token_age_days:.0f}日 (60日で完全失効・"
                   f"失効後は再OAuth必須)。早急に対応を — {msg}")
        doc["failures"].append({
            "platform": "threads_token_refresh",
            "error": msg,
            "at": datetime.now(JST).isoformat(),
        })
        with open(marker_path, "w") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as e:
        print(f"⚠️ marker 書込み失敗 (続行): {e}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Threads トークン自動更新")
    parser.add_argument("--token", required=True, help="publishing/tokens/threads/{id}.json")
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--force", action="store_true", help="鮮度に関係なく更新 (ただし <24h は不可)")
    parser.add_argument("--update-gh-secret", action="store_true",
                        help="更新後 gh secret set THREADS_TOKEN_<ID> で Secret にも反映")
    parser.add_argument("--failure-marker", default="meta_failure.json",
                        help="失敗 marker のパス (GHA workspace root 相対)")
    args = parser.parse_args()

    token_path = os.path.expanduser(args.token)
    if not os.path.isfile(token_path):
        print(f"ℹ️ {token_path} 無し → no-op (Threads 未セットアップは正常)", flush=True)
        return 0

    try:
        tok = json.loads(open(token_path).read())
    except Exception as e:
        append_failure_marker(args.failure_marker, f"threads token JSON 読込失敗: {e}", None)
        print(f"❌ token JSON 読込失敗: {e}", file=sys.stderr, flush=True)
        return 1

    if not tok.get("access_token"):
        print("ℹ️ threads.access_token 無し → no-op", flush=True)
        return 0

    now = datetime.now(JST)
    age_days = None
    refreshed_at = tok.get("refreshed_at")
    if refreshed_at:
        try:
            age = now - datetime.fromisoformat(refreshed_at)
            age_days = age.total_seconds() / 86400
        except Exception:
            pass

    # 鮮度チェック
    if age_days is not None:
        if age_days < 1.0:
            print(f"ℹ️ トークン年齢 {age_days * 24:.1f}h (<24h) — Meta が refresh を拒否するため no-op", flush=True)
            return 0
        if not args.force and age_days < args.max_age_days:
            print(f"✅ トークン年齢 {age_days:.1f}日 (< {args.max_age_days}日) — 更新不要", flush=True)
            return 0
        print(f"🔄 トークン年齢 {age_days:.1f}日 → refresh 実行", flush=True)
    else:
        print("🔄 refreshed_at 不明 → refresh 実行", flush=True)

    # refresh (client_secret 不要・旧トークンは失効しない)
    try:
        r = requests.get(f"{THREADS_GRAPH}/refresh_access_token", params={
            "grant_type": "th_refresh_token",
            "access_token": tok["access_token"],
        }, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"refresh HTTP {r.status_code}: {r.text[:300]}")
        d = r.json()
        new_token = d["access_token"]
        expires_in = int(d.get("expires_in", 60 * 24 * 3600))
    except Exception as e:
        append_failure_marker(args.failure_marker, f"Threads refresh 失敗: {e}", age_days)
        print(scrub(f"❌ refresh 失敗: {e}"), file=sys.stderr, flush=True)
        return 1

    # token JSON 書換え (atomic)
    tok["access_token"] = new_token
    tok["refreshed_at"] = now.isoformat()
    tok["expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
    tmp = token_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, token_path)
    print(f"✅ refresh 完了 (新 expires_at={tok['expires_at']})", flush=True)

    # Secret 書き戻し
    if args.update_gh_secret:
        # ⚠️ secret 名は必ず**ファイル名**から導出する (token JSON の account_id は使わない)。
        #    workflow の restore ステップは THREADS_TOKEN_<ID> をファイル名に lowercase して
        #    書くため、ファイル名だけが secret 名と round-trip する保証がある。JSON 内の
        #    account_id が乖離していると別 secret へ静かに書き続け 60日後に失効する
        account_id = os.path.splitext(os.path.basename(token_path))[0]
        secret_name = f"THREADS_TOKEN_{account_id.upper()}"
        repo = os.environ.get("GITHUB_REPOSITORY", "Knox1784/kakumei-video-pipeline")
        try:
            if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
                # ローカル実行は keychain の gh auth で動くため env 必須なのは GHA のみ
                if os.environ.get("GITHUB_ACTIONS"):
                    raise RuntimeError("GH_TOKEN 未設定 (Secret GH_PAT_SECRETS を確認)")
            r = subprocess.run(
                ["gh", "secret", "set", secret_name, "--repo", repo],
                input=open(token_path).read(), text=True,
                capture_output=True, timeout=60,
            )
            if r.returncode != 0:
                raise RuntimeError(f"gh secret set 失敗: {r.stderr.strip()[-300:]}")
            print(f"✅ Secret {secret_name} 更新完了", flush=True)
        except Exception as e:
            # 旧トークンは Secret に残っていてまだ有効 → 次 run で丸ごとリトライされる
            append_failure_marker(args.failure_marker,
                                  f"Secret 書き戻し失敗 ({secret_name}): {e} — "
                                  "旧トークンは有効なため次 run でリトライ", age_days)
            print(scrub(f"❌ Secret 書き戻し失敗: {e}"), file=sys.stderr, flush=True)
            return 1

    return 0  # 更新成功 (no-op と同じ exit 0。ログの ✅ で区別)


if __name__ == "__main__":
    sys.exit(main())
