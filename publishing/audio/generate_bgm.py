#!/usr/bin/env python3
"""
ElevenLabs Music API BGM生成ヘルパー

使用例:
  python3 generate_bgm.py \
    --prompt "Solemn classical strings, slow tempo, building tension" \
    --duration_ms 22000 \
    --output ~/Documents/.../publishing/audio/bgm/01_KIRAWARENA.mp3

video-useと同じパターン: requests直接、SDK不要、ELEVENLABS_API_KEYを.envから取得
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

API_URL = "https://api.elevenlabs.io/v1/music"
ENV_PATH = Path(__file__).resolve().parents[2] / "video-use" / ".env"


def load_api_key() -> str:
    """video-useと同じパターンで.envからキーを取得"""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "ELEVENLABS_API_KEY":
                return v.strip().strip('"').strip("'")
    v = os.environ.get("ELEVENLABS_API_KEY", "")
    if not v:
        sys.exit("ELEVENLABS_API_KEY not found")
    return v


def generate_bgm(prompt: str, duration_ms: int, output: str, max_retries: int = 3) -> dict:
    api_key = load_api_key()
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration_ms = max(3000, min(300000, int(duration_ms)))

    for attempt in range(max_retries):
        t0 = time.time()
        try:
            resp = requests.post(
                API_URL,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={"prompt": prompt, "music_length_ms": duration_ms},
                timeout=180,
            )
            elapsed = time.time() - t0

            if resp.status_code == 200:
                output_path.write_bytes(resp.content)
                return {
                    "success": True,
                    "path": str(output_path),
                    "size_kb": len(resp.content) / 1024,
                    "elapsed_s": elapsed,
                    "duration_ms": duration_ms,
                }
            elif resp.status_code in [429, 500, 502, 503, 504]:
                wait = 2 ** (attempt + 1)
                print(f"  Retry {attempt+1}/{max_retries} after {wait}s (status: {resp.status_code})", file=sys.stderr)
                time.sleep(wait)
                continue
            else:
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                }
        except requests.exceptions.RequestException as e:
            wait = 2 ** (attempt + 1)
            print(f"  Network error retry {attempt+1}/{max_retries} after {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)

    return {"success": False, "error": f"Failed after {max_retries} retries"}


def main():
    parser = argparse.ArgumentParser(description="ElevenLabs Music API BGM生成")
    parser.add_argument("--prompt", required=True, help="音楽生成プロンプト (英語推奨)")
    parser.add_argument("--duration_ms", type=int, required=True, help="楽曲長 (3000-300000ms)")
    parser.add_argument("--output", required=True, help="出力MP3ファイルパス")
    args = parser.parse_args()

    result = generate_bgm(args.prompt, args.duration_ms, args.output)

    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
