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
| `publishing/publishing-state/source-podcast/` | 投稿後の記録 (post-monitor が読む) |

## スケール上限と移行ポイント

- **現状 (Phase 1)**: GitHub Secrets 直管理、video を git にコミット、定刻トリガは **1台の Mac の launchd**。
- **Phase 100 (~100-500アカ運用) で必要な進化**:
  - 定刻トリガ → **外部の信頼できる定刻サービス**(cron-job.org 等)から GitHub API の `workflow_dispatch`/`repository_dispatch` を叩く形へ（Mac 依存を脱し、実行は GHA のまま）。launchd は1Mac=単一障害点なので卒業。
  - Secret 管理 → 外部(AWS Secrets Manager / 1Password)へ（100個手動は破綻）。
  - 動画ストレージ → R2/S3 へ（repo size 警告超え予想）。
  - OAuth → Production 昇格（Testing は7日で refresh 失効）。
  - post-monitor → GHA workflow 化（Mac 完全離脱）。

詳細運用 (queue meta.json スキーマ等) は `publishing/queue/README.md` 参照。
