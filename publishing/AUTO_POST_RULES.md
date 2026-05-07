# YouTube 自動投稿システム (発射台モデル)

GitHub Actions で「queue にあれば、決まった時刻に自動投稿」する仕組み。

## アーキ

```
queue に動画+meta 置く → git push → GHA cron → YouTube 投稿 (public) → publishing-state 生成 + push back → ローカル post-monitor が翌朝対象化
```

## 投稿スロット (JST、2026-05-07 拡張)

| 時刻 | 用途 |
|---|---|
| **07:30** | 通勤・登校時のスマホピーク |
| **12:00** | ランチ休憩中の最頻ピーク |
| **19:00** | 帰宅後リラックスタイム |
| **21:00** | 夜メイン1 (曜日横断の最強ピーク、自社データで実証) |
| **22:00** | 夜メイン2 (21時の余熱・寝る前1stチェック) |
| **23:00** | 夜遅 (寝落ち前の最後の一本) |

- 1スロット = 最大1本投稿、queue 空ならスキップ
- ±60分の窓内で発火 (GHA cron 遅延吸収、実測45分遅延あり)
- スロット変更は `posting_schedule.yaml` + `.github/workflows/auto_post.yml` の cron 行を**両方**編集
- 拡張根拠: 自社実投稿データで 21時台 = 1100〜4370 views/日で他帯を圧勝 → 夜帯を厚く取る方針

## 動画を投稿する手順

1. `publishing/queue/{clip_id}/short.mp4` を配置
2. 同ディレクトリに `meta.json` 作成 (スキーマは `publishing/queue/README.md` 参照)
3. `git add publishing/queue/{clip_id}/ && git commit && git push`
4. 次のスロットで自動投稿される

**処理順 = ディレクトリ名昇順** (FIFO)。先に出したい本は数字プレフィックスを小さく付ける (`01_`, `02_`...)。

## 新アカウント追加手順 (Phase 100 拡張)

1. Google Cloud で OAuth トークン取得 → `external_skills/youtube-uploader/scripts/upload.py --authorize`
2. GitHub Secret に登録 — **命名規則: `YT_TOKEN_<ACCOUNT_ID_UPPER>`**
   例: `YT_TOKEN_YOURESHOMA`, `YT_TOKEN_IM_SHOMA`
3. `.github/workflows/auto_post.yml` の `Restore tokens from secrets` ステップに env 1行追加:
   ```yaml
   YT_TOKEN_YOURESHOMA: ${{ secrets.YT_TOKEN_YOURESHOMA }}
   ```
4. meta.json で `"account_id": "youreshoma"` を指定すれば自動でそのトークン使用

## 失敗時の確認

- **GitHub Issue 自動作成**: Actions が失敗すると `auto-post-failure` ラベル付き Issue が立つ
- **手動で Actions タブ確認**: https://github.com/Knox1784/kakumei-video-pipeline/actions
- **トークン期限切れ (7日 / Testing OAuth status)**:
  ```bash
  python3 external_skills/youtube-uploader/scripts/upload.py --authorize \
    --token publishing/tokens/youtube/{account_id}.json
  cat publishing/tokens/youtube/{account_id}.json | pbcopy
  # → GitHub Secret YT_TOKEN_<ACCOUNT_UPPER> を Update で更新
  ```

## 重要ファイル

| ファイル | 役割 |
|---|---|
| `publishing/posting_schedule.yaml` | スロット定義 (machine readable) |
| `publishing/scripts/dispatch_queue.py` | スロット判定 + queue 消化ロジック |
| `.github/workflows/auto_post.yml` | GHA cron + token 復元 + Issue 通知 |
| `publishing/queue/{clip_id}/` | 投稿待ちの動画 + meta.json |
| `publishing/publishing-state/source-podcast/` | 投稿後の記録 (post-monitor が読む) |
| `publishing/scripts/monitor_runner.py` | launchd で動く 24h/72h 自動モニター (`git pull` で GHA push を取り込む) |

## スケール上限と移行ポイント

- **現状 (Phase 1)**: GitHub Secrets 直接管理、video を git にコミット、launchd で post-monitor
- **Phase 100 (~100アカ運用) で必要な進化**:
  - Secret 管理 → 外部 (AWS Secrets Manager / 1Password) に移行 (100個手動は破綻)
  - 動画ストレージ → R2/S3 移行 (repo size 1GB 警告超え予想)
  - OAuth → Production 昇格 (verification 必要、現在 Testing で 7日 refresh 失効)
  - post-monitor → GHA workflow 化 (Mac 完全離脱)

詳細運用 (queue meta.json スキーマ等) は `publishing/queue/README.md` 参照。
