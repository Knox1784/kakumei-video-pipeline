# 革命一家チャンネル オーディオ設計ルール (永続)

このファイルは Audio設計の **永続ルール**。Claude Code は毎セッションこのファイルを参照すること。
ユーザーがルール変更したい時は、このファイルを直接編集する。次回以降のEDL生成・mix_final実行で自動反映される。

---

## ⭐ 確定デフォルト設定 (v7 / 2026-04-27 ユーザー承認)

**Claude は新しいクリップを mix する時、毎回この設定を自動適用する。ユーザーから個別指示は不要。**

| 項目 | 値 | 根拠 |
|---|---|---|
| ナレ音量 | 0 dB (基準) | 思想伝達主役 |
| SFX音量 | **-3 dB** | ナレに近い存在感 |
| BGM音量 | **-5 dB** (平常時) | 迫力ある裏BGM |
| ダッキング | **ON** | 発話時にBGM自動低下、フック含む全発話自動カバー |
| ducking ratio | 8 | 発話時に約-9dB低下 |
| ducking attack | 20ms | 即時反応 |
| ducking release | 350ms | 自然に復帰 |
| Loudness target | -14 LUFS | YouTube/TikTok標準 |
| BGM素材正規化 | -16 LUFS | 各素材依存ゼロ化 |
| amix normalize | 0 | ナレに引きずられず音量保持 |
| BGM duration | clip + 2000ms | 末尾フェード用余裕 |
| BGM fade-in | 500ms | 自然な立ち上がり |
| BGM fade-out | 末尾1500ms | 自然な余韻 |
| SFX間隔 | 2.0秒固定 | 飽きさせない密度 |

これらは `audio_mix_config.yaml` に物理的に書き込まれている。Claude/mix_final.py はこのファイルを必ず参照。

**変更したい時**: ユーザーが直接 yaml を編集する。Claude経由不要。

---

## 🎯 SFXルール (必須・絶対遵守)

### 配置間隔
- **必ず2秒間隔で配置**: 0.0s, 2.0s, 4.0s, 6.0s, 8.0s, 10.0s, 12.0s, 14.0s, ...
- 個数の自動算出: `n_sfx = floor(clip_duration_s / 2.0) + 1`
- 例: 12.8秒クリップ → 7個 / 20秒クリップ → 11個 / 25秒クリップ → 13個
- **2秒未満の間隔は禁止** (息継ぎ感が消えて疲れる音になる)

### 各SFXの長さ
- 標準: 0.5秒 (短くサブリミナル)
- 例外: build-up系のみ 1.5秒許可 (10.0s〜の緊張上昇)
- 最大2.0秒以上禁止 (発話を邪魔する)

### 音量
- `audio_mix_config.yaml` の `sfx_db` 値に従う
- 個別調整は EDLの `audio.mix_override.sfx_db` で上書き可能

### 一意性 (重要・100アカ運用安全性)
- **同じSFXファイルを連続2回使わない** (息継ぎ感維持)
- **同じSFXファイルを別クリップで再利用しない** (アカウント連動バレ防止)
- 各SFXは ElevenLabs API で**毎回別プロンプト**で生成

---

## 🎼 SFX分類カタログ (時刻別の役割)

editor sub-agent はクリップごとに以下のカタログから**プロンプトを毎回揺らぎを入れて**生成する。

| 時刻 | 構造ビート | 役割 | プロンプト例 (毎回揺らぎ) |
|---|---|---|---|
| **0.0s** | Cold Open | hook / 注意フック | `subtle high-freq attention click, glassy` / `typewriter mechanical click` / `paper flip with reverb` / `metallic chime intimate` |
| **2.0s** | 本編突入 | transition signal | `soft whoosh with reverb tail` / `sweep transition` / `airy gust` / `digital pop` |
| **4.0s** | anchor | 安心感・引き込み | `warm bell tap` / `soft muted thud` / `wood knock with decay` / `hollow chime` |
| **6.0s** | Pattern Interrupt | 覚醒 / サブリミナル刺激 | `low pulse 90Hz heartbeat sync` / `metallic ding sharp` / `glitch pop` / `subtle bass thump` |
| **8.0s** | awareness peak | 注意維持 | `glassy sparkle high freq` / `crystal tinkle` / `magic shimmer` / `ethereal twinkle` |
| **10.0s** | build-up (1.5s長) | 緊張上昇 | `rising tension drone` / `string crescendo brief` / `reverse cymbal swell` / `pressure rise` |
| **12.0s+** | Payoff前 | attention reset | `metallic ding attention` / `bell punctuation` / `clear chime` |
| **14.0s+** | Payoff着地 | 解放感・満足感 | `deep warm impact thud` / `satisfying landing reverb` / `bass drop soft` / `closure thud` |
| **16.0s+** | CTA / fade | 余韻 | `chime fade` / `soft whoosh out` / `breath release` |

editor sub-agent はクリップ尺に応じて、上記のテンプレートから**1本ごとに違う組み合わせ**を選んでEDLに埋める。

---

## 🎻 BGMルール (必須・絶対遵守)

### 生成方法
- **ElevenLabs Music API でクラシック調を1本ずつ別生成** (再利用禁止)
- duration: `clip_duration + 2000ms` (末尾フェードアウト用)
- 100アカウント運用時の連動バレ防止のため、**同じBGMファイルを別クリップで使わない**

### 音量
- `audio_mix_config.yaml` の `bgm_db` 値に従う
- ナレ (0dB) を上回る設定は禁止 (max -3dB が上限)

### 雰囲気バリエーション (主題に応じて選択)
| 主題 | 推奨雰囲気 | プロンプト例 |
|---|---|---|
| 嘲笑乗り越え | solemn / dramatic | `solemn classical strings, building tension` |
| 自分を見つける | introspective / contemplative | `minimal piano with cello, contemplative` |
| 第一原理 | heroic / determined | `orchestral strings, heroic resolve` |
| 兄ライオン | warm / inspiring | `warm strings with horn, inspiring slow build` |
| 嫌われる勇気 | defiant / triumphant | `defiant string quartet, triumphant rise` |

### プロンプト揺らぎ (毎回ユニーク化)
```
mood = ["solemn", "dramatic", "introspective", "heroic", "contemplative", "defiant"]
instrument = ["solo piano", "string quartet", "orchestral strings", "minimal piano with cello"]
tempo = ["slow", "moderate", "building", "static"]

prompt = f"{random(instrument)}, {random(mood)} mood, {random(tempo)} tempo, classical inspiration"
```

→ 6 × 4 × 4 = 96通り × 主題別 = 実質無限のバリエーション

---

## ⛔ NGルール (絶対やらない)

| # | NG事項 | 理由 |
|---|---|---|
| 1 | 同BGMファイル使い回し | 100アカ運用バレ |
| 2 | 同SFXファイル連続使用 | 息継ぎ感消失 |
| 3 | SFX間隔2秒未満 | 疲労音になる |
| 4 | BGM音量がナレ超え | 発話聞き取り困難 |
| 5 | ナレ素材の二次変換 (pitch等) | 本人性損失 |
| 6 | loudnorm 抜きでの mix | 素材音量差で予測不能 |
| 7 | normalize=1 (ON) で amix | ナレに引きずられて全体縮小 |
| 8 | **プロンプトに実在アーティスト名を入れる** (Hans Zimmer / Beethoven録音 等) | **ElevenLabs ToS違反、HTTP 400エラー** |
| 9 | **代わりに使う**: "epic cinematic" / "orchestral" / "heroic crescendo" / "deep brass" 等の**ジャンル/楽器/雰囲気記述** | プロンプト揺らぎはこれで十分 |

---

## 🎚 音量バランスの背景思想

### 三層構造の役割
- **ナレ (0dB)**: 思想伝達の主役。最優先
- **SFX (相対 -3dB)**: 視聴離脱阻止のサブリミナル刺激
- **BGM (相対 -5dB)**: 感情誘導・没入感の下地 (ダッキング前提)

### loudnorm の二段適用
1. 各素材を `loudnorm=I=-16` で揃える (素材依存ゼロ化)
2. mix後に `loudnorm=I=-14` で全体正規化 (YouTube/TikTok標準)

### 🦆 オーディオダッキング (sidechain compression) ★必須
**プロYouTuberが必ず使う技術。発話時にBGMを自動で下げる。**

- ナレが鳴っている瞬間 → BGMが ratio=8 で自動圧縮 (約-9〜-12dB低下)
- ナレが終わると → BGMが350ms かけて元音量に復帰
- フック発話・通常発話・全区間で**自動的に**カバー (個別指示不要)
- 設定: audio_mix_config.yaml の `ducking` セクション

**効果**:
- 発話の聞き取りやすさが格段に上がる
- BGM平常時 (発話なし区間) は迫力ある音量で残る
- リスナー疲労が劇的に減る

これによって:
- 素材の元音量にかかわらず予測可能
- ループ再生時の音量変動なし
- アルゴリズム的にプロ品質と認識される
- フック発話部分でも自然にBGMが裏に下がる (手動編集不要)

---

## 📋 editor sub-agent への必須指示

EDL生成時、以下を**自動で**埋めること (ユーザーから個別指示なし):

```json
{
  "audio": {
    "bgm": {
      "prompt": "<上記カタログから揺らぎ生成>",
      "duration_ms": <clip_duration_ms + 2000>
    },
    "sfx_track": [
      // 2.0秒間隔で必ず配置、上記時刻別カタログから選択
      // 各SFXは別プロンプト、別ファイル
      {"time_s": 0.0,  "desc": "<0.0sカタログから>", "duration_s": 0.5, ...},
      {"time_s": 2.0,  "desc": "<2.0sカタログから>", "duration_s": 0.5, ...},
      {"time_s": 4.0,  "desc": "<4.0sカタログから>", "duration_s": 0.5, ...},
      ...
      {"time_s": <clip_duration - 2.0 with floor>, ...}
    ]
  }
}
```

---

## 📅 更新履歴

| 日付 | 変更 | 理由 |
|---|---|---|
| 2026-04-27 | 初版 | SFX 2秒間隔固定 / BGM -10dB / SFX -6dB / サブリミナル分類カタログ |
| 2026-04-27 | v4音量更新 | BGM -6dB / SFX -3dB (さらに前に出す、迫力重視) |
