#!/usr/bin/env python3
"""
shorts_v2 コンポジションパイプライン

入力: shorts_v2/NN_NAME/edl.json
処理:
  1. 既存 render_short.py で base動画 (1.0x, 字幕付き) を生成
  2. 1.5x atempo (映像+音声、ピッチ保持) で速度変換
  3. Cold Open 2秒動画を生成 (黒背景 + テキスト)
  4. concat: cold_open + main_15x → base.mp4
  5. mix_final.py で BGM + SFX を被せる → short_with_audio.mp4 (完成)

使用例:
  python3 compose_v2.py 01_KIRAWARENA_1MM
  python3 compose_v2.py --all
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHORTS_V2 = ROOT / "source-podcast/edit/shorts_v2"
EDIT_DIR = ROOT / "source-podcast/edit"
RENDER_SHORT = EDIT_DIR / "render_short.py"
MIX_FINAL = ROOT / "publishing/audio/mix_final.py"
PUBLISHING = ROOT / "publishing"

# Reuse render_short helpers (word-reveal SRT, styles, grade)
sys.path.insert(0, str(EDIT_DIR))
import render_short as rs

# 縦型1080x1920、Cold Openのテキストレンダリング用フォントマップ
FONT_FILES = {
    "Hiragino Sans W6": "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "Yu Gothic": "/System/Library/Fonts/Supplemental/YuGothic-Bold.otf",
    "Noto Sans JP": "/System/Library/Fonts/AquaKana.ttc",  # fallback
    "Source Han Sans": "/System/Library/Fonts/AquaKana.ttc",  # fallback
}


def run(cmd, cwd=None):
    """ffmpeg/python等のサブプロセス実行"""
    print(f"  $ {' '.join(shlex.quote(str(c)) for c in cmd[:8])}{'...' if len(cmd) > 8 else ''}")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  STDERR: {r.stderr[-1500:]}", file=sys.stderr)
        raise RuntimeError(f"Command failed: exit {r.returncode}")
    return r


def step_1_render_base(short_dir: Path) -> Path:
    """既存 render_short.py を実行して base となる short.mp4 を生成"""
    out = short_dir / "short.mp4"
    if out.exists():
        print(f"  [step1] short.mp4 既存スキップ")
        return out
    run(["python3", str(RENDER_SHORT), str(short_dir)])
    if not out.exists():
        raise RuntimeError(f"render_short.py did not produce {out}")
    return out


def step_2_atempo_15x(short_mp4: Path) -> Path:
    """1.5x atempo (ピッチ保持) で速度変換"""
    out = short_mp4.parent / "short_15x.mp4"
    if out.exists():
        print(f"  [step2] short_15x.mp4 既存スキップ")
        return out
    run([
        "ffmpeg", "-y", "-i", str(short_mp4),
        "-filter_complex", "[0:v]setpts=PTS/1.5[v];[0:a]atempo=1.5[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "h264", "-c:a", "aac", "-b:a", "192k",
        str(out),
    ])
    return out


def step_3_hook_clip(short_dir: Path, edl: dict) -> Path:
    """Extract the punchline footage from source as cold_open.mp4.

    Frontloaded hook = the same speech that body ends on → 伏線回収 structure.
    Burns word-by-word reveal subtitles synchronized to the speaker.
    """
    h = edl["hook_clip"]
    src = edl["sources"]["raw_podcast"]
    s = float(h["source_range"]["start"])
    e = float(h["source_range"]["end"])
    dur = e - s

    out = short_dir / "cold_open.mp4"
    if out.exists():
        print(f"  [step3] cold_open.mp4 既存スキップ")
        return out

    # Build multi-layer ASS for the hook range (output timeline = 0..dur)
    transcript_path = short_dir.parent.parent / "transcripts" / f"{Path(src).stem}.json"
    cues = rs.build_word_reveal_cues(transcript_path, [{"start": s, "end": e}],
                                     overrides=edl.get("transcript_overrides"))
    layers = edl.get("subtitles", {}).get("layers", rs.DEFAULT_LAYERS)
    ass_paths = rs.write_ass_layers(cues, short_dir, "_hook_subs", layers)

    # vf: center-crop landscape→9:16 vertical, scale 1080x1920, warm grade, burn all subtitle layers
    ass_chain = ",".join(
        f"ass='{str(p.resolve()).replace(':', chr(92) + ':').replace(chr(39), chr(92) + chr(39))}'"
        for p in ass_paths
    )
    vf = (
        f"crop=ih*9/16:ih,scale=1080:1920,setsar=1,"
        f"{rs.WARM_CINEMATIC},"
        f"{ass_chain}"
    )

    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{s:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100",
        str(out),
    ])
    return out


def step_4_concat(cold_open: Path, main_15x: Path) -> Path:
    """concat: cold_open + main_15x → base.mp4"""
    out = main_15x.parent / "base.mp4"
    if out.exists():
        print(f"  [step4] base.mp4 既存スキップ")
        return out
    run([
        "ffmpeg", "-y",
        "-i", str(cold_open),
        "-i", str(main_15x),
        "-filter_complex",
        "[0:v]scale=1080:1920,setsar=1[v0];[1:v]scale=1080:1920,setsar=1[v1];"
        "[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "h264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ])
    return out


def step_5_mix_audio(base_mp4: Path, edl: dict) -> Path:
    """mix_final.py で BGM + SFX を被せて完成"""
    audio = edl["audio"]
    bgm_path = ROOT / audio["bgm"]["output_path"]
    # Hook clip duration shifts SFX positions (SFX time_s is body-relative)
    h = edl["hook_clip"]
    hook_dur = float(h["source_range"]["end"]) - float(h["source_range"]["start"])
    sfx_specs = []
    for sfx in audio["sfx_track"]:
        sfx_path = ROOT / sfx["output_path"]
        time_s_shifted = sfx["time_s"] + hook_dur
        sfx_specs.append({"time_s": time_s_shifted, "file": str(sfx_path)})

    out = base_mp4.parent / "short_with_audio.mp4"
    run([
        "python3", str(MIX_FINAL),
        "--base", str(base_mp4),
        "--bgm", str(bgm_path),
        "--sfx-spec", json.dumps(sfx_specs),
        "--output", str(out),
    ])
    return out


def compose_one(short_dir: Path):
    """1本分のフルパイプライン実行"""
    edl = json.loads((short_dir / "edl.json").read_text())
    print(f"\n=== {short_dir.name} ({edl['title']}) ===")

    short_mp4 = step_1_render_base(short_dir)
    print(f"  step1: {short_mp4.name}")

    short_15x = step_2_atempo_15x(short_mp4)
    print(f"  step2: {short_15x.name}")

    cold_open = step_3_hook_clip(short_dir, edl)
    print(f"  step3: {cold_open.name}")

    base_mp4 = step_4_concat(cold_open, short_15x)
    print(f"  step4: {base_mp4.name}")

    final = step_5_mix_audio(base_mp4, edl)
    print(f"  step5: {final.name}  ⭐ 完成")
    return final


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("clip_id", nargs="?", help="例: 01_KIRAWARENA_1MM")
    parser.add_argument("--all", action="store_true", help="全クリップ処理")
    args = parser.parse_args()

    if args.all:
        clip_dirs = sorted([d for d in SHORTS_V2.iterdir() if d.is_dir() and (d / "edl.json").exists()])
    elif args.clip_id:
        clip_dirs = [SHORTS_V2 / args.clip_id]
    else:
        parser.error("clip_id か --all を指定")

    completed = []
    for d in clip_dirs:
        try:
            final = compose_one(d)
            completed.append(str(final))
        except Exception as e:
            print(f"  ❌ {d.name} FAILED: {e}", file=sys.stderr)

    print(f"\n=== 完了: {len(completed)}/{len(clip_dirs)} 本 ===")
    for f in completed:
        print(f"  {f}")


if __name__ == "__main__":
    main()
