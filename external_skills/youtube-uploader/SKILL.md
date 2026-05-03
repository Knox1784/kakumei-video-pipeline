---
name: youtube-uploader
description: 完成版ショートMP4をYouTube Data API v3でアップロードする。OAuth認証、メタデータ自動生成、resumable upload対応。
  Use this skill whenever the user says 'YouTubeにアップロードして', 'この動画を投稿して',
  'upload this to YouTube', 'この動画をアップして', 'YouTubeに上げて',
  'この動画を公開して', 'Shortsとして投稿して', 'アップロードして'.
  Also activate when the user provides a short MP4 path and asks for YouTube upload.
  Do NOT use this skill for downloading (source-downloader), transcription (transcriber),
  clip detection (clip-detector), video cutting (clip-extractor), or transformation (transformer).
---

## Overview

このSkillは完成版ショートMP4をYouTube Data API v3でアップロードする。パイプラインの6番目のステップ（Skill⑥）。

実行前に `references/youtube-api-reference.md` を読んで、APIのクォータと注意事項を確認すること。

**重要: テスト時は必ずprivacyStatus=privateでアップロードする。**

## Workflow

1. ユーザーからショートMP4パスを受け取る。ファイルが存在し、MP4であることを確認する。通常は `~/Downloads/clip-army/shorts/{videoID}_short{N}.mp4`。

2. メタデータを生成する:
   - **タイトル**: ソース動画の `.info.json` からタイトル・チャンネル名を参照し、クリップ内容に合った短いタイトルを生成。末尾に `#Shorts` を含める。最大100文字。
   - **説明**: ソース情報（元動画タイトル・チャンネル・URL）+ `#Shorts` + 関連ハッシュタグ。最大5000文字。
   - **タグ**: ソース動画のtags + 関連キーワード。

3. トークンファイルの存在確認:
   - デフォルト: `~/Downloads/clip-army/tokens/default.json`
   - アカウント指定時: `~/Downloads/clip-army/tokens/{account_id}.json`
   - トークンがない場合: `--authorize` で初回認証を案内する。

4. アップロードスクリプトを実行:
   ```bash
   python3 ~/.claude/skills/youtube-uploader/scripts/upload.py \
     --video "/path/to/short.mp4" \
     --title "タイトル #Shorts" \
     --description "説明文 #Shorts" \
     --tags "tag1,tag2" \
     --privacy private \
     --token ~/Downloads/clip-army/tokens/default.json
   ```

5. アップロード結果を報告:
   - video ID
   - URL (`https://youtube.com/shorts/{video_id}`)
   - チャンネル名
   - 公開状態（private / unlisted / public）

## Output Format

ユーザーへの報告フォーマット:

```
アップロード完了:
- Video ID: {video_id}
- URL: https://youtube.com/shorts/{video_id}
- チャンネル: {channel_name}
- 公開状態: {privacy}
- タイトル: {title}
```

## Edge Cases

- **トークンファイルが存在しない**: `--authorize`で初回認証を案内する。ブラウザが開きGoogleアカウントで承認するフロー。
- **トークン期限切れ**: スクリプトが自動でリフレッシュする。リフレッシュトークンも失効している場合は再認証を案内。
- **クォータ超過（403 quotaExceeded）**: 「クォータ超過。太平洋時間0:00（日本時間16:00-17:00）にリセット」と報告。次の日に再試行。
- **コンプライアンス監査未完了**: 全動画がprivateにロックされる。ユーザーに監査完了を案内。
- **ネットワーク中断**: resumable uploadが自動でリトライ（指数バックオフ、最大5回）。
- **タイトルが100文字超**: 自動で100文字に切り詰め。
- **同じ動画の重複アップロード**: YouTubeが重複検出する可能性あり。警告を出す。
- **publicでのアップロード要求**: テスト段階では「まずprivateでテストしてから公開しましょう」と提案。
