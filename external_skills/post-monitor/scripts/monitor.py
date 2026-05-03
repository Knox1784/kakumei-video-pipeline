#!/usr/bin/env python3
"""
Skill⑦ 投稿後モニタリング

使用例:
  # ヘルスチェック（Data API: 生存確認 + 基本stats）
  python3 monitor.py --health-check VIDEO_ID --token ~/Downloads/clip-army/tokens/default.json

  # Analytics（Analytics API: パフォーマンス分析）
  python3 monitor.py --analytics VIDEO_ID --token ~/Downloads/clip-army/tokens/default.json

  # フルレポート（両方）
  python3 monitor.py --full-report VIDEO_ID --token ~/Downloads/clip-army/tokens/default.json
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
DEFAULT_TOKEN = os.path.expanduser("~/Downloads/clip-army/tokens/default.json")


def get_credentials(token_path):
    """トークンファイルから認証情報を取得。期限切れなら自動リフレッシュ。"""
    token_path = os.path.expanduser(token_path)
    if not os.path.exists(token_path):
        print(f"Error: トークンが見つかりません: {token_path}", file=sys.stderr)
        print(
            "先にSkill⑥のupload.py --authorizeでトークンを取得してください",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        else:
            print("Error: トークンが無効です。再認証してください", file=sys.stderr)
            sys.exit(1)
    return creds


def health_check(youtube, video_ids):
    """Data API v3でヘルスチェック（最大50動画バッチ）"""
    ids_str = ",".join(video_ids) if isinstance(video_ids, list) else video_ids

    response = youtube.videos().list(part="status,statistics", id=ids_str).execute()

    results = []
    found_ids = set()

    for item in response.get("items", []):
        vid = item["id"]
        found_ids.add(vid)
        status = item["status"]
        stats = item["statistics"]

        result = {
            "video_id": vid,
            "upload_status": status.get("uploadStatus", "unknown"),
            "privacy": status.get("privacyStatus", "unknown"),
            "rejection_reason": status.get("rejectionReason"),
            "failure_reason": status.get("failureReason"),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        }
        results.append(result)

    # 見つからなかった動画 = 削除済み
    requested = video_ids if isinstance(video_ids, list) else [video_ids]
    for vid in requested:
        if vid not in found_ids:
            results.append(
                {
                    "video_id": vid,
                    "upload_status": "DELETED",
                    "privacy": "unknown",
                    "views": 0,
                    "likes": 0,
                    "comments": 0,
                }
            )

    return results


def analytics_check(youtube_analytics, video_id, days_back=7):
    """Analytics API v2でパフォーマンス分析"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    try:
        response = (
            youtube_analytics.reports()
            .query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,subscribersGained,subscribersLost",
                filters=f"video=={video_id}",
            )
            .execute()
        )

        if response.get("rows") and len(response["rows"]) > 0:
            headers = [h["name"] for h in response["columnHeaders"]]
            values = response["rows"][0]
            return dict(zip(headers, values))
        else:
            return {"note": "データ未反映（Analytics APIは48-72時間遅延があります）"}

    except Exception as e:
        return {"error": str(e)}


def determine_status(health, analytics=None):
    """ヘルスステータスを判定"""
    if health["upload_status"] == "DELETED":
        return "CRITICAL", "動画が削除されました。Skill⑤の加工品質を見直してください"

    if health["upload_status"] == "rejected":
        reason = health.get("rejection_reason", "不明")
        return "CRITICAL", f"動画が拒否されました: {reason}"

    if health["upload_status"] == "failed":
        reason = health.get("failure_reason", "不明")
        return "ERROR", f"動画の処理が失敗しました: {reason}"

    if health["upload_status"] != "processed":
        return "PENDING", f"処理中: {health['upload_status']}"

    if analytics and "averageViewPercentage" in analytics:
        avg_pct = analytics["averageViewPercentage"]
        if avg_pct > 100:
            return "EXCELLENT", f"ループ再生されています（{avg_pct:.0f}%）"
        elif avg_pct > 70:
            return "GOOD", f"視聴維持率良好（{avg_pct:.0f}%）"
        elif avg_pct < 50:
            return (
                "WARNING",
                f"視聴維持率低下（{avg_pct:.0f}%）。冒頭フック or テンポを改善",
            )

    if health["views"] == 0:
        return "WARNING", "再生数0。投稿直後の可能性。24時間後に再確認推奨"

    return "OK", "正常"


def main():
    parser = argparse.ArgumentParser(description="投稿後モニタリング")
    parser.add_argument("--health-check", metavar="VIDEO_ID", help="ヘルスチェック（Data API）")
    parser.add_argument(
        "--analytics", metavar="VIDEO_ID", help="パフォーマンス分析（Analytics API）"
    )
    parser.add_argument(
        "--full-report", metavar="VIDEO_ID", help="フルレポート（Data + Analytics）"
    )
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="トークンファイルパス")
    args = parser.parse_args()

    if not any([args.health_check, args.analytics, args.full_report]):
        parser.print_help()
        sys.exit(1)

    creds = get_credentials(args.token)

    if args.health_check:
        youtube = build("youtube", "v3", credentials=creds)
        results = health_check(youtube, args.health_check)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif args.analytics:
        youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)
        result = analytics_check(youtube_analytics, args.analytics)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.full_report:
        video_id = args.full_report
        youtube = build("youtube", "v3", credentials=creds)
        youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)

        health_results = health_check(youtube, video_id)
        health = health_results[0] if health_results else {}

        analytics = analytics_check(youtube_analytics, video_id)

        status_level, status_message = determine_status(health, analytics)

        report = {
            "video_id": video_id,
            "status_level": status_level,
            "status_message": status_message,
            "health": health,
            "analytics": analytics,
            "checked_at": datetime.now().isoformat(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
