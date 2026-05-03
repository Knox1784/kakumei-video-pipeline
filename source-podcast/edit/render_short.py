"""
Vertical short renderer.
Extracts segments from source, center-crops to vertical 1080x1920,
applies warm_cinematic grade, 30ms audio fades, and burns Japanese subtitles.

Usage:
    python render_short.py <short_dir>
    # reads <short_dir>/edl.json, writes <short_dir>/short.mp4
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Import compositions module from video-use helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "video-use" / "helpers"))
from compositions import get_composition

# warm_cinematic grade — actual preset from video-use/helpers/grade.py
WARM_CINEMATIC = (
    "eq=contrast=1.12:brightness=-0.02:saturation=0.88,"
    "colorbalance=rs=0.02:gs=0.0:bs=-0.03:rm=0.04:gm=0.01:bm=-0.02:rh=0.08:gh=0.02:bh=-0.05,"
    "curves=master='0/0 0.25/0.22 0.75/0.78 1/1'"
)

# ASS subtitle resolution — matches output exactly so FontSize is in pixels
ASS_PLAY_W = 1080
ASS_PLAY_H = 1920
ASS_FONT_NAME = "Hiragino Sans W6"

# Subtitle style presets (scalable — add more techniques here as needed)
# alignment numpad: 1-3=bottom L/C/R, 4-6=middle L/C/R, 7-9=top L/C/R
SUBTITLE_STYLES = {
    "horizontal_bottom_bold": {
        "alignment": 2, "font_size": 80, "outline": 5, "shadow": 1,
        "margin_l": 40, "margin_r": 40, "margin_v": 120,
        "bold": -1, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000",
        "vertical": False,
    },
    "vertical_inside_left": {
        "alignment": 7, "font_size": 70, "outline": 5, "shadow": 2,
        "margin_l": 200, "margin_r": 40, "margin_v": 80,
        "bold": -1, "primary_color": "&H00FFFFFF", "outline_color": "&H00000000",
        "vertical": True,  # text formatted with \N between every char → stacks downward
    },
    # Future techniques (add as needed):
    #   "karaoke_yellow_highlight": current word in yellow via \k tags
    #   "punchline_zoom_pulse":     payoff scaled up via \fscx/\fscy + \t() animation
    #   "right_side_vertical_red":  mirror of vertical_inside_left, alignment=9
    #   "top_banner_keyword":       single fixed keyword pinned at alignment=8
}
DEFAULT_LAYERS = ["vertical_inside_left"]  # vertical-only (no concurrent horizontal)

# Legacy single-style constant (kept for any old call sites)
SUB_STYLE_VERT = (
    "FontName=Hiragino Sans W6,FontSize=80,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=1,Outline=5,Shadow=1,"
    "Alignment=2,MarginV=120"
)

LOUDNORM_I = -14.0
LOUDNORM_TP = -1.0
LOUDNORM_LRA = 11.0


def srt_ts(s: float) -> str:
    total = int(round(s * 1000))
    h, r = divmod(total, 3600_000)
    m, r = divmod(r, 60_000)
    sec, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def build_word_reveal_cues(transcript_path: Path, ranges: list[dict]) -> list[tuple[float, float, str]]:
    """Build cumulative word-by-word reveal cues for the given source ranges.

    Returns list of (out_start_s, out_end_s, text) tuples in OUTPUT timeline (concat'd).
    Each char appears as it is spoken; sentence accumulates char-by-char and clears
    on sentence boundary (。！？ or silence ≥0.6s)."""
    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
    all_words = transcript['words']
    entries = []
    seg_offset = 0.0
    SENT_GAP = 0.6  # silence ≥0.6s = sentence break
    AFTERGLOW = 0.4  # full sentence stays this long after last char

    for r in ranges:
        seg_start = r['start']
        seg_end = r['end']
        seg_dur = seg_end - seg_start

        words_in = [w for w in all_words
                    if w.get('type') == 'word'
                    and w.get('start') is not None and w.get('end') is not None
                    and w['end'] > seg_start and w['start'] < seg_end]

        # Group into sentences (break on terminal punctuation OR silence ≥SENT_GAP)
        sentences = []
        current = []
        for i, w in enumerate(words_in):
            current.append(w)
            t = (w.get('text') or '').strip()
            ends = bool(t) and t[-1] in '。！？'
            if not ends and i + 1 < len(words_in):
                gap = words_in[i + 1]['start'] - w['end']
                if gap >= SENT_GAP:
                    ends = True
            if ends or i == len(words_in) - 1:
                if current:
                    sentences.append(current)
                    current = []
        if current:
            sentences.append(current)

        # For each sentence, build cumulative reveal cues
        for sent in sentences:
            cumulative = ""
            for i, w in enumerate(sent):
                t = (w.get('text') or '').strip()
                if not t:
                    continue
                cumulative += t
                cs = max(seg_start, w['start'])
                if i + 1 < len(sent):
                    ce = max(seg_start, sent[i + 1]['start'])
                else:
                    ce = min(seg_end, w['end'] + AFTERGLOW)
                # Convert to output timeline
                os_ = max(0.0, cs - seg_start) + seg_offset
                oe = max(0.0, ce - seg_start) + seg_offset
                if oe <= os_:
                    oe = os_ + 0.15
                clean = re.sub(r'\s+', '', cumulative).strip()
                if clean:
                    entries.append((os_, oe, clean))

        seg_offset += seg_dur

    entries.sort(key=lambda e: e[0])
    return entries


def write_srt(entries: list[tuple[float, float, str]], out_srt: Path) -> int:
    lines = []
    for i, (a, b, t) in enumerate(entries, start=1):
        lines.append(str(i))
        lines.append(f"{srt_ts(a)} --> {srt_ts(b)}")
        lines.append(t)
        lines.append("")
    out_srt.write_text("\n".join(lines), encoding='utf-8')
    return len(entries)


def _ass_ts(s: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cs (centiseconds)."""
    cs = int(round(s * 100))
    h, r = divmod(cs, 360_000)
    m, r = divmod(r, 6_000)
    sec, c = divmod(r, 100)
    return f"{h:d}:{m:02d}:{sec:02d}.{c:02d}"


def write_ass(entries: list[tuple[float, float, str]], out_ass: Path,
              style_name: str = "horizontal_bottom_bold") -> int:
    """Write ASS file with explicit PlayResX/Y for pixel-accurate FontSize.

    style_name selects from SUBTITLE_STYLES. If style.vertical=True, each Dialogue's
    text is split with \\N between every character to stack downward.
    """
    style = SUBTITLE_STYLES[style_name] if isinstance(style_name, str) else style_name
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {ASS_PLAY_W}\n"
        f"PlayResY: {ASS_PLAY_H}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{ASS_FONT_NAME},{style['font_size']},"
        f"{style['primary_color']},&H000000FF,{style['outline_color']},&H00000000,"
        f"{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},"
        f"{style['alignment']},{style['margin_l']},{style['margin_r']},{style['margin_v']},1\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    lines = [header]
    is_vertical = style.get("vertical", False)
    for a, b, t in entries:
        text = t.replace("\n", "\\N").replace(",", "，")
        if is_vertical:
            text = "\\N".join(list(text))  # stack each char on its own line
        lines.append(f"Dialogue: 0,{_ass_ts(a)},{_ass_ts(b)},Default,,0,0,0,,{text}\n")
    out_ass.write_text("".join(lines), encoding='utf-8')
    return len(entries)


def write_ass_layers(entries: list[tuple[float, float, str]], short_dir: Path,
                     base_name: str, layers: list[str]) -> list[Path]:
    """Write one ASS file per layer style. Returns list of paths in vf-application order."""
    paths = []
    for layer in layers:
        out_p = short_dir / f"{base_name}.{layer}.ass"
        write_ass(entries, out_p, layer)
        paths.append(out_p)
    return paths


def build_short_srt(edl: dict, transcript_path: Path, out_srt: Path, max_chars: int = 14):
    """Word-by-word reveal subs for body ranges, multi-layer ASS output.

    Returns (n_cues, [ass_paths]). Reads layers from edl["subtitles"]["layers"] or DEFAULT_LAYERS.
    """
    entries = build_word_reveal_cues(transcript_path, edl['ranges'])
    layers = edl.get("subtitles", {}).get("layers", DEFAULT_LAYERS)
    base_name = out_srt.stem  # strips .srt extension
    paths = write_ass_layers(entries, out_srt.parent, base_name, layers)
    return len(entries), paths


def _legacy_build_short_srt(edl: dict, transcript_path: Path, out_srt: Path, max_chars: int = 14):
    """Build natural-sentence SRT (shorter chunks for vertical) — preserved for fallback."""
    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
    all_words = transcript['words']

    entries = []
    seg_offset = 0.0

    for r in edl['ranges']:
        seg_start = r['start']
        seg_end = r['end']
        seg_dur = seg_end - seg_start

        # Collect words in this range
        words_in = []
        events_in = []
        for w in all_words:
            ws = w.get('start')
            we = w.get('end')
            if ws is None or we is None:
                continue
            if we <= seg_start or ws >= seg_end:
                continue
            if w.get('type') == 'word':
                words_in.append(w)
            elif w.get('type') == 'audio_event' and (we - ws) > 3.0:
                events_in.append(w)

        # Chunk words into short sentence pieces
        chunks = []
        buf_words = []
        buf_text = ""
        for w in words_in:
            text = (w.get('text') or '').strip()
            if not text:
                continue
            buf_words.append(w)
            buf_text += text
            # Break on punctuation
            if text[-1] in '。！？':
                chunks.append((buf_words[0]['start'], buf_words[-1]['end'], buf_text))
                buf_words = []
                buf_text = ""
                continue
            if text[-1] == '、' and len(buf_text) >= max_chars // 2:
                chunks.append((buf_words[0]['start'], buf_words[-1]['end'], buf_text))
                buf_words = []
                buf_text = ""
                continue
            if len(buf_text) >= max_chars:
                chunks.append((buf_words[0]['start'], buf_words[-1]['end'], buf_text))
                buf_words = []
                buf_text = ""
        if buf_words:
            chunks.append((buf_words[0]['start'], buf_words[-1]['end'], buf_text))

        # Handle long audio_events (split by sentences, distribute time)
        for e in events_in:
            ev_start = max(e['start'], seg_start)
            ev_end = min(e['end'], seg_end)
            ev_dur = ev_end - ev_start
            if ev_dur <= 0:
                continue
            text = (e.get('text') or '').strip()
            text = re.sub(r'^\(笑い\)?\s*', '', text)
            text = re.sub(r'^\(.*?\)\s*', '', text)
            if not text:
                continue
            parts = re.split(r'(?<=[。！？])\s*', text)
            parts = [p.strip() for p in parts if p.strip()]
            if not parts:
                continue
            refined = []
            for p in parts:
                if len(p) <= max_chars + 2:
                    refined.append(p)
                else:
                    buf = ""
                    for s in re.split(r'(?<=、)\s*', p):
                        s = s.strip()
                        if not s:
                            continue
                        if len(buf) + len(s) <= max_chars + 2:
                            buf += s
                        else:
                            if buf:
                                refined.append(buf)
                            buf = s
                    if buf:
                        refined.append(buf)
            total_chars = sum(len(p) for p in refined)
            if total_chars == 0:
                continue
            cursor = ev_start
            for p in refined:
                d = ev_dur * (len(p) / total_chars)
                chunks.append((cursor, cursor + d, p))
                cursor += d

        # Sort and convert to output-timeline offsets
        chunks.sort(key=lambda c: c[0])
        for cs, ce, ct in chunks:
            ls = max(seg_start, cs)
            le = min(seg_end, ce)
            os_ = max(0.0, ls - seg_start) + seg_offset
            oe = max(0.0, le - seg_start) + seg_offset
            if oe <= os_:
                oe = os_ + 0.4
            clean = re.sub(r'\s+', '', ct).strip()
            if clean:
                entries.append((os_, oe, clean))

        seg_offset += seg_dur

    entries.sort(key=lambda e: e[0])
    lines = []
    for i, (a, b, t) in enumerate(entries, start=1):
        lines.append(str(i))
        lines.append(f"{srt_ts(a)} --> {srt_ts(b)}")
        lines.append(t)
        lines.append("")
    out_srt.write_text("\n".join(lines), encoding='utf-8')
    return len(entries)


def extract_vertical(src: str, seg_start: float, seg_end: float, out: Path,
                     composition: str = "center_crop", composition_options: dict | None = None):
    """Extract segment with selected composition + warm_cinematic + 30ms fades."""
    dur = seg_end - seg_start
    # Build composition filter (subject-aware for face_track, static for others)
    comp_filter = get_composition(
        composition,
        video_path=src,
        seg_start=seg_start,
        seg_end=seg_end,
        src_w=1920, src_h=1080,
        tgt_w=1080, tgt_h=1920,
        options=composition_options or {},
    )
    vf = f"{comp_filter},{WARM_CINEMATIC}"
    fade_out_st = max(0.0, dur - 0.03)
    af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_st:.3f}:d=0.03"

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{seg_start:.3f}",
        "-i", src,
        "-t", f"{dur:.3f}",
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def concat_segs(seg_paths: list[Path], out: Path, tmp_dir: Path):
    list_txt = tmp_dir / "_concat.txt"
    list_txt.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_paths))
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(list_txt),
           "-c", "copy", str(out)]
    subprocess.run(cmd, check=True)
    list_txt.unlink(missing_ok=True)


def burn_subtitles(base: Path, srt_or_paths, out: Path):
    """Burn 1+ subtitle file(s). srt_or_paths can be a single Path or list of Paths.
    .ass files use the ass filter (PlayResX/Y authoritative). Multiple files chain in vf."""
    paths = srt_or_paths if isinstance(srt_or_paths, list) else [srt_or_paths]
    vf_parts = []
    for p in paths:
        abs_p = str(p.resolve()).replace(":", r"\:").replace("'", r"\'")
        if p.suffix.lower() == '.ass':
            vf_parts.append(f"ass='{abs_p}'")
        else:
            vf_parts.append(f"subtitles='{abs_p}':force_style='{SUB_STYLE_VERT}'")
    vf = ",".join(vf_parts)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-i", str(base), "-vf", vf,
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-c:a", "copy",
           "-movflags", "+faststart",
           str(out)]
    subprocess.run(cmd, check=True)


def apply_loudnorm(inp: Path, out: Path):
    """1-pass loudnorm (fast)."""
    f = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-i", str(inp), "-c:v", "copy", "-af", f,
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def render_short(short_dir: Path):
    edl_path = short_dir / "edl.json"
    edl = json.loads(edl_path.read_text(encoding='utf-8'))
    src = edl['sources']['raw_podcast']
    transcript_path = short_dir.parent.parent / "transcripts" / f"{Path(src).stem}.json"

    # 1. Multi-layer ASS subtitles (pixel-accurate via PlayResX/Y)
    srt_path = short_dir / f"{edl['id']}_subtitles.srt"  # base name only
    n_cues, ass_paths = build_short_srt(edl, transcript_path, srt_path)
    print(f"[{edl['id']}] ASS: {n_cues} cues × {len(ass_paths)} layers")

    # 2. Per-segment extract (composition + grade + fade)
    composition = edl.get("composition", "center_crop")
    comp_options = edl.get("composition_options", {})
    seg_paths = []
    for i, r in enumerate(edl['ranges']):
        seg_out = short_dir / f"seg_{i:02d}.mp4"
        extract_vertical(src, r['start'], r['end'], seg_out,
                         composition=composition, composition_options=comp_options)
        seg_paths.append(seg_out)
    print(f"[{edl['id']}] Extracted {len(seg_paths)} segment(s) [composition={composition}]")

    # 3. Concat
    base = short_dir / "base.mp4"
    if len(seg_paths) == 1:
        import shutil
        shutil.copy(seg_paths[0], base)
    else:
        concat_segs(seg_paths, base, short_dir)

    # 4. Burn subtitles (multi-layer)
    subbed = short_dir / "subbed.mp4"
    burn_subtitles(base, ass_paths, subbed)

    # 5. Loudnorm → final short.mp4
    final = short_dir / "short.mp4"
    apply_loudnorm(subbed, final)

    # Cleanup intermediate files
    for p in seg_paths:
        p.unlink(missing_ok=True)
    base.unlink(missing_ok=True)
    subbed.unlink(missing_ok=True)

    size_mb = final.stat().st_size / (1024 * 1024)
    print(f"[{edl['id']}] ✅ {final.name} ({size_mb:.1f} MB)")
    return final


if __name__ == "__main__":
    short_dir = Path(sys.argv[1]).resolve()
    render_short(short_dir)
