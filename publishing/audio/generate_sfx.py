#!/usr/bin/env python3
"""
ElevenLabs Sound Effects API SFX生成ヘルパー

使用例:
  python3 generate_sfx.py \
    --text "metallic ding bell, sharp attack, short decay" \
    --duration_s 0.3 \
    --output ~/Documents/.../publishing/audio/sfx/01_KIRAWARENA_03.mp3

サブリミナル効果のあるSFX用 (whoosh/ding/build-up/impact等)
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

API_URL = "https://api.elevenlabs.io/v1/sound-generation"
ENV_PATH = Path(__file__).resolve().parents[2] / "video-use" / ".env"


def load_api_key() -> str:
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


def generate_sfx(
    text: str,
    duration_s: float,
    output: str,
    prompt_influence: float = 0.7,
    max_retries: int = 3,
) -> dict:
    api_key = load_api_key()
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration_s = max(0.5, min(30.0, float(duration_s)))  # ElevenLabs API: 0.5-30s
    prompt_influence = max(0.0, min(1.0, float(prompt_influence)))

    for attempt in range(max_retries):
        t0 = time.time()
        try:
            resp = requests.post(
                API_URL,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "duration_seconds": duration_s,
                    "prompt_influence": prompt_influence,
                },
                timeout=60,
            )
            elapsed = time.time() - t0

            if resp.status_code == 200:
                output_path.write_bytes(resp.content)
                return {
                    "success": True,
                    "path": str(output_path),
                    "size_kb": len(resp.content) / 1024,
                    "elapsed_s": elapsed,
                    "duration_s": duration_s,
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
            print(f"  Network retry {attempt+1}/{max_retries} after {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)

    return {"success": False, "error": f"Failed after {max_retries} retries"}


def main():
    parser = argparse.ArgumentParser(description="ElevenLabs Sound Effects API SFX生成")
    parser.add_argument("--text", required=True, help="SFX記述プロンプト")
    parser.add_argument("--duration_s", type=float, required=True, help="長さ秒 (0.1-22.0)")
    parser.add_argument("--output", required=True, help="出力MP3パス")
    parser.add_argument("--prompt_influence", type=float, default=0.7, help="0.0-1.0")
    args = parser.parse_args()

    result = generate_sfx(args.text, args.duration_s, args.output, args.prompt_influence)

    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
