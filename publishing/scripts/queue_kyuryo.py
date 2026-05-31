#!/usr/bin/env python3
"""queue_kyuryo.py — source-kyuryo_2026-05-31 の 02-15 を publishing/queue/ に投入。

1日2本 (22:00 / 23:00) を 2026-06-01〜06-07 に段階配信。
not_before + target_slot を仕込むので、全14本を一括 push しても GHA が
毎日2本ずつ自動公開する (「発射台」モデル)。01_NARIAGARE は 5/31 投稿済み。
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHORTS = ROOT / "source-kyuryo_2026-05-31/edit/shorts"
QUEUE = ROOT / "publishing/queue"

COMMON = {
    "account_id": "kakumei_ikka",
    "privacy": "public",
    "source_video": "給料のあげかた.mov",
    "channel": "革命一家",
    "channel_id": "UCLFDso06pqOYLnXfv5-jDsQ",
    "experiment_arm": "duration_15to25s_loop_natural_kyuryo",
    "edit_style": "loop_friendly_tail",
}

HASH = "#給料の上げ方 #未来の総理大臣 #因幡匠瞬 #革命一家"
BASETAGS = ["Shorts", "革命一家", "因幡匠瞬", "未来の総理大臣", "給料の上げ方"]


def _m(title, desc, extra_tags, dur, nb, slot):
    return {
        "title": title,
        "description": f"{desc}\n{HASH}",
        "tags": BASETAGS + extra_tags,
        "duration_s": dur,
        "not_before": nb,
        "target_slot": slot,
    }


CLIP_META = {
    "02_GANBARU_GOMI": _m("頑張ったらお金が増える、はゴミ #Shorts",
        "「頑張ったらお金が増える」その考え方はゴミです。給料の本質を因幡匠瞬が解説。",
        ["努力", "正社員", "ビジネス"], 16.37, "2026-06-01T22:00:00+09:00", "22:00"),
    "03_GOMI_KASU": _m("ゴミです。カスです。【正社員の現実】 #Shorts",
        "「報われない」と嘆く前に。正社員の現実を一刀両断。",
        ["正社員", "キャリア", "年収"], 22.27, "2026-06-01T23:00:00+09:00", "23:00"),
    "04_SHACHO_KYAKU": _m("あなたの最初の客は「社長」だった #Shorts",
        "あなたの最初のお客さんは、患者でも家族でもなく「社長」。給料が上がる人の視点。",
        ["社長", "出世", "ビジネス"], 13.67, "2026-06-02T22:00:00+09:00", "22:00"),
    "05_TAKOYAKI_AI": _m("たこ焼き焼いてる場合じゃない #Shorts",
        "たこ焼きを無限に焼いても稼ぎは頭打ち。今集中すべきはAI。",
        ["AI", "選択と集中", "効率化"], 13.03, "2026-06-02T23:00:00+09:00", "23:00"),
    "06_IGAKU_TAKOYAKI": _m("医者とたこ焼きが同じ給料 #Shorts",
        "医者1回の手術と、たこ焼き売りまくり。実は同じ給料になる理由。",
        ["お金", "ビジネスモデル", "年収"], 19.29, "2026-06-03T22:00:00+09:00", "22:00"),
    "07_SHACHO_TODOKAZU": _m("あなたの頑張り、社長には見えていない #Shorts",
        "どんな良い提案も社長には届かない。新入社員が知るべき現実。",
        ["正社員", "評価", "キャリア"], 14.03, "2026-06-03T23:00:00+09:00", "23:00"),
    "08_SNS_SEIKOSHA": _m("SNSは成功者しか映さない #Shorts",
        "なぜ続かない？SNSは「成功した後」しか映さないから。",
        ["SNS", "努力", "継続"], 18.17, "2026-06-04T22:00:00+09:00", "22:00"),
    "09_SENTAKU_SHUCHU": _m("何をやらないかを決めろ #Shorts",
        "給料を上げる第一歩は「何をやらないか」を決めること。",
        ["選択と集中", "優先順位", "仕事術"], 13.49, "2026-06-04T23:00:00+09:00", "23:00"),
    "10_KANKYO_KAERO": _m("やり切って無理なら、環境を変えろ #Shorts",
        "やり切って無理なら環境を変えろ。逃げ癖との決定的な違い。",
        ["転職", "環境", "自己責任"], 19.19, "2026-06-05T22:00:00+09:00", "22:00"),
    "11_ONLYONE": _m("替えが効かない人になれ #Shorts",
        "階層で給料が決まる時代は終わり。替えが効かないオンリーワンになれ。",
        ["オンリーワン", "差別化", "AI時代"], 20.13, "2026-06-05T23:00:00+09:00", "23:00"),
    "12_MECHABURI": _m("メチャブリをもらえる場所に行け #Shorts",
        "時代の流れを読んで、メチャブリをもらえる若い会社へ行け。",
        ["環境", "成長", "キャリア"], 17.97, "2026-06-06T22:00:00+09:00", "22:00"),
    "13_YOUYAKU_KYURYO": _m("これでようやく給料が上がる #Shorts",
        "決裁者の利益を解像度高く動かす。これでようやく給料が上がる。",
        ["給料", "利益", "出世"], 13.73, "2026-06-06T23:00:00+09:00", "23:00"),
    "14_TEKO_GENRI": _m("給料の正体は「テコの原理」 #Shorts",
        "給料の正体はテコの原理。利益直結のKPIを見極めろ。",
        ["KPI", "ビジネス", "年収"], 14.77, "2026-06-07T22:00:00+09:00", "22:00"),
    "15_ICHIBYO": _m("その一秒一秒を続けろ #Shorts",
        "一年後の決算じゃない。今日の一秒一秒の行動を続けろ。",
        ["努力", "継続", "成功"], 22.66, "2026-06-07T23:00:00+09:00", "23:00"),
}


def queue_one(clip_id: str) -> bool:
    sf = SHORTS / clip_id / "short_final.mp4"
    if not sf.exists():
        print(f"⏸  {clip_id}: short_final.mp4 not built")
        return False
    if clip_id not in CLIP_META:
        print(f"❌ {clip_id}: no meta")
        return False
    qd = QUEUE / clip_id
    qd.mkdir(parents=True, exist_ok=True)
    shutil.copy(sf, qd / "short.mp4")
    meta = {"clip_id": clip_id, **COMMON, **CLIP_META[clip_id]}
    (qd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    m = CLIP_META[clip_id]
    print(f"✅ {clip_id}: {m['not_before'][:10]} {m['target_slot']} | {m['title'][:34]}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="+", help="Only these IDs")
    args = p.parse_args()
    targets = args.only or list(CLIP_META.keys())
    placed = sum(queue_one(c) for c in targets)
    print(f"\n=== {placed}/{len(targets)} queued ===")


if __name__ == "__main__":
    main()
