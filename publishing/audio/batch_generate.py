#!/usr/bin/env python3
"""
6本分のBGM + SFX を ThreadPool で並列生成

使用例:
  python3 batch_generate.py
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_bgm import generate_bgm
from generate_sfx import generate_sfx

ROOT = Path(__file__).resolve().parents[2]
SHORTS_V2 = ROOT / "source-podcast/edit/shorts_v2"
# EDLの output_path は "publishing/audio/..." 形式なので ROOT 起点で解決する


def gen_bgm_task(spec):
    """spec = {edl_id, prompt, duration_ms, output}"""
    out = ROOT / spec["output"]
    result = generate_bgm(spec["prompt"], spec["duration_ms"], str(out))
    return {"type": "bgm", "id": spec["edl_id"], **result}


def gen_sfx_task(spec):
    """spec = {edl_id, time_s, desc, duration_s, output}"""
    out = ROOT / spec["output"]
    result = generate_sfx(spec["desc"], spec["duration_s"], str(out))
    return {"type": "sfx", "id": spec["edl_id"], "time_s": spec["time_s"], **result}


def collect_all_tasks():
    """6本のEDLからBGM+SFXタスクを収集"""
    tasks = []
    edl_ids = sorted([d.name for d in SHORTS_V2.iterdir() if d.is_dir()])
    for edl_id in edl_ids:
        edl_path = SHORTS_V2 / edl_id / "edl.json"
        edl = json.loads(edl_path.read_text())
        audio = edl["audio"]

        tasks.append({
            "type": "bgm",
            "edl_id": edl_id,
            "prompt": audio["bgm"]["prompt"],
            "duration_ms": audio["bgm"]["duration_ms"],
            "output": audio["bgm"]["output_path"],
        })
        for sfx in audio["sfx_track"]:
            tasks.append({
                "type": "sfx",
                "edl_id": edl_id,
                "time_s": sfx["time_s"],
                "desc": sfx["desc"],
                "duration_s": sfx["duration_s"],
                "output": sfx["output_path"],
            })
    return tasks


def main():
    tasks = collect_all_tasks()
    bgm_tasks = [t for t in tasks if t["type"] == "bgm"]
    sfx_tasks = [t for t in tasks if t["type"] == "sfx"]

    print(f"BGM: {len(bgm_tasks)} 本")
    print(f"SFX: {len(sfx_tasks)} 個")
    print(f"合計: {len(tasks)} アセット並列生成開始...\n")

    success = 0
    failed = []

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = []
        for t in bgm_tasks:
            futures.append(ex.submit(gen_bgm_task, t))
        for t in sfx_tasks:
            futures.append(ex.submit(gen_sfx_task, t))

        for f in as_completed(futures):
            r = f.result()
            if r.get("success"):
                success += 1
                t_str = f"@{r['time_s']}s" if r["type"] == "sfx" else ""
                print(f"  ✅ [{r['type']}] {r['id']} {t_str} ({r.get('elapsed_s', 0):.1f}s, {r.get('size_kb', 0):.1f}KB)")
            else:
                failed.append(r)
                print(f"  ❌ [{r['type']}] {r['id']}: {r.get('error', '?')[:200]}")

    print(f"\n=== 完了: {success}/{len(tasks)} 成功 ===")
    if failed:
        print(f"\n=== 失敗 {len(failed)} 件 ===")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
