from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import director_pipeline
from app.services.director.renderers.ltx_i2v import LtxI2VRenderer
from app.services.director.policies import (
    apply_visual_style_lock,
    enforce_visual_style_on_clip_plans,
    strip_visible_text_directions,
)
from app.services.hardware_detect import _classify_vram_tier


def test_ltx_resolution_is_aligned_before_image_preparation():
    assert (
        director_pipeline._normalize_video_resolution(
            "ltx2_22B_distilled_gguf_q6_k",
            "1280x720",
        )
        == "1280x704"
    )
    assert (
        director_pipeline._normalize_video_resolution(
            "ltx2_22B_distilled_fp8",
            "848x480",
        )
        == "832x448"
    )


def test_non_ltx_resolution_is_not_changed():
    assert (
        director_pipeline._normalize_video_resolution(
            "wan2_1_14B",
            "1280x720",
        )
        == "1280x720"
    )


def test_smart_fit_preserves_full_source_inside_fixed_canvas(tmp_path):
    source = tmp_path / "portrait.png"
    destination = tmp_path / "smart.png"
    image = Image.new("RGB", (100, 200), (220, 30, 20))
    # Distinct top and bottom bands make it possible to prove that contain
    # fitting did not crop either edge of the portrait.
    for y in range(10):
        for x in range(100):
            image.putpixel((x, y), (0, 255, 0))
            image.putpixel((x, 199 - y), (0, 0, 255))
    image.save(source)

    director_pipeline._fit_i2v_image(
        str(source),
        str(destination),
        "320x192",
        "smart",
    )

    with Image.open(destination) as fitted:
        assert fitted.size == (320, 192)
        # The contained portrait is 96 px wide and 192 px tall, centered.
        assert fitted.getpixel((160, 0)) == (0, 255, 0)
        assert fitted.getpixel((160, 191)) == (0, 0, 255)


def test_crop_fit_fills_requested_canvas(tmp_path):
    source = tmp_path / "portrait.png"
    destination = tmp_path / "crop.png"
    Image.new("RGB", (100, 200), (20, 30, 220)).save(source)

    director_pipeline._fit_i2v_image(
        str(source),
        str(destination),
        "320x192",
        "crop",
    )

    with Image.open(destination) as fitted:
        assert fitted.size == (320, 192)


def test_explicit_comic_cover_crop_is_not_silently_changed_to_padding(tmp_path):
    source = tmp_path / "portrait.png"
    image = Image.new("RGB", (100, 200), (220, 30, 20))
    for y in range(10):
        for x in range(100):
            image.putpixel((x, y), (0, 255, 0))
            image.putpixel((x, 199 - y), (0, 0, 255))
    image.save(source)

    staged = director_pipeline._prepare_provided_clip_images(
        "test-pipeline",
        [str(source)],
        expected_count=1,
        out_dir=str(tmp_path / "outputs"),
        resolution="320x192",
        fit_mode="crop",
        protect_composition=True,
    )

    with Image.open(tmp_path / "outputs" / staged[0]) as fitted:
        assert fitted.size == (320, 192)
        assert fitted.getpixel((160, 0)) == (220, 30, 20)
        assert fitted.getpixel((160, 191)) == (220, 30, 20)


def test_crop_retained_fraction_detects_destructive_portrait_to_landscape_crop():
    retained = director_pipeline._crop_retained_fraction(
        (730, 1061),
        "1280x704",
    )

    assert retained == pytest.approx(0.3785, abs=0.001)


def test_blank_black_comic_capture_is_rejected_before_video_generation(tmp_path):
    source = tmp_path / "black-panel.png"
    Image.new("RGB", (320, 192), (0, 0, 0)).save(source)

    with pytest.raises(RuntimeError, match="captured as a blank black image"):
        director_pipeline._prepare_provided_clip_images(
            "test-pipeline",
            [str(source)],
            expected_count=1,
            out_dir=str(tmp_path / "outputs"),
            resolution="320x192",
        )


def test_dark_but_detailed_comic_capture_is_not_rejected(tmp_path):
    source = tmp_path / "dark-panel.png"
    image = Image.new("RGB", (320, 192), (1, 1, 1))
    for x in range(100, 220):
        for y in range(60, 132):
            image.putpixel((x, y), (18, 12, 8))
    image.save(source)

    staged = director_pipeline._prepare_provided_clip_images(
        "test-pipeline",
        [str(source)],
        expected_count=1,
        out_dir=str(tmp_path / "outputs"),
        resolution="320x192",
    )

    assert len(staged) == 1
    assert (tmp_path / "outputs" / staged[0]).is_file()


def test_smart_comic_anchors_only_compatible_panels_on_the_same_page():
    params = {
        "comic_end_frame_mode": "smart",
        "comic_shots": [
            {
                "page_number": 1,
                "characters": ["NARA"],
                "framing": "Medium shot",
            },
            {
                "page_number": 1,
                "characters": ["NARA"],
                "framing": "Close-up",
            },
            {
                "page_number": 2,
                "characters": ["KAEL"],
                "framing": "Wide establishing shot",
            },
        ],
    }

    assert director_pipeline._comic_end_image_filenames(
        params,
        ["panel-1.png", "panel-2.png", "panel-3.png"],
    ) == ["panel-2.png", "", ""]


def test_comic_anchor_manual_overrides_take_priority():
    params = {
        "comic_end_frame_mode": "all",
        "comic_shots": [
            {"end_frame_mode": "none"},
            {"end_frame_mode": "next-panel"},
            {},
        ],
    }

    assert director_pipeline._comic_end_image_filenames(
        params,
        ["panel-1.png", "panel-2.png", "panel-3.png"],
    ) == ["", "panel-3.png", ""]


def test_smart_comic_anchors_do_not_guess_without_shot_metadata():
    assert director_pipeline._comic_end_image_filenames(
        {"comic_end_frame_mode": "smart", "comic_shots": []},
        ["panel-1.png", "panel-2.png"],
    ) == ["", ""]


def test_comic_end_frames_are_disabled_by_default():
    assert director_pipeline._comic_end_image_filenames(
        {
            "comic_shots": [
                {"end_frame_mode": "auto"},
                {"end_frame_mode": "auto"},
            ],
        },
        ["panel-1.png", "panel-2.png"],
    ) == ["", ""]


def test_legacy_comic_anchor_names_still_resume_safely():
    assert director_pipeline._comic_end_image_filenames(
        {
            "comic_anchor_mode": "chain",
            "comic_shots": [
                {"transition_to_next": "cut"},
                {},
            ],
        },
        ["panel-1.png", "panel-2.png"],
    ) == ["", ""]


def test_faithful_comic_motion_guard_describes_both_approved_anchors():
    prompt = director_pipeline._comic_motion_prompt(
        "Her scarf moves in the breeze.",
        "faithful",
        True,
    )

    assert "Preserve identity, anatomy, costume" in prompt
    assert "supplied approved end keyframe" in prompt
    assert len(prompt) < 300


def test_locked_comic_camera_forbids_zoom_pan_tilt_and_vertical_drift():
    prompt = director_pipeline._comic_motion_prompt(
        "Her scarf moves in the breeze.",
        "faithful",
        False,
        camera_locked=True,
    )

    assert "Locked camera" in prompt
    assert "exact crop, horizon, perspective and field of view" in prompt
    assert len(prompt) < 300


def test_comic_camera_defaults_to_locked_but_respects_requested_push_in():
    assert director_pipeline._comic_camera_is_locked({"comic_shots": [{}]}, 0)
    assert not director_pipeline._comic_camera_is_locked(
        {"comic_shots": [{"camera_move": "push-in"}]},
        0,
    )


def test_living_still_forces_camera_lock_and_reference_preservation():
    params = {
        "comic_shots": [{
            "motion_mode": "living-still",
            "camera_move": "push-in",
        }],
    }

    assert director_pipeline._comic_motion_mode(params, 0) == "living-still"
    assert director_pipeline._comic_camera_is_locked(params, 0)
    prompt = director_pipeline._comic_motion_prompt(
        "A large action prompt inherited from the comic plan.",
        "faithful",
        False,
        camera_locked=True,
        motion_mode="living-still",
    )
    assert "Only subtle supported motion" in prompt
    assert "Locked camera" in prompt
    assert "Preserve identity" in prompt


def test_contextual_comic_motion_respects_authored_camera_and_performance():
    params = {
        "comic_shots": [{
            "motion_mode": "contextual",
            "camera_move": "push-in",
        }],
    }

    assert director_pipeline._comic_motion_mode(params, 0) == "contextual"
    assert not director_pipeline._comic_camera_is_locked(params, 0)
    prompt = director_pipeline._comic_motion_prompt(
        "Nara closes her hand around the seed and looks toward Kael.",
        "faithful",
        False,
        camera_locked=False,
        motion_mode="contextual",
    )
    assert "Perform only this action" in prompt
    assert "Locked camera" not in prompt


def test_legacy_comic_shots_keep_action_motion_mode():
    assert director_pipeline._comic_motion_mode({"comic_shots": [{}]}, 0) == "action"


def test_comic_preflight_freezes_exact_prompt_canvas_and_runtime_config(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        director_pipeline,
        "_wgp",
        SimpleNamespace(
            get_model_def=lambda _model: {"fps": 25},
            get_model_min_frames_and_step=lambda _model: (17, 8, 8),
        ),
    )
    pid = "preflight-contract"
    director_pipeline._pipelines[pid] = {
        "_clip_source_sizes": [(730, 1061)],
    }
    params = {
        "video_model": "ltx2_22B_distilled_1_1",
        "video_params": {
            "resolution": "1280x720",
            "num_inference_steps": 8,
            "stage2_steps": 3,
            "guidance_scale": 1,
            "input_video_strength": 0.7,
        },
        "comic_motion_fidelity": "faithful",
        "comic_motion_treatment": "contextual",
        "comic_shots": [{
            "page_number": 2,
            "panel_number": 3,
            "motion_mode": "contextual",
            "camera_move": "none",
        }],
        "video_loras": {"activated_loras": ["anime-motion.safetensors"]},
    }
    clip_plans = [{
        "video_prompt": "Nara studies the seed without changing position.",
        "image_prompt": "",
    }]
    planned_clips = [{
        "start": 0,
        "end": 3,
        "duration_sec": 3,
        "section_label": "2.3",
    }]

    try:
        previews, end_images = director_pipeline._build_comic_video_previews(
            pid,
            params,
            clip_plans,
            planned_clips,
            ["prepared-panel.png"],
            out_dir=str(tmp_path),
        )
    finally:
        director_pipeline._pipelines.pop(pid, None)

    preview = previews[0]
    assert end_images == [""]
    assert preview["source_resolution"] == "730x1061"
    assert preview["input_resolution"] == "1280x704"
    assert preview["output_resolution"] == "1280x704"
    assert preview["num_inference_steps"] == 8
    assert preview["stage2_steps"] == 3
    assert preview["frames"] == 73
    assert preview["input_video_strength"] == 0.9
    assert preview["activated_loras"] == ["anime-motion.safetensors"]
    assert "Perform only this action" in preview["prompt"]
    assert "Locked camera" in preview["prompt"]
    assert clip_plans[0]["_effective_video_prompt"] == preview["prompt"]
    assert clip_plans[0]["_effective_video_frames"] == preview["frames"]


def test_generate_single_preflight_clip_clones_frozen_contract(
    monkeypatch,
    tmp_path,
):
    started_threads = []

    class DeferredThread:
        def __init__(self, *, target, args, kwargs, daemon):
            self.target = target
            self.args = args
            self.kwargs = kwargs
            self.daemon = daemon

        def start(self):
            started_threads.append(self)

    monkeypatch.setattr(director_pipeline.threading, "Thread", DeferredThread)
    source_pid = "preflight-source"
    source_plans = [
        {
            "video_prompt": "first",
            "_effective_video_prompt": "FROZEN FIRST",
            "_effective_video_frames": 73,
        },
        {
            "video_prompt": "second",
            "_effective_video_prompt": "FROZEN SECOND",
            "_effective_video_frames": 81,
        },
    ]
    source_timings = [
        {"start": 0, "end": 3, "_effective_video_frames": 73},
        {"start": 3, "end": 6, "_effective_video_frames": 81},
    ]
    source_params = {
        "comic_preflight_only": True,
        "auto_mode": True,
        "comic_shots": [{"panel_number": 1}, {"panel_number": 2}],
        "provided_clip_image_paths": ["/tmp/first.png", "/tmp/second.png"],
    }
    fingerprint = director_pipeline._comic_preflight_fingerprint(
        source_params,
        source_plans,
        source_timings,
        ["first.png", "second.png"],
        str(tmp_path),
    )
    source_params["_comic_preflight_fingerprint"] = fingerprint
    director_pipeline._pipelines[source_pid] = {
        "id": source_pid,
        "status": "preview_ready",
        "clip_plans": source_plans,
        "clip_images": ["first.png", "second.png"],
        "_planned_clips": source_timings,
        "_clip_end_images": ["", "third.png"],
        "_clip_keyframes": [[], []],
        "params": source_params,
        "workspace": None,
        "out_dir": str(tmp_path),
        "_comic_preflight_fingerprint": fingerprint,
        "_preview_approved_fingerprint": fingerprint,
    }

    child_pid = None
    try:
        ok, message, child_pid = director_pipeline.start_preview_generation(
            source_pid,
            1,
            expected_fingerprint=fingerprint,
        )
        child = director_pipeline._pipelines[child_pid]
        assert ok
        assert message == "started"
        assert child["clip_plans"][0]["_effective_video_prompt"] == "FROZEN SECOND"
        assert child["clip_plans"][0]["_effective_video_frames"] == 81
        assert child["clip_images"] == ["second.png"]
        assert child["params"]["comic_shots"] == [{"panel_number": 2}]
        assert child["params"]["provided_clip_image_paths"] == ["/tmp/second.png"]
        assert child["params"]["_comic_prepared_end_images"] == ["third.png"]
        assert child["params"]["comic_preflight_only"] is False
        assert source_plans[1]["_effective_video_prompt"] == "FROZEN SECOND"
        assert len(started_threads) == 1
        assert started_threads[0].kwargs == {"resume": True}

        duplicate_ok, duplicate_message, duplicate_pid = (
            director_pipeline.start_preview_generation(
                source_pid,
                1,
                expected_fingerprint=fingerprint,
            )
        )
        assert duplicate_ok
        assert duplicate_message == "already_running"
        assert duplicate_pid == child_pid
        assert len(started_threads) == 1
    finally:
        director_pipeline._pipelines.pop(source_pid, None)
        if child_pid:
            director_pipeline._pipelines.pop(child_pid, None)


def test_i2v_prompt_always_anchors_illustrated_source_style():
    prompt = LtxI2VRenderer.ensure_source_style(
        "She turns toward camera while her coat and hair move in the wind.",
        SimpleNamespace(visual_style="2D anime, clean cel shading"),
    )

    assert "exact first frame" in prompt
    assert "do not restyle" in prompt
    assert "photorealistic" in prompt
    assert "2D anime, clean cel shading" in prompt


def test_story_anime_style_lock_rejects_live_action_recasting():
    prompt = apply_visual_style_lock(
        "The heroine turns toward the crystal tower.",
        "2D anime, clean cel shading, watercolor backgrounds",
        mode="video",
        preserve=True,
        has_reference=True,
    )

    assert prompt.startswith("VISUAL STYLE LOCK:")
    assert "2D anime" in prompt
    assert "no live action" in prompt
    assert "photorealistic people" in prompt
    assert "approved Story reference artwork" in prompt


def test_photoreal_story_lock_does_not_add_illustration_negative():
    prompt = apply_visual_style_lock(
        "A woman crosses the room.",
        "Photorealistic 35mm live-action drama",
        mode="video",
        preserve=True,
        has_reference=True,
    )

    assert "Photorealistic 35mm" in prompt
    assert "no live action" not in prompt
    assert "no 3D CGI" not in prompt


def test_story_style_lock_covers_images_windows_and_keyframes():
    plans = [{
        "image_prompt": "Opening frame.",
        "video_prompt": "",
        "window_prompts": ["First movement.", "Second movement."],
        "keyframe_prompts": ["Changed pose."],
    }]
    enforce_visual_style_on_clip_plans(
        plans,
        "European comic art, ink lines and flat color",
        preserve=True,
        has_reference=True,
    )

    assert "VISUAL STYLE LOCK:" in plans[0]["image_prompt"]
    assert plans[0]["video_prompt"] == ""
    assert all("VISUAL STYLE LOCK:" in item for item in plans[0]["window_prompts"])
    assert all("VISUAL STYLE LOCK:" in item for item in plans[0]["keyframe_prompts"])


def test_story_image_style_lock_respects_minimax_prompt_limit():
    prompt = apply_visual_style_lock(
        "Detailed opening-frame instruction " * 100,
        "2D anime, clean cel shading, watercolor backgrounds",
        mode="image",
        preserve=True,
        has_reference=True,
    )

    assert len(prompt) < 1500
    assert prompt.startswith("VISUAL STYLE LOCK:")


def test_story_prompt_contract_forces_character_medium_and_removes_lyric_lettering():
    plans = [{
        "image_prompt": "A low-poly singer stands under cyan light.",
        "video_prompt": (
            "The singer raises one hand. Text overlays: 'Despierta dentro de mí'. "
            "The camera slowly pushes in."
        ),
        "window_prompts": ["Processing text appears: 'anomalía detectada'."],
        "keyframe_prompts": ["The question '¿Quién soy?' materializes as corrupted text."],
        "h3_segment_prompts": ["Lines of code begin forming in the air: 'soy libre'."],
    }]

    enforce_visual_style_on_clip_plans(
        plans,
        "lo-fi PS1 world",
        preserve=True,
        character_visual_style="handmade plasticine claymation figures",
        allow_clip_text=False,
    )

    all_prompts = [
        plans[0]["image_prompt"], plans[0]["video_prompt"],
        *plans[0]["window_prompts"], *plans[0]["keyframe_prompts"],
        *plans[0]["h3_segment_prompts"],
    ]
    assert all("CHARACTER STYLE LOCK:" in prompt for prompt in all_prompts)
    assert all("NO VISIBLE TEXT LOCK:" in prompt for prompt in all_prompts)
    assert "Despierta dentro de mí" not in plans[0]["video_prompt"]
    assert "anomalía detectada" not in plans[0]["window_prompts"][0]
    assert "¿Quién soy?" not in plans[0]["keyframe_prompts"][0]
    assert "soy libre" not in plans[0]["h3_segment_prompts"][0]
    assert "The singer raises one hand" in plans[0]["video_prompt"]
    assert "The camera slowly pushes in" in plans[0]["video_prompt"]


def test_visible_text_cleanup_keeps_spoken_dialogue_and_negative_style_wording():
    prompt = (
        'VISUAL STYLE LOCK: low-poly game art, no text captions. '
        'The performer says "I am awake" while looking into camera.'
    )

    cleaned = strip_visible_text_directions(prompt)

    assert "no text captions" in cleaned
    assert 'says "I am awake"' in cleaned


def test_nominal_24gb_gpu_is_not_misclassified_as_low_vram():
    assert _classify_vram_tier(True, 23.5) == "high"
    assert _classify_vram_tier(True, 22.0) == "low"
    assert _classify_vram_tier(False, 24.0) == "none"
