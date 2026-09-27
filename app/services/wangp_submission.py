"""Translate Hocuspocus editing requests into the internal WanGP queue contract."""

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import uuid


class JsonRequest:
    """The generation facade consumes JSON only; keep one submission lifecycle."""

    def __init__(self, payload, *, trusted_tool=None):
        self.payload = payload
        self.trusted_tool = trusted_tool

    async def json(self):
        return deepcopy(self.payload)


def _prepare_canonical_image_references(body, model_def, workspace, *, uploads_dir, workspace_dir):
    canonical_refs = body.pop('canonical_image_refs', False)
    if canonical_refs:
        if canonical_refs is not True or not model_def.get('image_outputs') or body.get('image_mode') not in (1, 2):
            raise ValueError('Canonical image references require an image generation request')
        references = body.get('image_refs')
        if not isinstance(references, list) or not references or any(not isinstance(value, str) for value in references):
            raise ValueError('Canonical image references must be a non-empty ordered list')
        body['image_refs'] = [resolve_wangp_media(value, workspace, uploads_dir=uploads_dir,
                                                workspace_dir=workspace_dir) for value in references]


def _prepare_native_processors(body):
    if body.get('spatial_upsampling') or body.get('temporal_upsampling') or body.get('wangp_processor_settings'):
        from shared.wangp1272.processors import validate_selection, validated_settings
        error = validate_selection(body.get('spatial_upsampling', ''), body.get('temporal_upsampling', ''), body.get('image_mode') in (1, 2))
        if error:
            raise ValueError(error)
        body['wangp_processor_settings'] = validated_settings(body.get('spatial_upsampling', ''), body.get('wangp_processor_settings'))


def prepare_generation_inputs(body, model_def, workspace, *, uploads_dir, workspace_dir,
                              prepared_images=False, prepared_speech=False):
    """Validate processor options and resolve new-family media before admission."""
    _prepare_canonical_image_references(body, model_def, workspace,
                                        uploads_dir=uploads_dir, workspace_dir=workspace_dir)
    _prepare_native_processors(body)
    if not model_def.get('wangp_1272'):
        return
    if prepared_images and (not model_def.get('image_outputs') or body.get('image_mode') not in (1, 2)):
        raise ValueError('Prepared image inputs require an image generation request')
    if prepared_speech and (not model_def.get('audio_only') or body.get('generation_mode') != 'audio'):
        raise ValueError('Prepared speech inputs require an audio generation request')
    def resolve(value):
        return resolve_wangp_media(value, workspace, uploads_dir=uploads_dir, workspace_dir=workspace_dir)
    audio_fields = ('audio_guide', 'audio_guide2', 'audio_guide3', 'audio_guide4', 'audio_guide5', 'audio_guide6')
    for field in ('video_guide', 'video_guide2', 'video_mask', *audio_fields, 'image_start', 'image_end', 'image_refs'):
        if prepared_images and field in ('image_start', 'image_end', 'image_refs'):
            # Only the in-process Studio command adapter supplies this flag.
            # Those exact paths were resolved against each source workspace.
            continue
        if prepared_speech and field in audio_fields:
            continue
        values = body.get(field)
        if values:
            body[field] = [resolve(value) for value in values] if isinstance(values, list) else resolve(values)


def probe_video(path):
    """Read the display dimensions used by FFmpeg's autorotated frame extraction."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:stream_side_data=rotation:stream_tags=rotate:format=duration",
         "-of", "json", os.fspath(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    rotation = next((item["rotation"] for item in stream.get("side_data_list", [])
                     if item.get("rotation") is not None), stream.get("tags", {}).get("rotate", 0))
    try:
        if math.isclose(float(rotation) % 180, 90, abs_tol=0.01):
            width, height = height, width
    except (TypeError, ValueError):
        pass
    return width, height, float(info["format"]["duration"])


def viggle_parameters(body, *, video, reference, width, height, duration):
    """Pure adapter: fixed sampling and one reference, separate from SCAIL masks."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The control video must have a finite positive duration")
    if width <= 0 or height <= 0:
        raise ValueError("The control video has invalid dimensions")
    audio_mode = str(body.get("viggle_audio_mode") or "source")
    if audio_mode not in {"source", "generated"}:
        raise ValueError("Viggle audio mode must be source or generated")
    short_edge = {"480p": 480, "512p": 512, "704p": 704}.get(body.get("resolution_profile"), 480)
    scale = min(1.0, short_edge / min(width, height))
    target_w, target_h = [max(32, round(value * scale / 32) * 32) for value in (width, height)]
    return {
        "model_type": "viggle_animate", "prompt": "Viggle character replacement",
        "image_refs": [reference], "video_guide": video, "video_prompt_type": "IVU",
        "image_prompt_type": "T", "image_mode": 0, "resolution": f"{target_w}x{target_h}",
        "video_length": max(1, round(duration * 24)), "force_fps": "24",
        "num_inference_steps": 3, "sample_solver": "euler", "flow_shift": 3.0,
        "guidance_scale": 1.0, "guidance_phases": 1,
        "sliding_window_size": 124, "sliding_window_overlap": 18,
        "sliding_window_discard_last_frames": 0,
        "image_refs_relative_size": 100, "remove_background_images_ref": 0,
        "audio_prompt_type": "", "prompt_enhancer": "", "multi_prompts_gen_type": 0,
        "spatial_upsampling": body.get("spatial_upsampling") or "",
        "temporal_upsampling": body.get("temporal_upsampling") or "",
        "wangp_processor_settings": deepcopy(body.get("wangp_processor_settings") or {}),
        "seed": body.get("seed", -1), "workspace": body.get("workspace"),
        "provenance": deepcopy(body.get("provenance")),
        "generation_mode": "avatar", "edit_sub_mode": "recast", "viggle_audio_mode": audio_mode,
        "edit_recast_ref_path": reference, "edit_recast_ref_aligned": True,
        "edit_recast_resolution_profile": body.get("resolution_profile") or "480p",
        "viggle_source_video": video, "viggle_edited_frame": reference,
        "wangp_1272_revision": "362c3467a70e1136ceb52eec95907205a8f88543",
    }


def prepare_viggle_recast(body, resolve_media, uploads_dir, canonical_url=None):
    video = resolve_media(body.get("video_path"), body.get("workspace"))
    mappings = body.get("character_mappings") or []
    if not isinstance(mappings, list) or any(not isinstance(item, dict) for item in mappings):
        raise ValueError('Invalid Viggle reference mapping')
    if len(mappings) > 1:
        raise ValueError("Viggle uses one edited frame, not separate character mappings")
    raw_reference = body.get("ref_image_path") or (mappings[0].get("ref_image_path") if mappings else None)
    reference = resolve_media(raw_reference, body.get("workspace"))
    if not video or not reference:
        raise ValueError("Viggle requires a control video and an edited frame")
    from PIL import Image

    width, height, duration = probe_video(video)
    with Image.open(reference) as image:
        if abs(image.width / image.height - width / height) > 0.02:
            raise ValueError("Keep the control video's aspect ratio in the edited frame")
    original_video = video
    video, start, end = _trim_control_video(video, body, uploads_dir, duration)
    params = viggle_parameters(body, video=video, reference=reference,
                               width=width, height=height, duration=end - start)
    params["viggle_original_video"] = original_video
    params["viggle_source_range"] = {"start": start, "end": end}
    params.update(edit_video_path=original_video, edit_start_time=start, edit_end_time=end)
    if canonical_url is not None:
        params.update(edit_video_url=canonical_url(original_video), edit_recast_ref_url=canonical_url(reference))
    return params


def _trim_control_video(video, body, uploads_dir, duration):
    start = float(body.get("start_time") or 0)
    end = float(body.get("end_time") or duration)
    if not all(math.isfinite(value) for value in (start, end)) or not 0 <= start < end <= duration + 0.05:
        raise ValueError("Invalid Viggle source trim range")
    if start > 0 or end < duration - 0.05:
        folder = Path(uploads_dir)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"viggle_trim_{uuid.uuid4().hex}.mp4"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-ss", str(start),
                            "-t", str(end - start), "-c:v", "libx264", "-crf", "18",
                            "-c:a", "aac", os.fspath(target)],
                           check=True, capture_output=True, timeout=180)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        video = os.fspath(target)
    return video, start, end


def resolve_wangp_media(value, workspace, *, uploads_dir, workspace_dir):
    """Resolve explicit API roots without falling back to a same-name asset."""
    from urllib.parse import unquote, urlsplit, parse_qs
    raw = str(value or "")
    if not raw:
        raise ValueError("A media reference is required")
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raise ValueError("Choose a local media asset")
    if parsed.path.startswith('/api/v1/uploads/'):
        root = Path(uploads_dir).resolve()
        relative = unquote(parsed.path[len('/api/v1/uploads/'):])
        path = (root / relative).resolve()
    elif parsed.path.startswith('/api/v1/file/'):
        named = parse_qs(parsed.query).get('workspace', [workspace])[0]
        if named != workspace:
            raise ValueError("The selected media belongs to another workspace")
        root = Path(workspace_dir).resolve()
        path = (root / unquote(parsed.path[len('/api/v1/file/'):])).resolve()
    else:
        return _resolve_legacy_media(raw, uploads_dir, workspace_dir)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("The selected media is not available in its declared location")
    return os.fspath(path)


def wangp_media_url(path, workspace, *, uploads_dir, workspace_dir):
    """Persist the declared root, subpath and workspace, never only a basename."""
    from urllib.parse import quote, urlencode
    resolved = Path(path).resolve()
    for folder, prefix in ((uploads_dir, '/api/v1/uploads/'), (workspace_dir, '/api/v1/file/')):
        root = Path(folder).resolve()
        if resolved.is_relative_to(root):
            url = prefix + quote(resolved.relative_to(root).as_posix())
            return url + ('?' + urlencode({'workspace': workspace}) if prefix.endswith('file/') and workspace else '')
    raise ValueError('Media is outside the selected workspace and uploads')


def _resolve_legacy_media(raw, uploads_dir, workspace_dir):
    # Legacy round-trip extraction returns an absolute uploads path.
    roots = [Path(uploads_dir).resolve(), Path(workspace_dir).resolve()]
    candidates = [Path(raw).resolve()] if Path(raw).is_absolute() else [(root / raw).resolve() for root in roots]
    matches = [path for path in candidates if path.is_file() and any(path.is_relative_to(root) for root in roots)]
    if len(matches) != 1:
        raise ValueError("Media reference is missing or ambiguous; select it again")
    return os.fspath(matches[0])


def finalize_viggle_audio(output, model_type, mode, source, guide):
    if model_type == 'viggle_animate' and mode == 'source':
        preserve_source_audio(output, source or guide)


def preserve_source_audio(output, source):
    """Replace audio before publication. An audio-less source produces silence."""
    target = Path(output)
    temporary = target.with_name(f'.{target.stem}.{uuid.uuid4().hex}.mux{target.suffix}')
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-i', os.fspath(target), '-i', os.fspath(source),
                        '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'copy', '-c:a', 'aac',
                        '-af', 'apad', '-shortest', os.fspath(temporary)],
                       check=True, capture_output=True, timeout=180)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
