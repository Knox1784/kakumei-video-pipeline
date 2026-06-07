# YouTube 自動投稿システム (発射台モデル) + 障害対応ランブック

「queue に動画+meta を置けば、毎日決まった時刻に1本ずつ自動で public 投稿される」仕組み。
実行は **GitHub Actions**、定刻トリガは **Mac の launchd**（2026-06-02〜）。

> 📌 これは詳細運用 + 障害対応ドキュメント。要約は `CLAUDE.md` の「自動投稿」節。
> **🚨 投稿が止まったら → 下の「投稿が止まった時のランブック」へ直行。**

## アーキ (2段トリガ)

```
[毎日 22:00 / 23:00 JST]
  主トリガ : Mac launchd (com.kakumei.autopost)
             └ gh workflow run auto_post.yml   ← 定刻に GHA を叩くだけ
  予備トリガ: GHA schedule cron (各枠オフピーク分で3回冗長)
             └ Mac off の日のフォールバック (ベストエフォート)
        │
        ▼
  GitHub Actions: dispatch_queue.py
        ├ 現在スロット判定 (find_active_slot, ±60分窓, 過去スロット優先)
        ├ 同枠で既投稿なら skip (二重防止: posted_slot exact match)
        ├ queue 先頭(辞書順)を取得 (target_slot / not_before ゲート)
        ├ upload.py で YouTube に public 投稿
        └ publishing-state 生成 + queue dir 削除 + git push
        │
        ▼
  ローカル post-monitor (launchd, 翌朝 08:00) が publishing-state を自動対象化
```

**なぜ2段か**: GitHub Actions の `schedule`(cron) はベストエフォートで、遅延だけでなく **run ごと完全ドロップ**する（2026-06-01 に当日投稿ゼロを観測）。時刻が命なので、定刻に確実発火する **launchd を主**にし、実行(workflow_dispatch)だけ GHA に任せる（GHA の workflow_dispatch 実行自体は確実）。cron は Mac off 時の保険として残す。**二重投稿は dispatcher の投稿済み判定で防止**するので、両方が発火しても1本だけ投稿される。

## 投稿スロット (現状: 2枠)

| 時刻 (JST) | 用途 |
|---|---|
| **22:00** | 夜メイン (寝る前1stチェック) |
| **23:00** | 夜遅 (寝落ち前の最後の一本) |

- 1スロット = 最大1本、queue 空ならスキップ。
- **launchd が 22:00 / 23:00 ちょうどに発火** → 実投稿時刻も 22:00/23:00 ちょうどが正常な目印（遅延cronなら ~30分ずれる）。
- GHA 予備 cron は各枠を**オフピーク分で3回**: UTC `11/31/51 13 * * *`(22時台) / `11/31/51 14 * * *`(23時台)。
- `find_active_slot` が ±`slot_window_min`(60分) 窓で発火を吸収し、**過去スロット優先**。
- 履歴: 〜2026-05 は 07:30/12:00/19:00/21:00/22:00/23:00 の6枠。2026-05-20 に夜帯集中で 22:00/23:00 の2枠へ縮小。
- **スロット変更は3点同期**: `posting_schedule.yaml` の `slots` + `auto_post.yml` の cron + `com.kakumei.autopost.plist` の `StartCalendarInterval`。

## 動画を投稿する手順

1. `publishing/queue/{clip_id}/short.mp4` を配置
2. 同ディレクトリに `meta.json` 作成 (スキーマは `publishing/queue/README.md` 参照)
3. `git add publishing/queue/{clip_id}/ && git commit && git push`
4. 次のスロットで自動投稿される

**処理順 = ディレクトリ名昇順 (FIFO)**。先に出したい本は数字プレフィックスを小さく (`01_`, `02_`...)。

### target_slot / not_before でスケジュール指定

meta.json の optional フィールド:
- `target_slot`: `"22:00"` or `"23:00"` — そのスロット発火時のみ投稿（他枠では `🎯 ... → 次へ` で skip）。
- `not_before`: ISO8601（例 `"2026-06-08T22:00:00+09:00"`）— その時刻まで投稿しない（未来なら `⏰ ... → 次へ` で skip）。不正な形式は警告ログ + ゲート無視で投稿(fail-safe)。

両方未指定なら FIFO で最速スロット投稿。**複数日に分散**したい時は各 clip に「日付付き not_before + target_slot」を仕込んで一括 push すれば、GHA が毎日2本ずつ自動消化する（= 発射台モデル）。1日休んでも欠落せず1日スライドするだけ。

---

## 🐦 X (Twitter) クロスポスト (2026-06-06〜)

YouTube 投稿成功の直後、**同じ short.mp4 が X (@kakumei1784) にもネイティブ動画として自動投稿**される。

```
dispatch_queue.py:
  YouTube 投稿成功 → state 書込み
    → X クロスポスト (external_skills/x-uploader/scripts/upload.py)
        ├ 720x1280 に自動縮小 (X の解像度上限 = 長辺1280)
        ├ v2 chunked media upload → POST /2/tweets
        └ 成功/失敗を state JSON の x_post キーに記録
    → queue dir 削除 + git push
```

- **デフォルト全クリップ ON**。クリップ単位で止めるには meta.json に `"x_enabled": false`
- 本文 = meta.json `x_text`、無ければ title から `#Shorts` 除去 (日本語実質140字・自動切詰め)
- `privacy != "public"` のクリップは X には投稿しない (X に限定公開は無い)
- **X 失敗は YouTube 側に一切影響しない** (state 記録 + Issue `auto-post-failure-x` のみ。
  exit code を汚すと state 未push → YouTube 二重投稿になるため、構造的に exit 0 を維持)
- **X 失敗の自動リトライは無い** (queue は YouTube 成功時点で消化済み)。再投稿は手動 (下記ランブック)
- 認証 = OAuth 1.0a 4キー (無期限)。台帳: `publishing/x_accounts.yaml` / トークン: `publishing/tokens/x/`
- 課金 = **pay-per-use** (~$0.015/投稿、月60本≈$1-4)。自動チャージ ON ($1で$10補充)。
  **本文に URL を入れない** ($0.20/投稿 = 13倍課金 + リーチ低下)
- 🚫 **ポリシー大原則: X は革命一家1アカのみ**。複数アカへの同一/類似コンテンツ自動投稿は
  platform manipulation として禁止 (一斉BAN実績あり)。YouTube の 100 アカ構想は X に持ち込まない

### 🚨 X 投稿が止まった時 (ランブック)

> YouTube は投稿されているが X に出ていない / `auto-post-failure-x` Issue が来た時。

1. **Issue body のエラーを見る** → 401 / 403 / 429 / timeout で分岐:

| エラー | 原因 | 対処 |
|---|---|---|
| `401 認証エラー` | 4キー無効/失効 | Developer Console でキー再生成 → `publishing/tokens/x/kakumei_ikka.json` 更新 → `gh secret set X_TOKEN_KAKUMEI_IKKA < publishing/tokens/x/kakumei_ikka.json` |
| `403 Forbidden` | ①アプリ権限が Read-only ②権限変更後に Access Token 未再生成 ③クレジット残高ゼロ | ①② Console で Read and Write 確認 → **Access Token を再生成** → token/Secret 更新。③ Console → 請求書作成 → クレジット (自動チャージ確認) |
| `429 レート上限` | 24h キャップ到達 | 翌日自然回復。テスト投稿の撃ちすぎに注意 |
| `timeout` / `動画処理が...完了しません` | X 側の動画処理遅延 | 単発なら放置可 (次スロットは別クリップで正常化)。連発なら手動再投稿で再現確認 |
| `X token malformed (4キー欠落)` | Secret の中身が壊れている | ローカルの token JSON を `--verify` で確認してから `gh secret set` し直す |

2. **認証の生存確認** (read のみ・課金最小):
```bash
python3 external_skills/x-uploader/scripts/upload.py --verify \
  --token publishing/tokens/x/kakumei_ikka.json
```

3. **失敗したクリップの手動再投稿** (動画は YouTube に出ているので state JSON から特定):
```bash
# state の x_post.status=="failed" のクリップを探す
grep -l '"status": "failed"' publishing/publishing-state/source-podcast/*.json
# 動画は queue から消えているので Zone B の short_final.mp4 を使う
python3 external_skills/x-uploader/scripts/upload.py \
  --video <Zone B の short_final.mp4> --text "本文" \
  --token publishing/tokens/x/kakumei_ikka.json
# 成功したら state JSON の x_post を手で書き換え (tweet_id/url)
```

4. **連続失敗中の Issue は1本に集約**される (既存 open Issue に comment 追記)。直ったら Issue を close。

---

## 📘 Meta クロスポスト (FB Reels / IG Reels / Threads) (2026-06-06〜)

YouTube 投稿成功 + X クロスポストの直後、**同じ short.mp4 が Facebook Page (Reels)・
Instagram (Reels)・Threads (動画+本文) にも自動投稿**される。セットアップは `SETUP_META.md`。

```
dispatch_queue.py:
  YouTube 成功 → state 書込み → X クロスポスト
    → post_to_meta()  [platform 毎に独立・FB 失敗が IG/Threads を止めない]
        ├ facebook : meta-uploader (video_reels 3-phase + rupload バイナリ)
        ├ instagram: meta-uploader (resumable rupload バイナリ。9004系は新コンテナで1回再試行)
        └ threads  : meta-uploader (GITHUB_SHA 固定 raw URL を Meta が fetch)
    → 結果を state JSON の fb_post / ig_post / threads_post に一括追記
    → queue dir 削除 + git push
```

- **デフォルト全クリップ ON**。meta.json の `meta_enabled` (マスター) / `fb_enabled` / `ig_enabled` /
  `threads_enabled` で個別 OFF (スキーマは `publishing/queue/README.md`)
- 本文デフォルト = title から `#Shorts` 除去 (X と同じ)。IG のみ + tags 先頭5個のハッシュタグ
- **Meta 失敗は YouTube/X に一切影響しない** (X と同じ exit 0 死守構造。marker は
  `meta_failure.json` の failures[] 配列 → Issue label `auto-post-failure-meta` に集約・自動リトライ無し)
- **wall-clock deadline 720s**: Meta チェーン全体の上限。超過 platform は `skipped_deadline`
  記録 (job timeout kill による state 未push = 二重投稿を構造的に防ぐ)
- 認証 (2 App 構成・詳細は `meta_accounts.yaml`):
  - **App A** → `tokens/meta/{id}.json` = FB+IG 共用の**無期限 Page token** (Secret `META_TOKEN_<ID>`)
  - **App B** → `tokens/threads/{id}.json` = Threads **60日 token** (Secret `THREADS_TOKEN_<ID>`)。
    auto_post.yml が毎 run 鮮度チェック → 7日超で自動 refresh → `GH_PAT_SECRETS` で Secret 書き戻し
- 課金: Meta API は**無料**
- 🚫 **各プラットフォーム1アカのみ** (CIB 一括BAN リスク。X と同じ原則。100アカ構想は持ち込まない)
- 動画仕様の要: **音声 ≤128kbps** (IG 上限)。queue 配置は必ず `prepare_queue_clip.py` 経由

### 🚨 Meta 投稿が止まった時 (ランブック)

> YouTube/X は出ているが FB/IG/Threads に出ていない / `auto-post-failure-meta` Issue が来た時。
> Issue body の「失敗内訳」で **どの platform が何で失敗したか** が分かる。

| エラー | 原因 | 対処 |
|---|---|---|
| `190` トークン失効 | パスワード変更 / 2FA 変更 / セキュリティイベント (Page token) or 60日失効 (Threads) | `authorize.py --account-id <id>` 再実行 (片側だけなら `--skip-fb`/`--skip-threads`) → `gh secret set META_TOKEN_<ID>` / `THREADS_TOKEN_<ID>` |
| `200` / `10` 権限不足 | scope 不足・Page role 喪失 | Graph API Explorer で5 scope を付けて再採取 → authorize.py |
| `9004` / `FAILED_DOWNLOADING_VIDEO` (Threads) | raw URL が fetch 不能 (repo private 化 / GitHub 障害) | `gh repo view --json visibility` で public 確認。恒常的なら GitHub Pages 切替 (SETUP_META.md Step 4a) |
| `2207026` スペック違反 (IG) | 音声 >128kbps 等 | queue 配置が `prepare_queue_clip.py` 経由か確認。`--normalize-existing` で一括修正 |
| `4`/`17`/`32`/`613`/`2207042` rate limit | FB Reels 30/24h・IG 100/24h・Threads 250/24h | 1日2本運用では通常起きない。テスト撃ちすぎ確認 → 24h 自然回復 |
| `threads_token_refresh` 失敗 | refresh 失敗 or `GH_PAT_SECRETS` 未設定/期限切れ | PAT 再発行 (fine-grained・このrepo・Secrets: RW) → `gh secret set GH_PAT_SECRETS` → 手動更新: `python3 external_skills/meta-uploader/scripts/refresh_threads_token.py --token publishing/tokens/threads/<id>.json --force --update-gh-secret` |
| `token_restore` malformed | Secret の中身が壊れている | ローカル token JSON を `--verify` で確認 → `gh secret set` し直す |
| 🚨 「トークン年齢 50日超」警告 | refresh が止まって failing 状態が放置されている | **60日で完全失効 (再OAuth必須) になる前に** 上記 PAT 行の対処を即実施 |

**認証の生存確認** (read のみ・無料):
```bash
python3 external_skills/meta-uploader/scripts/upload.py --verify --platform facebook  --token publishing/tokens/meta/kakumei_ikka.json
python3 external_skills/meta-uploader/scripts/upload.py --verify --platform instagram --token publishing/tokens/meta/kakumei_ikka.json
python3 external_skills/meta-uploader/scripts/upload.py --verify --platform threads   --token publishing/tokens/threads/kakumei_ikka.json
```

**失敗したクリップの手動再投稿** (動画は queue から消えている):
```bash
# state の fb_post/ig_post/threads_post で "status": "failed" のクリップを探す
grep -l '"status": "failed"' publishing/publishing-state/source-podcast/*.json
# FB / IG: Zone B のマスター (short_with_audio.mp4) から再投稿
python3 external_skills/meta-uploader/scripts/upload.py --platform facebook \
  --video <Zone B の short_with_audio.mp4> --text "説明文" \
  --token publishing/tokens/meta/kakumei_ikka.json
# Threads: SHA 固定 URL は履歴上の blob として生き続けるためそのまま使える
#   (URL は GHA run ログ or 下記で再構築: 当時の commit SHA + clip_id)
python3 external_skills/meta-uploader/scripts/upload.py --platform threads \
  --video-url "https://raw.githubusercontent.com/Knox1784/kakumei-video-pipeline/<SHA>/publishing/queue/<clip_id>/short.mp4" \
  --text "本文" --token publishing/tokens/threads/kakumei_ikka.json
# 成功したら state JSON の該当キーを手で書き換え
```

**テスト投稿の掃除**: FB/Threads は `upload.py --delete <POST_ID> --platform ...`。**IG のみ API 削除不可** → アプリから手動。

---

## 🚨 投稿が止まった時のランブック

> 症状「YouTube に出ていない / queue が減らない」。上から順に。コマンドは全て読み取り専用（安全）。
> `<repo>` = `/Users/knoxv/Documents/Claude/Projects/video-use-test`

### Step 0 — 大前提: そもそも投稿時刻が来ているか
投稿は **夜2枠 (22:00 / 23:00 JST) のみ**。`TZ=Asia/Tokyo date` で今が 22:00 を過ぎているか確認。**まだなら正常**（待つだけ）。昼間に「投稿されてない」は当たり前。

### Step 1 — 事実確認 (3コマンド)
```bash
cd <repo> && git fetch -q origin
gh run list --workflow=auto_post.yml --limit 10                                 # 発火履歴
git ls-tree --name-only origin/main publishing/queue/                            # queue 残 (READMEのみ=補充切れ)
git ls-tree --name-only origin/main publishing/publishing-state/source-podcast/  # 投稿済み一覧 (直近を見る)
```

### Step 2 — 発火したか?
- **その時間帯(22時台/23時台)に `workflow_dispatch` run がある** → launchd は発火済み。出てないなら **Step 3**(dispatch側)。
- **`schedule` run しか無い / 大幅遅延** → launchd 不発、cron が拾った → **診断A**。
- **その時間帯に run が1つも無い** → 主・予備とも不発 → **診断A**（B は想定内）。

### Step 3 — run は走ったが投稿してない
`gh run view <id> --log | grep -iE "active slot|skip|uploaded|queue|not_before|FAILED"` で理由を見る:

| ログ | 意味 | 対処 |
|---|---|---|
| `no active slot at HH:MM` | 発火時刻がスロット窓(±60分)外 | launchd が定刻発火してるか(診断A)。cron が60分超遅延した時も出る。窓内に手動再投稿(下の緊急手動投稿) |
| `already posted within slot` | 同枠で既に投稿済み | **正常**(二重防止が働いた) |
| `queue empty → skip` | 補充切れ | 動画を補充 (build → queue → push) |
| `⏰ ... not_before ... 未到達` | meta の not_before が未来 | 日付/タイムゾーン確認。今出すなら not_before を過去に直して push |
| `❌ ... upload.py failed` / `invalid_grant` | YouTube token 失効 | **診断C** |

### 診断A — launchd トリガが動いていない
```bash
launchctl list | grep autopost                          # ロード状態 + 最終 exit code
cat ~/Library/Logs/com.kakumei.autopost.err.log          # エラー
```
| 症状 | 原因 | 対処 |
|---|---|---|
| `launchctl list` に出ない | 未ロード | 「セットアップ・再構築」節で再 bootstrap |
| exit **127** + err `can't open input file` | **TCC**: ~/Documents を launchd が読めない | plist が **gh 直起動**になっているか確認（シェルスクリプト経由はNG）。下の「セットアップ」節 |
| err に auth系 / `HTTP 401` / `gh: To get started` | gh 認証切れ/未認証 | **診断C の gh 部分** |
| exit 0 だが GHA に run が出ない | gh は動いたが dispatch 失敗 | repo名 / `--ref` 確認。手動 `gh workflow run ...` で再現確認 |
| その時間 Mac がスリープ/オフだった | 想定内 | 起床時に launchd が追いつく。完全オフの日は GHA cron 予備が拾う。頻発するなら外部トリガ化(スケール節) |

### 診断B — GHA cron が飛んだ
GHA `schedule` はベストエフォートで遅延/ドロップは**仕様**。launchd 主が前提なので cron 単独の不発は基本問題ない。**cron をいじるより launchd を直す**(診断A)。

### 診断C — token 失効
- **YouTube 投稿 token** (`invalid_grant` 等):
  ```bash
  python3 external_skills/youtube-uploader/scripts/upload.py --authorize \
    --token publishing/tokens/youtube/{account_id}.json
  cat publishing/tokens/youtube/{account_id}.json | pbcopy   # → GitHub Secret YT_TOKEN_<ID_UPPER> を Update
  ```
  (Testing OAuth status だと refresh token が7日で失効。Production 昇格で恒久化 → スケール節)
- **gh token** (launchd の gh が auth 失敗): `gh auth status` → `gh auth login` で再認証。確実にするなら plist の `EnvironmentVariables` に `GH_TOKEN`(= `gh auth token` の値) を入れて keychain 非依存にする。

### 失敗の自動通知
- GHA の job が失敗すると `auto-post-failure` ラベル付き **Issue が自動作成**される: https://github.com/Knox1784/kakumei-video-pipeline/issues
- Actions タブ: https://github.com/Knox1784/kakumei-video-pipeline/actions

---

## launchd トリガの確実なセットアップ・再構築

主トリガは launchd agent `com.kakumei.autopost`。**新しい Mac / 壊れた時の再構築**手順:

```bash
cd <repo>
# 1. plist を LaunchAgents へ (参照コピー = publishing/scripts/com.kakumei.autopost.plist)
cp publishing/scripts/com.kakumei.autopost.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/com.kakumei.autopost.plist     # → OK

# 2. ロード (再ロード時は bootout してから bootstrap)
launchctl bootout   gui/$(id -u)/com.kakumei.autopost 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kakumei.autopost.plist

# 3. 即時テスト発火 (スロット外でやれば skip = 安全に「連鎖だけ」確認できる)
launchctl kickstart -k gui/$(id -u)/com.kakumei.autopost

# 4. 検証
launchctl list | grep autopost                                              # → 左の数字が exit 0
gh run list --workflow=auto_post.yml --event=workflow_dispatch --limit 1     # → 直後に新 run
# その run の log が "no active slot → skip" (スロット外テスト時) かつ queue が減ってない = 正常
```

**⚠️ 設計上の必須ポイント (ハマりどころ)**:
- **plist は `gh` を直接起動する**。`ProgramArguments` = `/opt/homebrew/bin/gh`, `workflow`, `run`, `auto_post.yml`, `--repo`, `Knox1784/kakumei-video-pipeline`, `--ref`, `main`。**シェルスクリプト経由にしない** — `~/Documents` は macOS の TCC(プライバシー保護)で **launchd から読めず** `exit 127 / can't open input file` になる（最初これで失敗した）。
- **ログは `~/Library/Logs/`** に出す（`~/Documents` は同じ理由で書けない可能性）。
- **gh 認証**: keychain 利用（ユーザーが GUI ログイン中なら launchd からアクセス可）。ログインしていない時間帯にも確実に動かすなら、plist の `EnvironmentVariables` に `GH_TOKEN`(= `gh auth token` の出力) を入れて keychain 非依存にする。gh token には `workflow` スコープが必要。
- **タイムゾーン**: `StartCalendarInterval` は **Mac のローカル時刻**で発火。Mac が JST 前提（`date +%Z` で確認）。
- 予備の GHA cron / dispatcher は触らなくてよい（二重投稿は防止される）。

## 緊急手動投稿 (今すぐ1本出したい時)

**スロット窓(おおむね 21:00〜23:59 JST)内**なら手動トリガ可:
```bash
gh workflow run auto_post.yml --repo Knox1784/kakumei-video-pipeline --ref main
# or  publishing/scripts/run_dispatch_trigger.sh   (自分のシェルからの手動実行は TCC 無関係でOK)
```
→ queue 先頭の該当スロット clip が投稿される。**窓外(昼など)に撃つと `no active slot` で skip**（誤投稿しない安全側）。slot_window は 60分なので 21:00〜 / 22:00〜 が無難。

## 新アカウント追加手順 (Phase 100 拡張)

1. Google Cloud で OAuth トークン取得 → `external_skills/youtube-uploader/scripts/upload.py --authorize`
2. GitHub Secret に登録 — **命名規則 `YT_TOKEN_<ACCOUNT_ID_UPPER>`**（例 `YT_TOKEN_YOURESHOMA`）
3. `.github/workflows/auto_post.yml` の `Restore tokens from secrets` に env 1行追加:
   ```yaml
   YT_TOKEN_YOURESHOMA: ${{ secrets.YT_TOKEN_YOURESHOMA }}
   ```
4. meta.json で `"account_id": "youreshoma"` を指定すれば自動でそのトークン使用

## 重要ファイル

| ファイル | 役割 |
|---|---|
| `~/Library/LaunchAgents/com.kakumei.autopost.plist` | **主トリガ (live)**。22:00/23:00 JST に gh で GHA 起動 |
| `publishing/scripts/com.kakumei.autopost.plist` | 上の**参照コピー** (版管理用 / 再構築の元) |
| `publishing/scripts/run_dispatch_trigger.sh` | **手動**トリガ用スクリプト (launchd は使わない) |
| `~/Library/Logs/com.kakumei.autopost.{out,err}.log` | launchd トリガのログ (診断A で見る) |
| `publishing/posting_schedule.yaml` | スロット定義 (machine readable) |
| `publishing/scripts/dispatch_queue.py` | スロット判定 + queue 消化 + 二重防止 (`posted_slot` exact match) |
| `.github/workflows/auto_post.yml` | GHA 本体 (予備 cron + token 復元 + 投稿 + state push + Issue) |
| `publishing/queue/{clip_id}/` | 投稿待ちの動画 + meta.json |
| `publishing/publishing-state/source-podcast/` | 投稿後の記録 (post-monitor が読む)。X 結果は `x_post` キー |
| `external_skills/x-uploader/scripts/upload.py` | X 投稿実体 (720x1280 縮小 + v2 media upload + /2/tweets) |
| `publishing/x_accounts.yaml` | X アカウント台帳 (pay-per-use 課金・1アカ限定ポリシー) |
| `publishing/tokens/x/{account_id}.json` | X OAuth 1.0a 4キー (gitignore。GHA は Secret `X_TOKEN_<ID>` から復元) |
| `external_skills/meta-uploader/scripts/upload.py` | Meta 投稿実体 (FB Reels 3-phase / IG resumable rupload / Threads URL fetch) |
| `external_skills/meta-uploader/scripts/authorize.py` | Meta トークン採取 (対話式・ホスティング不要) |
| `external_skills/meta-uploader/scripts/refresh_threads_token.py` | Threads 60日トークン自動更新 (auto_post.yml が毎 run 実行) |
| `publishing/meta_accounts.yaml` | Meta アカウント台帳 (2 App 構成・1アカ限定ポリシー・PAT 期限) |
| `publishing/tokens/meta/{id}.json` / `tokens/threads/{id}.json` | Meta トークン (gitignore。Secret `META_TOKEN_<ID>` / `THREADS_TOKEN_<ID>` から復元) |
| `publishing/scripts/prepare_queue_clip.py` | queue 配置 (音声 128kbps 正規化 — IG/Threads 適合の必須経路) |
| `publishing/SETUP_META.md` | Meta セットアップ手順 (Phase 0 チェックリスト) |

## スケール上限と移行ポイント

- **現状 (Phase 1)**: GitHub Secrets 直管理、video を git にコミット、定刻トリガは **1台の Mac の launchd**。
- **Phase 100 (~100-500アカ運用) で必要な進化**:
  - 定刻トリガ → **外部の信頼できる定刻サービス**(cron-job.org 等)から GitHub API の `workflow_dispatch`/`repository_dispatch` を叩く形へ（Mac 依存を脱し、実行は GHA のまま）。launchd は1Mac=単一障害点なので卒業。
  - Secret 管理 → 外部(AWS Secrets Manager / 1Password)へ（100個手動は破綻）。
  - 動画ストレージ → R2/S3 へ（repo size 警告超え予想）。
  - OAuth → Production 昇格（Testing は7日で refresh 失効）。
  - post-monitor → GHA workflow 化（Mac 完全離脱）。

詳細運用 (queue meta.json スキーマ等) は `publishing/queue/README.md` 参照。
