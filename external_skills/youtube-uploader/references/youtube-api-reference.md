# YouTube Data API v3 リファレンス（Claude Code実行用）

> YouTube Data API v3公式ドキュメントから、Skill⑥で使う部分を抽出。
> 最終更新: 2026-04-15

---

## 1. インストール済み環境

| ツール | バージョン | 備考 |
|--------|-----------|------|
| google-api-python-client | 2.194.0 | YouTube APIクライアント |
| google-auth-oauthlib | 1.3.1 | OAuth 2.0認証フロー |
| google-auth-httplib2 | 0.3.1 | HTTP認証トランスポート |
| Python | 3.10.4 | |

### 認証ファイルの場所

| ファイル | パス | 説明 |
|---------|------|------|
| client_secret.json | `~/Downloads/clip-army/credentials/client_secret.json` | Google Cloud ConsoleからDL。変更不要 |
| トークンファイル | `~/Downloads/clip-army/tokens/{account_id}.json` | 初回認証時に自動生成。アカウントごとに1つ |

---

## 2. クォータ

| 項目 | 値 |
|------|-----|
| デフォルト日次クォータ | 10,000ユニット |
| videos.insert（アップロード） | 1,600ユニット/回 |
| videos.update（メタデータ更新） | 50ユニット/回 |
| videos.list（ステータス確認） | 1ユニット/回 |
| **1日のアップロード上限** | **約6本**（10,000 ÷ 1,600） |
| リセット時刻 | 毎日太平洋時間00:00（日本時間16:00 or 17:00） |

### クォータ増加申請

- フォーム: YouTube API Services - Audit and Quota Extension Form
- 無料。コンプライアンス監査が必要
- Phase 1（100アカウント×5本/日）には大幅な増加が必要

---

## 3. OAuth 2.0 認証

### 認証フロー（Desktop app）

```python
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import json, os

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET = os.path.expanduser("~/Downloads/clip-army/credentials/client_secret.json")

def get_credentials(token_path):
    """トークンファイルから認証情報を取得。期限切れなら自動リフレッシュ。"""
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # 初回: ブラウザが開いてユーザーが承認する
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # トークンを保存
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    
    return creds
```

### 重要な注意点

- **"Testing"状態**: リフレッシュトークンが7日で失効。"Production"にする必要あり
- **コンプライアンス監査未完了**: 全動画がprivateにロックされる
- **アクセストークン有効期限**: 約1時間。`creds.refresh(Request())`で自動更新

---

## 4. videos.insert（アップロード）

### 基本コマンド

```python
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

youtube = build("youtube", "v3", credentials=creds)

body = {
    "snippet": {
        "title": "タイトル（最大100文字）",
        "description": "説明文 #Shorts（最大5000文字）",
        "tags": ["tag1", "tag2"],
        "categoryId": "22",  # People & Blogs
    },
    "status": {
        "privacyStatus": "private",  # private / unlisted / public
        "selfDeclaredMadeForKids": False,
        "notifySubscribers": False,  # バルクアップロード時はFalse
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

response = request.execute()
video_id = response["id"]
```

### snippet パラメータ

| フィールド | 最大長 | 必須 | 説明 |
|-----------|--------|------|------|
| title | 100文字 | Yes | タイトル。`#Shorts`を含める |
| description | 5000文字 | No | 説明文。`#Shorts`を含める |
| tags | — | No | 関連キーワードのリスト |
| categoryId | — | No | カテゴリ。`"22"`=People & Blogs |

### status パラメータ

| フィールド | 値 | 説明 |
|-----------|-----|------|
| privacyStatus | "private" / "unlisted" / "public" | 公開状態 |
| selfDeclaredMadeForKids | False | COPPA準拠。子供向けでなければFalse |
| notifySubscribers | False | バルクアップロード時はFalse必須 |
| publishAt | ISO 8601 | 予約公開（privacyStatus="private"時のみ） |

---

## 5. Resumable Upload（中断再開）

```python
import time
from googleapiclient.errors import HttpError

def resumable_upload(request, max_retries=5):
    """指数バックオフ付きresumable upload"""
    response = None
    retry = 0
    
    while response is None:
        try:
            status, response = request.next_chunk()
            if response:
                return response  # アップロード完了
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retry += 1
                if retry > max_retries:
                    raise
                wait = 2 ** retry
                print(f"サーバーエラー。{wait}秒後にリトライ...")
                time.sleep(wait)
            elif e.resp.status == 403:
                raise Exception("クォータ超過。明日リトライしてください")
            elif e.resp.status == 401:
                raise Exception("認証エラー。トークンを再取得してください")
            else:
                raise
    
    return response
```

---

## 6. Shorts固有の要件

| 項目 | 要件 |
|------|------|
| 専用API | なし。通常のvideos.insertを使う |
| 自動判定条件 | 9:16アスペクト比 + 3分以内 |
| `#Shorts` | タイトルと説明に含める（推奨。判定を助ける） |
| サムネイル | 手動設定不可。YouTube自動生成 |
| 推奨解像度 | 1080×1920, 30fps, MP4 H.264 |
| 最適な長さ | 15〜60秒 |

---

## 7. アップロード後の確認

```python
def check_video_status(youtube, video_id):
    """アップロード後の処理状態を確認"""
    response = youtube.videos().list(
        part="status,processingDetails",
        id=video_id
    ).execute()
    
    if response["items"]:
        item = response["items"][0]
        return {
            "uploadStatus": item["status"]["uploadStatus"],
            "privacyStatus": item["status"]["privacyStatus"],
            # processingDetailsはオーナーのみアクセス可
        }
    return None
```

### uploadStatus の値

| 値 | 意味 |
|----|------|
| uploaded | アップロード済み（処理中） |
| processed | 処理完了（視聴可能） |
| failed | 処理失敗 |
| rejected | 拒否（ポリシー違反等） |
| deleted | 削除済み |

---

## 8. マルチアカウント管理

### トークンファイル構造

```
~/Downloads/clip-army/tokens/
├── default.json          メインアカウント
├── account_001.json      サブアカウント1
├── account_002.json      サブアカウント2
└── ...
```

各ファイルの中身:
```json
{
  "token": "ya29...",
  "refresh_token": "1//...",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "165534952501-...",
  "client_secret": "...",
  "scopes": ["https://www.googleapis.com/auth/youtube.upload"]
}
```

### 初回認証手順（アカウントごとに1回）

```bash
python3 ~/.claude/skills/youtube-uploader/scripts/upload.py \
  --authorize \
  --token ~/Downloads/clip-army/tokens/account_001.json
```
→ ブラウザが開く → Googleアカウントで承認 → token.jsonが生成される

### アップロード間の遅延

```python
import random, time
time.sleep(random.uniform(60, 300))  # 1〜5分のランダム遅延
```

---

## 9. やってはいけないこと

1. **クォータ回避のために複数Google Cloudプロジェクトを作らない**: ToS違反 → API停止
2. **`notifySubscribers=True`でバルクアップロードしない**: 登録者にスパム → チャンネル評価低下
3. **トークンをコードにハードコードしない**: credentials/tokens/はgitignore対象
4. **同じ動画を複数チャンネルにアップロードしない**: YouTube重複検出 → フラグ
5. **コンプライアンス監査なしでpublicアップロードしない**: privateにロックされる
6. **テスト時にpublicでアップロードしない**: 必ずprivateで動作確認してから
7. **遅延なしで連続アップロードしない**: 不自然な行動パターン → フラグ
