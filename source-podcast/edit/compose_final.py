"""Compose animation + SFX + speed-up onto each short.
Output: shorts/<ID>/short_final.mp4 (vertical 1080x1920, 1.2x speed, with anim + SFX)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

SHORTS_DIR = Path(__file__).resolve().parent / "shorts"

# Animation start time per short (in original seconds before speed-up)
ANIM_START = {
    "01_HOOK_LINE": 3.0,
    "02_LION_BIRD": 15.0,
    "03_OLDER_LION": 20.0,
    "04_95_UNCONSCIOUS": 4.0,
    "05_GOKU_TRAINING": 6.0,
    "06_MARATHON": 12.0,
    "07_NO_FEAR_HATED": 15.0,
    "08_WORLD_SAVE": 15.0,
    "09_HAMBURGER": 20.0,
    "10_FIRST_PRINCIPLE": 25.0,
}

SPEED = 1.2  # playback speed-up factor


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def generate_sfx_whoosh(out: Path, duration: float = 0.5) -> None:
    """Bandpass-filtered white noise — whoosh."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={duration}",
        "-af", "bandpass=f=800:w=600,afade=t=in:d=0.03,afade=t=out:d=0.3,volume=0.35",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def generate_sfx_ding(out: Path, duration: float = 0.35) -> None:
    """Pure sine with quick decay — ding."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=1320:duration={duration}",
        "-af", "afade=t=out:d=0.3,volume=0.25",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def compose_one(short_dir: Path) -> tuple[str, bool, str, float]:
    name = short_dir.name
    t0 = time.time()
    try:
        short_mp4 = short_dir / "short.mp4"
        anim_mov = short_dir / "animation.mov"
        final = short_dir / "short_final.mp4"

        if not short_mp4.exists() or not anim_mov.exists():
            return (name, False, "missing short.mp4 or animation.mov", time.time() - t0)

        anim_dur = probe_duration(anim_mov)
        anim_start = ANIM_START.get(name, 3.0)
        anim_end = anim_start + anim_dur

        # Generate SFX into temp files
        sfx_whoosh = short_dir / "_sfx_whoosh.m4a"
        sfx_ding = short_dir / "_sfx_ding.m4a"
        generate_sfx_whoosh(sfx_whoosh, 0.5)
        generate_sfx_ding(sfx_ding, 0.35)

        # Mid-animation ding time (for "reveal" emphasis)
        ding_time = anim_start + anim_dur * 0.6

        # Build filter_complex:
        # [0] = base short (video+audio)
        # [1] = animation (video only, has alpha)
        # [2] = whoosh SFX
        # [3] = ding SFX
        filter_complex = (
            # Animation: PTS shift so frame 0 aligns with anim_start in output (Hard Rule 4)
            f"[1:v]setpts=PTS-STARTPTS+{anim_start}/TB[a1];"
            # Overlay with enable window
            f"[0:v][a1]overlay=enable='between(t,{anim_start:.3f},{anim_end:.3f})'[v_mid];"
            # Speed up video (Hard Rule 3 about fades is satisfied by short.mp4 already having fades)
            f"[v_mid]setpts=PTS/{SPEED}[outv];"
            # Audio: delay SFX to anim_start and ding_time, mix with base audio
            f"[2:a]adelay={int(anim_start*1000)}|{int(anim_start*1000)}[a_w];"
            f"[3:a]adelay={int(ding_time*1000)}|{int(ding_time*1000)}[a_d];"
            f"[0:a][a_w][a_d]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[a_mix];"
            # Speed up audio (pitch-preserving)
            f"[a_mix]atempo={SPEED}[outa]"
        )

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(short_mp4),
            "-i", str(anim_mov),
            "-i", str(sfx_whoosh),
            "-i", str(sfx_ding),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(final),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        # Cleanup
        sfx_whoosh.unlink(missing_ok=True)
        sfx_ding.unlink(missing_ok=True)

        size_mb = final.stat().st_size / (1024 * 1024)
        dt = time.time() - t0
        return (name, True, f"{final.name} ({size_mb:.1f}MB)", dt)
    except subprocess.CalledProcessError as e:
        return (name, False, f"ffmpeg: {e.stderr.decode()[:300] if e.stderr else str(e)}", time.time() - t0)
    except Exception as e:
        return (name, False, str(e), time.time() - t0)


def main():
    shorts = sorted([d for d in SHORTS_DIR.iterdir() if d.is_dir()])
    print(f"Composing {len(shorts)} final shorts (parallel, max 5)...")
    print(f"Settings: speed={SPEED}x, SFX whoosh@anim_start, ding@mid-anim\n")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(compose_one, d): d for d in shorts}
        done = 0
        for fut in as_completed(futures):
            name, ok, info, dt = fut.result()
            done += 1
            status = "✅" if ok else "❌"
            print(f"{status} [{done}/{len(shorts)}] {name} ({dt:.1f}s) — {info[:200]}")

    print(f"\nTotal: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
