#!/usr/bin/env python3
"""queue_value.py — あなたのバリューは何か の 01-12 を publishing/queue/ に投入。

1日2本 (22:00/23:00 JST) を 2026-06-16〜06-21 に段階配信 (戦略ごっこ 6/15 の後)。
queue 配置は prepare_queue_clip.normalize 経由 (音声128k=IG/Threads適合・素のcp禁止)。
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_queue_clip import normalize

ROOT = Path(__file__).resolve().parents[2]
SHORTS = ROOT / "source-value_2026-06-10/edit/shorts"
QUEUE = ROOT / "publishing/queue"

COMMON = {
    "account_id": "kakumei_ikka", "privacy": "public",
    "source_video": "あなたのバリューは何か.MOV",
    "channel": "革命一家", "channel_id": "UCLFDso06pqOYLnXfv5-jDsQ",
    "experiment_arm": "duration_15to25s_loop_natural_value", "edit_style": "loop_friendly_tail",
}
HASH = "#あなたのバリューは何か #未来の総理大臣 #因幡匠瞬 #革命一家"
BASETAGS = ["Shorts", "革命一家", "因幡匠瞬", "未来の総理大臣", "バリュー"]


def _m(title, desc, extra, dur, nb, slot):
    return {"title": title, "description": f"{desc}\n{HASH}", "tags": BASETAGS + extra,
            "duration_s": dur, "not_before": nb, "target_slot": slot}


CLIP_META = {
    "01_DOKURITSU": _m("独立してコケる奴はアホ #Shorts",
        "幹部より優秀になって独立してコケる。組織・人脈・チームという無形資産の大切さを理解せず飛び出すのは、もうアホ。",
        ["独立", "起業", "組織"], 21.6, "2026-06-16T22:00:00+09:00", "22:00"),
    "02_BOKORARERU": _m("ボコられるのは慢心の結果 #Shorts",
        "すごい先輩方にボコられるのは、今まで慢心してた結果じゃない？——いやほんとその通りで。",
        ["慢心", "成長", "自己分析"], 15.4, "2026-06-16T23:00:00+09:00", "23:00"),
    "03_MONALISA": _m("モナリザも20億枚あれば無価値 #Shorts",
        "替えが効く人に価値はない。モナリザも20億枚あったら無価値。あなたしか出せない希少価値を持て。",
        ["希少価値", "バリュー", "独自性"], 18.3, "2026-06-17T22:00:00+09:00", "22:00"),
    "04_SHINGAKUKA": _m("自分を神格化するな #Shorts",
        "満足してないと言いながら無意識で喜んでる。自分を神格化しすぎ。そこがカス。",
        ["慢心", "メンタル", "自己分析"], 22.8, "2026-06-17T23:00:00+09:00", "23:00"),
    "05_AMAE": _m("お前、甘えてるよな #Shorts",
        "解像度も人脈も敵わないのは承知の上で——でもやっぱり甘えてるところあるよな。21歳の下剋上。",
        ["下剋上", "ビジネス", "議論"], 20.2, "2026-06-18T22:00:00+09:00", "22:00"),
    "06_JISHIN": _m("SNSを見るのはほぼ地獄 #Shorts",
        "まだ何者でもない若者がSNSを見ると、成功した状態の人ばかり上がってくる。ほぼ地獄。",
        ["SNS", "若者", "自信"], 20.6, "2026-06-18T23:00:00+09:00", "23:00"),
    "07_KEKKA": _m("結果しか見てないから甘い #Shorts",
        "出資されることがどんだけ尊いか。結果しか見ず過程を見ないから、まだ甘々。",
        ["過程", "結果", "SNS"], 18.2, "2026-06-19T22:00:00+09:00", "22:00"),
    "08_CHUUSOTSU": _m("中卒で公認会計士を諦めた男 #Shorts",
        "中卒で公認会計士なら日本唯一のブランド。だが勉強が続かず、ただの中卒になった男の話。",
        ["キャリア", "挫折", "継続"], 20.5, "2026-06-19T23:00:00+09:00", "23:00"),
    "09_KOUGEKI": _m("攻撃が最大の防御 #Shorts",
        "保守的すぎる。攻撃が最大の防御。守りを固めるより、攻撃してチャレンジし続けろ。",
        ["挑戦", "マインド", "攻め"], 13.5, "2026-06-20T22:00:00+09:00", "22:00"),
    "10_TEAM": _m("仲間がいるから飛び込める #Shorts",
        "チームといる時が一番攻撃力が高い。ルフィも料理は作れない。仲間がいるからトップのバリューを出せる。",
        ["仲間", "チーム", "リーダー"], 18.4, "2026-06-20T23:00:00+09:00", "23:00"),
    "11_GOKAN": _m("五感で妄想しろ #Shorts",
        "半年後の自分を五感でイメージしろ。三ツ星レストランかクルーザーの上か。妄想の解像度が現実になる。",
        ["目標", "イメージ", "自己実現"], 16.8, "2026-06-21T22:00:00+09:00", "22:00"),
    "12_MINNA_DAME": _m("みんなができることはダメ #Shorts",
        "コンスタントは大前提。みんなができることはダメ。自分だけの強みを極めてバリューにしろ。",
        ["バリュー", "独自性", "差別化"], 13.8, "2026-06-21T23:00:00+09:00", "23:00"),
}


def queue_one(cid):
    sf = SHORTS / cid / "short_final.mp4"
    if not sf.exists():
        print(f"⏸  {cid}: short_final.mp4 not built"); return False
    qd = QUEUE / cid
    qd.mkdir(parents=True, exist_ok=True)
    normalize(sf, qd / "short.mp4")  # 音声128k (IG/Threads適合)
    meta = {"clip_id": cid, **COMMON, **CLIP_META[cid]}
    (qd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    m = CLIP_META[cid]
    print(f"✅ {cid}: {m['not_before'][:10]} {m['target_slot']} | {m['title'][:30]}")
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
