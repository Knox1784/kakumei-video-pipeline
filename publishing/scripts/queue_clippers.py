#!/usr/bin/env python3
"""
queue_clippers.py — source-clippers_2026-05-15 を publishing/queue/ に投入。

5本ずつバッチで追加投入する設計 (1本テスト → 4本 → 残りに展開、 で随時 not_before 更新)。
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHORTS_DIR = ROOT / "source-clippers_2026-05-15/edit/shorts"
QUEUE_DIR = ROOT / "publishing/queue"
RAW_FILENAME = "クリッパー集団計画.mp4"

COMMON = {
    "account_id": "kakumei_ikka",
    "privacy": "public",
    "source_video": RAW_FILENAME,
    "channel": "革命一家",
    "channel_id": "UCLFDso06pqOYLnXfv5-jDsQ",
    "experiment_arm": "duration_15to25s_loop_natural_clippers",
    "edit_style": "loop_friendly_tail",
}

# 5/15(木) 23:00 から開始、 以降は 21:00/23:00 ペース
CLIP_META = {
    "24_ELON_VISION": {
        "title": "俺らイーロンマスクに見せる映像を作る #Shorts",
        "description": "革命一家ショウマ「優秀なクリッパー集団は相手が何を売りたいかを理解する。 イーロンマスクに見せる映像を、 物語を設計する」\n#自分を見つける #ショウマ #革命一家 #クリッパー集団計画 #イーロンマスク",
        "tags": ["Shorts", "革命一家", "ショウマ", "クリッパー", "イーロンマスク", "マーケティング", "物語設計"],
        "source_range_summary": "824-855 (イーロンマスクに見せる映像、 物語設計)",
        "duration_s": 21.96,
        "not_before": "2026-05-15T23:00:00+09:00",
    },
    "25_ICHIOKU_OKR": {
        "title": "あと半年で一億円の利益を上げたい #Shorts",
        "description": "革命一家ショウマ「クリッパーはバックエンド商品。 あと半年で一億円の利益を上げたい」\n#自分を見つける #ショウマ #革命一家 #クリッパー集団計画 #一億円",
        "tags": ["Shorts", "革命一家", "ショウマ", "クリッパー", "一億円", "ビジネスモデル"],
        "source_range_summary": "242-264 (バックエンド商品、 一億円目標)",
        "duration_s": 13.97,
        "not_before": "2026-05-16T21:00:00+09:00",
    },
    "26_30000HON": {
        "title": "月3万6千本、 一日360本量産できる #Shorts",
        "description": "革命一家ショウマ「素材が無限にあったら月3万6千本量産できる、 一日360本。 一から二位からマジ出せるんよ」\n#自分を見つける #ショウマ #革命一家 #クリッパー集団計画 #量産",
        "tags": ["Shorts", "革命一家", "ショウマ", "クリッパー", "量産", "AI", "スケール"],
        "source_range_summary": "588-624 (月3万6千本量産論)",
        "duration_s": 24.19,
        "not_before": "2026-05-16T23:00:00+09:00",
    },
    "27_BOSHARU": {
        "title": "ボシャるじゃなくてポシャルじゃね？(笑) #Shorts",
        "description": "革命一家ショウマの言い間違い「ボシャる」 → コタカ突っ込み「ポシャルじゃね？」 笑い込み\n#自分を見つける #ショウマ #革命一家 #クリッパー集団計画 #ぽしゃる",
        "tags": ["Shorts", "革命一家", "ショウマ", "コタカ", "言い間違い", "ミーム"],
        "source_range_summary": "1435-1460 (リーダー責任論 + 言い間違い)",
        "duration_s": 16.73,
        "not_before": "2026-05-17T21:00:00+09:00",
        "target_slot": "21:00",
    },
    "28_ZERO_KIKAN": {
        "title": "一本目からお金もらえるのがエグい #Shorts",
        "description": "革命一家コタカ「クリッパー集団なら、 一本目の動画からお金もらえる。 ゼロ円期間がない。 動画素材ももらえる、 編集と投稿の手間だけ」\n#自分を見つける #ショウマ #革命一家 #クリッパー集団計画 #成果報酬",
        "tags": ["Shorts", "革命一家", "ショウマ", "コタカ", "クリッパー", "成果報酬", "ゼロ円"],
        "source_range_summary": "1216-1238 (ゼロ円期間なし)",
        "duration_s": 14.99,
        "not_before": "2026-05-17T23:00:00+09:00",
        "target_slot": "23:00",
    },
}


def queue_one(clip_id: str) -> bool:
    short_final = SHORTS_DIR / clip_id / "short_final.mp4"
    if not short_final.exists():
        print(f"⏸  {clip_id}: short_final.mp4 not built")
        return False
    if clip_id not in CLIP_META:
        print(f"❌ {clip_id}: no meta defined")
        return False
    queue_id = QUEUE_DIR / clip_id
    queue_id.mkdir(parents=True, exist_ok=True)
    shutil.copy(short_final, queue_id / "short.mp4")
    meta = {"clip_id": clip_id, **COMMON, **CLIP_META[clip_id]}
    (queue_id / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ queued {clip_id}: not_before={CLIP_META[clip_id]['not_before']} | {CLIP_META[clip_id]['title'][:40]}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="+", help="Only process these IDs")
    args = p.parse_args()
    targets = args.only or list(CLIP_META.keys())
    placed = 0
    for cid in targets:
        if queue_one(cid):
            placed += 1
    print(f"\n=== {placed}/{len(targets)} queued ===")


if __name__ == "__main__":
    main()
