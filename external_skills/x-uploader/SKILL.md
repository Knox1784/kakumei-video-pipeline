# x-uploader — X (Twitter) ショート動画アップローダー

YouTube 自動投稿 (youtube-uploader) のクロスポスト先として、X に動画+本文を投稿する。
youtube-uploader と同じ CLI 契約: subprocess 起動、stdout 末尾に結果 JSON ブロック。

## 役割分担

- **GHA 自動投稿** (本番): `publishing/scripts/dispatch_queue.py` が YouTube 投稿成功後に
  本スクリプトを subprocess で呼ぶ。トークンは GHA Secret `X_TOKEN_<ID>` から復元される
- **手動/テスト**: ローカルから直接 CLI 実行

## CLI

```bash
# 認証テスト (read のみ。pay-per-use 課金最小)
python3 scripts/upload.py --verify --token publishing/tokens/x/kakumei_ikka.json

# 動画投稿
python3 scripts/upload.py \
  --video path/to/short_final.mp4 \
  --text "ツイート本文" \
  --token publishing/tokens/x/kakumei_ikka.json

# 投稿の削除 (テスト掃除用)
python3 scripts/upload.py --delete <TWEET_ID> --token publishing/tokens/x/kakumei_ikka.json
```

成功時の stdout 末尾 JSON: `{tweet_id, url, text, limits}` (limits = 残量ヘッダ)。

## 認証 — OAuth 1.0a user context

トークン JSON (`publishing/tokens/x/{account_id}.json`、gitignored):

```json
{
  "api_key": "...", "api_key_secret": "...",
  "access_token": "...", "access_token_secret": "..."
}
```

- 4キーは**無期限・ローテーション無し** (OAuth 2.0 PKCE の refresh ローテーションは
  ステートレス CI で token 喪失事故の元なので不採用)
- キー取得: developer.x.com → アプリ → **権限を Read and Write に設定 → その後に**
  Access Token & Secret を生成 (順序を逆にすると Read-only トークン → 投稿 403)
- アカウント台帳: `publishing/x_accounts.yaml`

## 技術仕様 (2026-06 時点)

| 項目 | 値 |
|---|---|
| media upload | **専用パス形式** (2026-06 実機確認済): `POST /2/media/upload/initialize` (JSON) → `POST /2/media/upload/{id}/append` (multipart) → `POST /2/media/upload/{id}/finalize` → `GET /2/media/upload?media_id=` poll。旧 command=INIT 形式は廃止済 (`/2/media/upload` は画像/字幕専用化) |
| 投稿 | `POST /2/tweets` `{"text", "media": {"media_ids": [...]}}` |
| 動画上限 | 0.5〜140s / ≤512MB / 解像度 32x32〜**1280x1024** (長辺1280) |
| 自動縮小 | 上限超過時 ffmpeg で縮小 (1080x1920 → 720x1280)。非 Premium 再生上限は 720p なので画質ロス実質ゼロ |
| 本文 | weighted 280 (CJK・絵文字=2 → **日本語実質140字**)。超過は `…` 自動切詰め |
| 課金 | pay-per-use ~$0.015/投稿。**URL 入り本文は $0.20 (13倍) → 使わない** |
| 安全装置 | STATUS poll hard deadline 240s / per-request timeout 30s / 5xx 指数バックオフ |

## エラー対応 (詳細は publishing/AUTO_POST_RULES.md の X ランブック)

- **401** → キー無効。Console で再生成 → token JSON 更新 → `gh secret set`
- **403** → ①アプリ権限 Read-only ②権限変更後にトークン未再生成 ③クレジット残高ゼロ
- **429** → 24h レートキャップ。翌日自然回復

## ポリシー上の大原則

- 自アカウント自作コンテンツの自動投稿は X Automation Rules で明示的に許可
- 🚫 **複数アカウントへの同一/類似コンテンツ投稿は禁止** (platform manipulation)。
  X 展開は革命一家 1 アカ (@kakumei1784) のみ。100 アカ構想は X に適用しない
- ハッシュタグは 2 個以下。テスト投稿も課金されるため検証は `--verify` を優先
