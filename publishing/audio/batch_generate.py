#!/usr/bin/env python3
"""
shorts_v2 配下のEDL から BGM + SFX を ThreadPool で並列生成

使用例:
  python3 batch_generate.py                    # 全EDL対象 (既存を上書き)
  python3 batch_generate.py --only 07_ONLY_ONE # 1本だけ
  python3 batch_generate.py --skip-existing    # 既存ファイルはスキップ
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_bgm import generate_bgm
from generate_sfx import generate_sfx

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHORTS_DIR = ROOT / "source-podcast/edit/shorts_v2"
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


def collect_all_tasks(shorts_dir=None, only=None, skip_existing=False):
    """EDLからBGM+SFXタスクを収集 (only でID絞り、skip_existing で既存スキップ)"""
    if shorts_dir is None:
        shorts_dir = DEFAULT_SHORTS_DIR
    shorts_dir = Path(shorts_dir)
    tasks = []
    edl_ids = sorted([d.name for d in shorts_dir.iterdir() if d.is_dir()])
    if only:
        edl_ids = [x for x in edl_ids if x in only]
    for edl_id in edl_ids:
        edl_path = shorts_dir / edl_id / "edl.json"
        if not edl_path.exists():
            continue
        edl = json.loads(edl_path.read_text())
        audio = edl["audio"]

        bgm_out = ROOT / audio["bgm"]["output_path"]
        if not (skip_existing and bgm_out.exists()):
            tasks.append({
                "type": "bgm",
                "edl_id": edl_id,
                "prompt": audio["bgm"]["prompt"],
                "duration_ms": audio["bgm"]["duration_ms"],
                "output": audio["bgm"]["output_path"],
            })
        for sfx in audio["sfx_track"]:
            sfx_out = ROOT / sfx["output_path"]
            if skip_existing and sfx_out.exists():
                continue
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
    p = argparse.ArgumentParser()
    p.add_argument("--shorts-dir", type=Path, default=None,
                   help="Directory containing {ID}/edl.json (default: source-podcast/edit/shorts_v2)")
    p.add_argument("--only", nargs="+", help="EDL ID(s) to limit generation to")
    p.add_argument("--skip-existing", action="store_true", help="Skip files that already exist")
    args = p.parse_args()
    tasks = collect_all_tasks(shorts_dir=args.shorts_dir, only=args.only, skip_existing=args.skip_existing)
    if not tasks:
        print("No tasks (already generated or no matching EDLs).")
        return
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
