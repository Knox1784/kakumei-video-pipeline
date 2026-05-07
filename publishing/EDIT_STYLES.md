# 革命一家ショート 編集スタイル レジストリ (永続)

このファイルは編集スタイルの**永続レジストリ**。Claude Code は毎セッションこのファイルを参照すること (`CLAUDE.md` 経由)。
ユーザーが新しい型を追加・変更したい時は、このファイルを直接編集する。次回以降のEDL生成で自動反映される。

設計パターンは `AUDIO_DESIGN_RULES.md` と同じ二層永続化:
- `CLAUDE.md` ← 起動時自動読込、主要ルール抜粋 + ポインタ
- このファイル ← 型ごとの詳細

---

## ⭐ 共通ベース構造 (全型に適用)

| 要素 | 値 | 出典 |
|---|---|---|
| 出力解像度 | 1080×1920 (縦型 9:16) | render_short.py |
| ベース動画 grade | warm_cinematic | render_short.py |
| 字幕 | `vertical_inside_left_brush` (Yuji Mai 筆フォント) | SUBTITLE_STYLES |
| 字幕累積上限 | 16文字 (オーバーフロー防止) | render_short.py MAX_CUM_CHARS |
| 本編速度 | 1.5x atempo (ピッチ保持) | compose_v2.py step_2 |
| Cold Open 速度 | 1.0x | compose_v2.py step_3 |
| 音響設計 | `AUDIO_DESIGN_RULES.md` 参照 (v7 設定) | publishing/audio/ |
| SFX 配置 | 2秒間隔 (0/2/4/6...) | AUDIO_DESIGN_RULES.md |
| **精密末尾トリム** | **最後の発話直後 (+30〜50ms バッファ) でブツ切り終了** | post-compose ffmpeg `-t` |

各型の差は **EDL の `ranges` の組み方** + **`hook_clip` との関係**だけ。compose_v2.py / render_short.py の改修は基本不要。

### 精密末尾トリムの手順 (全型で必須)

完成 (`short_with_audio.mp4`) 後、以下で末尾の無音 BGM/SFX tail をカット:

1. `ffmpeg -i SHORT.mp4 -af silencedetect=n=-25dB:d=0.15 -f null -` で末尾シレンス検出
2. 最後の `silence_start` 値 = speech 終了時刻 (例: 12.17s)
3. 出力ファイルを `ffmpeg -i SHORT.mp4 -t {speech_end + 0.03〜0.05s} -c:v libx264 -c:a aac OUT.mp4` でトリム
4. **注意**: `loop_friendly_tail` 型では特に重要 — ループ時に [末尾セリフ → 冒頭 hook] が音響的に隙間なく繋がる必要あるため、必ず実施する

**設計上の根拠**: speech 終了後の無音 BGM tail はループ感を弱め、視聴維持率も下げる。viral ショートの常識として「最後の発話の瞬間 = 動画終了」がベスト。

---

## 型 1: `hook_payoff_repeat` — 「回収」型 (既存)

### 思想
強烈なパンチラインを冒頭に出して引きつけ、本編で前提を共有させ、末尾で**同じセリフを再び聞かせて回収**する古典的バイラル構造。

### When to use
- パンチラインが**短く強い**ときに最適 (2-4秒)
- 再聴で意味が深まる insight 系
- 「あ、最初のあれはこういう意味か!」という納得感を作りたい時

### 構造

```
[Cold Open (hook 1.0x)] → [Body 1.5x ending with same hook range] → 終
   ↑                                                        ↑
   ─────────── 同じセリフが2回流れる (1回目1.0x、2回目1.5x) ───
```

EDL での実装:
```json
{
  "style": "hook_payoff_repeat",
  "ranges": [
    {本編ビルドアップ},
    ...
    {hook range}                    ← 本編末尾も hook と同じ範囲
  ],
  "hook_clip": {
    "source_range": {hook range}    ← Cold Open 用、ranges 末尾と一致
  }
}
```

### 例
- 03_NISEMONO (1714.84-1743.92, hook=1740.96-1743.92)
- 06_YUME_WO, 07_ONLY_ONE, 08_OOTANI_HABIT, 09_CHOSHO_KIETA など (既存7本+30s 3本)

---

## 型 2: `loop_friendly_tail` — 「ループ最適化」型 (2026-05-07 新規)

### 思想
ショート動画は**自動ループ再生**される。ループ時に「動画末尾→冒頭」が繋がるとき、それが**元音声と同じ並び**で発話が連続するように設計する。視聴者は「気づかずに何周も見る」状態に陥り、Replay 率と総視聴時間が伸びる。

### When to use
- ループ前提でリーチを伸ばしたいとき
- 元音声で hook の**直前にも自然な setup** がある場合 (元発話の流れを使える)
- 視聴者に「いつ終わったか分からない」体験を作りたい時

### 構造

```
[Cold Open (hook 1.0x)] → [Body 1.5x ending with PRECEDING line of hook in source] → ループ
                                                                                       ↓
                                                                          冒頭 hook へ自然接続
```

具体例 (元音声: ... A → B (hook) → C ...):
- 動画冒頭: [B] (hook 1.0x)
- 動画末尾: [A] (本編末尾、1.5x)
- YouTube ループ時: [A] → [B] = **元音声の自然な並び**で発話が連続 → ループ感が消える

### EDL での実装
```json
{
  "style": "loop_friendly_tail",
  "ranges": [
    {本編ビルドアップ},
    ...
    {hook の直前にあるセリフ範囲}    ← ranges 末尾は hook の直前で終わる
  ],
  "hook_clip": {
    "source_range": {hook range}     ← Cold Open のみに使用、ranges には含めない
  }
}
```

### 「直前セリフ」の特定手順
1. `transcripts/IMG_6372.json` で hook 範囲の `start` 直前の word を遡る
2. 自然な phrase 区切り (silence ≥0.4s or 文末) を見つける
3. その区切り直前までを ranges 末尾の cut の `end` に設定
4. ループ確認: 「[直前末尾] → [hook 冒頭]」が音響的に滑らかか試聴

### 例
- 10_TAMASHII (予定、2026-05-07)
- 11_TOUKOU_BETSU (予定、2026-05-07)

---

## 型の追加方法 (Phase 100 への布石)

新しい型を追加するときは:
1. このファイルに新セクション `## 型 N: <name>` を追加
2. 「思想」「When to use」「構造」「EDL 実装」「例」の5項目を埋める
3. compose_v2.py に分岐ロジックが必要なら、現状の単一パイプラインで複数型を吸収できないか先に検討
4. EDL の `style` フィールドに新名を設定して使用開始

---

## A/B テストの設計

`experiment_arm` を EDL/meta.json に付与して、複数 arm を同時並行で投稿することで**型の効果を比較計測**する。

| arm 例 | 説明 |
|---|---|
| `duration_short` | 既存 7本 (10-18s, hook_payoff_repeat) — baseline |
| `duration_30s` | 30s尺、hook_payoff_repeat (07/08/09) |
| `duration_30s_loop` | 30s尺、loop_friendly_tail (10/11、新規) |

KPI 指標 (post-monitor が 24h/72h で取得):
- `views` — 累計視聴回数
- `averageViewPercentage` — 視聴維持率
- **Replay 率** (loop 型なら高くなるはず — 仮説の中核)
- `likes` / `comments` — エンゲージメント

集計は `publishing/scripts/analyze_ab.py` で arm 別に group by して比較 (今後実装)。

---

## 更新履歴

| 日付 | 変更 |
|---|---|
| 2026-05-07 | 初版作成。型1 (hook_payoff_repeat) と型2 (loop_friendly_tail) を登録 |
