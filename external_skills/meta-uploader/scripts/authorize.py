#!/usr/bin/env python3
"""
Meta (FB Page / Instagram / Threads) トークン採取ヘルパー — 対話式・ホスティング不要

やること:
  [App A: FB+IG]  Graph API Explorer の short-lived user token を貼る
     → fb_exchange_token で 60日 user token に交換
     → /me/accounts から **無期限 Page トークン** を取得
     → Page から instagram_business_account (IG user id) を導出
     → publishing/tokens/meta/{account_id}.json に保存
  [App B: Threads] 認可 URL を表示 → ブラウザで承認 → リダイレクト先 URL を貼る
     → code → short token → th_exchange_token で 60日トークンに交換
     → publishing/tokens/threads/{account_id}.json に保存

使用例:
  python3 authorize.py --account-id kakumei_ikka              # FB/IG + Threads 両方
  python3 authorize.py --account-id kakumei_ikka --skip-threads   # FB/IG のみ
  python3 authorize.py --account-id kakumei_ikka --skip-fb        # Threads のみ

前提 (publishing/SETUP_META.md 参照):
  - App A (Business type) 作成済み + Graph API Explorer で short token 採取済み
    (scopes: pages_show_list, pages_read_engagement, pages_manage_posts,
             instagram_basic, instagram_content_publish)
  - App B (Access the Threads API use case) 作成済み + 自分が Threads Tester
    (Threads アプリ内 設定 → アカウント → Webサイトのアクセス許可 で招待承認済み)
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse, parse_qs

import requests

GRAPH = "https://graph.facebook.com/v25.0"
THREADS_GRAPH = "https://graph.threads.net"
JST = timezone(timedelta(hours=9))

# トークン漏洩スクラバー (upload.py と同一) — ネットワーク例外のメッセージには
# トークン/secret 入り URL が埋まることがあるため、エラー表示前に必ず通す
_SCRUB_PATTERNS = [
    re.compile(r"access_token=[^&\s\"']+"),
    re.compile(r"client_secret=[^&\s\"']+"),
    re.compile(r"fb_exchange_token=[^&\s\"']+"),
    re.compile(r"\bEAA[0-9A-Za-z]{20,}"),
    re.compile(r"\bTH[A-Z][0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bIGQ[0-9A-Za-z_\-]{20,}"),
]


def scrub(text: str) -> str:
    for pat in _SCRUB_PATTERNS:
        text = pat.sub("***SECRET***", text)
    return text

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
META_TOKENS_DIR = os.path.join(ROOT, "publishing", "tokens", "meta")
THREADS_TOKENS_DIR = os.path.join(ROOT, "publishing", "tokens", "threads")


def die(msg: str):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def ask(prompt: str, default: str = "") -> str:
    sfx = f" [{default}]" if default else ""
    v = input(f"{prompt}{sfx}: ").strip()
    return v or default


def get_json(url: str, params: dict, ctx: str, token: str | None = None) -> dict:
    """token を渡すと Authorization: Bearer ヘッダで送る (URL クエリに載せない)。"""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        die(scrub(f"{ctx} ネットワークエラー: {e}"))
    if r.status_code >= 400:
        die(scrub(f"{ctx} 失敗 (HTTP {r.status_code}): {r.text[:500]}"))
    return r.json()


def post_json(url: str, data: dict, ctx: str) -> dict:
    try:
        r = requests.post(url, data=data, timeout=30)
    except requests.RequestException as e:
        die(scrub(f"{ctx} ネットワークエラー: {e}"))
    if r.status_code >= 400:
        die(scrub(f"{ctx} 失敗 (HTTP {r.status_code}): {r.text[:500]}"))
    return r.json()


def load_existing(path: str) -> dict:
    """既存トークンファイルがあれば読み込み (merge モード — 片側だけ再認証できる)。"""
    if os.path.isfile(path):
        try:
            return json.loads(open(path).read())
        except Exception:
            print(f"⚠️ 既存 {path} が読めないため新規作成します")
    return {}


def write_token(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    print(f"✅ 保存: {path}")


# ---------------------------------------------------------------------------
# App A: FB Page + Instagram
# ---------------------------------------------------------------------------

def authorize_fb_ig(account_id: str) -> dict:
    print("\n=== [App A] Facebook Page + Instagram ===")
    print("Graph API Explorer (https://developers.facebook.com/tools/explorer/) で:")
    print("  1. 対象アプリ (App A) を選択")
    print("  2. Permissions に pages_show_list, pages_read_engagement, pages_manage_posts,")
    print("     instagram_basic, instagram_content_publish を追加")
    print("  3. Generate Access Token → ポップアップで自分の Page / IG を承認\n")

    app_id = ask("App A の App ID")
    app_secret = ask("App A の App Secret")
    short_token = ask("Graph API Explorer で生成した short-lived token")
    if not (app_id and app_secret and short_token):
        die("App ID / Secret / token は必須です")

    # 1. 60日 user token に交換
    d = get_json(f"{GRAPH}/oauth/access_token", {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }, "fb_exchange_token")
    long_user_token = d["access_token"]
    print("✅ 60日 user token に交換完了")

    # 2. 無期限 Page トークン取得 (token は Bearer ヘッダで送る)
    d = get_json(f"{GRAPH}/me/accounts",
                 {"fields": "id,name,access_token"},
                 "/me/accounts", token=long_user_token)
    pages = d.get("data", [])
    if not pages:
        die("管理している Page が見つかりません。Page 作成 + token 承認時に Page を選択したか確認")
    if len(pages) == 1:
        page = pages[0]
    else:
        print("管理 Page 一覧:")
        for i, p in enumerate(pages):
            print(f"  [{i}] {p['name']} (id={p['id']})")
        page = pages[int(ask("使用する Page の番号", "0"))]
    print(f"✅ Page: {page['name']} (id={page['id']}) — このトークンは無期限")

    # 3. IG user id 導出
    d = get_json(f"{GRAPH}/{page['id']}",
                 {"fields": "instagram_business_account{id,username}"},
                 "instagram_business_account", token=page["access_token"])
    ig = d.get("instagram_business_account")
    if not ig:
        print("⚠️ この Page に Instagram プロアカウントが連携されていません!")
        print("   → IG アプリ: 設定 → アカウントセンター等で Page と連携 → 本スクリプト再実行")
        print("   (今回は IG 無しで保存します。facebook のみ投稿可能)")
    else:
        print(f"✅ Instagram: @{ig.get('username')} (ig_user_id={ig['id']})")

    out = {
        "account_id": account_id,
        "app_id": app_id,
        "fb": {
            "page_id": page["id"],
            "page_name": page["name"],
            "page_access_token": page["access_token"],
            "acquired_at": datetime.now(JST).isoformat(),
        },
    }
    if ig:
        out["ig"] = {"ig_user_id": ig["id"], "username": ig.get("username")}
    return out


# ---------------------------------------------------------------------------
# App B: Threads
# ---------------------------------------------------------------------------

def authorize_threads(account_id: str) -> dict:
    print("\n=== [App B] Threads ===")
    threads_app_id = ask("App B の Threads App ID (⚠️ Basic Settings の App ID とは別物。"
                         "Use cases → Customize → Settings で確認)")
    threads_app_secret = ask("App B の Threads App Secret")
    redirect_uri = ask("App B に登録した Redirect Callback URL", "https://localhost/callback")
    if not (threads_app_id and threads_app_secret):
        die("Threads App ID / Secret は必須です")

    auth_url = (
        "https://threads.net/oauth/authorize"
        f"?client_id={threads_app_id}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        "&scope=threads_basic,threads_content_publish,threads_delete"
        "&response_type=code"
    )
    print("\n以下の URL をブラウザで開いて承認してください")
    print("(エラーになる場合: Threads Tester 招待を Threads アプリ内で承認済みか確認):\n")
    print(f"  {auth_url}\n")
    print("承認後にリダイレクトされた URL (https://localhost/callback?code=... — エラー画面でOK)")
    redirected = ask("をそのまま貼り付け")

    # URL でも code 単体でも受ける。末尾の #_ は Meta 仕様のゴミなので除去
    code = redirected
    if "code=" in redirected:
        code = parse_qs(urlparse(redirected).query).get("code", [""])[0]
    code = code.split("#")[0].strip()
    if not code:
        die("code が取得できませんでした")

    # 1. code → short-lived token
    d = post_json(f"{THREADS_GRAPH}/oauth/access_token", {
        "client_id": threads_app_id,
        "client_secret": threads_app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }, "Threads code 交換")
    short_token = d["access_token"]
    print("✅ short-lived token 取得")

    # 2. 60日トークンに交換
    d = get_json(f"{THREADS_GRAPH}/access_token", {
        "grant_type": "th_exchange_token",
        "client_secret": threads_app_secret,
        "access_token": short_token,
    }, "th_exchange_token")
    long_token = d["access_token"]
    expires_in = int(d.get("expires_in", 60 * 24 * 3600))
    now = datetime.now(JST)
    print(f"✅ 60日トークン取得 (expires_in={expires_in}s)")

    # 3. ユーザー確認
    d = get_json(f"{THREADS_GRAPH}/v1.0/me",
                 {"fields": "id,username"}, "/me", token=long_token)
    print(f"✅ Threads: @{d.get('username')} (user_id={d['id']})")

    return {
        "account_id": account_id,
        "threads_app_id": threads_app_id,
        "user_id": d["id"],
        "username": d.get("username"),
        "access_token": long_token,
        "refreshed_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Meta トークン採取 (対話式)")
    parser.add_argument("--account-id", required=True, help="例: kakumei_ikka")
    parser.add_argument("--skip-fb", action="store_true", help="FB/IG セクションを skip")
    parser.add_argument("--skip-threads", action="store_true", help="Threads セクションを skip")
    args = parser.parse_args()

    # GHA secret 名 (META_TOKEN_<ID> / THREADS_TOKEN_<ID>) にファイル名が round-trip するため
    # charset を制限する (ハイフン/大文字が混ざると refresh の secret 書き戻しが壊れる)
    if not re.fullmatch(r"[a-z0-9_]+", args.account_id):
        die(f"--account-id は [a-z0-9_] のみ使用可: {args.account_id!r}")

    meta_path = os.path.join(META_TOKENS_DIR, f"{args.account_id}.json")
    threads_path = os.path.join(THREADS_TOKENS_DIR, f"{args.account_id}.json")

    if not args.skip_fb:
        data = load_existing(meta_path)
        data.update(authorize_fb_ig(args.account_id))
        write_token(meta_path, data)

    if not args.skip_threads:
        data = load_existing(threads_path)
        data.update(authorize_threads(args.account_id))
        write_token(threads_path, data)

    uid = args.account_id.upper()
    print("\n=== 次のステップ ===")
    print("# 1. 動作確認 (read のみ)")
    if not args.skip_fb:
        print(f"python3 external_skills/meta-uploader/scripts/upload.py --verify --platform facebook  --token {os.path.relpath(meta_path, ROOT)}")
        print(f"python3 external_skills/meta-uploader/scripts/upload.py --verify --platform instagram --token {os.path.relpath(meta_path, ROOT)}")
    if not args.skip_threads:
        print(f"python3 external_skills/meta-uploader/scripts/upload.py --verify --platform threads   --token {os.path.relpath(threads_path, ROOT)}")
    print("# 2. GHA Secret 登録")
    if not args.skip_fb:
        print(f"gh secret set META_TOKEN_{uid} < {os.path.relpath(meta_path, ROOT)}")
    if not args.skip_threads:
        print(f"gh secret set THREADS_TOKEN_{uid} < {os.path.relpath(threads_path, ROOT)}")
    print("# 3. publishing/meta_accounts.yaml に台帳エントリ追記 (テンプレは同ファイル参照)")


if __name__ == "__main__":
    main()
