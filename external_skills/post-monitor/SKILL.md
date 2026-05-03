---
name: post-monitor
description: 投稿済みYouTube動画のヘルスチェックとパフォーマンス分析を行う。Data API v3で生存確認、Analytics API v2で視聴維持率・トラフィック分析。
  Use this skill whenever the user says '動画の状態を確認して', 'ヘルスチェックして',
  'この動画は生きてる？', 'パフォーマンスを見て', 'check video status',
  'monitor this video', '投稿後のチェックをして', 'この動画のアナリティクスを見て',
  '24時間チェックして', '72時間チェックして', '動画が消されてないか確認'.
  Also activate when the user provides a YouTube video ID and asks for status check or analytics.
  Do NOT use this skill for downloading, transcription, clip detection, video cutting,
  transformation, or uploading.
---

## Overview

このSkillは投稿済みYouTube動画のヘルスチェック（生存確認）とパフォーマンス分析を行う。パイプラインの最後のステップ（Skill⑦）であり、Skill⑤（transformation品質）へのフィードバックループを形成する。

2つのAPIを使い分ける:
- **Data API v3**: 生存確認（削除・拒否検出）+ 基本stats（リアルタイム）
- **Analytics API v2**: 視聴維持率・トラフィックソース・登録者増減（48-72時間遅延）

実行前に `references/youtube-monitor-reference.md` を読んで、APIの使い分けと注意事項を確認すること。

## Workflow

1. ユーザーからVideo ID（Skill⑥の出力）を受け取る。

2. チェックの種類を判断する:
   - **ヘルスチェック**（投稿直後〜24時間）: Data APIのみ
   - **パフォーマンス分析**（48時間以降）: Data API + Analytics API
   - **フルレポート**: 両方まとめて

3. ヘルスチェックを実行:
   ```bash
   python3 ~/.claude/skills/post-monitor/scripts/monitor.py \
     --health-check VIDEO_ID \
     --token ~/Downloads/clip-army/tokens/default.json
   ```

4. パフォーマンス分析を実行（48時間以降のみ）:
   ```bash
   python3 ~/.claude/skills/post-monitor/scripts/monitor.py \
     --analytics VIDEO_ID \
     --token ~/Downloads/clip-army/tokens/default.json
   ```

5. フルレポートを実行:
   ```bash
   python3 ~/.claude/skills/post-monitor/scripts/monitor.py \
     --full-report VIDEO_ID \
     --token ~/Downloads/clip-army/tokens/default.json
   ```

6. 結果を解釈し、ユーザーに報告:
   - **CRITICAL**: 動画削除 or 拒否 → Skill⑤の加工品質を見直す提案
   - **WARNING**: 再生数0 or 視聴維持率低下 → 原因と改善提案
   - **GOOD/EXCELLENT**: 正常 or ループ再生 → 好調の報告
   - Analytics未反映の場合: 「データは48-72時間遅延があります」と説明

## Output Format

### ヘルスチェック結果

```
ヘルスチェック結果:
- Video ID: {video_id}
- ステータス: {upload_status}（processed = 正常）
- 公開状態: {privacy}
- 再生数: {views}
- いいね: {likes}
- コメント: {comments}
```

### フルレポート

```
フルレポート:
- Video ID: {video_id}
- 判定: {status_level}（{status_message}）
- 再生数: {views}
- 平均視聴維持率: {averageViewPercentage}%（100%超=ループ再生）
- 平均視聴時間: {averageViewDuration}秒
- 登録者増減: +{gained} / -{lost}
- 確認日時: {checked_at}
```

## Edge Cases

- **動画が削除されている（items空）**: 「CRITICAL: 動画が削除されました」と報告。Skill⑤の加工品質レビューを提案。
- **動画が拒否された（rejected）**: rejectionReasonを報告（copyright, duplicate, inappropriate等）。
- **Analytics APIデータが未反映**: 48-72時間遅延のため。「データ未反映」と報告し、後日再チェックを案内。
- **24時間後にAnalytics APIを叩く要求**: 「データ遅延のためData APIのみでチェックします」と説明。
- **複数動画の一括チェック**: Data APIは最大50動画をバッチ処理可能。1つずつ叩かない。
- **reused content / inauthentic contentフラグ**: APIでは検出不可。「メール通知とYouTube Studioで確認してください」と案内。
- **トークン期限切れ**: 自動リフレッシュ。失敗時は再認証を案内。
