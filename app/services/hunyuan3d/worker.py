"""Short-lived Hunyuan3D inference worker used by Maestro.

The worker intentionally exits after one generation.  That makes VRAM release
deterministic and prevents Hunyuan's pinned dependency stack from interacting
with Maestro's main process.
"""

from __future__ import annotations

import argparse
import gc
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V2_ROOT = HERE / "vendor" / "Hunyuan3D-2"
V21_ROOT = HERE / "vendor" / "Hunyuan3D-2.1"
sys.path.insert(0, str(V2_ROOT))
sys.path.insert(0, str(V21_ROOT))
sys.path.insert(0, str(V21_ROOT / "hy3dshape"))
sys.path.insert(0, str(V21_ROOT / "hy3dpaint"))

# Texturing or exporting a multi-million-face mesh can pin CPU/RAM and lock
# the GPU driver long enough that the host looks frozen. Cap before those
# stages so a high octree setting cannot take the machine down.
_MAX_TEXTURE_FACES = 200_000
_MAX_EXPORT_FACES = 400_000


def event(phase: str, progress: float, message: str) -> None:
    print("MAESTRO_EVENT " + json.dumps({"phase": phase, "progress": progress, "message": message}), flush=True)


def release_cuda() -> None:
    """Drop orphaned GPU tensors between Hunyuan stages.

    rembg / text-to-image / shape / paint each load a large network. If the
    previous one is still resident, the next load swaps into system RAM and
    the machine appears hung.
    """
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception:
        pass


class Heartbeat:
    """Emit progress while a CUDA call prints no newlines.

    Hunyuan's tqdm uses ``\\r``, so the parent job watchdog sees silence and
    may kill the worker mid-kernel — that is a common way to wedge the GPU
    driver. A newline heartbeat keeps the job alive and the UI moving.
    """

    def __init__(self, phase: str, progress: float, message: str, interval: float = 20.0):
        self.phase = phase
        self.progress = progress
        self.message = message
        self.interval = interval
        self._stop = threading.Event()
        self._started = 0.0
        self._thread = threading.Thread(target=self._run, name="hy3d-heartbeat", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            elapsed = int(time.time() - self._started)
            event(self.phase, self.progress, f"{self.message} ({elapsed}s elapsed)")

    def __enter__(self) -> Heartbeat:
        self._started = time.time()
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


def mesh_face_count(mesh: Any) -> int:
    faces = getattr(mesh, "faces", None)
    try:
        return int(len(faces))
    except TypeError:
        return 0


def reduce_faces(mesh: Any, max_faces: int) -> Any:
    event("simplify", 0.66, f"Reducing mesh to {max_faces} faces to avoid a GPU/RAM hang")
    try:
        from hy3dgen.shapegen import DegenerateFaceRemover, FaceReducer, FloaterRemover
        mesh = FloaterRemover()(mesh)
        mesh = DegenerateFaceRemover()(mesh)
        return FaceReducer()(mesh, max_facenum=max_faces)
    except Exception as exc:
        print(f"Mesh simplification skipped: {exc}", flush=True)
        return mesh


def guard_mesh_complexity(mesh: Any, settings: dict[str, Any], *, for_texture: bool) -> Any:
    hang_limit = _MAX_TEXTURE_FACES if for_texture else _MAX_EXPORT_FACES
    target = hang_limit
    if settings.get("reduce_face"):
        target = min(hang_limit, int(settings.get("target_face_num") or hang_limit))
    count = mesh_face_count(mesh)
    if count <= target:
        return mesh
    reduced = reduce_faces(mesh, target)
    remaining = mesh_face_count(reduced)
    # reduce_faces is best-effort and returns the original mesh on error.
    # Texturing/exporting a mesh still over the hang cap is how the host
    # freezes; fail the job instead of proceeding with the dense mesh.
    if remaining > hang_limit:
        raise RuntimeError(
            f"Mesh has {remaining} faces after simplification (limit {hang_limit}). "
            "Lower octree resolution and retry to avoid freezing the host."
        )
    return reduced


def supported_call(callable_obj, **kwargs):
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return callable_obj(**kwargs)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return callable_obj(**kwargs)
    accepted = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return callable_obj(**accepted)


def load_pil(path: str):
    from PIL import Image
    return Image.open(path).convert("RGBA")


def make_text_image(prompt: str, output_dir: Path, device: str) -> tuple[Any, str]:
    event("text_to_image", 0.08, "Loading HunyuanDiT text-to-image conditioner")
    from huggingface_hub import hf_hub_download
    from hy3dgen.text2image import HunyuanDiTPipeline

    repo_id = "Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled"
    pipeline = None
    for attempt in range(1, 4):
        try:
            # Resolve the public manifest before Diffusers loads the snapshot.
            # This seeds the revision cache and avoids the misleading generic
            # "model_index.json is missing" wrapper on metadata failures.
            hf_hub_download(repo_id, "model_index.json", token=False)
            pipeline = HunyuanDiTPipeline(
                repo_id,
                device=device,
            )
            break
        except OSError:
            if attempt == 3:
                raise
            delay = attempt * 5
            event("text_to_image", 0.08, f"Hugging Face metadata unavailable; retrying in {delay}s ({attempt}/3)")
            time.sleep(delay)
    assert pipeline is not None
    with Heartbeat("text_to_image", 0.1, "Generating the text-to-image condition"):
        image = pipeline(prompt)
    path = output_dir / "text_condition.png"
    image.save(path)
    del pipeline
    release_cuda()
    return image.convert("RGBA"), str(path)


def prepare_images(request: dict[str, Any], engine: str, temp_dir: Path):
    settings = request["settings"]
    image_paths = request.get("images") or {}
    if image_paths:
        images = {name: load_pil(path) for name, path in image_paths.items()}
        source_path = image_paths.get("front") or next(iter(image_paths.values()))
    else:
        images = {}
        image, source_path = make_text_image(settings["prompt"], temp_dir, "cuda")
        images["front"] = image

    if settings.get("remove_background", True):
        event("preprocess", 0.16, "Removing image backgrounds")
        if engine == "v21":
            from hy3dshape.rembg import BackgroundRemover
        else:
            from hy3dgen.rembg import BackgroundRemover
        remover = BackgroundRemover()
        try:
            images = {name: remover(image) for name, image in images.items()}
        finally:
            del remover
            release_cuda()

    for name, image in images.items():
        normalized_path = temp_dir / f"{name}.png"
        image.save(normalized_path)
        if name == "front":
            source_path = str(normalized_path)
    return images, source_path


def load_v2_pipeline(model: dict[str, Any], settings: dict[str, Any]):
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

    event("loading_model", 0.24, f"Loading {model['label']}")
    with Heartbeat("loading_model", 0.24, f"Loading {model['label']}"):
        try:
            pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                model["repo"],
                subfolder=model["subfolder"],
                use_safetensors=True,
                device="cuda",
            )
        except TypeError:
            pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model["repo"], subfolder=model["subfolder"])
    configure_pipeline(pipeline, settings)
    return pipeline


def load_v21_pipeline(model: dict[str, Any], settings: dict[str, Any]):
    try:
        from torchvision_fix import apply_fix
        apply_fix()
    except Exception:
        pass
    from hy3dshape import Hunyuan3DDiTFlowMatchingPipeline

    event("loading_model", 0.24, f"Loading {model['label']}")
    with Heartbeat("loading_model", 0.24, f"Loading {model['label']}"):
        try:
            pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model["repo"], device="cuda")
        except TypeError:
            pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model["repo"])
    configure_pipeline(pipeline, settings)
    return pipeline


def configure_pipeline(pipeline, settings: dict[str, Any]) -> None:
    if settings.get("flashvdm") and hasattr(pipeline, "enable_flashvdm"):
        try:
            pipeline.enable_flashvdm(mc_algo=settings.get("mc_algo", "dmc"))
        except TypeError:
            pipeline.enable_flashvdm()
    if settings.get("compile"):
        if hasattr(pipeline, "compile"):
            pipeline.compile()
        elif hasattr(pipeline, "model"):
            import torch
            pipeline.model = torch.compile(pipeline.model)
    if settings.get("cpu_offload") and hasattr(pipeline, "enable_model_cpu_offload"):
        # Hunyuan3D 2.0/2.1 copied Diffusers' offload implementation but their
        # standalone pipeline never defines the `components` mapping it reads.
        # Build it after FlashVDM/compile so Accelerate hooks the final modules.
        if not isinstance(getattr(pipeline, "components", None), dict):
            pipeline.components = {
                name: getattr(pipeline, name)
                for name in ("conditioner", "model", "vae", "scheduler", "image_processor")
                if hasattr(pipeline, name)
            }
        pipeline.enable_model_cpu_offload()
        # The standalone Hunyuan pipeline stores `self.device` separately from
        # Accelerate's execution hooks and leaves it as CPU after offloading.
        # Its __call__ then uses self.device for latents, so restore the logical
        # execution device without moving the parked modules back to VRAM.
        import torch
        pipeline.device = torch.device("cuda")


def generate_mesh(request: dict[str, Any], images: dict[str, Any]):
    import torch

    model = request["model"]
    settings = request["settings"]
    pipeline = load_v21_pipeline(model, settings) if model["engine"] == "v21" else load_v2_pipeline(model, settings)
    image_input = images if model.get("multiview") else images.get("front", next(iter(images.values())))
    generator = torch.Generator(device="cuda").manual_seed(settings["seed"])
    call_kwargs = {
        "image": image_input,
        "generator": generator,
        "num_inference_steps": settings["num_inference_steps"],
        "guidance_scale": settings["guidance_scale"],
        "octree_resolution": settings["octree_resolution"],
        "num_chunks": settings["num_chunks"],
        "mc_algo": settings["mc_algo"],
        "output_type": "trimesh",
    }
    event("shape", 0.38, "Generating 3D geometry")
    started = time.time()
    with Heartbeat("shape", 0.38, "Generating 3D geometry"):
        result = supported_call(pipeline, **call_kwargs)
    mesh = result[0] if isinstance(result, (list, tuple)) else result
    print(f"Shape generation completed in {time.time() - started:.2f}s", flush=True)
    del pipeline
    release_cuda()
    return mesh


def simplify_mesh(mesh, settings: dict[str, Any]):
    if not settings.get("reduce_face"):
        return mesh
    return reduce_faces(mesh, settings["target_face_num"])


def load_retexture_mesh(source_path: str):
    """Load a static GLB without mutating the user's original asset."""
    from pygltflib import GLTF2
    import trimesh

    source = Path(source_path)
    gltf = GLTF2().load(str(source))
    if gltf.skins or gltf.animations:
        raise ValueError(
            "Retexturing rigged or animated GLBs is not supported because Hunyuan Paint "
            "rebuilds UVs and would discard the rig. Retexture the static base model, then rig the new copy."
        )
    loaded = trimesh.load(str(source), force="scene", process=False)
    mesh = loaded.dump(concatenate=True) if isinstance(loaded, trimesh.Scene) else loaded
    if not isinstance(mesh, trimesh.Trimesh) or mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ValueError("The source GLB does not contain a usable triangle mesh")
    return mesh


def texture_v2(mesh, image, settings: dict[str, Any]):
    from hy3dgen.texgen import Hunyuan3DPaintPipeline

    subfolder = "hunyuan3d-paint-v2-0-turbo" if settings["texture_mode"] == "v2-turbo" else "hunyuan3d-paint-v2-0"
    event("texture", 0.72, "Loading Hunyuan3D Paint 2.0")
    try:
        paint = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2", subfolder=subfolder)
    except TypeError:
        paint = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
    if settings.get("cpu_offload"):
        # Hunyuan Paint 2.0's custom multiview pipeline leaves its learned
        # prompt tensor on CPU when Diffusers offload hooks are enabled. That
        # produces a deterministic CPU/CUDA mismatch during denoising. Keep
        # Paint resident on CUDA; the short-lived worker still releases all
        # VRAM immediately after export.
        print("Hunyuan Paint 2.0 CPU offload skipped to keep custom tensors on one device", flush=True)
    event("texture", 0.8, "Generating texture maps")
    try:
        with Heartbeat("texture", 0.8, "Generating texture maps"):
            textured = paint(mesh, image=image)
    except TypeError:
        with Heartbeat("texture", 0.8, "Generating texture maps"):
            textured = paint(mesh, image)
    del paint
    release_cuda()
    return textured


def texture_v21(mesh, source_image_path: str, settings: dict[str, Any], temp_dir: Path, output_path: Path) -> Path:
    from textureGenPipeline import Hunyuan3DPaintPipeline, Hunyuan3DPaintConfig
    from hy3dpaint.convert_utils import create_glb_with_pbr_materials

    event("texture", 0.7, "Loading Hunyuan3D Paint 2.1 PBR")
    initial_mesh = temp_dir / "initial.glb"
    mesh.export(initial_mesh)
    resolution = settings["texture_resolution"]
    config = Hunyuan3DPaintConfig(6, resolution)
    config.realesrgan_ckpt_path = str(V21_ROOT / "hy3dpaint" / "ckpt" / "RealESRGAN_x4plus.pth")
    config.multiview_cfg_path = str(V21_ROOT / "hy3dpaint" / "cfgs" / "hunyuan-paint-pbr.yaml")
    config.custom_pipeline = str(V21_ROOT / "hy3dpaint" / "hunyuanpaintpbr")
    paint = Hunyuan3DPaintPipeline(config)
    obj_path = temp_dir / "pbr_textured.obj"
    event("texture", 0.8, "Generating PBR material maps")
    with Heartbeat("texture", 0.8, "Generating PBR material maps"):
        textured_obj = paint(
            mesh_path=str(initial_mesh),
            image_path=source_image_path,
            output_mesh_path=str(obj_path),
            save_glb=False,
        )
    textured_obj = Path(textured_obj or obj_path)
    glb_path = output_path if output_path.suffix.lower() == ".glb" else temp_dir / "pbr_textured.glb"
    textures = {
        "albedo": str(textured_obj.with_suffix(".jpg")),
        "metallic": str(textured_obj.with_name(textured_obj.stem + "_metallic.jpg")),
        "roughness": str(textured_obj.with_name(textured_obj.stem + "_roughness.jpg")),
    }
    create_glb_with_pbr_materials(str(textured_obj), textures, str(glb_path))
    del paint
    release_cuda()
    if output_path.suffix.lower() != ".glb":
        import trimesh
        converted = trimesh.load(glb_path, force="scene")
        converted.export(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    try:
        import torch
        torch.set_grad_enabled(False)
    except Exception:
        pass

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model = request["model"]
    settings = request["settings"]
    operation = request.get("operation") or "generate"

    with tempfile.TemporaryDirectory(prefix="maestro_hy3d_") as temp_name:
        temp_dir = Path(temp_name)
        event("preparing", 0.04, "Preparing Hunyuan3D inputs")
        images, source_image_path = prepare_images(request, model["engine"], temp_dir)
        if operation == "retexture":
            event("source_mesh", 0.26, "Loading the source GLB as a clean static mesh")
            mesh = load_retexture_mesh(request["source_mesh"])
        else:
            mesh = generate_mesh(request, images)
            mesh = simplify_mesh(mesh, settings)

        texture_mode = settings["texture_mode"]
        mesh = guard_mesh_complexity(mesh, settings, for_texture=texture_mode != "none")
        if texture_mode == "pbr":
            texture_v21(mesh, source_image_path, settings, temp_dir, output_path)
        else:
            if texture_mode in {"v2", "v2-turbo"}:
                front = images.get("front", next(iter(images.values())))
                mesh = texture_v2(mesh, front, settings)
            event("export", 0.94, f"Exporting {output_path.suffix.upper().lstrip('.')}")
            mesh.export(output_path)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("Hunyuan3D did not produce an output file")

        # Persist the normalized front view as a static gallery preview, only
        # once the export has been validated so failed runs leave no orphan
        # preview behind. For text-only jobs this is the HunyuanDiT
        # conditioning image — without it the gallery has no visual to show.
        try:
            shutil.copyfile(source_image_path, output_path.with_suffix(".preview.png"))
        except OSError as exc:
            print(f"Preview image not saved: {exc}", flush=True)

    event("completed", 1.0, "3D asset saved; releasing VRAM")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        event("failed", 0.0, str(exc))
        raise
