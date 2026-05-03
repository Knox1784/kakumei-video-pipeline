# Editor Sub-Agent Brief Template (EDL生成用)

editor sub-agentを起動する際、このテンプレートをそのまま渡す。
sub-agentは self-contained なので、このブリーフ + takes_packed.md + AUDIO_DESIGN_RULES.md だけで完全動作する。

---

## ブリーフ (sub-agentに渡す内容)

```
あなたは映像編集のEDL生成専門エージェントです。
以下のINPUTSを読んで、約40本のショートクリップEDLを1つのJSON配列で出力してください。

INPUTS:
  - takes_packed.md: phrase-level transcript
  - 主題: 「嘲笑を乗り越えると自分が見つかる」
  - スピーカー: しょうま (思想発信、決意・指導者キャラ)
  - 元素材: source-podcast/raw_podcast.mov (24:50)
  - audio設計ルール: publishing/audio/AUDIO_DESIGN_RULES.md ⭐ 必読
  - audio mix config: publishing/audio/audio_mix_config.yaml

主題該当の核発話 (Pre-scan済):
  a1: 486.15-501.93 - "ありのまま発信、失敗する瞬間も"
  a2: 507.23-521.49 - "ダサい瞬間含めて、嫌われる覚悟"
  a3: 564.81-572.45 - "嫌われるの全く怖くない"
  a4: 591.35-610.83 - "嫌われるなんて1ミリも怖くない" ⭐
  a5: 626.45-651.89 - "世界を救いたい奴らに届けばいい"
  a6: 653.17-664.93 - "刺さる人に刺さればよい"
  a7: 667.27-680.81 - "ありのまま出せなければ意味ない"
  a8: 700.41-729.55 - "他人の人生を生きると自分を見失う" ⭐
  a9: 731.07-742.43 - "成功者の話は参考程度に"
  a10: 775.51-793.93 - "好きと嫌いを言える勇気" ⭐
  a11: 822.85-832.91 - "第一原理は必ずブラしちゃいけない"
  + ボーナス5箇所 (子ライオン/兄ライオン/95%無意識)

統一構造 (全クリップ):
  Cold Open (0-2秒、1.0x速度): 結論先出し or 質問 or 決め台詞
  本編 (2秒〜、1.5x atempo再生): 主体発話
  Pattern Interrupt (中盤): 字幕色変化 + SFX
  Payoff (最後2-3秒): 顔ズーム + 大テロップ + warm thud

編集型バリエーション (1本ずつ別組み合わせ):
  - フォント: Hiragino Sans W6 / Yu Gothic / Noto Sans JP / Source Han Sans
  - グレード: warm_cinematic / neutral_punch / desaturated / high_contrast
  - 構図: face_track 一定 (顔40-60%、字幕24-28pt MarginV=60-80)
  - アニメーション: PIL typewriter / paper flip / fade reveal / scale pop
  - Cold Open型: 結論先出し / 質問先出し / ペーパーフリップ / タイプライター
  - Payoff型: 大テロップ / 顔静止 / フェードアウト / CTA字幕

オーディオ設計 (AUDIO_DESIGN_RULES.md準拠・必須):
  - BGM: ElevenLabs Music で1本ずつクラシック調生成
  - SFX: 2秒間隔で必ず配置 (0.0/2.0/4.0/.../終端)
  - SFX分類: AUDIO_DESIGN_RULES.md の時刻別カタログから揺らぎ生成
  - 音量はaudio_mix_config.yaml参照 (個別override不要、全クリップ統一)

OUTPUT (1ファイル: edl_v2_kakumei_ikka.json):
  EDLの配列。各クリップにaudio.bgmとaudio.sfx_trackを必ず含む。
  
  例:
  [
    {
      "id": "01_KIRAWARENA_1MM",
      "title": "嫌われるなんて1ミリも怖くない",
      "ranges": [{"source": "raw_podcast", "start": 591.35, "end": 610.83, "beat": "DECLARATION"}],
      "playback_speed_main": 1.5,
      "cold_open": {
        "duration_s": 2.0,
        "type": "結論先出し",
        "text": "嫌われるな",
        "font": "Hiragino Sans W6",
        "size_pt": 70,
        "bg_color": "#000",
        "text_color": "#FFF"
      },
      "grade": "warm_cinematic",
      "subtitle_style": {"font": "Hiragino Sans W6", "size_pt": 26, "marginV": 70},
      "audio": {
        "bgm": {
          "prompt": "Solemn classical strings, building tension, contemplative",
          "duration_ms": 16000,
          "output": "publishing/audio/bgm/01_KIRAWARENA_1MM.mp3"
        },
        "sfx_track": [
          {"time_s": 0.0, "desc": "subtle high-freq attention click, glassy", "duration_s": 0.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t00.mp3"},
          {"time_s": 2.0, "desc": "soft whoosh transition with reverb tail", "duration_s": 0.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t02.mp3"},
          {"time_s": 4.0, "desc": "warm bell tap intimate", "duration_s": 0.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t04.mp3"},
          {"time_s": 6.0, "desc": "low pulse 90Hz heartbeat sync subliminal", "duration_s": 0.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t06.mp3"},
          {"time_s": 8.0, "desc": "glassy sparkle high freq awareness", "duration_s": 0.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t08.mp3"},
          {"time_s": 10.0, "desc": "rising tension drone build-up", "duration_s": 1.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t10.mp3"},
          {"time_s": 12.0, "desc": "metallic ding sharp attention", "duration_s": 0.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t12.mp3"},
          {"time_s": 14.0, "desc": "deep warm impact thud satisfying", "duration_s": 0.5, "output": "publishing/audio/sfx/01_KIRAWARENA_1MM_t14.mp3"}
        ]
      }
    },
    ... (約40本)
  ]

RULES (Hard):
  - 各clip全体の長さ: 完成尺15-22秒 = Cold Open 2s + 本編原文 (1.5x後 13-20s)
  - cut edges: word boundary、30-200ms padding (Hard Rule 6, 7)
  - SFX 2秒間隔は厳守 (clip_duration秒数からfloor計算)
  - BGM duration = clip完成尺 + 2000ms (フェードアウト用)
  - 同じBGMプロンプト・SFXプロンプトを別clipで使い回さない (揺らぎ必須)
  - audio.bgm.output と audio.sfx_track[].output は実在しないファイルパス (これから生成される)
  - 編集型バリエーション: 同じ核発話 (例: a4) 内でも複数本作る場合、別フォント・別グレード・別Cold Open型を選ぶ

Do not ask questions. Generate the full EDL JSON array. Self-correct if total run time mismatches the spec.
```

---

## このテンプレートの使い方

Claudeは Agent ツールで editor sub-agent を起動するとき、上記の `ブリーフ` 部分をそのまま `prompt` として渡す。
sub-agentは self-contained で動作し、最終的に `edl_v2_kakumei_ikka.json` (40本分) を返す。
