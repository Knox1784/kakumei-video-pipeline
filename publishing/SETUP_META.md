# Meta (FB/IG/Threads) クロスポスト セットアップ手順 (Phase 0)

コードは導入済み・**トークンが無い限り何も起きない** (silent skip)。
この手順を上から実施すると FB Page Reels / Instagram Reels / Threads への自動クロスポストが有効になる。
所要: アカウント作成 ~30分 + App/トークン ~30分 + ライブテスト ~30分。

> 進め方の推奨: **FB+IG を先に有効化 → 数日安定を確認 → Threads を有効化**。
> (Threads は 60日トークン+PAT+URL fetch と可動部が多く、リスクの大半がここに集中)

---

## Step 1 — アカウント作成 (Meta 側)

- [ ] **Facebook Page 作成**: facebook.com (個人アカウントでログイン) → メニュー → ページ → 作成。
      名前: 革命一家。作成後、ページの「概要」等から **Page ID を控える** (数字)
- [ ] **Instagram アカウント作成** → 設定 → アカウントの種類とツール → **プロアカウントに切替** (クリエイター or ビジネス)
- [ ] **IG を FB Page に連携**: IG 設定 → アカウントセンター → アカウント追加で FB を接続後、
      FB Page 設定 → リンク済みのアカウント → Instagram → アカウントをリンク
      (⚠️ これが無いと API から IG に投稿できない。authorize.py が検出して警告する)
- [ ] **Threads アカウント作成**: Threads アプリで IG アカウントからログイン

## Step 2 — Meta App 作成 (developers.facebook.com)

- [ ] developer 登録: developers.facebook.com → スタート (個人 FB アカウントで可。Business 認証不要)
- [ ] **App A 作成** (FB+IG 用): My Apps → Create App →
      use case 「**その他 (Other)**」 → タイプ「**ビジネス (Business)**」 → 名前例 `kakumei-fbig-autopost`
      - ⚠️ Business タイプは Dev/Live モード切替が無い (Standard Access で動く)。**公開申請・審査は一切不要**
- [ ] **App B 作成** (Threads 用): Create App → use case 「**Access the Threads API**」
      - ⚠️ App A に追加しようとしても Facebook Login 系 use case と非互換で不可。**必ず別 App**
      - App roles → Roles → **Threads Tester** に自分の Threads アカウントを追加
      - **Threads アプリ内で承認**: 設定 → アカウント → Webサイトのアクセス許可 → 招待を承認
      - Use cases → Customize → Settings で **Threads App ID / Threads App Secret** を控える
        (⚠️ Basic Settings の App ID とは**別物**。OAuth はこちらを使う)
      - Redirect Callback URL に `https://localhost/callback` を登録
        (Uninstall/Delete Callback URL も同じ値で埋めてよい)

## Step 3 — トークン採取 (ホスティング不要・対話式)

- [ ] **App A の short-lived token**: [Graph API Explorer](https://developers.facebook.com/tools/explorer/) →
      アプリ = App A を選択 → Permissions に以下を追加 → **Generate Access Token** → ポップアップで Page/IG を承認
      ```
      pages_show_list, pages_read_engagement, pages_manage_posts,
      instagram_basic, instagram_content_publish
      ```
- [ ] **authorize.py 実行** (短命トークンを貼るだけで全部やる):
      ```bash
      python3 external_skills/meta-uploader/scripts/authorize.py --account-id kakumei_ikka
      ```
      → 60日交換 → **無期限 Page token** 取得 → IG user id 導出 → Threads 認可 (ブラウザ承認 → リダイレクト URL 貼付け)
      → `publishing/tokens/meta/kakumei_ikka.json` + `publishing/tokens/threads/kakumei_ikka.json` 生成
- [ ] **verify** (read のみ・投稿しない):
      ```bash
      python3 external_skills/meta-uploader/scripts/upload.py --verify --platform facebook  --token publishing/tokens/meta/kakumei_ikka.json
      python3 external_skills/meta-uploader/scripts/upload.py --verify --platform instagram --token publishing/tokens/meta/kakumei_ikka.json
      python3 external_skills/meta-uploader/scripts/upload.py --verify --platform threads   --token publishing/tokens/threads/kakumei_ikka.json
      ```

## Step 4 — 🚨 配線前の必須ライブテスト

> **このステップが最重要。** 2つの未検証リスクを本番前に潰す。

- [ ] **(a) Threads × raw URL テスト** — Meta の fetcher が raw.githubusercontent.com
      (Content-Type: application/octet-stream) を受けるかは公式に未保証:
      ```bash
      # commit 済み queue クリップの SHA 固定 URL でテスト投稿
      SHA=$(git rev-parse origin/main)
      python3 external_skills/meta-uploader/scripts/upload.py --platform threads \
        --video-url "https://raw.githubusercontent.com/Knox1784/kakumei-video-pipeline/${SHA}/publishing/queue/10_KANKYO_KAERO/short.mp4" \
        --text "接続テスト (すぐ消します)" \
        --token publishing/tokens/threads/kakumei_ikka.json
      # 成功 → --delete <POST_ID> で削除
      ```
      - ✅ 成功 → そのまま運用 (dispatcher は自動で SHA URL を組み立てる)
      - ❌ `FAILED_DOWNLOADING_VIDEO` → **GitHub Pages を有効化** (repo Settings → Pages → main / root) し、
        `dispatch_queue.py` の `_threads_video_url()` を `https://knox1784.github.io/kakumei-video-pipeline/...` に差替え
        (Pages はビルド遅延が数分あるため「queue は投稿の数時間前までに push」運用 — 現状の運用で既に満たしている)
- [ ] **(b) FB 手動テスト投稿** → 投稿が**ログアウト状態 (シークレットウィンドウ)** でも見えるか確認 → `--delete` で削除
- [ ] **(c) IG 手動テスト投稿** → 同様に公開確認 → IG は API 削除不可のため**アプリから手動削除**
- [ ] **(d) Page token 無期限確認**: `--verify --platform facebook` が通れば実質OK
      (厳密には Graph API Explorer の Debug ツールで expires_at=never を確認)

## Step 5 — GHA Secrets 登録 (自動投稿の有効化スイッチ)

> Secrets を入れた瞬間から次のスロットで自動クロスポストが始まる。FB+IG だけ先に入れる運用可。

- [ ] ```bash
      gh secret set META_TOKEN_KAKUMEI_IKKA    < publishing/tokens/meta/kakumei_ikka.json
      gh secret set THREADS_TOKEN_KAKUMEI_IKKA < publishing/tokens/threads/kakumei_ikka.json
      ```
- [ ] **PAT 作成** (Threads トークン自動 refresh 用):
      GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate:
      - Repository access: **Only select repositories → kakumei-video-pipeline**
      - Permissions → Repository permissions → **Secrets: Read and write**
      - Expiration: 1年 (⚠️ **期限日を meta_accounts.yaml の pat_expires とカレンダーに記入**)
      ```bash
      gh secret set GH_PAT_SECRETS   # ← 生成された github_pat_... を貼る
      ```
- [ ] **既存 queue の音声正規化** (IG 上限 128kbps 対応・1回だけ):
      ```bash
      python3 publishing/scripts/prepare_queue_clip.py --normalize-existing
      git add publishing/queue && git commit -m "chore: queue 音声を全プラットフォーム適合に正規化" && git push
      ```
- [ ] 台帳記入: `publishing/meta_accounts.yaml` の `<記入>` 箇所を埋める

## Step 6 — 本番確認

- [ ] スロット外 (昼間) に手動発火 → 「no active slot → skip」+ Restore/Refresh ステップが緑なら配管OK:
      ```bash
      gh workflow run auto_post.yml --repo Knox1784/kakumei-video-pipeline --ref main
      gh run watch $(gh run list --workflow=auto_post.yml --limit 1 --json databaseId -q '.[0].databaseId')
      ```
- [ ] 当日 22:00 の実投稿後: state JSON に `fb_post` / `ig_post` / `threads_post` が記録されているか確認:
      ```bash
      cat publishing/publishing-state/source-podcast/<clip_id>.json
      ```
- [ ] 各プラットフォームで実投稿を目視確認

## 今後の新クリップ配置 (変更点は1つだけ)

queue への配置を `prepare_queue_clip.py` 経由にする (音声正規化を自動適用):
```bash
python3 publishing/scripts/prepare_queue_clip.py \
  --src source-<ep>/edit/shorts_v2/<CLIP>/short_with_audio.mp4 --clip-id <CLIP>
# → meta.json を作成 → git add/commit/push (従来通り)
```

## トラブル時

→ `publishing/AUTO_POST_RULES.md` の「🚨 Meta 投稿が止まった時」ランブック参照。
