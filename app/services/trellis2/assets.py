"""Pinned official weights and a complete, locally verifiable offline bundle."""
from __future__ import annotations

import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]
CACHE = APP_DIR / "ckpts/model3d/trellis2"
BUNDLE = CACHE / "bundle"
REPOSITORIES = {
    "microsoft/TRELLIS.2-4B": ("af44b45f2e35a493886929c6d786e563ec68364d", ["pipeline.json", "ckpts/*.json", "ckpts/*.safetensors"]),
    "microsoft/TRELLIS-image-large": ("25e0d31ffbebe4b5a97464dd851910efc3002d96", ["ckpts/ss_dec_conv3d_16l8_fp16.*"]),
    "facebook/dinov3-vitl16-pretrain-lvd1689m": ("ea8dc2863c51be0a264bab82070e3e8836b02d51", ["*.json", "*.safetensors"]),
    "briaai/RMBG-2.0": ("5df4c9c76d8170882c34f6986e848ee07fd0ba43", ["*.json", "*.safetensors", "*.py"]),
}


def downloaded(cache: Path = CACHE) -> bool:
    try:
        receipt = json.loads((cache / "complete.json").read_text())
        if receipt["revisions"] != {repo: value[0] for repo, value in REPOSITORIES.items()}:
            return False
        files = receipt["files"]
        if not files or "bundle/pipeline.json" not in files:
            return False
        for relative, size in files.items():
            path = (cache / relative).resolve()
            if not path.is_relative_to(cache.resolve()) or not path.is_file() or size <= 0 or path.stat().st_size != size:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def download(cache: Path = CACHE) -> None:
    from fnmatch import fnmatch
    from huggingface_hub import HfApi, snapshot_download, get_hf_file_metadata, hf_hub_url
    from huggingface_hub.errors import GatedRepoError

    if downloaded(cache):
        return
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "complete.json").unlink(missing_ok=True)
    snapshots, files, inventory = {}, {}, {}
    try:
        # Check gated weight access before downloading the large 4B transformer.
        for repo, (revision, patterns) in REPOSITORIES.items():
            info = HfApi().model_info(repo, revision=revision, files_metadata=True)
            expected = [file for file in info.siblings if any(fnmatch(file.rfilename, p) for p in patterns)]
            if not expected:
                raise RuntimeError(f"No weights found for {repo}")
            weight = next(file for file in expected if file.rfilename.endswith('.safetensors'))
            get_hf_file_metadata(hf_hub_url(repo, weight.rfilename, revision=revision))
            inventory[repo] = expected
        import shutil
        missing_size = 0
        for repo, expected in inventory.items():
            revision = REPOSITORIES[repo][0]
            snapshot = cache / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots" / revision
            for file in expected:
                path = snapshot / file.rfilename
                if not path.is_file() or path.stat().st_size != file.size:
                    missing_size += file.size or 0
        if shutil.disk_usage(cache).free < missing_size + 2 * 1024**3:
            raise RuntimeError("Insufficient free disk space for the complete TRELLIS.2 weights bundle")
        for repo, (revision, patterns) in REPOSITORIES.items():
            print(f"[TRELLIS.2] Downloading {repo} at {revision}", flush=True)
            expected = inventory[repo]
            snapshot = Path(snapshot_download(repo, revision=revision, cache_dir=cache / "hub",
                                              allow_patterns=patterns, max_workers=2))
            snapshots[repo] = snapshot
            for file in expected:
                path = snapshot / file.rfilename
                if not file.size or not path.is_file() or path.stat().st_size != file.size:
                    raise RuntimeError(f"Incomplete download: {repo}/{file.rfilename}")
                files[str(path.relative_to(cache))] = file.size
    except GatedRepoError as error:
        raise RuntimeError("TRELLIS.2 also requires DINOv3 and RMBG-2.0. Accept their Hugging Face access terms, "
                           "then use Advanced > Log in to Hugging Face and retry. "
                           "https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m "
                           "https://huggingface.co/briaai/RMBG-2.0") from error
    config = json.loads((snapshots["microsoft/TRELLIS.2-4B"] / "pipeline.json").read_text())
    args = config["args"]
    for key, value in args["models"].items():
        if value.startswith("microsoft/TRELLIS-image-large/"):
            args["models"][key] = str(snapshots["microsoft/TRELLIS-image-large"] / value.split("/", 2)[2])
        else:
            args["models"][key] = str(snapshots["microsoft/TRELLIS.2-4B"] / value)
    args["image_cond_model"]["args"]["model_name"] = str(snapshots["facebook/dinov3-vitl16-pretrain-lvd1689m"])
    args["rembg_model"]["args"]["model_name"] = str(snapshots["briaai/RMBG-2.0"])
    bundle = cache / "bundle"
    bundle.mkdir(exist_ok=True)
    pipeline = bundle / "pipeline.json"
    pipeline.write_text(json.dumps(config, indent=2))
    files["bundle/pipeline.json"] = pipeline.stat().st_size
    temporary = cache / "complete.tmp"
    temporary.write_text(json.dumps({"revisions": {repo: value[0] for repo, value in REPOSITORIES.items()}, "files": files}, indent=2))
    temporary.replace(cache / "complete.json")
    if not downloaded(cache):
        raise RuntimeError("TRELLIS.2 download verification failed")


if __name__ == "__main__":
    download()
