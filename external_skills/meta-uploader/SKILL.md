# meta-uploader — Meta (Facebook Page Reels / Instagram Reels / Threads) アップローダー

YouTube 自動投稿 (youtube-uploader) のクロスポスト先として、Meta 3プラットフォームに動画+本文を投稿する。
youtube-uploader / x-uploader と同じ CLI 契約: subprocess 起動、stdout 末尾に結果 JSON ブロック。

**1 skill = 3 platform** の理由: FB と IG は同一 App・同一の無期限 Page トークンで投稿する (技術的に同じもの)。
Threads だけ別 App・別トークンだが、台帳・失敗処理・ポリシーが Meta ファミリーで共通のため同居。
**投稿先の個別制御は meta.json の `fb_enabled` / `ig_enabled` / `threads_enabled` で行う** (skill 構成とは無関係)。

## 役割分担

- **GHA 自動投稿** (本番): `publishing/scripts/dispatch_queue.py` の `post_to_meta()` が YouTube 投稿成功後に
  本スクリプトを platform 毎に subprocess で呼ぶ。トークンは GHA Secret `META_TOKEN_<ID>` / `THREADS_TOKEN_<ID>` から復元
- **手動/テスト**: ローカルから直接 CLI 実行

## CLI

```bash
# 認証テスト (read のみ・投稿しない)
python3 scripts/upload.py --verify --platform facebook  --token publishing/tokens/meta/kakumei_ikka.json
python3 scripts/upload.py --verify --platform instagram --token publishing/tokens/meta/kakumei_ikka.json
python3 scripts/upload.py --verify --platform threads   --token publishing/tokens/threads/kakumei_ikka.json

# 投稿 (facebook / instagram はバイナリ直アップロード)
python3 scripts/upload.py --platform facebook  --video short.mp4 --text "説明文" --token publishing/tokens/meta/kakumei_ikka.json
python3 scripts/upload.py --platform instagram --video short.mp4 --text "キャプション" --token publishing/tokens/meta/kakumei_ikka.json

# Threads (⚠️ バイナリ不可 — 公開 URL 必須。GHA では SHA 固定 raw URL が自動で渡る)
python3 scripts/upload.py --platform threads --video-url "https://raw.githubusercontent.com/.../short.mp4" \
  --text "本文" --token publishing/tokens/threads/kakumei_ikka.json

# テスト投稿の削除 (facebook / threads のみ。Instagram は API 削除不可 → アプリから手動)
python3 scripts/upload.py --delete <POST_ID> --platform facebook --token ...
```

成功時の stdout 末尾 JSON: `{platform, url, text, ...}` (+ fb: `video_id`/`status`, ig: `media_id`/`permalink`, threads: `post_id`/`permalink`)。

## 認証 — 2 App 構成 (公式制約: Threads use case は Facebook Login と非互換)

| | App A (Business type) | App B (Threads use case) |
|---|---|---|
| 対象 | Facebook Page + Instagram | Threads |
| トークン | **無期限 Page トークン1本** | 60日トークン (**自動 refresh 必須**) |
| ファイル | `publishing/tokens/meta/{id}.json` | `publishing/tokens/threads/{id}.json` |
| GHA Secret | `META_TOKEN_<ID>` (書込み一度きり) | `THREADS_TOKEN_<ID>` (refresh が自動書換え) |

- トークン採取: `scripts/authorize.py --account-id <id>` (対話式・Graph API Explorer の short token を貼るだけ)
- Threads refresh: `scripts/refresh_threads_token.py` (auto_post.yml が毎 run 実行、7日超で自動更新)
- アカウント台帳: `publishing/meta_accounts.yaml`
- ⚠️ 「無期限」Page トークンもパスワード変更/2FA変更/セキュリティイベント/app secret ローテで失効する → `--verify` で確認、authorize.py 再実行で復旧 (2分)

## 技術仕様 (2026-06 時点・公式 docs 確認済)

| 項目 | Facebook | Instagram | Threads |
|---|---|---|---|
| エンドポイント | `/{page}/video_reels` 3-phase + rupload バイナリ | `/{ig-user}/media?upload_type=resumable` + rupload → `media_publish` | `/{user}/threads` (video_url) → `threads_publish` |
| 動画上限 | 9:16, **3〜90s**, 24-60fps | 9:16, 3s〜15min, ≤300MB, **音声≤128kbps** | 9:16, ≤300s, ≤1GB |
| 本文 | description (制限緩) | caption ≤2,200字 (自動切詰め) | text ≤**500字** (自動切詰め) |
| レート | **30投稿/24h/Page** | 100/24h | 250/24h |
| 動画の渡し方 | バイナリ直 | バイナリ直 | **公開 URL のみ** (Meta が cURL fetch) |

- preflight: ffprobe で検査、音声 >128kbps なら音声のみ再エンコード (映像 copy)。
  ⚠️ Threads は committed bytes を fetch するため preflight では直せない → **queue 配置時に
  `publishing/scripts/prepare_queue_clip.py` で正規化するのが本質対応** (これは安全網)
- **トークンは絶対に URL クエリに入れない** (Authorization ヘッダのみ) + 全出力スクラバー
  — repo/Issue が public のため。スクラバーは `EAA...`/`TH...`/`access_token=` を `***TOKEN***` に置換
- 安全装置: per-request timeout 30s / 5xx 指数バックオフ / poll hard deadline /
  FB は finish 受理済みなら処理未完でも成功扱い (`"status":"processing"`) /
  IG の 9004/2207052 は新コンテナで1回だけ再試行

## エラー対応 (詳細は publishing/AUTO_POST_RULES.md の Meta ランブック)

- **190** → トークン失効 (パスワード変更等)。authorize.py 再実行 → `gh secret set`
- **200 / 10** → scope 不足。Graph API Explorer で必要 scope を付けて再取得
- **9004 / 2207052** → メディア fetch/処理失敗。Threads は repo public + SHA URL 確認、IG は自動再試行済み
- **2207026** → 動画スペック違反 (音声 >128kbps 等)。prepare_queue_clip.py 経由か確認
- **4 / 17 / 32 / 613 / 2207042** → レート上限。24h 自然回復

## ポリシー上の大原則

- ✅ 自アカウント自作コンテンツの無人 API 投稿は Meta 公式の本来用途
- ✅ **自ブランドの FB+IG+Threads 同一コンテンツ展開は公式に明示許可** (2025-07 Meta ポリシー:
  罰則対象は「他人の」コンテンツ転載。自分の Page/プロフィール間の使い回しは OK と明記)
- ✅ 自社ロゴ焼き込み OK (公式明言)。⚠️ **YouTube から再ダウンロードした動画は使わない** (必ずローカル/queueのマスター)
- 🚫 **Meta は各プラットフォーム1アカのみ** (FB Page / IG / Threads 各1)。複数アカへの同一/類似コンテンツ
  自動投稿は CIB (Coordinated Inauthentic Behavior) としてネットワーク一括BAN。**100アカ構想は Meta に持ち込まない** (X と同じ原則)
- テスト投稿は `--delete` で掃除 (IG のみ API 削除不可)。課金なし (Meta API は無料)
