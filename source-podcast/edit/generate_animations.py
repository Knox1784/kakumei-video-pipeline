"""Generate 10 diverse animations for shorts.
Each animation is PIL-based PNG sequence → WebM with alpha channel.
Saved to shorts/<ID>/animation.webm
"""
from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

FPS = 30
W, H = 1080, 1920
SHORTS_DIR = Path(__file__).resolve().parent / "shorts"
TMP_BASE = Path("/tmp/anim_gen")
TMP_BASE.mkdir(exist_ok=True)


# ----- Easing -----
def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * t ** 3
    return 1 - (-2 * t + 2) ** 3 / 2


# ----- Font -----
def font(size: int, weight: str = "W6") -> ImageFont.FreeTypeFont:
    candidates = [
        f"/System/Library/Fonts/ヒラギノ角ゴシック {weight}.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ----- Save sequence → WebM with alpha -----
def save_frames(frames: list[Image.Image], out_path: Path, anim_id: str) -> None:
    """Save PNG sequence, encode to ProRes 4444 MOV with alpha (reliable)."""
    tmp = TMP_BASE / anim_id
    tmp.mkdir(exist_ok=True)
    for p in tmp.glob("*.png"):
        p.unlink()
    for i, img in enumerate(frames):
        img.save(tmp / f"f_{i:04d}.png")
    # Force output to .mov for ProRes
    out_mov = out_path.with_suffix(".mov")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS),
        "-i", str(tmp / "f_%04d.png"),
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-vendor", "apl0",
        str(out_mov),
    ]
    subprocess.run(cmd, check=True)
    for p in tmp.glob("*.png"):
        p.unlink()


def text_size(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont):
    bbox = draw.textbbox((0, 0), text, font=f)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# =========================================================================
# ANIM 01: HOOK_LINE — keyword reveal + strikethrough on "成功者"
# =========================================================================
def anim_01(out_path: Path):
    dur, n = 3.5, int(3.5 * FPS)
    frames = []
    f_big = font(92, "W9")
    f_mid = font(68, "W6")
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Phase 1 (0-0.3): text slides in from bottom
        # Phase 2 (0.3-0.55): "成功者" flash red
        # Phase 3 (0.55-0.75): strikethrough drawn
        # Phase 4 (0.75-1.0): result text fade in
        y_center = 550
        if t < 0.3:
            e = ease_out_cubic(t / 0.3)
            y = int(y_center + (1 - e) * 200)
            alpha = int(e * 255)
            tw, th = text_size(d, "自分を成功者だと思った時点で", f_mid)
            d.text(((W - tw) // 2, y), "自分を成功者だと思った時点で", font=f_mid, fill=(255, 255, 255, alpha))
        elif t < 0.75:
            tw, th = text_size(d, "自分を成功者だと思った時点で", f_mid)
            d.text(((W - tw) // 2, y_center), "自分を成功者だと思った時点で", font=f_mid, fill=(255, 255, 255, 255))
            # "成功者" is at chars 3-6 — locate approximately
            # redraw with color overlay on 成功者
            prefix = "自分を"
            target = "成功者"
            pw, _ = text_size(d, prefix, f_mid)
            tw_full, _ = text_size(d, "自分を成功者だと思った時点で", f_mid)
            start_x = (W - tw_full) // 2 + pw
            tw2, th2 = text_size(d, target, f_mid)
            # Red rectangle behind
            if t > 0.4:
                red_e = ease_out_cubic(min(1.0, (t - 0.4) / 0.15))
                d.rectangle([start_x - 8, y_center - 4, start_x + tw2 + 8, y_center + th2 + 4],
                            fill=(255, 60, 60, int(red_e * 180)))
                d.text((start_x, y_center), target, font=f_mid, fill=(255, 255, 255, 255))
            # Strikethrough
            if t > 0.55:
                strike_e = ease_in_out_cubic(min(1.0, (t - 0.55) / 0.2))
                sy = y_center + th2 // 2
                sx_start = start_x - 8
                sx_end = start_x + int(tw2 * strike_e) + 8
                d.line([(sx_start, sy), (sx_end, sy)], fill=(255, 255, 50, 255), width=9)
        else:
            # Phase 4: result appears below
            tw, th = text_size(d, "自分を成功者だと思った時点で", f_mid)
            d.text(((W - tw) // 2, y_center), "自分を成功者だと思った時点で", font=f_mid, fill=(200, 200, 200, 255))
            # strikethrough permanent
            prefix = "自分を"
            pw, _ = text_size(d, prefix, f_mid)
            tw_full, _ = text_size(d, "自分を成功者だと思った時点で", f_mid)
            start_x = (W - tw_full) // 2 + pw
            tw2, th2 = text_size(d, "成功者", f_mid)
            d.line([(start_x - 8, y_center + th2 // 2), (start_x + tw2 + 8, y_center + th2 // 2)],
                   fill=(255, 255, 50, 255), width=9)
            # Result text
            e = ease_out_cubic(min(1.0, (t - 0.75) / 0.25))
            y2 = int(y_center + 200 + (1 - e) * 80)
            alpha = int(e * 255)
            result = "成功者じゃない"
            rw, rh = text_size(d, result, f_big)
            d.text(((W - rw) // 2, y2), result, font=f_big, fill=(255, 100, 100, alpha))
        frames.append(img)
    save_frames(frames, out_path, "01")


# =========================================================================
# ANIM 02: LION_BIRD — side-by-side comparison with X mark
# =========================================================================
def anim_02(out_path: Path):
    dur, n = 5.0, int(5.0 * FPS)
    f_emoji = font(260)
    f_label = font(54, "W6")
    f_mark = font(400, "W9")
    lion = "🦁"; bird = "🕊️"
    frames = []
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if t >= 0.0:
            e = ease_out_cubic(min(1.0, t / 0.3))
            lx = int(200 + (1 - e) * -400)
            d.text((lx, 500), lion, font=f_emoji, fill=(255, 255, 255, int(e * 255)))
            d.text((lx - 20, 780), "子ライオン", font=f_label, fill=(200, 200, 200, int(e * 255)))
        if t >= 0.3:
            e = ease_out_cubic(min(1.0, (t - 0.3) / 0.3))
            rx = int(620 + (1 - e) * 400)
            d.text((rx, 500), bird, font=f_emoji, fill=(255, 255, 255, int(e * 255)))
            d.text((rx - 30, 780), "経験の鳥", font=f_label, fill=(200, 200, 200, int(e * 255)))
        if t >= 0.5:
            e = ease_out_cubic(min(1.0, (t - 0.5) / 0.3))
            d.line([(420, 620), (420 + int(240 * e), 620)], fill=(255, 200, 50, 255), width=8)
            d.polygon([(660, 620), (640, 610), (640, 630)], fill=(255, 200, 50, 255))
        if t >= 0.78:
            e = ease_in_out_cubic(min(1.0, (t - 0.78) / 0.22))
            size = max(20, int(e * 500))
            xmark_font = font(size, "W9")
            tw, th = text_size(d, "✗", xmark_font)
            d.text((650 + 130 - tw // 2, 500 + 130 - th // 2), "✗", font=xmark_font, fill=(255, 50, 50, 255))
        frames.append(img)
    save_frames(frames, out_path, "02")


# =========================================================================
# ANIM 03: OLDER_LION — hierarchy tree
# =========================================================================
def anim_03(out_path: Path):
    dur, n = 4.5, int(4.5 * FPS)
    f_emoji = font(180)
    f_label = font(42, "W6")
    f_big = font(90, "W9")
    frames = []
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Parent (top) at y=300
        # Older brother (middle-left) at y=700
        # Child viewer (middle-right) at y=700
        if t >= 0.0:
            e = ease_out_cubic(min(1.0, t / 0.25))
            d.text((W // 2 - 90, int(300 + (1 - e) * -100)), "🦁", font=f_emoji, fill=(255, 255, 255, int(e * 255)))
            d.text((W // 2 - 80, 500), "親ライオン", font=f_label, fill=(150, 150, 150, int(e * 255)))
        if t >= 0.25:
            e = ease_out_cubic(min(1.0, (t - 0.25) / 0.25))
            # Lines from parent to children
            d.line([(W // 2, 500), (300, 700 - int(50 * (1 - e)))], fill=(100, 100, 100, int(e * 255)), width=5)
            d.line([(W // 2, 500), (W - 300, 700 - int(50 * (1 - e)))], fill=(100, 100, 100, int(e * 255)), width=5)
        if t >= 0.4:
            e = ease_out_cubic(min(1.0, (t - 0.4) / 0.2))
            # Older brother (Shoma) — emphasized orange
            lx = 300 - 90
            ly = int(700 + (1 - e) * -80)
            d.text((lx, ly), "🦁", font=f_emoji, fill=(255, 180, 50, int(e * 255)))
            d.text((lx, 900), "兄(Shoma)", font=f_label, fill=(255, 180, 50, int(e * 255)))
        if t >= 0.55:
            e = ease_out_cubic(min(1.0, (t - 0.55) / 0.2))
            rx = W - 300 - 90
            ry = int(700 + (1 - e) * -80)
            d.text((rx, ry), "🦁", font=f_emoji, fill=(100, 180, 255, int(e * 255)))
            d.text((rx, 900), "子(You)", font=f_label, fill=(100, 180, 255, int(e * 255)))
        if t >= 0.78:
            e = ease_in_out_cubic(min(1.0, (t - 0.78) / 0.22))
            # Arrow from brother to child
            d.line([(480, 790), (480 + int(160 * e), 790)], fill=(255, 180, 50, 255), width=10)
            d.polygon([(640, 790), (620, 775), (620, 805)], fill=(255, 180, 50, 255))
        frames.append(img)
    save_frames(frames, out_path, "03")


# =========================================================================
# ANIM 04: 95_UNCONSCIOUS — iceberg
# =========================================================================
def anim_04(out_path: Path):
    dur, n = 4.0, int(4.0 * FPS)
    f_label = font(56, "W6")
    f_pct = font(140, "W9")
    frames = []
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Waterline at y=500
        # Iceberg tip above (5%), body below (95%)
        water_y = 500
        if t >= 0.0:
            e = ease_out_cubic(min(1.0, t / 0.3))
            # Iceberg above water (tip)
            tip_h = int(120 * e)
            tip = [(W // 2, water_y - tip_h), (W // 2 - 90, water_y), (W // 2 + 90, water_y)]
            d.polygon(tip, fill=(240, 250, 255, 255))
        if t >= 0.25:
            e = ease_in_out_cubic(min(1.0, (t - 0.25) / 0.4))
            # Body below water
            body_h = int(800 * e)
            body = [(W // 2 - 90, water_y), (W // 2 + 90, water_y),
                    (W // 2 + 250, water_y + body_h), (W // 2 - 250, water_y + body_h)]
            d.polygon(body, fill=(180, 200, 220, 200))
            # Water line
            d.line([(100, water_y), (W - 100, water_y)], fill=(80, 140, 200, 255), width=6)
        if t >= 0.5:
            e = ease_out_cubic(min(1.0, (t - 0.5) / 0.25))
            # Labels
            d.text((100, water_y - 140), "意識", font=f_label, fill=(200, 200, 200, int(e * 255)))
            d.text((60, water_y - 80), "5%", font=f_pct, fill=(255, 255, 255, int(e * 255)))
        if t >= 0.7:
            e = ease_out_cubic(min(1.0, (t - 0.7) / 0.25))
            d.text((100, water_y + 200), "無意識", font=f_label, fill=(100, 200, 255, int(e * 255)))
            d.text((80, water_y + 280), "95%", font=f_pct, fill=(100, 200, 255, int(e * 255)))
        frames.append(img)
    save_frames(frames, out_path, "04")


# =========================================================================
# ANIM 05: GOKU_TRAINING — progress bar + counter
# =========================================================================
def anim_05(out_path: Path):
    dur, n = 4.0, int(4.0 * FPS)
    f_label = font(52, "W6")
    f_count = font(220, "W9")
    frames = []
    bar_y = 800
    bar_x = 100
    bar_w = W - 200
    bar_h = 60
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Counter from 1 to 100
        count = min(100, int(t * 100))
        # Label
        d.text((W // 2 - 100, bar_y - 200), "修行", font=f_label, fill=(255, 200, 50, 255))
        # Big counter
        ctext = f"{count:03d}"
        cw, ch = text_size(d, ctext, f_count)
        d.text(((W - cw) // 2, bar_y - 400), ctext, font=f_count, fill=(255, 200, 50, 255))
        # Bar background
        d.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=30, fill=(40, 40, 40, 200))
        # Bar fill
        fill_w = int(bar_w * (count / 100))
        if fill_w > 10:
            d.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=30, fill=(255, 200, 50, 255))
        # Level text
        d.text((bar_x + bar_w // 2 - 50, bar_y + 80), "LEVEL UP", font=f_label, fill=(255, 200, 50, 200))
        frames.append(img)
    save_frames(frames, out_path, "05")


# =========================================================================
# ANIM 06: MARATHON — two runners side-by-side
# =========================================================================
def anim_06(out_path: Path):
    dur, n = 5.0, int(5.0 * FPS)
    f_emoji = font(160)
    f_label = font(44, "W6")
    frames = []
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Ground line
        ground_y = 900
        d.line([(50, ground_y), (W - 50, ground_y)], fill=(100, 100, 100, 200), width=4)
        # Two runners moving
        # Phase 1 (0-0.3): Fade in
        # Phase 2 (0.3-0.7): Run together
        # Phase 3 (0.7-1.0): Shoma a bit ahead
        base_x1 = 250  # You
        base_x2 = 600  # Shoma
        offset1 = 0
        offset2 = 0
        if t >= 0.3:
            bob = math.sin(t * 20) * 8  # bobbing
        else:
            bob = 0
        if t >= 0.7:
            e = ease_in_out_cubic(min(1.0, (t - 0.7) / 0.3))
            offset2 = int(e * 100)
        # Draw runners
        fade = ease_out_cubic(min(1.0, t / 0.3))
        a = int(fade * 255)
        d.text((base_x1 + offset1, ground_y - 170 + int(bob)), "🏃", font=f_emoji, fill=(100, 200, 255, a))
        d.text((base_x2 + offset2, ground_y - 170 + int(bob)), "🏃", font=f_emoji, fill=(255, 180, 50, a))
        # Labels
        d.text((base_x1 + 10, ground_y + 40), "You", font=f_label, fill=(100, 200, 255, a))
        d.text((base_x2 + 10, ground_y + 40), "Shoma", font=f_label, fill=(255, 180, 50, a))
        frames.append(img)
    save_frames(frames, out_path, "06")


# =========================================================================
# ANIM 07: NO_FEAR_HATED — "怖い" shrinking to "0"
# =========================================================================
def anim_07(out_path: Path):
    dur, n = 3.5, int(3.5 * FPS)
    frames = []
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Phase 1 (0-0.25): 怖い appears huge
        # Phase 2 (0.25-0.7): shrinks down
        # Phase 3 (0.7-1.0): becomes 0 with green glow
        if t < 0.25:
            e = ease_out_cubic(t / 0.25)
            size = int(100 + e * 300)
            ff = font(size, "W9")
            tw, th = text_size(d, "怖い", ff)
            d.text(((W - tw) // 2, (H - th) // 2), "怖い", font=ff, fill=(200, 50, 50, int(e * 255)))
        elif t < 0.7:
            e = ease_in_out_cubic((t - 0.25) / 0.45)
            size = int(400 - e * 370)
            ff = font(max(20, size), "W9")
            tw, th = text_size(d, "怖い", ff)
            d.text(((W - tw) // 2, (H - th) // 2), "怖い", font=ff, fill=(200, 50, 50, 255))
            # Ruler hint
            if e > 0.5:
                fr = font(40, "W6")
                rw, _ = text_size(d, "1mm", fr)
                d.text((W // 2 - rw // 2, H // 2 + 80), "1mm", font=fr, fill=(255, 255, 255, 200))
        else:
            e = ease_out_cubic((t - 0.7) / 0.3)
            # 0 with green pulse
            pulse = 1.0 + math.sin(t * 30) * 0.05
            size = int(500 * pulse)
            ff = font(size, "W9")
            tw, th = text_size(d, "0", ff)
            d.text(((W - tw) // 2, (H - th) // 2), "0", font=ff, fill=(100, 255, 100, 255))
            # Sub
            fs = font(60, "W6")
            sub = "1ミリも怖くない"
            sw, sh = text_size(d, sub, fs)
            d.text(((W - sw) // 2, (H + th) // 2 + 80), sub, font=fs, fill=(255, 255, 255, int(e * 255)))
        frames.append(img)
    save_frames(frames, out_path, "07")


# =========================================================================
# ANIM 08: WORLD_SAVE — radar with 1 dot remaining
# =========================================================================
def anim_08(out_path: Path):
    dur, n = 4.0, int(4.0 * FPS)
    f_label = font(48, "W6")
    frames = []
    random.seed(42)
    n_dots = 60
    # Pre-generate dot positions
    dots = [(random.randint(200, W - 200), random.randint(400, H - 400)) for _ in range(n_dots)]
    target_idx = 30  # the lucky one
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Phase 1 (0-0.3): All dots appear
        # Phase 2 (0.3-0.7): Most fade to grey/invisible
        # Phase 3 (0.7-1.0): Target dot pulses green + label
        for idx, (px, py) in enumerate(dots):
            if t < 0.3:
                e = ease_out_cubic(min(1.0, t / 0.3))
                d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(255, 255, 255, int(e * 255)))
            elif t < 0.7:
                e = ease_in_out_cubic(min(1.0, (t - 0.3) / 0.4))
                if idx != target_idx:
                    # fade out
                    alpha = int((1 - e) * 255)
                    if alpha > 5:
                        d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(120, 120, 120, alpha))
                else:
                    d.ellipse([px - 8, py - 8, px + 8, py + 8], fill=(100, 255, 150, 255))
            else:
                # pulsing
                pulse = 1.0 + math.sin(t * 20) * 0.3
                if idx == target_idx:
                    r = int(30 * pulse)
                    d.ellipse([px - r, py - r, px + r, py + r], fill=(100, 255, 150, 150))
                    d.ellipse([px - 12, py - 12, px + 12, py + 12], fill=(100, 255, 150, 255))
        if t >= 0.75:
            e = ease_out_cubic(min(1.0, (t - 0.75) / 0.25))
            label = "世界を救う人"
            lw, _ = text_size(d, label, f_label)
            px, py = dots[target_idx]
            d.text((px - lw // 2, py - 80), label, font=f_label, fill=(100, 255, 150, int(e * 255)))
        frames.append(img)
    save_frames(frames, out_path, "08")


# =========================================================================
# ANIM 09: HAMBURGER — emoji + donut chart
# =========================================================================
def anim_09(out_path: Path):
    dur, n = 4.5, int(4.5 * FPS)
    f_emoji = font(280)
    f_pct = font(120, "W9")
    f_label = font(48, "W6")
    frames = []
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Phase 1 (0-0.3): hamburger appears
        # Phase 2 (0.3-0.7): donut chart draws
        # Phase 3 (0.7-1.0): labels
        if t >= 0.0:
            e = ease_out_cubic(min(1.0, t / 0.3))
            scale = 0.5 + 0.5 * e
            size = int(280 * scale)
            ff = font(max(20, size))
            d.text((W // 2 - 140, 400), "🍔", font=ff, fill=(255, 255, 255, int(e * 255)))
        if t >= 0.3:
            e = ease_in_out_cubic(min(1.0, (t - 0.3) / 0.4))
            # Donut chart — arc drawing
            cx, cy = W // 2, 1100
            r = 200
            # 5% slice (top)
            arc_end = 360 * 0.05 * e
            d.pieslice([cx - r, cy - r, cx + r, cy + r], start=-90, end=-90 + arc_end,
                       fill=(255, 100, 100, 255), outline=None)
            # 95% slice
            arc_end2 = 360 * 0.95 * e
            d.pieslice([cx - r, cy - r, cx + r, cy + r], start=-90 + arc_end, end=-90 + arc_end + arc_end2,
                       fill=(255, 180, 50, 255), outline=None)
            # Inner hole
            d.ellipse([cx - 100, cy - 100, cx + 100, cy + 100], fill=(0, 0, 0, 0))
        if t >= 0.7:
            e = ease_out_cubic(min(1.0, (t - 0.7) / 0.3))
            d.text((W // 2 - 260, 1400), "5%意識", font=f_label, fill=(255, 100, 100, int(e * 255)))
            d.text((W // 2 + 50, 1400), "95%無意識", font=f_label, fill=(255, 180, 50, int(e * 255)))
        frames.append(img)
    save_frames(frames, out_path, "09")


# =========================================================================
# ANIM 10: FIRST_PRINCIPLE — compass with rotating needle
# =========================================================================
def anim_10(out_path: Path):
    dur, n = 5.0, int(5.0 * FPS)
    f_label = font(56, "W6")
    f_n = font(80, "W9")
    frames = []
    cx, cy = W // 2, 900
    r = 280
    for i in range(n):
        t = i / (n - 1)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Phase 1 (0-0.2): compass circle appears
        # Phase 2 (0.2-0.6): needle rotating
        # Phase 3 (0.6-0.8): needle locks north
        # Phase 4 (0.8-1.0): label "第一原理"
        # Compass circle
        if t >= 0.0:
            e = ease_out_cubic(min(1.0, t / 0.2))
            alpha = int(e * 255)
            for rr in range(r - 8, r + 1):
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(255, 220, 50, alpha))
            # N mark
            d.text((cx - 25, cy - r - 80), "N", font=f_n, fill=(255, 220, 50, alpha))
        # Needle
        if t >= 0.2:
            e = ease_in_out_cubic(min(1.0, (t - 0.2) / 0.4))
            # Rotating: sweep 720 degrees then stop at 90 (north)
            if t < 0.7:
                angle = (e * 720 - 90) % 360
            else:
                # Settle at north
                settle_e = ease_out_cubic((t - 0.7) / 0.3)
                start_angle = (0.5 * 720 - 90) % 360  # snapshot at t=0.7
                # Just point north
                angle = -90
            rad = math.radians(angle)
            nlen = r - 30
            nx = cx + nlen * math.cos(rad)
            ny = cy + nlen * math.sin(rad)
            d.line([(cx, cy), (nx, ny)], fill=(255, 50, 50, 255), width=14)
            # Tail (opposite)
            nx2 = cx - (nlen - 60) * math.cos(rad)
            ny2 = cy - (nlen - 60) * math.sin(rad)
            d.line([(cx, cy), (nx2, ny2)], fill=(180, 180, 180, 255), width=10)
            # Center pin
            d.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], fill=(255, 220, 50, 255))
        if t >= 0.8:
            e = ease_out_cubic((t - 0.8) / 0.2)
            label = "第一原理"
            lw, _ = text_size(d, label, f_label)
            d.text(((W - lw) // 2, cy - r - 180), label, font=f_label, fill=(255, 220, 50, int(e * 255)))
            # External arrows bouncing
            for a in [135, 225, 315]:
                rad = math.radians(a)
                bx = cx + (r + 200 - int(e * 150)) * math.cos(rad)
                by = cy + (r + 200 - int(e * 150)) * math.sin(rad)
                d.line([(bx, by),
                        (cx + (r + 50) * math.cos(rad), cy + (r + 50) * math.sin(rad))],
                       fill=(150, 150, 150, 200), width=6)
        frames.append(img)
    save_frames(frames, out_path, "10")


# =========================================================================
# MAIN — parallel generation
# =========================================================================
ANIMS = [
    ("01_HOOK_LINE", anim_01),
    ("02_LION_BIRD", anim_02),
    ("03_OLDER_LION", anim_03),
    ("04_95_UNCONSCIOUS", anim_04),
    ("05_GOKU_TRAINING", anim_05),
    ("06_MARATHON", anim_06),
    ("07_NO_FEAR_HATED", anim_07),
    ("08_WORLD_SAVE", anim_08),
    ("09_HAMBURGER", anim_09),
    ("10_FIRST_PRINCIPLE", anim_10),
]


def main():
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    t0 = time.time()

    def do(item):
        name, fn = item
        out = SHORTS_DIR / name / "animation.webm"
        ts = time.time()
        try:
            fn(out)
            return (name, True, time.time() - ts, None)
        except Exception as e:
            return (name, False, time.time() - ts, str(e))

    print(f"Generating {len(ANIMS)} animations in parallel (max 4 workers)...\n")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(do, item): item for item in ANIMS}
        done = 0
        for fut in as_completed(futures):
            name, ok, dt, err = fut.result()
            done += 1
            print(f"{'✅' if ok else '❌'} [{done}/{len(ANIMS)}] {name} ({dt:.1f}s)"
                  + (f"  ERR: {err[:200]}" if err else ""))

    print(f"\nTotal: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
