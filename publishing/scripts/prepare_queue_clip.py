#!/usr/bin/env python3
"""
queue 配置ヘルパー — Zone B の完成クリップを全プラットフォーム適合の形で queue に置く

なぜ必要か:
  - IG Reels は音声 AAC >128kbps を**確定リジェクト**する (公式スペック + 実リジェクト報告)
  - Threads は「リポジトリに commit された bytes」を URL fetch するため、
    投稿時の再エンコードでは直せない → **queue に置く時点で正規化するのが唯一の対処位置**
  - 既存の compose パイプラインは ~200kbps AAC を出すため、ここで音声のみ 128kbps に
    再エンコード (映像は無劣化 -c:v copy、数秒で完了) + moov atom 先頭化 (+faststart)

使用例:
  python3 publishing/scripts/prepare_queue_clip.py \
    --src source-podcast/edit/shorts_v2/16_NEW_CLIP/short_with_audio.mp4 \
    --clip-id 16_NEW_CLIP
  # → publishing/queue/16_NEW_CLIP/short.mp4 が生成される
  # → あとは meta.json を作って git add/commit/push (publishing/queue/README.md 参照)

  # 既存 queue を一括で再正規化 (Meta go-live 時に1回):
  python3 publishing/scripts/prepare_queue_clip.py --normalize-existing
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE_DIR = ROOT / "publishing/queue"

# IG Reels の音声上限 = 128kbps。ffmpeg の -b:a 128k は実測 ~131kbps を出す
# (AAC エンコーダのオーバーヘッド) ため、判定閾値は「128k ターゲットの実出力」を
# 許容する 136k に設定 (これを 128_000 にすると自分の出力を毎回再エンコードする)
COMPLIANT_AUDIO_BPS = 136_000
TARGET_AUDIO_BITRATE = "128k"


def probe(path: Path) -> dict:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,bit_rate,sample_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()[-300:]}")
    d = json.loads(r.stdout)
    out = {"duration": float(d["format"]["duration"])}
    for s in d.get("streams", []):
        if s.get("codec_type") == "audio":
            out.update(acodec=s.get("codec_name"),
                       abr=int(s.get("bit_rate") or 0),
                       asr=int(s.get("sample_rate") or 0))
    return out


def normalize(src: Path, dst: Path) -> bool:
    """src を全プラットフォーム適合の形で dst に書く。再エンコードしたら True。"""
    info = probe(src)
    compliant = (info.get("acodec") == "aac"
                 and 0 < info.get("abr", 0) <= COMPLIANT_AUDIO_BPS
                 and info.get("asr", 0) <= 48000)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if compliant:
        # 音声は仕様内 → remux のみ (faststart 保証。無劣化・一瞬)
        cmd = ["ffmpeg", "-y", "-i", str(src), "-c", "copy",
               "-movflags", "+faststart", str(dst)]
        action = "remux (音声仕様内・faststart 保証のみ)"
    else:
        # 音声のみ 128kbps AAC に再エンコード (映像 copy)
        cmd = ["ffmpeg", "-y", "-i", str(src), "-c:v", "copy",
               "-c:a", "aac", "-b:a", TARGET_AUDIO_BITRATE, "-ar", "48000",
               "-movflags", "+faststart", str(dst)]
        action = (f"音声再エンコード ({info.get('acodec')}@{info.get('abr', 0)//1000}kbps "
                  f"→ aac@128kbps, 映像 copy)")
    print(f"  {src.name}: {action}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-300:]}")
    shown = dst.relative_to(ROOT) if dst.is_relative_to(ROOT) else dst
    print(f"  ✅ → {shown} ({dst.stat().st_size / 1e6:.1f}MB)", flush=True)
    return not compliant


def normalize_existing():
    """既存 queue の short.mp4 を一括再正規化 (in-place)。Meta go-live 時に1回実行。"""
    dirs = sorted(d for d in QUEUE_DIR.iterdir() if d.is_dir() and (d / "short.mp4").exists())
    if not dirs:
        print("queue に対象なし")
        return
    changed = 0
    for d in dirs:
        src = d / "short.mp4"
        tmp = d / "short_normalized.mp4"
        if normalize(src, tmp):
            tmp.replace(src)
            changed += 1
        else:
            tmp.unlink()
            print(f"  ⏭ {d.name}: 既に適合 → 変更なし", flush=True)
    print(f"\n{changed}/{len(dirs)} 本を再エンコード。変更があれば git add/commit/push を忘れずに")


def main():
    parser = argparse.ArgumentParser(description="queue 配置 (全プラットフォーム適合の音声正規化付き)")
    parser.add_argument("--src", help="Zone B の完成クリップ (short_with_audio.mp4 等)")
    parser.add_argument("--clip-id", help="queue ディレクトリ名 (例: 16_NEW_CLIP)")
    parser.add_argument("--normalize-existing", action="store_true",
                        help="既存 queue の short.mp4 を一括再正規化")
    args = parser.parse_args()

    if args.normalize_existing:
        normalize_existing()
        return

    if not (args.src and args.clip_id):
        parser.error("--src と --clip-id が必要です (または --normalize-existing)")
    src = Path(args.src).expanduser()
    if not src.is_file():
        print(f"❌ ファイルが見つかりません: {src}", file=sys.stderr)
        sys.exit(1)
    dst = QUEUE_DIR / args.clip_id / "short.mp4"
    normalize(src, dst)
    meta_path = QUEUE_DIR / args.clip_id / "meta.json"
    if not meta_path.exists():
        print(f"\n次: {meta_path.relative_to(ROOT)} を作成 (スキーマは publishing/queue/README.md)")
        print(f"    → git add publishing/queue/{args.clip_id}/ && git commit && git push")


if __name__ == "__main__":
    main()
