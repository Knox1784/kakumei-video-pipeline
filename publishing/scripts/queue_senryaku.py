#!/usr/bin/env python3
"""queue_senryaku.py — 戦略ごっこをするな の 01-12 を publishing/queue/ に投入。

1日2本 (22:00 / 23:00 JST) を 2026-06-10〜06-15 に段階配信。
not_before + target_slot を仕込むので一括 push しても毎日2本ずつ自動公開される。
主トリガ = launchd com.kakumei.autopost (定刻)、予備 = GHA cron。
"""
import argparse, json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHORTS = ROOT / "source-senryaku_2026-06-10/edit/shorts"
QUEUE = ROOT / "publishing/queue"

COMMON = {
    "account_id": "kakumei_ikka",
    "privacy": "public",
    "source_video": "戦略ごっこをするな.MOV",
    "channel": "革命一家",
    "channel_id": "UCLFDso06pqOYLnXfv5-jDsQ",
    "experiment_arm": "duration_15to25s_loop_natural_senryaku",
    "edit_style": "loop_friendly_tail",
}
HASH = "#戦略ごっこをするな #未来の総理大臣 #因幡匠瞬 #革命一家"
BASETAGS = ["Shorts", "革命一家", "因幡匠瞬", "未来の総理大臣", "戦略ごっこをするな"]


def _m(title, desc, extra, dur, nb, slot):
    return {"title": title, "description": f"{desc}\n{HASH}", "tags": BASETAGS + extra,
            "duration_s": dur, "not_before": nb, "target_slot": slot}


# 6/10〜6/15、各日 22:00/23:00
CLIP_META = {
    "01_NEJI_HAZUSE": _m("頭のネジを外すしかない #Shorts",
        "巨人に営業しても相手にされない？目に留まるには——もう頭のネジを外すしかない。",
        ["営業", "成り上がり", "マインド"], 20.7, "2026-06-10T22:00:00+09:00", "22:00"),
    "02_TSUUHOU_KACHI": _m("通報されても、それで勝ち #Shorts",
        "しつこく営業して通報されても、相手の認知に入れば勝ち。普通の営業では埋もれる。",
        ["営業", "しつこさ", "ビジネス"], 16.7, "2026-06-10T23:00:00+09:00", "23:00"),
    "03_KASU": _m("お前の将来設計はカスだ #Shorts",
        "翔真の将来設計もゴミ？はい、カスです。リソースのない若者が夢を語る前に。",
        ["自己啓発", "若者", "行動"], 16.3, "2026-06-11T22:00:00+09:00", "22:00"),
    "04_GUNRERU": _m("金がない奴は金がない奴と群れる #Shorts",
        "資本主義は富めるものが富む。金がない奴は金がない奴で群れる。そこから抜け出せ。",
        ["資本主義", "巨人", "お金"], 18.2, "2026-06-11T23:00:00+09:00", "23:00"),
    "05_GURUGURU": _m("頭グルグルは自信がない証拠 #Shorts",
        "頭の中でグルグル戦略を考えてるのは、自信がなくて嫌なことから逃げてるだけ。",
        ["戦略", "自信", "行動"], 12.5, "2026-06-12T22:00:00+09:00", "22:00"),
    "06_KURUTTA": _m("狂った奴らといろ #Shorts",
        "環境を変えろ。狂った奴ら、ネジが外れた人たちといろ。普通の人といたら終わる。",
        ["環境", "成功", "マインド"], 12.8, "2026-06-12T23:00:00+09:00", "23:00"),
    "07_DEKIMASU": _m("できなくても「できます」と言え #Shorts",
        "できる確信がなくても『できます』と言って受けろ。やってみて怒られる。以上。",
        ["営業", "行動", "勇気"], 12.7, "2026-06-13T22:00:00+09:00", "22:00"),
    "08_SEKKEI": _m("設計5%・行動95% #Shorts",
        "リソースのないお前は設計5%・行動95%。考えすぎて動けないのが一番のゴミ。",
        ["戦略", "行動", "若者"], 19.9, "2026-06-13T23:00:00+09:00", "23:00"),
    "09_OKURIMONO": _m("今の環境はマジで贈り物 #Shorts",
        "バイトを辞めるな。今目の前にある環境はマジで贈り物。一秒一秒最適化しろ。",
        ["環境", "バイト", "最適化"], 17.8, "2026-06-14T22:00:00+09:00", "22:00"),
    "10_KAMI_KANKYO": _m("神が環境を変えてくれる #Shorts",
        "一秒一秒を極めたら、自動的に神が環境を変えてくれる。動かない奴には何も来ない。",
        ["環境", "行動", "マインド"], 15.7, "2026-06-14T23:00:00+09:00", "23:00"),
    "11_EIGYOU": _m("今すぐやるのは営業一択 #Shorts",
        "今から具体的に何をすべき？営業一択。泥臭く、一番やらないといけないこと。",
        ["営業", "ビジネス", "行動"], 12.2, "2026-06-15T22:00:00+09:00", "22:00"),
    "12_KEIKEN": _m("金より経験をもらえ #Shorts",
        "契約に失敗してもいい。お金より経験をもらえることが価値。経験が次の武器になる。",
        ["経験", "成長", "ビジネス"], 15.9, "2026-06-15T23:00:00+09:00", "23:00"),
}


def queue_one(cid):
    sf = SHORTS / cid / "short_final.mp4"
    if not sf.exists():
        print(f"⏸  {cid}: short_final.mp4 not built"); return False
    qd = QUEUE / cid
    qd.mkdir(parents=True, exist_ok=True)
    shutil.copy(sf, qd / "short.mp4")
    meta = {"clip_id": cid, **COMMON, **CLIP_META[cid]}
    (qd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    m = CLIP_META[cid]
    print(f"✅ {cid}: {m['not_before'][:10]} {m['target_slot']} | {m['title'][:32]}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="+")
    args = p.parse_args()
    targets = args.only or list(CLIP_META.keys())
    placed = sum(queue_one(c) for c in targets)
    print(f"\n=== {placed}/{len(targets)} queued ===")


if __name__ == "__main__":
    main()
