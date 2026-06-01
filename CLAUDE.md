# Video-use-test プロジェクト規約

このファイルは Claude Code が起動時に自動読込する**プロジェクト固有のルール集約**。
ZONE A (video-use本体) を改造せず、プロジェクト全体の運用ルールをここで管理する。

---

## 🏗 プロジェクト構造の大原則

```
~/Documents/Claude/Projects/video-use-test/
├── 🟦 video-use/              ZONE A: 道具 (絶対に改造しない)
├── 🟥 source-<ep>/            ZONE B: エピソードデータ (素材+成果物)
└── 🟩 publishing/             ZONE C: 投稿運用 (新規・改造OK)
    ├── tokens/youtube/        OAuthトークン (Gmail × チャンネル別)
    ├── audio/                 BGM/SFX生成・mix
    └── publishing-state/      投稿記録
```

詳細は `README.md` 参照。

---

## 🎵 オーディオ設計ルール (毎クリップで自動適用)

クリップ生成・編集時は **以下を必ず参照** すること。ユーザーから個別指示が無くても自動適用する:

### 必須参照ファイル
- **`publishing/audio/AUDIO_DESIGN_RULES.md`** ← 思想・運用ルール (人間が読む)
- **`publishing/audio/audio_mix_config.yaml`** ← 数値設定 (機械が読む)

### 主要ルール (AUDIO_DESIGN_RULES.mdの抜粋)
- SFXは**2秒間隔で必ず配置** (0.0s, 2.0s, 4.0s, ...)
- BGMは**ElevenLabs Music API で迫力ある cinematic orchestral を1本ずつ別生成** (再利用禁止)
- BGMプロンプトに**実在アーティスト名を入れない** (ToS違反・拒否される)
- mix時は `loudnorm=-16` で各素材を揃え、最終 `loudnorm=-14` (YouTube標準) に正規化

### ⭐ 確定デフォルト設定 (v7 / 2026-04-27 ユーザー承認)
- **ナレ 0dB / SFX -3dB / BGM -5dB**
- **オーディオダッキング ON** (発話時にBGM自動低下、ratio=8 / attack=20ms / release=350ms)
- これらは `publishing/audio/audio_mix_config.yaml` に書き込み済
- **新規クリップ生成・mix時、Claude は毎回この設定を自動適用する。個別指示不要**
- 変更したい時はユーザーが yaml を直接編集

### ルール変更の方法
ユーザーは `AUDIO_DESIGN_RULES.md` または `audio_mix_config.yaml` を直接編集すれば全クリップに反映。
**Claudeへの個別指示は不要**。

---

## ✂️ 編集スタイルルール (型レジストリ)

クリップ生成時は **以下を必ず参照** すること。EDL 作成時に `style` フィールドで型を選択する:

### 必須参照ファイル
- **`publishing/EDIT_STYLES.md`** ← 型レジストリ詳細 (人間可読)

### 現在登録されている型
| 型名 | 構造 | 適用例 |
|---|---|---|
| `hook_payoff_repeat` | hook→body→**same-line-回収** (本編末尾が hook と同じ) | 既存7本+30s 3本 (07/08/09) |
| `loop_friendly_tail` | hook→body→**hook の直前セリフ** (元音声でループ自然接続) | 10_TAMASHII / 11_TOUKOU_BETSU (2026-05-07新規) |

### 共通ベース (全型)
- 出力 1080×1920、warm_cinematic grade
- 字幕: `vertical_inside_left_brush` (Yuji Mai 筆フォント、累積上限16文字)
- 本編 1.5x atempo、Cold Open 1.0x
- SFX 2秒間隔、音響は `AUDIO_DESIGN_RULES.md` v7 設定 (自動適用)

### ルール変更の方法
ユーザーは `EDIT_STYLES.md` を直接編集すれば反映。新しい型を追加する時は同ファイルの「型の追加方法」セクション参照。
**Claudeへの個別指示は不要**。

---

## 📺 投稿運用ルール

### アカウント管理
- 全YouTubeアカウントは `publishing/youtube_accounts.yaml` で台帳管理
- トークンは `publishing/tokens/youtube/{id}.json`

### 投稿先優先順位 (現フェーズ)
1. **革命一家 (@kakumei_ikka)** ← Phase 1 メインチャンネル
2. ビデオポッドキャスト切り抜き (@youreshoma) ← サブ
3. 匠瞬 (@im_shoma) ← 旧資産

### 投稿時の必須挙動
- 初回は必ず `privacy=unlisted` (限定公開)
- 1日6本までのクォータ制約 (40本なら7日分散)
- 投稿後 video_id を `publishing/publishing-state/<source>/<clip_id>.json` に記録

### 自動投稿 (2026-05-04〜 GHA 稼働中)
- **GitHub Actions が毎日 2スロット (22:00 / 23:00 JST) で発火**。各スロットは**オフピーク分で 3回ずつ冗長発火**する (2026-06-01: GHA schedule が run ごと完全ドロップ＝当日投稿ゼロを観測 → 多重試行で対策。二重投稿は dispatcher の投稿済み判定で防止)
- `publishing/queue/{clip_id}/{short.mp4, meta.json}` を git push しておけば、次のスロットで public 投稿
- 1スロット=1本、queue 空ならスキップ
- 朝/昼/夕方/21時の cron は廃止 (二重防御: cron 自体無し + active_slot=None でスキップ)
- 個別 clip で「22 だけ」「23 だけ」と pinpoint したい場合は meta.json に `target_slot: "23:00"`
- 失敗時は `auto-post-failure` ラベル付き Issue が自動作成
- 詳細運用は **`publishing/AUTO_POST_RULES.md`** 参照

### post-monitor 自動チェック (2026-05-01〜 launchd 稼働中)
- **launchd `com.kakumei.postmonitor` が毎日 08:00 起動** → `publishing/scripts/run_monitor.sh`
- `publishing-state/source-podcast/*.json` を全件 glob、`privacy=="public"` のみ対象
- 24h後 (20-48h窓): health check / 72h後 (60-168h窓): full report
- 結果は元 JSON の `monitor_results` 配列に冪等追記
- **新規投稿は publishing-state JSON を置くだけで自動対象化**。追加作業不要
- 詳細運用は **`publishing/scripts/README.md`** 参照

---

## 🎯 KPI第一原理 (戦略バックボーン)

`/Users/knoxv/Documents/Claude/Projects/切り抜きショート量産軍隊　〜1日500アカ並列運用　月75,000本投稿/KPI聖書.md` 参照。

要点:
- ROIではなく**「ありったけのVIRAL性」**を引き出す (Roy Lee/Cluely戦略)
- 100アカ運用 (Phase 1) が前提なので、**全アセットがユニーク化されている**こと
- 同じBGM・SFX・編集型を複数アカ・複数本で使い回さない (連動バレ防止)

---

## 🛠 技術スタック

| 用途 | ツール | API |
|---|---|---|
| 文字起こし | ElevenLabs Scribe | `/v1/speech-to-text` |
| BGM生成 | ElevenLabs Music API | `/v1/music` |
| SFX生成 | ElevenLabs Sound Effects | `/v1/sound-generation` |
| 動画render | ffmpeg + video-use | local |
| 音mix | ffmpeg amix + loudnorm | local |
| YouTube投稿 | youtube-uploader skill | YouTube Data API v3 |
| 投稿後分析 | post-monitor skill | YouTube Analytics API v2 |

---

## 📅 更新履歴

| 日付 | 変更 |
|---|---|
| 2026-04-27 | 初版作成。audio設計の永続化、ルール文書二層構造を確立 |
| 2026-05-07 | 編集スタイル型レジストリ (`publishing/EDIT_STYLES.md`) 追加。スロット 4→6 拡張 (22:00/23:00 追加) |
