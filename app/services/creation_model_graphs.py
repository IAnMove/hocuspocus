"""Small Comfy API graphs matching the pinned upstream node contracts."""
import math
import shutil
from pathlib import Path

from services.creation_model_catalog import FLUX_FILES, DRAMA_FILES, validate


def node(kind, **inputs):
    return {"class_type": kind, "inputs": inputs}


def copy_input(source, folder, prefix, index):
    source = Path(source)
    if not source.is_file():
        raise ValueError("A selected input file is missing")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{prefix}_{index}{source.suffix.lower()}"
    shutil.copyfile(source, destination)
    return destination.name


def build_workflow(params, prefix, input_dir):
    validate(params)
    return flux_graph(params, prefix, input_dir) if params["model_type"].startswith("flux3_") else drama_graph(params, prefix, input_dir)


def flux_graph(params, prefix, input_dir):
    width, height = (int(part) for part in params.get("resolution", "1024x1024").split("x"))
    if min(width, height) < 64 or max(width, height) > 4096 or width % 16 or height % 16:
        raise ValueError("FLUX 3 dimensions must be multiples of 16 between 64 and 4096")
    steps = int(params.get("num_inference_steps", 16))
    if not 4 <= steps <= 50:
        raise ValueError("FLUX 3 uses 4–50 sampling steps")
    solver = params.get("sample_solver") or "euler"
    if solver not in ("euler", "er_sde"):
        raise ValueError("Choose Euler or ER-SDE for FLUX 3")
    batch = int(params.get("batch_size", 1))
    if not 1 <= batch <= 4:
        raise ValueError("FLUX 3 batch size must be between one and four")
    graph = {
        "1": node("UNETLoader", unet_name=Path(FLUX_FILES[0]).name, weight_dtype="default"),
        "2": node("CLIPLoader", clip_name=Path(FLUX_FILES[1]).name, type="flux3", device="default"),
        "3": node("VAELoader", vae_name=Path(FLUX_FILES[2]).name),
        "4": node("CLIPTextEncode", clip=["2", 0], text=params["prompt"]),
        "5": node("CLIPTextEncode", clip=["2", 0], text=""),
        "6": node("EmptyFlux2LatentImage", width=width, height=height, batch_size=batch),
    }
    positive, negative = ["4", 0], ["5", 0]
    refs = list(params.get("image_refs") or [])
    if params.get("image_guide"):
        refs.insert(0, params["image_guide"])
    for i, source in enumerate(refs):
        load, scale, encode, pos, neg = (str(20 + 5 * i + j) for j in range(5))
        graph[load] = node("LoadImage", image=copy_input(source, input_dir, prefix, i))
        graph[scale] = node("ImageScaleToTotalPixels", image=[load, 0], upscale_method="lanczos",
                            megapixels=1.0, resolution_steps=16)
        graph[encode] = node("VAEEncode", pixels=[scale, 0], vae=["3", 0])
        graph[pos] = node("ReferenceLatent", conditioning=positive, latent=[encode, 0])
        graph[neg] = node("ReferenceLatent", conditioning=negative, latent=[encode, 0])
        positive, negative = [pos, 0], [neg, 0]
    graph["7"] = node("KSampler", model=["1", 0], positive=positive, negative=negative,
                      latent_image=["6", 0], seed=int(params["seed"]), steps=steps, cfg=1.0,
                      sampler_name=solver, scheduler="simple", denoise=1.0)
    graph["8"] = node("VAEDecode", samples=["7", 0], vae=["3", 0])
    graph["9"] = node("SaveImage", images=["8", 0], filename_prefix=prefix)
    return graph, "9"


def drama_graph(params, prefix, input_dir):
    duration = float(params.get("duration_seconds", 60))
    if not math.isfinite(duration) or not 1 <= duration <= 180:
        raise ValueError("Drama 3 duration must be between one and 180 seconds per chunk")
    text = params["prompt"]
    clone = params["model_type"] == "drama3_base"
    if not clone and params.get("alt_prompt", "").strip():
        text = "Direction: " + params["alt_prompt"].strip() + "\nLine: " + text
    graph = {
        "1": node("Drama3Loader", model_name=Path(DRAMA_FILES[0]).name, experts="in RAM",
                  expert_cache_gb=float((params.get("custom_settings") or {}).get("expert_cache_gb", 0)),
                  second_gpu="none", split_layer=0),
        "2": node("Drama3CodecLoader", codec_name=Path(DRAMA_FILES[1]).name),
        "3": node("Drama3Generate", model=["1", 0], text=text, seed=int(params["seed"]),
                  temperature=float(params.get("temperature", 1)), top_p=float(params.get("top_p", .9)),
                  top_k=int(params.get("top_k", 30)), max_frames=min(8192, math.ceil(duration * 21.5)),
                  split_long_text=True),
        "4": node("Drama3Decode", codec=["2", 0], codes=["3", 0]),
        "5": node("SaveAudio", audio=["4", 0], filename_prefix=prefix),
    }
    if clone:
        graph["6"] = node("LoadAudio", audio=copy_input(params["audio_guide"], input_dir, prefix, 0))
        graph["7"] = node("Drama3EncodeVoice", codec=["2", 0], audio=["6", 0], transcript=params["alt_prompt"])
        graph["3"]["inputs"]["voices.voice0"] = ["7", 0]
    return graph, "5"
