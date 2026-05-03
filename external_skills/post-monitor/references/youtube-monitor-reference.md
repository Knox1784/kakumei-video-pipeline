# YouTube 投稿後モニタリング リファレンス（Claude Code実行用）

> YouTube Data API v3 + YouTube Analytics API v2を使った投稿後ヘルスチェック・パフォーマンス分析。
> 最終更新: 2026-04-15

---

## 1. 2つのAPIの使い分け

| | Data API v3 | Analytics API v2 |
|--|------------|-----------------|
| 目的 | 動画の生死・ステータス確認 | パフォーマンス分析 |
| データ | uploadStatus, rejectionReason, views, likes | 平均視聴時間, 視聴維持率, トラフィックソース, engagedViews |
| データ遅延 | **リアルタイム** | **48-72時間遅延** |
| クォータ | 10,000ユニット/日（Skill⑥と共有） | **別枠クォータ** |
| スコープ | `youtube` | `yt-analytics.readonly` |

### チェックタイミングと使用API

| タイミング | API | チェック内容 |
|-----------|-----|------------|
| **24時間後** | Data APIのみ | 生存確認 + views/likes |
| **48時間後** | Data API + Analytics API | 生存 + 初動パフォーマンス |
| **72時間後** | Data API + Analytics API | 生存 + 詳細分析 |

---

## 2. Data API v3 — ヘルスチェック

### 基本クエリ

```python
from googleapiclient.discovery import build

youtube = build("youtube", "v3", credentials=creds)

response = youtube.videos().list(
    part="status,statistics",
    id="VIDEO_ID"  # カンマ区切りで最大50個
).execute()
```

**コスト**: 1ユニット/回（最大50動画をバッチ処理可能）

### レスポンス解析

```python
if not response["items"]:
    # 動画が存在しない = 削除された
    status = "DELETED"
else:
    item = response["items"][0]
    upload_status = item["status"]["uploadStatus"]
    privacy = item["status"]["privacyStatus"]
    views = int(item["statistics"].get("viewCount", 0))
    likes = int(item["statistics"].get("likeCount", 0))
```

### uploadStatus の値

| 値 | 意味 | 対応 |
|----|------|------|
| `processed` | 正常（視聴可能） | OK |
| `uploaded` | アップロード済み（処理中） | 待機 |
| `rejected` | 拒否された | rejectionReasonを確認 |
| `failed` | 処理失敗 | failureReasonを確認 |
| (items空) | 削除された | アラート |

### rejectionReason の値

| 値 | 意味 |
|----|------|
| `claim` | 著作権クレーム |
| `copyright` | 著作権違反 |
| `duplicate` | 重複コンテンツ |
| `inappropriate` | 不適切なコンテンツ |
| `termsOfUse` | 利用規約違反 |
| `uploaderAccountSuspended` | アカウント停止 |

### API非対応の検出項目（重要）

以下は**APIでは検出できない**。メール通知とYouTube Studio目視に依存:
- コミュニティガイドライン違反ストライク
- 「reused content」フラグ
- 「inauthentic content」フラグ
- 収益化ステータスの変更

---

## 3. Analytics API v2 — パフォーマンス分析

### サービス構築

```python
youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)
```

同じOAuth credentialsで Data API と Analytics API の両方を構築できる。

### 基本クエリ

```python
response = youtube_analytics.reports().query(
    ids="channel==MINE",
    startDate="2026-04-14",
    endDate="2026-04-15",
    metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,subscribersGained,subscribersLost",
    filters="video==VIDEO_ID"
).execute()
```

**コスト**: 1ユニット/回（Data APIとは別枠クォータ）

### 主要メトリクス

| メトリクス | 説明 | Shorts重要度 |
|-----------|------|-------------|
| `views` | 総再生数 | ★★★ |
| `engagedViews` | 収益化対象の再生数（2025年3月〜） | ★★★ |
| `estimatedMinutesWatched` | 総視聴時間（分） | ★★ |
| `averageViewDuration` | 平均視聴時間（秒） | ★★★ |
| `averageViewPercentage` | 平均視聴維持率（%）。**100%超=ループ再生** | ★★★★★ |
| `likes` | いいね数 | ★★ |
| `comments` | コメント数 | ★★ |
| `subscribersGained` | 登録者増加数 | ★★★ |
| `subscribersLost` | 登録者減少数 | ★★ |

### Shorts専用フィルタ

```python
response = youtube_analytics.reports().query(
    ids="channel==MINE",
    startDate="2026-04-14",
    endDate="2026-04-15",
    metrics="views,engagedViews,averageViewPercentage",
    dimensions="creatorContentType",
    filters="creatorContentType==SHORTS"
).execute()
```

### レスポンス形式

```python
{
    "columnHeaders": [
        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
        ...
    ],
    "rows": [
        [1234, 567, 45.2, 112.5, ...]  # 値の配列
    ]
}
```

---

## 4. Shorts固有の分析指標

### 最重要: averageViewPercentage

- **100%超え = ループ再生されている** → バズの兆候
- 70-100% = 良好。視聴者が最後まで見ている
- 50-70% = 普通
- 50%未満 = 冒頭フックが弱い or テンポに問題

### engagedViews（2025年3月〜）

- Shortsの「再生」と「エンゲージド再生」は別カウント
- 再生: スタートした瞬間にカウント
- エンゲージド再生: 数秒以上視聴 or いいね/コメントした場合のみ
- 収益化はengagedViewsベース

### API非対応の指標（YouTube Studioのみ）

- スワイプ率（Viewed vs Swiped Away）
- リミックス数
- Shortsフィード詳細インプレッション

---

## 5. ヘルスステータス判定ロジック

```python
def determine_status(data_api_result, analytics_result=None):
    if data_api_result["status"] == "DELETED":
        return "CRITICAL", "動画が削除されました。Skill⑤の加工品質を見直してください"
    
    if data_api_result["status"] == "REJECTED":
        reason = data_api_result.get("rejection_reason", "不明")
        return "CRITICAL", f"動画が拒否されました: {reason}"
    
    if data_api_result["views"] == 0 and hours_since_upload > 24:
        return "WARNING", "24時間経過しても再生数0。シャドウBANの可能性"
    
    if analytics_result:
        avg_pct = analytics_result.get("averageViewPercentage", 0)
        if avg_pct > 100:
            return "EXCELLENT", f"ループ再生されています（{avg_pct:.0f}%）"
        elif avg_pct > 70:
            return "GOOD", f"視聴維持率良好（{avg_pct:.0f}%）"
        elif avg_pct < 50:
            return "WARNING", f"視聴維持率低下（{avg_pct:.0f}%）。冒頭フック or テンポを改善"
    
    return "OK", "正常"
```

---

## 6. やってはいけないこと

1. **24時間後にAnalytics APIを叩かない**: データ遅延48-72時間。ゼロが返るだけ
2. **500動画を1つずつ確認しない**: Data APIは`id=ID1,ID2,...`で最大50個バッチ処理
3. **ポリシー違反フラグのAPI検出に頼らない**: reused content/inauthentic contentフラグはAPI非対応。メール通知とStudio確認が必要
4. **Analytics APIのクエリを頻繁に叩かない**: データは1日1回更新。同じ日に何度叩いても同じ結果
5. **averageViewPercentageが低い動画を放置しない**: Skill③の判定基準かSkill⑤のテロップ/テンポを改善するフィードバックを出す
