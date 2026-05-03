#!/usr/bin/env python3
"""
最終音声mix: base動画 (映像+ナレ) + BGM + SFX[] → 完成動画

設計思想:
- 映像トラックは触らない (-c:v copy で再エンコードゼロ、品質劣化なし)
- 音声のみ amix で voice + bgm + sfx を多層合成
- 音量バランスは audio_mix_config.yaml から読み込み (single source of truth)
- 全体を loudnorm で YouTube/TikTok標準 -14 LUFS に正規化
- EDLの audio.mix_override で個別クリップ音量上書き可能

使用例:
  python3 mix_final.py \
    --base /path/to/base.mp4 \
    --bgm /path/to/bgm.mp3 \
    --sfx-spec '[{"time_s": 0.0, "file": "sfx_01.mp3"}, ...]' \
    --output /path/to/short_with_audio.mp4
"""
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

try:
    import yaml  # PyYAML
except ImportError:
    print("PyYAML not installed. Falling back to manual config parser.", file=sys.stderr)
    yaml = None


CONFIG_PATH = Path(__file__).resolve().parent / "audio_mix_config.yaml"


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """audio_mix_config.yaml を読む。yaml未インストール時は最小パーサーで対応"""
    if yaml:
        return yaml.safe_load(config_path.read_text())

    # 最小限のyamlパーサー (依存削減)
    config = {"volumes": {}, "loudness": {}, "bgm": {}, "sfx": {}, "mix": {}}
    section = None
    for line in config_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not line.startswith(" ") and s.endswith(":"):
            section = s.rstrip(":")
            if section not in config:
                config[section] = {}
            continue
        if ":" in s and section:
            k, v = s.split(":", 1)
            v = v.strip().strip('"').strip("'")
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    if v in ("true", "True"):
                        v = True
                    elif v in ("false", "False"):
                        v = False
            config[section][k.strip()] = v
    return config


def build_filter_complex(
    bgm_path: str,
    sfx_specs: list,
    config: dict,
    base_has_audio: bool = True,
    mix_override: dict = None,
) -> tuple:
    """
    ffmpeg -filter_complex の文字列と入力ファイルリストを構築

    Returns:
      (filter_str, input_files)
    """
    vols = config["volumes"]
    if mix_override:
        vols = {**vols, **mix_override}

    narration_db = vols.get("narration_db", 0)
    sfx_db = vols.get("sfx_db", -10)
    bgm_db = vols.get("bgm_db", -22)

    bgm_cfg = config.get("bgm", {})
    fade_in_ms = bgm_cfg.get("fade_in_ms", 500)
    fade_out_ms = bgm_cfg.get("fade_out_ms", 1500)

    loud = config.get("loudness", {})
    target_lufs = loud.get("integrated_target_lufs", -14)
    true_peak = loud.get("true_peak_db", -1)
    lra = loud.get("loudness_range", 11)

    # 入力 0: base動画 (映像+ナレ)、1: BGM、2..N+1: 各SFX
    input_files = [bgm_path] + [s["file"] for s in sfx_specs]

    parts = []

    # 各素材を loudnorm で -16 LUFS に揃えてから相対音量を適用
    # → 素材ごとの元音量差に依存しない予測可能なmix
    PRE_NORM = "loudnorm=I=-16:TP=-1:LRA=11"

    # ダッキング設定
    duck_cfg = config.get("ducking", {})
    duck_enabled = duck_cfg.get("enabled", False) and base_has_audio
    duck_threshold = duck_cfg.get("threshold", 0.04)
    duck_ratio = duck_cfg.get("ratio", 8)
    duck_attack = duck_cfg.get("attack_ms", 20)
    duck_release = duck_cfg.get("release_ms", 350)

    # ナレ層: 素材正規化 → 相対音量
    # ダッキング有効時は asplit で2系統に複製 (mix用 + sidechain用)
    if base_has_audio:
        if duck_enabled:
            parts.append(
                f"[0:a]{PRE_NORM},volume={narration_db}dB,"
                f"asplit=2[narr][narr_sc]"
            )
        else:
            parts.append(f"[0:a]{PRE_NORM},volume={narration_db}dB[narr]")

    # BGM duration をffprobeで取得 → fade_outの正しい開始時刻を計算
    bgm_dur_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(bgm_path)],
        capture_output=True, text=True
    )
    try:
        bgm_duration_s = float(bgm_dur_probe.stdout.strip())
    except (ValueError, AttributeError):
        bgm_duration_s = 30.0  # fallback
    fade_out_start_s = max(0, bgm_duration_s - fade_out_ms / 1000.0)

    # BGM層: 素材正規化 → 相対音量 → フェードイン → フェードアウト (末尾のみ)
    bgm_label = "bgm_pre" if duck_enabled else "bgm"
    parts.append(
        f"[1:a]{PRE_NORM},volume={bgm_db}dB,"
        f"afade=t=in:st=0:d={fade_in_ms/1000.0},"
        f"afade=t=out:st={fade_out_start_s}:d={fade_out_ms/1000.0}:curve=tri[{bgm_label}]"
    )

    # ダッキング: ナレが鳴っている瞬間にBGMを自動的に下げる (sidechain compression)
    if duck_enabled:
        parts.append(
            f"[bgm_pre][narr_sc]sidechaincompress="
            f"threshold={duck_threshold}:ratio={duck_ratio}:"
            f"attack={duck_attack}:release={duck_release}[bgm]"
        )

    # SFX層: 素材正規化 → 相対音量 → 時刻配置
    sfx_labels = []
    for i, s in enumerate(sfx_specs):
        delay_ms = int(s["time_s"] * 1000)
        label = f"sfx{i}"
        parts.append(
            f"[{i+2}:a]{PRE_NORM},adelay={delay_ms}|{delay_ms},volume={sfx_db}dB[{label}]"
        )
        sfx_labels.append(f"[{label}]")

    # 全レイヤー合成 (normalize=0 で各レイヤー音量を保持)
    layers = []
    if base_has_audio:
        layers.append("[narr]")
    layers.append("[bgm]")
    layers.extend(sfx_labels)

    n_inputs = len(layers)
    amix_norm = config.get("mix", {}).get("amix_normalize", 0)
    parts.append(
        f"{''.join(layers)}amix=inputs={n_inputs}:"
        f"duration=longest:dropout_transition=0:normalize={amix_norm}[mix]"
    )

    # Loudness正規化 (YouTube標準)
    parts.append(f"[mix]loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}[a_out]")

    return ";".join(parts), input_files


def mix(
    base_video: str,
    bgm_path: str,
    sfx_specs: list,
    output: str,
    config_path: Path = CONFIG_PATH,
    mix_override: dict = None,
) -> dict:
    config = load_config(config_path)
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # base動画にaudioあるか確認
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(base_video)],
        capture_output=True, text=True
    )
    base_has_audio = "audio" in probe.stdout

    filter_str, input_files = build_filter_complex(
        bgm_path, sfx_specs, config, base_has_audio, mix_override
    )

    mix_cfg = config.get("mix", {})
    cmd = ["ffmpeg", "-y", "-i", str(base_video)]
    for f in input_files:
        cmd.extend(["-i", str(f)])
    cmd.extend([
        "-filter_complex", filter_str,
        "-map", "0:v",
        "-map", "[a_out]",
        "-c:v", "copy",
        "-c:a", mix_cfg.get("output_codec", "aac"),
        "-b:a", mix_cfg.get("output_bitrate", "192k"),
        "-ar", str(mix_cfg.get("output_sample_rate", 44100)),
        "-ac", str(mix_cfg.get("output_channels", 2)),
        str(output_path),
    ])

    print(f"[mix_final] Running ffmpeg with {len(sfx_specs)} SFX layer(s)...", file=sys.stderr)

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {
            "success": False,
            "error": proc.stderr[-1500:],
            "cmd": shlex.join(cmd[:30]) + " ...",
        }

    return {
        "success": True,
        "output": str(output_path),
        "size_mb": output_path.stat().st_size / (1024 * 1024),
        "n_sfx": len(sfx_specs),
        "config_used": str(config_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Audio multi-layer mix")
    parser.add_argument("--base", required=True, help="base動画 (映像+ナレ済)")
    parser.add_argument("--bgm", required=True, help="BGM mp3")
    parser.add_argument("--sfx-spec", required=True, help="JSON: [{time_s, file}, ...]")
    parser.add_argument("--output", required=True, help="出力mp4")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="audio_mix_config.yaml")
    parser.add_argument("--override", default=None, help='JSON: {"narration_db": 0, ...}')
    args = parser.parse_args()

    sfx_specs = json.loads(args.sfx_spec)
    mix_override = json.loads(args.override) if args.override else None

    result = mix(
        args.base, args.bgm, sfx_specs, args.output,
        config_path=Path(args.config),
        mix_override=mix_override,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
