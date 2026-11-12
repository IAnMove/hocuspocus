"""MiniMax H3-Image over the public API. HTTP is faked. No test reaches the network."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from PIL import Image

from services import remote_image_generation as remote
from services import remote_image_worker
from services.director.image_prompt_rules import get_image_prompt_rules
from services.director.prompt_polish import get_image_guide
from services.enhance_guides import get_enhance_guide
from services.guide_resolution import match_guide_stem
from services.minimax_h3_image_service import (
    MODEL_FAST,
    MODEL_STANDARD,
    MiniMaxImageError,
    generate_image,
    output_size,
    prepare_prompt,
)
from services.remote_h3_image import prepare_h3_image

KEY = "test-key-not-real-0123456789"
SERVICES = {"minimax_image_api_key": KEY}


def _png(path: Path, size: tuple[int, int] = (128, 128)) -> Path:
    Image.new("RGB", size, (20, 80, 140)).save(path)
    return path


def _resolve(root: Path):
    def resolve(value: str):
        path = root / Path(value).name
        if not path.is_file():
            raise ValueError("the picture is not available")
        return str(path), {"sha256": "ab" * 32, "size_bytes": path.stat().st_size}
    return resolve


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.content = b"jpeg-bytes"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _payload(size="1024x1024"):
    return {
        "request_id": "req-h3",
        "data": [{
            "url": "https://files.example.invalid/out.jpg",
            "revised_prompt": "A red lantern in the rain, no text",
            "size": size,
        }],
    }


def test_named_ratios_and_small_canvases_become_legal_sizes():
    assert output_size("16:9") == "2720x1536"
    assert output_size("9:16") == "1536x2720"
    assert output_size("1:1") == "2048x2048"
    assert output_size("1024x1024") == "1024x1024"
    assert output_size("2048x2048") == "2048x2048"
    assert output_size("") == "2048x2048"
    grown = output_size("832x480")
    width, height = (int(part) for part in grown.split("x"))
    assert width * height >= 655_360
    assert 1 / 3 <= width / height <= 3


def test_a_prompt_is_kept_whole_up_to_32000_characters():
    assert prepare_prompt("  un farol  en la lluvia ") == "un farol en la lluvia"
    with pytest.raises(MiniMaxImageError):
        prepare_prompt(" ")
    with pytest.raises(MiniMaxImageError):
        prepare_prompt("a" * 32001)


def test_text_to_image_posts_size_and_leaves_expansion_on(tmp_path):
    post = Mock(return_value=_Response(_payload()))
    downloaded = Mock(return_value=_Response(_payload()))
    with patch("services.minimax_h3_image_service.requests.post", post), patch(
        "services.minimax_h3_image_service.requests.get", downloaded,
    ):
        result = generate_image(
            api_key=KEY, model_type=MODEL_STANDARD, prompt="un farol en la lluvia",
            resolution="1024x1024", output_dir=str(tmp_path),
        )
    body = post.call_args.kwargs["json"]
    assert post.call_args.args[0].endswith("/v1/images/generations")
    assert body["model"] == "MiniMax-H3-Image"
    assert body["size"] == "1024x1024"
    assert "aspect_ratio" not in body
    assert "disable_prompt_enhanced" not in body
    assert body["response_format"] == "url"
    assert result["revised_prompt"].startswith("A red lantern")
    assert KEY not in Path(result["path"]).with_suffix(".meta.json").read_text(encoding="utf-8")


def test_highspeed_edit_sends_references_and_no_expansion_flag(tmp_path):
    picture = _png(tmp_path / "hero.png")
    post = Mock(return_value=_Response(_payload("2048x2048")))
    with patch("services.minimax_h3_image_service.requests.post", post), patch(
        "services.minimax_h3_image_service.requests.get", return_value=_Response(_payload()),
    ):
        generate_image(
            api_key=KEY, model_type=MODEL_FAST, prompt="the same person, blue coat",
            resolution="2048x2048", output_dir=str(tmp_path), reference_paths=[str(picture)],
            disable_prompt_enhanced=True,
        )
    body = post.call_args.kwargs["json"]
    assert post.call_args.args[0].endswith("/v1/images/edits")
    assert body["model"] == "MiniMax-H3-Image-Highspeed"
    assert body["images"][0]["image_url"].startswith("data:image/")
    assert "disable_prompt_enhanced" not in body


def test_a_tiny_reference_is_refused_before_the_request(tmp_path):
    picture = _png(tmp_path / "tiny.png", (32, 32))
    post = Mock()
    with patch("services.minimax_h3_image_service.requests.post", post):
        with pytest.raises(MiniMaxImageError) as caught:
            generate_image(
                api_key=KEY, model_type=MODEL_STANDARD, prompt="a face",
                resolution="1024x1024", output_dir=str(tmp_path), reference_paths=[str(picture)],
            )
    assert caught.value.status_code == 422
    post.assert_not_called()


def test_prepare_keeps_sixteen_pictures_and_notes_the_rest(tmp_path):
    paths = [_png(tmp_path / f"ref-{index}.png") for index in range(18)]
    params = {
        "workspace": "default",
        "model_type": MODEL_STANDARD,
        "prompt": "the same coat",
        "resolution": "832x480",
        "image_guide": [paths[0].name],
        "image_refs": [path.name for path in paths[1:]],
        "image_mask": ["mask.png"],
        "negative_prompt": "blur",
        "activated_loras": ["nope.safetensors"],
    }
    # The mask is named but not a file the resolver must open: it is ignored before resolve.
    working, resources = prepare_h3_image(params, services=SERVICES, resolve=_resolve(tmp_path))
    assert working["resolution"] != "832x480"
    assert len(working["image_refs"]) == 16
    assert working["image_refs"][0].endswith("ref-0.png")
    reasons = " ".join(item.get("reason", "") for item in resources)
    assert "655360" in reasons
    assert "at most 16" in reasons
    assert "no mask" in reasons
    assert "no negative prompt" in reasons
    assert "no LoRA" in reasons
    assert "aspect_ratio" not in working


def test_prepare_refuses_an_unknown_door_for_image_01_limits():
    """Image-01 still shortens a long prompt. H3-Image does not, until 32000."""
    long_prompt = "palabra " * 400
    prepared, _resources = remote.prepare_remote_image(
        {"workspace": "default", "model_type": MODEL_STANDARD, "prompt": long_prompt, "resolution": "1024x1024"},
        services=SERVICES,
    )
    assert prepared["prompt"].startswith("palabra")
    assert len(prepared["prompt"]) > 1500
    with pytest.raises(HTTPException):
        remote.prepare_remote_image(
            {"workspace": "default", "model_type": "minimax:image-01", "prompt": "", "resolution": "1024x1024"},
            services=SERVICES,
        )


def test_catalog_options_and_defaults_keep_image_01_first():
    entries = remote.catalog_entries(False)
    assert [item["model_type"] for item in entries] == [
        "minimax:image-01", MODEL_STANDARD, MODEL_FAST,
    ]
    assert entries[1]["director"]["max_image_refs"] == 16
    assert entries[1]["resource_requirements"]["tier"] == "remote"
    assert remote.model_options()["max_image_refs"] == 1
    assert remote.model_options(MODEL_FAST)["max_image_refs"] == 16
    assert remote.defaults()["resolution"] == "1024x1024"
    assert remote.defaults(MODEL_STANDARD)["resolution"] == "2048x2048"
    assert remote.uses_minimax_image_api(MODEL_STANDARD)
    assert remote.uses_minimax_image_api("minimax:image-01")
    assert not remote.uses_minimax_image_api("minimax:no-such-model")
    assert not remote.uses_minimax_image_api("minimax_h3")


def test_the_worker_calls_h3_and_refuses_an_unknown_minimax_image_id(tmp_path):
    job = {
        "id": "job-h3", "task_id": "task-h3", "root_task_id": "task-h3",
        "status": "queued", "progress": 0, "message": "Queued", "workspace": "default",
        "output_files": [], "out_dir": str(tmp_path),
        "params": {
            "model_type": MODEL_FAST,
            "prompt": "un farol",
            "resolution": "1024x1024",
            "generation_mode": "image",
        },
    }
    post = Mock(return_value=_Response(_payload()))
    with patch("services.minimax_h3_image_service.requests.post", post), patch(
        "services.minimax_h3_image_service.requests.get", return_value=_Response(_payload()),
    ):
        done = remote_image_worker.run_remote_image_job(
            job, services=lambda: SERVICES, publish_sidecar=lambda *args, **kwargs: None,
            remove_persisted=lambda _job: None,
        )
    assert done is True
    assert post.call_args.kwargs["json"]["model"] == "MiniMax-H3-Image-Highspeed"
    assert job["status"] == "completed"
    unknown = {
        "id": "job-unknown", "status": "queued", "progress": 0, "message": "Queued",
        "workspace": "default", "output_files": [], "out_dir": str(tmp_path),
        "params": {"model_type": "minimax:no-such-model", "prompt": "x", "resolution": "1024x1024"},
    }
    with patch("services.minimax_image_service.requests.post") as image_01:
        failed = remote_image_worker.run_remote_image_job(
            unknown, services=lambda: SERVICES, publish_sidecar=lambda *a, **k: None,
            remove_persisted=lambda _job: None,
        )
    assert failed is False and unknown["status"] == "failed"
    image_01.assert_not_called()


def test_prompt_guides_follow_h3_image_and_not_the_video_stem():
    assert match_guide_stem("minimax:h3-image") == ""
    assert match_guide_stem("minimax_h3") == "minimax_h3_video"
    plain = get_enhance_guide(MODEL_FAST, "image", False)
    edited = get_enhance_guide(MODEL_STANDARD, "image", True)
    assert "2048x2048" in plain
    assert "Picture 1" in edited
    assert "Picture 1" not in plain
    assert "the image contains no text" in get_image_prompt_rules(False, image_model=MODEL_STANDARD).lower()
    assert "Picture 1" in get_image_prompt_rules(True, image_model=MODEL_FAST)
    assert "2048x2048" in get_image_guide(MODEL_STANDARD, "light")
