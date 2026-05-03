# SETUP.md — 新規メンバー向けオンボーディング

このドキュメントは **video-use-test を初めて使う人** が**自分のマシンで一通り動かすまで**の手順。
最終ゴール: 自分の podcast 素材から 革命一家風の縦型ショート動画を生成 → YouTube 投稿 → 自動モニタリング。

---

## 0. 前提環境

| 項目 | 必要 |
|---|---|
| OS | macOS (launchd 自動モニター利用のため。Linux でも代替可だが crontab 必要) |
| Python | 3.10 以上 |
| ffmpeg | latest (`brew install ffmpeg`) |
| Claude Code | latest (skill 経由で操作するため) |
| Google アカウント | YouTube チャンネル所有のもの |
| ElevenLabs アカウント | API key 取得用 (有料プラン推奨: Music API + Sound Effects に必要) |

---

## 1. リポジトリ取得 → 基本セットアップ

```bash
git clone <repo-url> video-use-test
cd video-use-test
bash setup.sh
```

`setup.sh` がやること:
- Python deps インストール (video-use editable + google-api libs + requests + pyyaml)
- `video-use/.env` を `.env.example` から作成
- 必要ディレクトリ作成 (`publishing/tokens/youtube/`, `publishing/publishing-state/source-podcast/`, etc.)
- `external_skills/{post-monitor,youtube-uploader}` を `~/.claude/skills/` に symlink
- (任意) launchd 自動モニターを 08:00 起動で登録

---

## 2. ElevenLabs API key

1. https://elevenlabs.io でアカウント作成 (Music API 利用には Creator プラン以上)
2. ダッシュボード → Settings → API Keys → 新規発行
3. `video-use/.env` を編集:
   ```
   ELEVENLABS_API_KEY=sk_<your_key_here>
   ```

---

## 3. Google Cloud project + OAuth client (各メンバー自前)

YouTube 投稿・分析には **自分の GCP プロジェクト** が必要 (重要: 配布元のプロジェクトは共有しない方針)。

### 3-1. プロジェクト作成

1. https://console.cloud.google.com → "新しいプロジェクト"
2. プロジェクト名: 任意 (例: `my-shorts-pipeline`)

### 3-2. API 有効化

サイドバー: **APIs & Services → Library**
以下2つを検索 → ENABLE:
- ✅ **YouTube Data API v3** (動画アップロード・statistics)
- ✅ **YouTube Analytics API** (視聴維持率・再生分析)

### 3-3. OAuth consent screen 設定

サイドバー: **APIs & Services → OAuth consent screen**
1. User type: **External**
2. App name / User support email / Developer contact: 自分の情報
3. Scopes: 何も追加しなくて OK (CLI 側で要求)
4. **Test users**: 投稿に使う Google アカウント (Gmail) を**全部追加**
   ⚠️ Test status のままでは **refresh_token が 7日で失効**。長期運用には Production 昇格 (Google の app verification 必要)

### 3-4. OAuth Client ID 作成

サイドバー: **APIs & Services → Credentials**
1. "+ CREATE CREDENTIALS" → **OAuth client ID**
2. Application type: **Desktop app**
3. Name: 任意
4. CREATE → **JSON ダウンロード**
5. ダウンロードした JSON を以下のパスに配置:
   ```
   publishing/credentials/youtube_client_secret.json
   ```

---

## 4. YouTube チャンネル authorize (チャンネル毎)

複数チャンネル運用するなら 1 チャンネルずつ実行:

```bash
# 例: 自分のメインチャンネルを authorize
python3 external_skills/youtube-uploader/scripts/upload.py --authorize \
  --token publishing/tokens/youtube/main.json
```

ブラウザが開く → Google ログイン → "このアプリは Google で確認されていません" 警告は **詳細 → unsafe に進む** → アクセス許可。
完了後、`publishing/tokens/youtube/main.json` に refresh_token が保存される。

複数アカウント: ファイル名 (`main.json`, `subchan.json`, ...) で識別。

---

## 5. publishing/youtube_accounts.yaml に追記

自分のチャンネル情報を台帳に登録:

```yaml
accounts:
  - id: main
    handle: "@your_handle"
    channel_id: "UC..."
    gmail: "you@gmail.com"
    status: Testing  # or Production
    notes: "メインチャンネル"
```

---

## 6. 動作検証

### 6-1. post-monitor が API を叩けるか

```bash
python3 publishing/scripts/monitor_runner.py --force --dry-run
```

期待: トークン認証エラーなし、`state files: N` と表示される (新規環境なら N=0 で OK)。

### 6-2. monitor.py 単体で既存動画を叩く (任意)

自分のチャンネルに**既存の public 動画**があれば:

```bash
python3 external_skills/post-monitor/scripts/monitor.py --health-check <video_id> \
  --token publishing/tokens/youtube/main.json
```

期待: views/likes/comments が JSON で返る。

---

## 7. 新エピソードを始める (制作フロー)

### 7-1. 元素材を配置

自分の podcast 動画 (long form recording, 30分〜1時間) を:

```
source-podcast/<your_video>.MOV   # 例: IMG_1234.MOV
```

⚠️ `.gitignore` で `*.MOV` `*.mp4` は除外されるので git push されない (大容量素材は別途 Drive/Dropbox で配布する想定)

### 7-2. 文字起こし (3〜5分、ElevenLabs Scribe API)

```bash
python3 video-use/helpers/transcribe.py source-podcast/<your_video>.MOV
# → source-podcast/edit/transcripts/<your_video>.json
```

### 7-3. takes packing

```bash
python3 video-use/helpers/pack_transcripts.py --edit-dir source-podcast/edit
# → source-podcast/edit/takes_packed.md
```

### 7-4. 候補抽出 + EDL 作成

Claude Code 上で `takes_packed.md` を読みながら、各クリップの EDL JSON を `source-podcast/edit/shorts_v2/<NN_NAME>/edl.json` に作る。
スキーマと例は `CLAUDE.md` および既存の編集パターンを参照。

### 7-5. 音響生成 (BGM + SFX 並列)

```bash
python3 publishing/audio/batch_generate.py
# 各 EDL の audio セクションから BGM/SFX を ElevenLabs API で生成
```

### 7-6. コンポジション

```bash
python3 source-podcast/edit/shorts_v2/compose_v2.py --all
# → 各 shorts_v2/<NN_NAME>/short_with_audio.mp4
```

### 7-7. アップロード (unlisted → 視聴 → public)

Claude Code セッションで `youtube-uploader` skill を起動して投稿。
詳しくは README.md と `~/.claude/skills/youtube-uploader/SKILL.md` 参照。

### 7-8. publishing-state に記録

各クリップ投稿後、`publishing/publishing-state/source-podcast/<clip_id>.json` を作成:

```json
{
  "clip_id": "01_HOOK",
  "video_id": "<youtube_id>",
  "privacy": "public",
  "made_public_at": "YYYY-MM-DD",
  "title": "...",
  "channel": "...",
  "tags": ["..."]
}
```

→ launchd を有効化していれば**翌日 08:00 から自動的に 24h/72h モニター対象**。

---

## 8. 自動モニター (launchd) 詳細

`setup.sh` で y を選んだなら既に登録済。手動操作:

```bash
# 状態確認
launchctl list | grep kakumei

# 即時テスト実行
launchctl start com.kakumei.postmonitor

# 日次ログ確認
tail -f publishing/scripts/logs/monitor_$(date +%Y-%m-%d).log

# 一時停止
bash publishing/scripts/install_launchd.sh stop

# 再有効化
bash publishing/scripts/install_launchd.sh
```

詳細は `publishing/scripts/README.md` 参照。

---

## 9. トラブルシューティング

| 症状 | 原因 / 対処 |
|---|---|
| `monitor.py: ModuleNotFoundError: google` | `setup.sh` 未実行 or 別 Python 使用。`python3 -m pip install google-auth google-auth-oauthlib google-api-python-client` |
| `403 quotaExceeded` | YouTube Data API クォータ超 (10000/日)。翌日リセット待ち |
| `invalid_grant` (refresh失敗) | OAuth Test status の 7日制限切れ。再 authorize: `--authorize` 付きで実行 |
| `403 youtubeSignupRequired` | チャンネルがまだ作成されていない。YouTube Studio でチャンネル開設 |
| Analytics データが空 | 投稿後 48〜72時間遅延あり。72h check のタイミングで揃う |
| launchd が発火しない | スリープ中は走らない。次回起動後の 08:00 で catch-up |
| ELEVENLABS Music API 拒否 | プロンプトに実在アーティスト名禁止 (ToS 違反)。`AUDIO_DESIGN_RULES.md` 参照 |

---

## 10. このプロジェクトの哲学 (絶対読んで欲しい)

- **CLAUDE.md** — プロジェクト全体規約、ZONE 分離原則、Audio v7 デフォルト
- **publishing/audio/AUDIO_DESIGN_RULES.md** — 音響設計の永続ルール
- **README.md** — フォルダ構造の意味、ZONE A/B/C
- **`/Users/<...>/KPI聖書.md`** (作成者ローカル参照) — Roy/Tate式 viral 第一原理。チームで共有してください

---

## 11. 質問・改善

- このリポジトリの作成者: 稲葉ショウマ (`shomainaba1784@gmail.com`)
- 改善提案歓迎。SETUP.md の不明点があれば issue に
