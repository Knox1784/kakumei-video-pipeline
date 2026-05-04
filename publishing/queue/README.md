# 投稿キュー (発射台)

このディレクトリに `{clip_id}/short.mp4` + `{clip_id}/meta.json` を置くと、
GitHub Actions が `publishing/posting_schedule.yaml` で定義されたスロット時刻に1本ずつ自動投稿する。

## 使い方

1. クリップを作る (今まで通り `compose_v2.py` 等で `short_with_audio.mp4` 完成)
2. queue にディレクトリを作って配置:
   ```bash
   mkdir publishing/queue/{clip_id}
   cp source-podcast/edit/shorts_v2/{clip_id}/short_with_audio.mp4 \
      publishing/queue/{clip_id}/short.mp4
   ```
3. `meta.json` を作成 (下記スキーマ)
4. `git add publishing/queue/{clip_id}/ && git commit && git push`
5. 次のスロットで自動投稿される

## 処理順 (FIFO)

ディレクトリ名の **文字列昇順**。先に出したい本は数字プレフィックスを小さく付けてリネーム:
- `01_KAGAMI` → `04_NEKO` の順で消化
- 飛び込みで最優先したいなら `00_URGENT_*` のようにリネーム

## meta.json スキーマ

```json
{
  "clip_id": "08_NEW_CLIP",
  "title": "タイトル #Shorts",
  "description": "説明文\n#自分を見つける #ショウマ #革命一家",
  "tags": ["Shorts", "革命一家", "ショウマ", "..."],
  "account_id": "kakumei_ikka",
  "privacy": "public",
  "source_video": "IMG_6372.MOV",
  "source_range_summary": "1714-1742 (multi-segment)",
  "duration_s": 12.9,
  "channel": "革命一家",
  "channel_id": "UCLFDso06pqOYLnXfv5-jDsQ"
}
```

| フィールド | 必須 | 内容 |
|---|---|---|
| `clip_id` | ✅ | 一意ID。`publishing-state/{clip_id}.json` のファイル名になる |
| `title` | ✅ | YouTube タイトル (100文字以下) |
| `description` | 推奨 | 説明文 |
| `tags` | 推奨 | カンマ区切りタグ |
| `account_id` | ✅ | `publishing/tokens/youtube/{account_id}.json` のファイル名と一致 |
| `privacy` | デフォルト public | `public` / `unlisted` / `private` |
| `source_video` ほか | 推奨 | 後の analytics 改善ループで参照 |

## スロット時刻

現在の運用 (`publishing/posting_schedule.yaml`):
- 07:30 / 12:00 / 19:00 / 21:00 JST

スロット変更時は `posting_schedule.yaml` + `.github/workflows/auto_post.yml` の cron 行を**両方**編集。

## 動作仕様

- queue が空のスロット → スキップ (no-op)
- 1スロット = 1本まで (`already_posted_in_slot` チェックで二重投稿防止)
- 投稿成功: queue ディレクトリ削除 + `publishing-state/source-podcast/{clip_id}.json` 生成 + git push
- 投稿失敗: GitHub Issue が自動作成される (label: `auto-post-failure`)

## トラブルシューティング

- **トークン期限切れ (Testing OAuth)**: 7日経過で refresh_token 失効 → `external_skills/youtube-uploader/scripts/upload.py --authorize` で再取得 → `kakumei_ikka.json` の中身を GitHub Secret `KAKUMEI_IKKA_TOKEN` に再登録
- **Quota 超過**: 1日 6本 (10000 unit / 1600 unit per upload)。スロット4本運用なら通常到達しない
