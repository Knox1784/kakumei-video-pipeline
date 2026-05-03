# post-monitor 自動巡回 (運用メモ)

革命一家チャンネルへ投稿した動画の **24時間後ヘルスチェック / 72時間後 Analytics** を自動化する仕組み。
チーム/自分が「いつ・何が・どこで」走っているか忘れないための要約。

---

## いつ走る?

- **毎日 08:00 (ローカル時刻)** に launchd が `run_monitor.sh` を起動
- ジョブ名: `com.kakumei.postmonitor`
- plist 場所: `~/Library/LaunchAgents/com.kakumei.postmonitor.plist`
- macOSがスリープ中の場合は次回ログイン後に catch-up 実行

## 何を見ている?

`publishing/publishing-state/source-podcast/*.json` を全件 glob して以下を判定:

| 条件 | 動作 |
|---|---|
| `privacy != "public"` | スキップ (unlisted/private は対象外) |
| `made_public_at` (or `posted_at`) から **20〜48h 経過** かつ未実施 | `monitor.py --health-check` 実行 → `health_24h` として追記 |
| 同上で **60〜168h 経過** かつ未実施 | `monitor.py --full-report` 実行 → `full_72h` として追記 |
| 既に同種 `check_type` が `monitor_results` に在る | 冪等スキップ |

## 結果はどこに?

各 `publishing-state/source-podcast/{clip_id}.json` の `monitor_results` 配列に追記:

```json
{
  ...既存フィールド...,
  "monitor_results": [
    {
      "checked_at": "2026-05-02T08:00:01+00:00",
      "hours_since_post": 26.0,
      "check_type": "health_24h",
      "data": {...health_check の生 JSON...},
      "alert_level": "ok|warning|critical|improvement_signal",
      "alert_reason": "..."
    }
  ]
}
```

ログ: `publishing/scripts/logs/monitor_YYYY-MM-DD.log` に日次追記 + launchd の `launchd.{out,err}.log`

## アラート閾値

| 状況 | level |
|---|---|
| `upload_status` が DELETED / rejected / failed | **critical** |
| 24h 時点で views == 0 | **warning** |
| 72h 時点で `averageViewPercentage` < 50% | **improvement_signal** |
| その他 | ok |

critical/warning は stderr + ログに `⚠️  ALERT [...]` で出力される (Slack/メール通知は将来拡張)。

---

## 今後の投稿で自動的に対象化される条件

新しい切り抜きを投稿したら、以下を満たす JSON を `publishing/publishing-state/source-podcast/` に置くだけ:

```json
{
  "clip_id": "...",
  "video_id": "YouTube動画ID",
  "privacy": "public",          ← これが public でないとスキップされる
  "made_public_at": "YYYY-MM-DD" ← この日付から 24h/72h カウント
}
```

それ以外のフィールド (title, channel, tags 等) はモニター動作には不要。

**追加作業ゼロ**: launchd は毎朝勝手に走るので、JSONを置いた翌日には自動的に health_24h、3日後には full_72h が追記される。

---

## 運用コマンド

```bash
# 状態確認
launchctl list | grep kakumei

# 即時実行 (テスト用)
launchctl start com.kakumei.postmonitor

# 経過時間判定をバイパスして強制実行 (検証用、JSON書き込みあり)
python3 publishing/scripts/monitor_runner.py --force

# 書き込みなしの動作確認
python3 publishing/scripts/monitor_runner.py --force --dry-run

# 特定の clip_id だけ
python3 publishing/scripts/monitor_runner.py --only 03_NISEMONO --force

# 一時停止
launchctl unload ~/Library/LaunchAgents/com.kakumei.postmonitor.plist

# 再開
launchctl load ~/Library/LaunchAgents/com.kakumei.postmonitor.plist
```

---

## 制約とスケール上限

| 項目 | 現状 | 限界 |
|---|---|---|
| 対象チャンネル | **kakumei_ikka 1本のみ** (`publishing/tokens/youtube/kakumei_ikka.json` 固定) | 他チャンネル対応は `monitor_runner.py` の TOKEN を JSON 内 `account_id` から動的解決に変更すれば可能 |
| トークン期限 | 7日 (OAuth Testing status) | 期限切れたら全 API 失敗 → upload.py --authorize で再取得 |
| 実行環境 | このMacのlaunchd | スリープ/電源OFFで取りこぼし |
| 並列度 | 順次1本ずつ | 数十本までは数分で終わる |
| 通知 | ログのみ | critical 見落とし可能 |

## Phase 100 (100アカ運用) への移行で必要な変更

1. **GitHub Actions cron** へ移行 (24/365稼働、Mac依存ゼロ)
2. **OAuth Production 昇格** (refresh_token 無期限化)
3. **`monitor_runner.py` のトークン動的解決** (`account_id` ベース)
4. **critical/warning の Slack/Gmail push** 追加

---

## 関連ファイル

- `publishing/scripts/monitor_runner.py` — 巡回ロジック本体
- `publishing/scripts/run_monitor.sh` — launchd 用ラッパ
- `~/.claude/skills/post-monitor/scripts/monitor.py` — 個別 video_id への monitor CLI (改造禁止: 共有 skill)
- `~/Library/LaunchAgents/com.kakumei.postmonitor.plist` — スケジューラ定義
- `publishing/tokens/youtube/kakumei_ikka.json` — OAuth token (両 scopes)
- `publishing/publishing-state/source-podcast/*.json` — 投稿記録 (= モニター対象台帳)
