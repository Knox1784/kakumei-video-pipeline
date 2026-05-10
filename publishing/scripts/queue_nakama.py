#!/usr/bin/env python3
"""
queue_nakama.py — source-nakama_2026-04-25 の 14-23 を publishing/queue/ に投入。

- short_final.mp4 が存在するクリップだけを処理 (未 build はスキップ)
- meta.json は CLIP_META + 共通フィールドで生成
- not_before は仮設定 (5/11 12:00/21:00 から 1日2本ペース)
  → ユーザー時刻指定後は meta.json を直接編集 + 再push

Usage:
  python3 queue_nakama.py
  python3 queue_nakama.py --only 14_TAIYO 15_KYUJUKYU
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHORTS_DIR = ROOT / "source-nakama_2026-04-25/edit/shorts"
QUEUE_DIR = ROOT / "publishing/queue"
RAW_FILENAME = "仲間｜カット＿４・２５（２）.mp4"

COMMON = {
    "account_id": "kakumei_ikka",
    "privacy": "public",
    "source_video": RAW_FILENAME,
    "channel": "革命一家",
    "channel_id": "UCLFDso06pqOYLnXfv5-jDsQ",
    "experiment_arm": "duration_30s_loop_natural",
    "edit_style": "loop_friendly_tail",
}

# 仮スケジュール: 5/11(日) から 1日2本 (12:00 / 21:00)。
# ユーザー時刻指定後はここを編集して再 push。
CLIP_META = {
    "14_TAIYO": {
        "title": "俺という太陽を浴びる人生 #Shorts",
        "description": "革命一家ショウマの podcast 切り抜き。\n「俺という太陽を浴びることによって本当に人生が幸福度高くなった」\n#自分を見つける #ショウマ #革命一家 #太陽 #自尊心",
        "tags": ["Shorts", "革命一家", "ショウマ", "自分を見つける", "太陽", "自尊心", "リーダーシップ"],
        "source_range_summary": "875-911 (太陽論)",
        "duration_s": 25.0,
        "not_before": "2026-05-10T21:00:00+09:00",
    },
    "15_KYUJUKYU": {
        "title": "「99%の庶民みたいに言うのやめよう」 #Shorts",
        "description": "革命一家ショウマの podcast 切り抜き。\nコティの愛あるツッコミ → ショウマ「やめます今すぐ」\n#自分を見つける #ショウマ #革命一家 #謙虚 #99パー庶民",
        "tags": ["Shorts", "革命一家", "ショウマ", "コティ", "謙虚", "ツッコミ", "庶民"],
        "source_range_summary": "1126-1170 (99%庶民、コティのツッコミ)",
        "duration_s": 32.2,
        "not_before": "2026-05-10T23:00:00+09:00",
    },
    "16_KOROSHI": {
        "title": "仲間を下げる奴は、もう、殺しでえ #Shorts",
        "description": "革命一家ショウマの podcast 切り抜き。\n「仲間を下げて自分が助かろうとする人は、もう、殺しでえ」\n#自分を見つける #ショウマ #革命一家 #仲間 #忠誠",
        "tags": ["Shorts", "革命一家", "ショウマ", "仲間", "忠誠", "リーダー論", "経営者"],
        "source_range_summary": "691-720 (殺しでえ宣言)",
        "duration_s": 18.4,
        "not_before": "2026-05-11T21:00:00+09:00",
    },
    "17_SENBAI_GET": {
        "title": "千倍の名誉を得ろう (言い間違い+笑) #Shorts",
        "description": "革命一家ショウマのエンディング「千倍の名誉を得ろう」言い間違い+コティツッコミ\n#自分を見つける #ショウマ #革命一家 #世界を救う英雄",
        "tags": ["Shorts", "革命一家", "ショウマ", "名誉", "英雄", "ミーム", "得ろう"],
        "source_range_summary": "1311-1352 (英雄宣言、千倍の名誉得ろう)",
        "duration_s": 28.3,
        "not_before": "2026-05-11T23:00:00+09:00",
    },
    "18_KAMI_NO_KOE": {
        "title": "神様の声「謙虚、謙虚、謙虚、謙虚」 #Shorts",
        "description": "革命一家ショウマ「神様の声が聞こえる人に言われる、お前は常に謙虚であれ」\n#自分を見つける #ショウマ #革命一家 #謙虚 #神様",
        "tags": ["Shorts", "革命一家", "ショウマ", "謙虚", "神様", "スピリチュアル"],
        "source_range_summary": "1164-1192 (神様の声、謙虚連呼)",
        "duration_s": 21.6,
        "not_before": "2026-05-12T21:00:00+09:00",
    },
    "19_AKUEIKYO": {
        "title": "俺の人生に悪影響を与えた人なんていない #Shorts",
        "description": "革命一家ショウマ「俺の人生に悪影響を与えてきた人なんていなくて、本当にいない」\n#自分を見つける #ショウマ #革命一家 #人間関係",
        "tags": ["Shorts", "革命一家", "ショウマ", "人間関係", "認知", "悪影響"],
        "source_range_summary": "237-271 (悪影響なし論)",
        "duration_s": 24.6,
        "not_before": "2026-05-12T23:00:00+09:00",
    },
    "20_SHIJI_MACHI": {
        "title": "指示待ちなんて俺のチームには一人もいない #Shorts",
        "description": "革命一家ショウマ「自分が今やるべきことは何かっていうことを常に考えられる、行動できる」\n#自分を見つける #ショウマ #革命一家 #チーム論 #経営",
        "tags": ["Shorts", "革命一家", "ショウマ", "チーム論", "経営", "起業家", "自律"],
        "source_range_summary": "992-1024 (指示待ち論)",
        "duration_s": 22.3,
        "not_before": "2026-05-13T21:00:00+09:00",
    },
    "21_LUFFY_10NIN": {
        "title": "ルフィのクルー10人で最高 - エグい景色を見られる #Shorts",
        "description": "革命一家ショウマ「ルフィはあの十人で、クルー十人で最高と思ってる。エグい景色を見られる」\n#自分を見つける #ショウマ #革命一家 #ワンピース #仲間",
        "tags": ["Shorts", "革命一家", "ショウマ", "ワンピース", "ルフィ", "仲間", "エグい"],
        "source_range_summary": "624-658 (ルフィ10人クルー論)",
        "duration_s": 25.5,
        "not_before": "2026-05-13T23:00:00+09:00",
    },
    "22_AISHITERU": {
        "title": "俺がその人たちに一番愛をかけてる #Shorts",
        "description": "革命一家ショウマ「俺がその人たちに一番愛をかけてるってことが一番大きい」\n#自分を見つける #ショウマ #革命一家 #愛 #人間関係",
        "tags": ["Shorts", "革命一家", "ショウマ", "愛", "人間関係", "リーダー"],
        "source_range_summary": "308-338 (一番愛をかけてる論)",
        "duration_s": 20.1,
        "not_before": "2026-05-14T21:00:00+09:00",
    },
    "23_SOBA_HIKUI": {
        "title": "相場より低くても物語についていきたい人 #Shorts",
        "description": "革命一家ショウマ「相場より圧倒的に低い額を提示しても、物語が面白いからついていきたい」\n#自分を見つける #ショウマ #革命一家 #経営者 #採用",
        "tags": ["Shorts", "革命一家", "ショウマ", "経営者", "採用", "選別", "物語"],
        "source_range_summary": "502-540 (相場より低くても文句言わない仲間)",
        "duration_s": 30.5,
        "not_before": "2026-05-14T23:00:00+09:00",
    },
}


def queue_one(clip_id: str) -> bool:
    short_final = SHORTS_DIR / clip_id / "short_final.mp4"
    if not short_final.exists():
        print(f"⏸  {clip_id}: short_final.mp4 not yet built → skipped")
        return False
    if clip_id not in CLIP_META:
        print(f"❌ {clip_id}: no meta defined")
        return False

    queue_id = QUEUE_DIR / clip_id
    queue_id.mkdir(parents=True, exist_ok=True)

    # Copy short.mp4
    shutil.copy(short_final, queue_id / "short.mp4")

    # Compose meta.json
    meta = {"clip_id": clip_id, **COMMON, **CLIP_META[clip_id]}
    (queue_id / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ queued {clip_id}: not_before={CLIP_META[clip_id].get('not_before')} | {CLIP_META[clip_id]['title'][:40]}...")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="+", help="Only process these IDs")
    args = p.parse_args()

    targets = args.only or list(CLIP_META.keys())
    placed = 0
    for clip_id in targets:
        if queue_one(clip_id):
            placed += 1
    print(f"\n=== {placed}/{len(targets)} queued ===")


if __name__ == "__main__":
    main()
