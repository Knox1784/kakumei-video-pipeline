"""
Composition presets — subject-aware framing for vertical/square/other formats.

Mirrors grade.py's API pattern:
- Named presets return an ffmpeg filter chain string
- Dynamic presets (face_track) compute crop from source analysis
- Raw ffmpeg filter string passthrough for custom compositions

Usage (module):
    from compositions import get_composition
    vf = get_composition("face_track", video_path, seg_start, seg_end)

Presets:
    center_crop              — static center 9:16 crop, simple
    blur_fill                — full frame + blurred fill above/below
    face_track               — OpenCV face detection, horizontal tracking
    face_track_with_anim_zone — A+C hybrid (face top 2/3, anim zone bottom 1/3)
    two_speaker_split        — [todo] vertical split for dual speakers
    manual_offset            — static crop at user-specified offset
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


# Static preset registry — simple filter chains that don't need source analysis
STATIC_PRESETS: dict[str, str] = {
    "center_crop": "crop=608:1080:656:0,scale=1080:1920",
    "blur_fill": (
        "split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,gblur=sigma=40[bg2];"
        "[fg]scale=1080:-2[fg2];"
        "[bg2][fg2]overlay=0:(H-h)/2"
    ),
}


def list_presets() -> list[str]:
    return list(STATIC_PRESETS.keys()) + ["face_track", "face_track_with_anim_zone", "manual_offset"]


def get_composition(
    name: str,
    video_path: Optional[str] = None,
    seg_start: float = 0.0,
    seg_end: Optional[float] = None,
    src_w: int = 1920,
    src_h: int = 1080,
    tgt_w: int = 1080,
    tgt_h: int = 1920,
    options: Optional[dict] = None,
) -> str:
    """Return ffmpeg filter chain string for the named composition.

    For dynamic presets (face_track), video_path + seg times are required.
    """
    options = options or {}

    if name in STATIC_PRESETS:
        return STATIC_PRESETS[name]

    if name == "face_track":
        if not video_path:
            raise ValueError("face_track requires video_path")
        return build_face_track(video_path, seg_start, seg_end, src_w, src_h, tgt_w, tgt_h)

    if name == "face_track_with_anim_zone":
        if not video_path:
            raise ValueError("face_track_with_anim_zone requires video_path")
        anim_pct = options.get("anim_zone_height_pct", 33)
        return build_face_track_with_anim_zone(
            video_path, seg_start, seg_end, src_w, src_h, tgt_w, tgt_h, anim_pct
        )

    if name == "manual_offset":
        dx = options.get("offset_x", 0)
        dy = options.get("offset_y", 0)
        crop_w = int(src_h * tgt_w / tgt_h)  # 9:16 window width given source height
        # Clamp offsets
        default_x = (src_w - crop_w) // 2
        x = max(0, min(src_w - crop_w, default_x + dx))
        y = max(0, min(src_h - src_h, 0 + dy))  # no vertical clamp needed since crop=full height
        return f"crop={crop_w}:{src_h}:{x}:{y},scale={tgt_w}:{tgt_h}"

    # If name doesn't match a preset, assume it's a raw ffmpeg filter string
    if name and ("=" in name or "," in name):
        return name

    raise KeyError(f"Unknown composition preset: {name!r}. Available: {list_presets()}")


# -------- Face detection (OpenCV) -------------------------------------------


def extract_frame_png(video_path: str, timestamp: float, out_path: Path) -> bool:
    """Extract a single frame at timestamp via ffmpeg. Returns True on success."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{timestamp:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=30)
        return out_path.exists()
    except Exception:
        return False


def detect_face_center(video_path: str, timestamp: float, src_w: int, src_h: int) -> tuple[int, int]:
    """Detect face bounding box at given time. Returns (center_x, center_y) in source pixels.
    Falls back to frame center if no face found.
    """
    import cv2  # imported lazily

    with tempfile.TemporaryDirectory() as td:
        frame_path = Path(td) / "frame.png"
        if not extract_frame_png(video_path, timestamp, frame_path):
            return (src_w // 2, src_h // 2)
        img = cv2.imread(str(frame_path))
        if img is None:
            return (src_w // 2, src_h // 2)

    # Try Haar cascade (built-in, fast)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))

    if len(faces) == 0:
        # Try profile face cascade as fallback
        profile_path = cv2.data.haarcascades + "haarcascade_profileface.xml"
        profile_cascade = cv2.CascadeClassifier(profile_path)
        faces = profile_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))

    if len(faces) == 0:
        return (img.shape[1] // 2, img.shape[0] // 2)

    # Pick the largest face (closest to camera)
    fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    cx = fx + fw // 2
    cy = fy + fh // 2
    return (int(cx), int(cy))


def sample_face_positions(video_path: str, seg_start: float, seg_end: float,
                          src_w: int, src_h: int, n_samples: int = 3) -> tuple[int, int]:
    """Sample face positions at multiple points in the segment, return median.
    More robust than single detection (handles temporary occlusion/tilt).
    """
    if seg_end is None or seg_end <= seg_start:
        return detect_face_center(video_path, seg_start, src_w, src_h)

    times = []
    if n_samples == 1:
        times = [(seg_start + seg_end) / 2]
    else:
        step = (seg_end - seg_start) / (n_samples + 1)
        times = [seg_start + (i + 1) * step for i in range(n_samples)]

    centers = [detect_face_center(video_path, t, src_w, src_h) for t in times]
    xs = sorted(c[0] for c in centers)
    ys = sorted(c[1] for c in centers)
    # Median
    median_x = xs[len(xs) // 2]
    median_y = ys[len(ys) // 2]
    return (median_x, median_y)


# -------- Face-tracking compositions ----------------------------------------


def build_face_track(
    video_path: str,
    seg_start: float,
    seg_end: Optional[float],
    src_w: int,
    src_h: int,
    tgt_w: int,
    tgt_h: int,
) -> str:
    """Horizontal face-tracking crop.
    Crops a 9:16 (or tgt aspect) window horizontally centered on detected face,
    full source height. Scales to target dimensions.
    """
    cx, _ = sample_face_positions(video_path, seg_start, seg_end, src_w, src_h)

    # Crop window: maintain target aspect ratio, use full source height
    crop_w = int(src_h * tgt_w / tgt_h)  # e.g., 1080 * 1080/1920 = 607.5 → 608
    # Make even (required by ffmpeg)
    crop_w = crop_w + (crop_w % 2)
    crop_h = src_h

    # Offset so face is centered horizontally in crop
    x_offset = cx - crop_w // 2
    # Clamp to source bounds
    x_offset = max(0, min(src_w - crop_w, x_offset))
    # Make offset even
    x_offset = x_offset - (x_offset % 2)

    return f"crop={crop_w}:{crop_h}:{x_offset}:0,scale={tgt_w}:{tgt_h}"


def build_face_track_with_anim_zone(
    video_path: str,
    seg_start: float,
    seg_end: Optional[float],
    src_w: int,
    src_h: int,
    tgt_w: int,
    tgt_h: int,
    anim_pct: int = 33,
) -> str:
    """A+C hybrid: face in top (100-anim_pct)% zone, animation placeholder below.

    For now (before animation) the animation zone is filled with a blurred
    tinted version of the same frame. Later this can be replaced with an overlay.
    """
    face_zone_h = int(tgt_h * (100 - anim_pct) / 100)
    anim_zone_h = tgt_h - face_zone_h
    # Face zone needs 9:16 of the face_zone_h — hmm actually we want 1080 wide:
    # Face zone is tgt_w × face_zone_h
    # To fill it from src, crop and scale to tgt_w × face_zone_h

    cx, _ = sample_face_positions(video_path, seg_start, seg_end, src_w, src_h)

    # Face zone aspect: tgt_w / face_zone_h
    face_zone_aspect = tgt_w / face_zone_h
    # Crop from source with matching aspect (use full source height)
    crop_w = int(src_h * face_zone_aspect)
    crop_w = crop_w + (crop_w % 2)
    crop_h = src_h
    x_offset = cx - crop_w // 2
    x_offset = max(0, min(src_w - crop_w, x_offset))
    x_offset = x_offset - (x_offset % 2)

    # Split into two: face zone (cropped around face, scaled) and anim zone (blurred background)
    # Using ffmpeg's split, crop, scale, and vstack
    face_crop = f"crop={crop_w}:{crop_h}:{x_offset}:0,scale={tgt_w}:{face_zone_h}"
    anim_fill = (
        f"crop={crop_w}:{crop_h}:{x_offset}:0,"
        f"scale={tgt_w}:{anim_zone_h}:force_original_aspect_ratio=increase,"
        f"crop={tgt_w}:{anim_zone_h},"
        f"gblur=sigma=30,"
        f"eq=brightness=-0.2:saturation=0.5"
    )

    return (
        f"split=2[face][anim];"
        f"[face]{face_crop}[face_out];"
        f"[anim]{anim_fill}[anim_out];"
        f"[face_out][anim_out]vstack=2"
    )


# -------- CLI --------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Composition presets for video framing.")
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--print-filter", metavar="NAME")
    ap.add_argument("--video", help="Source video for face-track presets")
    ap.add_argument("--seg-start", type=float, default=0.0)
    ap.add_argument("--seg-end", type=float, default=None)
    args = ap.parse_args()

    if args.list_presets:
        for p in list_presets():
            print(p)
        sys.exit(0)

    if args.print_filter:
        flt = get_composition(
            args.print_filter,
            video_path=args.video,
            seg_start=args.seg_start,
            seg_end=args.seg_end,
        )
        print(flt)
        sys.exit(0)

    ap.print_help()
