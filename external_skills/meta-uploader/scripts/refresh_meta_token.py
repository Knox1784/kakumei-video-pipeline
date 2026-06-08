#!/usr/bin/env python3
"""
Meta (FB Page + IG) Page トークンの自動更新 — auto_post.yml が毎 run 実行する

設計の肝:
  - FB ログイン経路の Page トークンは「未公開アプリだと60日」で失効する。
  - だが交換元の **ユーザートークンは無期限** (expires_at=0)。これを master 鍵として
    トークンJSONに保管し、そこから `/me/accounts` で Page トークンを定期再生成する。
    → app secret も再OAuth も不要。ユーザー作業は永久にゼロ。
  - データアクセス期限 (90日の「未使用」失効) は毎晩の投稿で更新され続けるため発動しない。
    万一 IG 連携が外れたら refresh が検知して Issue 化する。

ロジック:
  - fb.refreshed_at が --max-age-days (既定30日) 以内 → 何もしない (exit 0)
  - 超過 → 無期限ユーザートークンで /me/accounts → 新 Page トークン → IG 連携確認
    → トークンJSON 書換え → --update-gh-secret なら gh secret set で Secret 反映
  - 失敗 → meta_failure.json の failures[] に追記して exit 1 (Report Meta failure が Issue 化)

使用例:
  python3 refresh_meta_token.py --token publishing/tokens/meta/kakumei_ikka.json --update-gh-secret
  python3 refresh_meta_token.py --token publishing/tokens/meta/kakumei_ikka.json --force --update-gh-secret
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

GRAPH = "https://graph.facebook.com/v25.0"
JST = timezone(timedelta(hours=9))

# トークン漏洩スクラバー (upload.py と同一) — ネットワーク例外メッセージに
# トークン入り URL が埋まり marker→public Issue / GHA ログに流れるのを遮断
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


def append_failure_marker(marker_path: str, error: str):
    """meta_failure.json の failures[] に追記。絶対に raise しない。必ず scrub。"""
    try:
        doc = {"clip_id": None, "at": datetime.now(JST).isoformat(), "failures": []}
        if os.path.exists(marker_path):
            try:
                doc = json.loads(open(marker_path).read())
                doc.setdefault("failures", [])
            except Exception:
                pass
        doc["failures"].append({
            "platform": "meta_token_refresh",
            "error": scrub(error)[-2000:],
            "at": datetime.now(JST).isoformat(),
        })
        with open(marker_path, "w") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as e:
        print(f"⚠️ marker 書込み失敗 (続行): {e}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Meta (FB+IG) Page トークン自動更新")
    parser.add_argument("--token", required=True, help="publishing/tokens/meta/{id}.json")
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--update-gh-secret", action="store_true",
                        help="更新後 gh secret set META_TOKEN_<ID> で Secret にも反映")
    parser.add_argument("--failure-marker", default="meta_failure.json")
    args = parser.parse_args()

    token_path = os.path.expanduser(args.token)
    if not os.path.isfile(token_path):
        print(f"ℹ️ {token_path} 無し → no-op (Meta 未セットアップは正常)", flush=True)
        return 0

    try:
        tok = json.loads(open(token_path).read())
    except Exception as e:
        append_failure_marker(args.failure_marker, f"meta token JSON 読込失敗: {e}")
        print(scrub(f"❌ token JSON 読込失敗: {e}"), file=sys.stderr, flush=True)
        return 1

    user_token = tok.get("user_access_token")
    if not user_token:
        # 旧形式 (user token 未保管) は再生成できない → 静かに skip (Page token は手動更新)
        print("ℹ️ user_access_token 無し → 自動 refresh 不可 (no-op)", flush=True)
        return 0

    fb = tok.get("fb") or {}
    page_id = fb.get("page_id")
    if not page_id:
        append_failure_marker(args.failure_marker, "fb.page_id 欠落")
        print("❌ fb.page_id 欠落", file=sys.stderr, flush=True)
        return 1

    # 鮮度チェック
    now = datetime.now(JST)
    refreshed_at = fb.get("refreshed_at")
    if refreshed_at and not args.force:
        try:
            age_days = (now - datetime.fromisoformat(refreshed_at)).total_seconds() / 86400
            if age_days < args.max_age_days:
                print(f"✅ Page トークン年齢 {age_days:.1f}日 (< {args.max_age_days}日) — 更新不要", flush=True)
                return 0
            print(f"🔄 Page トークン年齢 {age_days:.1f}日 → 再生成", flush=True)
        except Exception:
            print("🔄 refreshed_at 解析不可 → 再生成", flush=True)
    else:
        print("🔄 Page トークン再生成 (force/初回)", flush=True)

    H = {"Authorization": f"Bearer {user_token}"}
    try:
        # 1. 無期限ユーザートークンから Page トークン再生成 (app secret 不要)
        r = requests.get(f"{GRAPH}/me/accounts", headers=H,
                         params={"fields": "id,name,access_token"}, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"/me/accounts HTTP {r.status_code}: {r.text[:200]}")
        pages = r.json().get("data", [])
        page = next((p for p in pages if p["id"] == page_id), None)
        if not page or not page.get("access_token"):
            raise RuntimeError(
                f"page_id={page_id} が /me/accounts に無い (ユーザートークン失効/権限剥奪の可能性)")
        new_page_token = page["access_token"]

        # 2. IG 連携確認 (毎晩使っていれば外れないが、外れたら検知して Issue 化)
        r2 = requests.get(f"{GRAPH}/{page_id}",
                          headers={"Authorization": f"Bearer {new_page_token}"},
                          params={"fields": "instagram_business_account{id,username}"}, timeout=30)
        iba = r2.json().get("instagram_business_account") if r2.status_code == 200 else None
        if not iba:
            # FB は生きているので致命ではない。marker で警告のみ (return は成功扱いにしない)
            append_failure_marker(args.failure_marker,
                                  "IG 連携が確認できない (instagram_business_account=null)。"
                                  "IG 投稿が止まる可能性 — FB Page と IG の連携を確認")
    except Exception as e:
        append_failure_marker(args.failure_marker, f"Meta Page トークン再生成失敗: {e}")
        print(scrub(f"❌ 再生成失敗: {e}"), file=sys.stderr, flush=True)
        return 1

    # 3. トークンJSON 書換え (atomic)
    fb["page_access_token"] = new_page_token
    fb["page_name"] = page.get("name", fb.get("page_name"))
    fb["refreshed_at"] = now.isoformat()
    tok["fb"] = fb
    if iba:
        tok["ig"] = {"ig_user_id": iba["id"], "username": iba.get("username")}
    tmp = token_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, token_path)
    print(f"✅ Page トークン再生成完了 (IG: @{(iba or {}).get('username', '?')})", flush=True)

    # 4. Secret 書き戻し (Threads と同じく旧トークンは消えないので失敗しても次 run でリトライ可)
    if args.update_gh_secret:
        account_id = os.path.splitext(os.path.basename(token_path))[0]  # ファイル名から (secret 名 round-trip 保証)
        secret_name = f"META_TOKEN_{account_id.upper()}"
        repo = os.environ.get("GITHUB_REPOSITORY", "Knox1784/kakumei-video-pipeline")
        try:
            if os.environ.get("GITHUB_ACTIONS") and not os.environ.get("GH_TOKEN"):
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
            append_failure_marker(args.failure_marker,
                                  f"Secret 書き戻し失敗 ({secret_name}): {e} — "
                                  "次 run でリトライ (旧トークンはまだ有効)")
            print(scrub(f"❌ Secret 書き戻し失敗: {e}"), file=sys.stderr, flush=True)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
