# Shoma Video-use Project

**ショーマ・イナバの思想発信Podcastを Claude Code + video-use で量産するプロジェクト。**
長尺YouTube + ショート10本(TikTok/Reels/Shorts)を同時生成。将来はサロンメンバー300人のクリッピング軍団の土台。

---

## 🚀 New here? → **[SETUP.md](SETUP.md)**

新しくこのプロジェクトを使う人は、まず `SETUP.md` を読む。
Python/ffmpeg → ElevenLabs API key → Google Cloud OAuth → YouTube channel authorize → 動作検証、までを1ページで案内。

---

## 🎯 このドキュメントの目的

1. チームメンバー全員が**フォルダ構造の意味を共通理解**する
2. 新エピソードを始める時に**どこに何を置くか迷わない**
3. video-use本体と成果物の**分離原則**を守る
4. Driveバックアップ・共有が**エピソード単位で完結**する

---

## 🟦🟥 大原則: 2ゾーン分離

プロジェクトは常に**2つのゾーン**に分かれている。これを混ぜると全てが壊れる。

```
┌────────────────────────────────────────────────────────┐
│  🟦 ZONE A — 道具(スキル本体)                           │
│     ・git管理、読むだけ、絶対に書き込まない              │
│     ・バックアップ不要 (GitHubから再cloneで復元可)      │
│     ・チーム全員が共有コピー                             │
└────────────────────────────────────────────────────────┘
                         │
                   symlink via
                ~/.claude/skills/video-use
                         │
┌────────────────────────────────────────────────────────┐
│  🟥 ZONE B — データ(素材と成果物)                       │
│     ・エピソード毎に1パッケージ                          │
│     ・Driveに丸ごと同期してバックアップ                  │
│     ・他メンバーとはこのゾーンを共有                     │
└────────────────────────────────────────────────────────┘
```

### なぜ分離するのか

- **道具の更新でデータが壊れない** — video-useのgit pullは安全
- **データの移動が簡単** — エピソードフォルダを丸ごとコピー/Drive同期可
- **チーム展開が容易** — メンバーは道具(ZONE A)を共有、各自のZONE Bを持つ
- **バックアップ戦略がシンプル** — ZONE Bのみバックアップすれば良い

### 🟩 ZONE C — 投稿運用 (`publishing/`)

ZONE A/B に加え、**投稿・配信の運用レイヤ** `publishing/` がある（新規・改造OK）。動画を `publishing/queue/` に置けば、GitHub Actions + Mac の launchd トリガで毎日 22:00 / 23:00 JST に自動で public 投稿される「発射台」モデル。**YouTube 投稿成功の直後、同じ clip が X (@kakumei1784) にもネイティブ動画として自動クロスポストされる**（2026-06-06〜・デフォルト全クリップON、meta.json `x_enabled: false` で個別OFF）。

- **自動投稿の仕組み・運用・障害対応(投稿が止まった時の復旧ランブック)・確実なセットアップ手順は → `publishing/AUTO_POST_RULES.md`**（X クロスポストの仕組み・X ランブックも同ファイル）
- 投稿後の自動モニター(視聴維持率等)は → `publishing/scripts/README.md`

---

## 📂 完全なフォルダ構造

```
/Users/knoxv/Documents/Claude/Projects/video-use-test/
│
├── README.md                              ← このファイル(人間向け+Claude向け兼用)
│
├── 🟦 video-use/                          ═════ ZONE A: 道具 ═════
│   ├── SKILL.md                          (Claude Codeが読むスキル定義)
│   ├── helpers/
│   │   ├── transcribe.py                 音声→文字起こし
│   │   ├── pack_transcripts.py           圧縮版テキスト生成
│   │   ├── timeline_view.py              検査用PNG生成
│   │   ├── render.py                     メインレンダラー
│   │   ├── grade.py                      カラープリセット
│   │   └── compositions.py  🆕           構図制御(face_track等)
│   └── .env                              ELEVENLABS_API_KEY
│
└── 🟥 source-<ep-名>/                     ═════ ZONE B: エピソード毎 ═════
    ├── raw.mov                           ①録画素材を直接ここに保存
    └── edit/                             ②video-useが自動作成
        ├── transcripts/
        │   └── raw.json                  Scribe文字起こしキャッシュ
        ├── takes_packed.md               ③LLMが読むテキスト(~12KB)
        ├── edl.json                      ④編集決定書(長尺用)
        ├── master.srt                    ⑤字幕ファイル
        ├── preview.mp4                   ⑥長尺プレビュー
        ├── final.mp4                     ⑦長尺完成版 ⭐
        ├── verify/                       Self-eval用PNG群
        ├── project.md                    セッション記憶
        └── shorts/                       ⑧ショート量産
            ├── 01_HOOK_LINE/
            │   ├── edl.json
            │   ├── animation.mov         アニメーション(ProRes 4444)
            │   └── short_final.mp4      ⭐ 完成ショート
            ├── 02_LION_BIRD/
            │   └── ... (同様の構造)
            ...
            └── 10_FIRST_PRINCIPLE/
```

---

## 📦 1エピソード = 1完結パッケージ

「エピソード」フォルダ1つで以下が全部揃う:

| # | 成果物 | 意味 |
|---|---|---|
| ① | `raw.mov` | ソース(録画) |
| ③ | `takes_packed.md` | 全発話テキスト(LLM用) |
| ④ | `edl.json` | 編集決定(再現可能) |
| ⑤ | `master.srt` | 字幕(単独配布も可) |
| ⑦ | `final.mp4` | **長尺完成版** ⭐ |
| ⑧ | `shorts/NN/short_final.mp4` | **ショート10本** ⭐ |

**このフォルダ全体をDriveに上げるだけで完結バックアップ**。他メンバーが受け取って再編集も可能(`edl.json`で意思が共有される)。

---

## 🏭 ショート量産の構造

1本の長尺Podcastから **10本のショート** が自動生成される仕組み:

```
raw.mov (2時間)
     │
     ↓ Transcribe (ElevenLabs Scribe, 1回だけ課金)
     │
transcripts/raw.json ←─── キャッシュ、以降無料
     │
     ↓ Pack
     │
takes_packed.md (~12KB)
     │
     ├──────┬──────────────────────┐
     ↓      ↓                      ↓
  長尺EDL  ショートEDL × 10         (将来追加可能)
  生成     生成                    ・多言語字幕版
     │      │                      ・別アカウント用バリエーション
     ↓      ↓                      ・アナリストデータ連動版
  final.mp4  shorts/
  (長尺)    ├ 01/short_final.mp4
            ├ 02/short_final.mp4
            ├ ...
            └ 10/short_final.mp4
```

### ショート1本の構成要素

```
shorts/01_HOOK_LINE/short_final.mp4
   ├─ ベース動画 (face_trackで縦型1080×1920、warm_cinematic)
   ├─ 字幕焼き込み (Hiragino Sans 20pt, 下端)
   ├─ アニメーション overlay (ProRes 4444 alpha付)
   ├─ SFX (whoosh at 出現, ding at 中間)
   └─ 1.2x 速度 (pitch保持)
```

### 将来の派生量産 (サロン展開時)

```
shorts/01_HOOK_LINE/
├─ short_final.mp4              (公式ショーマ版)
├─ edl.json                     ← 人間が読める編集指示
├─ variants/                    ← メンバーがここを編集
│   ├─ member_A_edl.json        ("私は動物好きだからもっと鳥っぽく")
│   ├─ member_A_short.mp4
│   ├─ member_B_edl.json
│   └─ member_B_short.mp4
```

サロンメンバーは `edl.json` を編集 → `render_short.py` で派生版を生成 → 自分のアカウントで投稿。
**1公式ショート × N人 × 複数スタイル = 量産乗数**。

---

## 🗓 エピソード管理の推奨パターン

```
/Users/knoxv/Documents/Claude/Projects/shoma-podcasts/
│
├── video-use/                          ← ZONE A (プロジェクトrootに1つ)
│
├── ep12_2026-04-20_成功者批判/          ← エピソード毎にフォルダ
├── ep13_2026-04-27_時間管理/
├── ep14_2026-05-04_失敗の価値/
└── ep15_2026-05-11_Xxxxxxx/
```

命名規則: `ep<番号>_<収録日>_<主題>`

---

## 🎨 確定済みスタイル (今セッションで決定)

次回以降のレンダーでは**これらを既定として自動適用**。変更したければ `render.py` 等を編集。

| 項目 | 値 |
|---|---|
| 字幕フォント | Hiragino Sans W6 |
| 字幕サイズ(縦型) | 20pt |
| 字幕位置(縦型) | MarginV=40 (画面下端近く) |
| カラーグレード | warm_cinematic |
| ラウドネス | -14 LUFS (YouTube/TikTok準拠) |
| 構図(ショート) | face_track (顔検出自動中央) |
| 速度(ショート) | 1.2x (pitch保持) |
| SFX(ショート) | whoosh at anim出現 + ding at 中間 |

**将来このスタイルを変えるときは `project.md` に理由を記録**すること。

---

## ⚡ 新エピソード開始の手順

1. **録画保存先を `source-<ep>/raw.mov` に直接設定** (OBS/Riverside等)
2. 録画完了後:
   ```bash
   cd /Users/knoxv/Documents/Claude/Projects/video-use-test/source-<ep>
   claude
   ```
3. Claude Codeで: 「この素材を編集して」
4. 戦略提案が出る → 承認
5. 長尺 `edit/final.mp4` 完成
6. 続けて: 「ショート10本量産して」
7. `edit/shorts/NN/short_final.mp4` 完成

**所要時間目安**: 2時間素材で実質2-3時間(Transcribe+Render含む)。

---

## 🚀 初回セットアップ (新メンバー向け)

```bash
# 1. video-use クローン
git clone https://github.com/browser-use/video-use
cd video-use
ln -s "$(pwd)" ~/.claude/skills/video-use

# 2. Python依存
pip install -e .
pip install opencv-python

# 3. ffmpeg (brew経由、未インストールなら)
brew install ffmpeg

# 4. .env作成
cp .env.example .env
# .envに ELEVENLABS_API_KEY=... を追記

# 5. プロジェクトフォルダ作成
mkdir -p ~/Documents/Claude/Projects/shoma-podcasts/video-use
# 以下、上記と同じセットアップを video-use/ 内に複製
```

---

## 🛠 関連Skill (`~/.claude/skills/`)

本プロジェクトでvideo-useと連携して使うスキル:

- **source-downloader** — yt-dlpでYouTube素材取得
- **transcriber** — Whisper ASR (Scribeと併用可)
- **clip-detector** — バイラル瞬間検出
- **clip-extractor** — 区間切り出し
- **transformer** — 縦型+テロップ(video-useと役割重複、要統合検討)
- **youtube-uploader** — 完成品アップロード
- **x-uploader** — X (Twitter) クロスポスト (YouTube投稿成功後に dispatch が自動実行)
- **post-monitor** — 投稿後アナリティクス

### 棲み分け
- **video-use** = 長尺編集 + ショート量産(本プロジェクト中核)
- **clip-army系** = 素材取得 → video-useに渡す → アップロード → 監視 (前後連携)

---

## 💰 コスト構造

| 項目 | コスト |
|---|---|
| video-use本体 | 無料(MITライセンスOSS) |
| Claude Code Pro/Max/Team | 月額 (必須) |
| ElevenLabs Scribe | 2時間素材あたり ~$0.30 (690 credits) |
| 再編集 | **$0** (transcriptキャッシュで無料) |

月4エピソード想定: ElevenLabs約 $1.2/月 + Claude Code月額。
従来の編集外注(1本5,000-30,000円)比で**実質ゼロ**。

---

## ⚠️ 既知の課題

次回以降の改善候補:

1. **emoji描画不具合** — PIL+Apple Color Emojiの相性。対応: 絵文字を幾何図形/文字ラベルに置換
2. **outro検査バグ** — timeline_view が fdur ちょうどで失敗。対応: end時刻を `fdur - 0.5`
3. **face_track水平のみ** — 縦軸ズーム未実装。顔をもっと大きく見せたい場合に制約
4. **Manim/Remotion未活用** — アニメはPIL実装のみ。将来は数式アニメ(Manim)・ブランドタイポ(Remotion)導入
5. **縦軸自動追従** — Shomaが縦方向に動くケースで未対応

---

## 📚 参考資料

- [video-use GitHub](https://github.com/browser-use/video-use)
- [SKILL.md 詳細ルール](./video-use/SKILL.md) (12 Hard Rules等)
- [ElevenLabs Scribe](https://elevenlabs.io/docs/capabilities/speech-to-text)

---

## 🧠 プロジェクト記憶の場所

Claude Codeの長期memoryは以下に保存される:
```
~/.claude/projects/-Users-knoxv-Documents-Claude-Projects-video-use-test/memory/
```

userタイプ/feedbackタイプ/projectタイプ/referenceタイプで整理。
次回セッション開始時に自動ロードされ、今日の学習(スタイル確定・運用知見)が活きる。

---

## ✅ チェックリスト: 新エピソード開始前

- [ ] `source-<ep>/` フォルダ作成済み
- [ ] `raw.mov` が正しい場所にある
- [ ] `~/.claude/skills/video-use` シンボリックリンク存在
- [ ] `video-use/.env` に `ELEVENLABS_API_KEY` 設定済み
- [ ] ElevenLabs残クレジット確認 (2時間素材=690クレジット必要)
- [ ] ffmpeg, Python, OpenCV 動作確認

すべてOKなら `cd source-<ep> && claude` で開始。
