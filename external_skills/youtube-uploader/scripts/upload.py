#!/usr/bin/env python3
"""
Skill⑥ YouTube Shorts アップローダー

使用例:
  # 初回認証（ブラウザが開く）
  python3 upload.py --authorize --token ~/Downloads/clip-army/tokens/default.json

  # アップロード（private）
  python3 upload.py \
    --video ~/Downloads/clip-army/shorts/lbi4wzfAYh8_short1.mp4 \
    --title "Roy Lee Method #Shorts" \
    --description "The Roy Lee Method explained #Shorts" \
    --tags "business,startup,shorts" \
    --privacy private \
    --token ~/Downloads/clip-army/tokens/default.json

  # アップロード（public）
  python3 upload.py \
    --video ~/Downloads/clip-army/shorts/lbi4wzfAYh8_short1.mp4 \
    --title "Roy Lee Method #Shorts" \
    --privacy public \
    --token ~/Downloads/clip-army/tokens/default.json
"""
import argparse
import json
import os
import sys
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CLIENT_SECRET = os.path.expanduser(
    "~/Downloads/clip-army/credentials/client_secret.json"
)
DEFAULT_TOKEN = os.path.expanduser("~/Downloads/clip-army/tokens/default.json")


def get_credentials(token_path):
    """トークンファイルから認証情報を取得。期限切れなら自動リフレッシュ。"""
    creds = None
    token_path = os.path.expanduser(token_path)

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("トークンをリフレッシュ中...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET):
                print(
                    f"Error: client_secret.jsonが見つかりません: {CLIENT_SECRET}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print("ブラウザで認証してください...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)

        # トークンを保存
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print(f"トークンを保存しました: {token_path}")

    return creds


def upload_video(youtube, video_path, title, description, tags, privacy):
    """動画をYouTubeにアップロードする（resumable upload）"""
    body = {
        "snippet": {
            "title": title[:100],  # 最大100文字
            "description": description[:5000],  # 最大5000文字
            "tags": tags,
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=-1,  # 一括アップロード（Shortsは小さいので最速）
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=False,
    )

    return resumable_upload(request)


def resumable_upload(request, max_retries=5):
    """指数バックオフ付きresumable upload"""
    response = None
    retry = 0

    while response is None:
        try:
            print("アップロード中...")
            status, response = request.next_chunk()
            if response:
                video_id = response["id"]
                print(f"アップロード完了: https://youtube.com/shorts/{video_id}")
                return response
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retry += 1
                if retry > max_retries:
                    raise
                wait = 2**retry
                print(f"サーバーエラー({e.resp.status})。{wait}秒後にリトライ...")
                time.sleep(wait)
            elif e.resp.status == 403:
                error_reason = ""
                try:
                    error_reason = json.loads(e.content)["error"]["errors"][0]["reason"]
                except Exception:
                    pass
                if error_reason == "quotaExceeded":
                    print(
                        "Error: クォータ超過。太平洋時間0:00（日本時間16:00-17:00）にリセットされます",
                        file=sys.stderr,
                    )
                else:
                    print(f"Error: 403 Forbidden - {error_reason}", file=sys.stderr)
                sys.exit(1)
            elif e.resp.status == 401:
                print(
                    "Error: 認証エラー。トークンを再取得してください（--authorize）",
                    file=sys.stderr,
                )
                sys.exit(1)
            else:
                raise

    return response


def main():
    parser = argparse.ArgumentParser(description="YouTube Shorts アップローダー")
    parser.add_argument("--authorize", action="store_true", help="認証のみ実行（トークン生成）")
    parser.add_argument("--video", help="アップロードするMP4ファイルパス")
    parser.add_argument("--title", default="", help="タイトル（最大100文字）")
    parser.add_argument("--description", default="", help="説明文（最大5000文字）")
    parser.add_argument("--tags", default="", help="カンマ区切りのタグ")
    parser.add_argument(
        "--privacy",
        default="private",
        choices=["private", "unlisted", "public"],
        help="公開状態（デフォルト: private）",
    )
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="トークンファイルパス")
    args = parser.parse_args()

    # 認証
    creds = get_credentials(args.token)

    if args.authorize:
        print("認証完了。トークンが保存されました。")
        sys.exit(0)

    # アップロード
    if not args.video:
        print("Error: --video でアップロードするファイルを指定してください", file=sys.stderr)
        sys.exit(1)

    video_path = os.path.expanduser(args.video)
    if not os.path.isfile(video_path):
        print(f"Error: ファイルが見つかりません: {video_path}", file=sys.stderr)
        sys.exit(1)

    youtube = build("youtube", "v3", credentials=creds)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    response = upload_video(
        youtube=youtube,
        video_path=video_path,
        title=args.title,
        description=args.description,
        tags=tags,
        privacy=args.privacy,
    )

    # 結果をJSON出力
    result = {
        "video_id": response["id"],
        "url": f"https://youtube.com/shorts/{response['id']}",
        "title": response["snippet"]["title"],
        "privacy": response["status"]["privacyStatus"],
        "channel": response["snippet"].get("channelTitle", ""),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
