"""Compare base and official Turbo through HocusPocus, retaining requests and PNGs.

Run against a freshly started backend. Does not change saved model choices.
Each model gets an unscored warmup; every scored pair uses identical inputs.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

MODELS = ("qwen_image_21", "qwen_image_21_turbo")
CASES = {
    "portrait": "Editorial photograph of a woman with freckles and curly auburn hair wearing a green knitted sweater, holding a ceramic mug in both hands, sitting beside a window. Natural soft side lighting, realistic skin texture, shallow depth of field, detailed fingers and knitted fabric. No text.",
    "typography": 'A clean illustrated travel poster. Large heading exactly "HOCUSPOCUS". Subtitle exactly "MADRID AT SUNSET". At the bottom exactly "CREATE YOUR WORLD". A red tram crosses a cobblestone street with balconies and warm sunset light. Crisp readable typography, refined graphic design, no additional text.',
    "objects": "A small blue ceramic robot watering a fern in a terracotta pot on a sunny wooden windowsill. The robot holds one yellow watering can with both hands. A red book and a glass of water sit to the right of the pot. Detailed glazed ceramic, natural green leaves, coherent shadows, editorial product photograph.",
    "native2k": "An isolated ornate glass potion bottle with a golden stopper and purple glowing liquid, surrounded by three small green leaves. Transparent background, no shadow on a surface, detailed glass reflections, fantasy game inventory asset, no text.",
    "edit": "Change only the blue ceramic robot to glossy red ceramic. Keep its shape, the yellow watering can, the fern, the terracotta pot, the red book, the glass of water, the composition and lighting unchanged.",
}


def request(base, route, body=None):
    req = urllib.request.Request(base.rstrip("/") + route,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read().decode()}") from error


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def report(output, results):
    """Standalone comparison with unchanged output images on a checkerboard."""
    rows = []
    by_pair = {(row["model"], row["case"]): row for row in results}
    for case in CASES:
        cells = []
        for model in MODELS:
            row = by_pair.get((model, case))
            if not row:
                continue
            phases = [phase for timing in row["status"].get("task_timings", [])
                      for phase in timing.get("phase_timings", [])]
            sampling = sum(phase["seconds"] for phase in phases if "denoising" in phase["phase"].lower())
            caption = f'{model}: {row["status"].get("processing_time_sec")} s total; {sampling:.2f} s sampling'
            cells.append(f'<figure><a href="{model}/{case}/output-0.png"><img src="{model}/{case}/output-0.png" loading="lazy"></a><figcaption>{html.escape(caption)}</figcaption></figure>')
        if cells:
            rows.append(f'<section><h2>{html.escape(case)}</h2><p>{html.escape(CASES[case])}</p><div class="pair">{"".join(cells)}</div></section>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Qwen 2.1 Base / Official Turbo</title>
<style>body{margin:2em;background:#14151b;color:#eee;font:16px system-ui}main{max-width:1400px;margin:auto}section{margin:3em 0}.pair{display:flex;gap:1em}figure{margin:0;flex:1;min-width:0}img{width:100%;background:repeating-conic-gradient(#999 0% 25%,#ddd 0% 50%) 50% / 24px 24px}figcaption{padding:.5em}p{max-width:100ch}a{color:inherit}@media(max-width:700px){.pair{display:block}figure{margin-bottom:1em}}</style>
<main><h1>Qwen 2.1 Base / Official Turbo</h1><p>RTX 4090 · INT8 ConvRot · SDPA · profile 3 · CFG 1 · seed 20261010. Base: 40 steps; official Turbo: 8 steps. Each model warmed up before scoring. Identical prompts and inputs; both edits use the base objects image. 1024² except native2k at 2048². Times exclude queue and download. This small comparison does not establish identical quality for all prompts.</p>'''
    (output / "comparison.html").write_text(page + "".join(rows) + "</main></html>")


def run_case(base, output, workspace, model, case, reference=None):
    folder = output / model / case
    result_file = folder / "result.json"
    if result_file.exists():
        saved = json.loads(result_file.read_text())
        if saved["status"]["status"] != "completed":
            raise RuntimeError(f"Previous job failed; inspect {result_file} before retrying.")
        return saved
    active_file = folder / "active.json"
    if active_file.exists():
        active = json.loads(active_file.read_text())
    else:
        defaults = request(base, "/api/v1/defaults/" + model)
        params = {**defaults, "model_type": model, "prompt": CASES.get(case, CASES["objects"]),
            "seed": 20261010, "resolution": "2048x2048" if case == "native2k" else "1024x1024",
            "num_inference_steps": 8 if model.endswith("_turbo") else 40,
            "guidance_scale": 1, "batch_size": 1, "video_length": 1, "image_mode": 1,
            "override_profile": 3, "override_attention": "sdpa", "sample_solver": "default",
            "multi_prompts_gen_type": 2, "activated_loras": [], "loras_multipliers": "",
            "skip_steps_cache_type": "", "workspace": workspace, "negative_prompt": "",
            "video_prompt_type": "KI" if reference else "", "image_refs": [str(reference)] if reference else [],
            "remove_background_images_ref": 0,
            "output_name": f"{model}-{case}",
        }
        save(folder / "request.json", params)
        started = time.time()
        submission = request(base, "/api/v1/generate", params)
        active = {"job_id": submission["job_id"], "started_at": started}
        save(active_file, active)
    previous = None
    history = folder / "status-history.jsonl"
    while True:
        status = request(base, "/api/v1/status/" + active["job_id"])
        save(folder / "status.json", status)
        with history.open("a") as handle:
            handle.write(json.dumps({"observed_at": time.time(), **status}) + "\n")
        phase = (status["status"], (status.get("phase") or "").split("|", 1)[0].strip())
        if phase != previous:
            print(model, case, phase, flush=True)
            previous = phase
        if status["status"] in ("completed", "failed", "cancelled", "interrupted", "leftover"):
            break
        if time.time() - active["started_at"] > 1800:
            raise RuntimeError(f"Timed out; job {active['job_id']} left visible. Resume this script to reattach.")
        time.sleep(1)
    result = {"model": model, "case": case, "wall_seconds": round(time.time() - active["started_at"], 3), "status": status}
    if status["status"] != "completed":
        save(result_file, result)
        raise RuntimeError(f"{model}/{case}: {status.get('error') or status}")
    for index, filename in enumerate(status.get("output_files") or []):
        url = base.rstrip("/") + "/api/v1/file/" + urllib.parse.quote(filename) + "?workspace=" + workspace
        with urllib.request.urlopen(url, timeout=120) as response:
            (folder / f"output-{index}.png").write_bytes(response.read())
    save(result_file, result)
    print(model, case, status.get("processing_time_sec"), "seconds", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workspace", default="qwen21_turbo_benchmark")
    parser.add_argument("--models", nargs="+", choices=MODELS, default=MODELS)
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=tuple(CASES))
    args = parser.parse_args()
    request(args.base_url, "/api/v1/workspaces", {"name": args.workspace})
    results = []
    def score(model, case, reference=None):
        results.append(run_case(args.base_url, args.output_dir, args.workspace, model, case, reference))
        save(args.output_dir / "results.json", results)
        report(args.output_dir, results)
    for model in args.models:
        run_case(args.base_url, args.output_dir, args.workspace, model, "warmup")
        for case in args.cases:
            if case != "edit":
                score(model, case)
    # Reference encoding can trigger the INT8 engine's session-wide kernel fallback.
    # Complete both models' text-to-image rows before any reference edit.
    if "edit" in args.cases:
        source = args.output_dir / MODELS[0] / "objects" / "result.json"
        if not source.exists():
            raise RuntimeError("Run the base objects case first; both edits must use the same source PNG.")
        filename = json.loads(source.read_text())["status"]["output_files"][0]
        reference = Path(__file__).resolve().parents[1] / "outputs" / args.workspace / filename
        for model in args.models:
            score(model, "edit", reference)


if __name__ == "__main__":
    main()
