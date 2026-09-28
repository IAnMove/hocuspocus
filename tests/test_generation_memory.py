"""Queue RAM headroom and per-model step pace. Probes are injected."""

from __future__ import annotations

import os
import sys
import types

import pytest


_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.abspath(os.path.join(_HERE, "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services.generation_memory import (  # noqa: E402
    assess_pace,
    include_performance,
    is_large_video_model,
    large_video_model_ids,
    min_available_bytes,
    note_inference_step,
    prepare_queued_model,
    record_pace,
)
from services.generation_output_name import generation_receipt_view  # noqa: E402


_GIB = 1024**3
_LIMIT = 24 * _GIB


def _prepare(model, available, calls, cache, **kwargs):
    return prepare_queued_model(
        model,
        available_bytes=available,
        unload=calls.append,
        release_cache=lambda: cache.append("cleared"),
        **kwargs,
    )


def test_ram_above_threshold_does_not_unload():
    calls, cache = [], []
    above = _prepare("minimax_h3", _LIMIT + 1, calls, cache)
    assert above["released"] is False
    assert above["reason"] == "ram_available"
    assert calls == []
    assert cache == []
    equal = _prepare("ltx2_22B", _LIMIT, calls, cache)
    assert equal["released"] is False
    assert calls == []
    assert cache == []


def test_low_ram_before_large_video_unloads_inactive_families_and_clears_cache():
    for model in ("minimax_h3", "ltx2_22B", "t2v", "ltx2_22B_distilled", "minimax_h3_fused_turbo"):
        calls, cache = [], []
        result = _prepare(model, _LIMIT - 1, calls, cache)
        assert result["released"] is True
        assert result["reason"] == "low_ram"
        assert calls == ["image", "tts", "music"]
        assert cache == ["cleared"]
        assert is_large_video_model(model)


def test_still_image_model_does_not_unload_when_ram_is_low():
    calls, cache = [], []
    result = _prepare("flux", 1, calls, cache)
    assert result == {"released": False, "reason": "not_large_video", "families": []}
    assert calls == []
    assert cache == []
    assert _prepare("qwen_image_21_bf16", 1, calls, cache)["reason"] == "not_large_video"


def test_smaller_video_models_do_not_take_the_large_video_path():
    calls, cache = [], []
    for model in (
        "t2v_1.3B",
        "vace_1.3B",
        "sky_df_1.3B",
        "ti2v_2_2",
        "lucy_edit",
        "kiwi_edit",
        "ovi",
        "ltx2_19B",
        "ltx2_distilled",
        "h3_advanced_fl2va",
        "hunyuan",
    ):
        result = _prepare(model, 1, calls, cache)
        assert result["reason"] == "not_large_video"
        assert not is_large_video_model(model)
    assert calls == []
    assert cache == []


def test_unknown_ram_does_not_unload():
    calls, cache = [], []

    def boom():
        raise OSError("meminfo")

    raised = prepare_queued_model(
        "t2v", probe=boom, unload=calls.append, release_cache=lambda: cache.append("cleared"),
    )
    missing = prepare_queued_model(
        "t2v", probe=lambda: None, unload=calls.append, release_cache=lambda: cache.append("cleared"),
    )
    assert raised["reason"] == "ram_available"
    assert missing["reason"] == "ram_available"
    assert calls == []
    assert cache == []


def test_ram_threshold_is_configurable_without_a_code_edit(monkeypatch):
    monkeypatch.delenv("HOCUSPOCUS_QUEUE_RAM_MIN_BYTES", raising=False)
    assert min_available_bytes() == _LIMIT
    monkeypatch.setenv("HOCUSPOCUS_QUEUE_RAM_MIN_BYTES", "nope")
    assert min_available_bytes() == _LIMIT
    monkeypatch.setenv("HOCUSPOCUS_QUEUE_RAM_MIN_BYTES", "-1")
    assert min_available_bytes() == _LIMIT
    monkeypatch.setenv("HOCUSPOCUS_QUEUE_RAM_MIN_BYTES", "100")
    calls, cache = [], []
    assert _prepare("t2v", 100, calls, cache)["released"] is False
    assert _prepare("t2v", 99, calls, cache)["released"] is True
    assert calls == ["image", "tts", "music"]


def test_pace_ratio_marks_only_a_clear_slowdown_and_a_missing_baseline_is_healthy():
    missing = assess_pace(2.0, None)
    healthy = assess_pace(1.5, 1.0)
    slow = assess_pace(2.0, 1.0)
    assert missing["degraded"] is False
    assert missing["reason"] == "no_baseline"
    assert missing["baseline_s_per_step"] is None
    assert healthy["degraded"] is False
    assert healthy["reason"] == "within_baseline"
    assert slow["degraded"] is True
    assert slow["reason"] == "slower_than_baseline"
    assert slow["s_per_step"] == 2.0
    assert slow["baseline_s_per_step"] == 1.0
    assert set(slow) == {"s_per_step", "baseline_s_per_step", "degraded", "reason"}


def test_first_pace_sample_sets_the_baseline_and_later_samples_keep_it():
    book = {}
    first = record_pace("minimax_h3", 1.0, book=book)
    second = record_pace("minimax_h3", 2.0, book=book)
    third = record_pace("minimax_h3", 1.5, book=book)
    assert first["degraded"] is False
    assert first["baseline_s_per_step"] is None
    assert book["minimax_h3"] == 1.0
    assert second["degraded"] is True
    assert second["baseline_s_per_step"] == 1.0
    assert third["degraded"] is False
    assert third["baseline_s_per_step"] == 1.0
    assert book["minimax_h3"] == 1.0


def test_receipt_and_status_include_the_performance_object(tmp_path):
    slow = assess_pace(2.0, 1.0)
    receipt = {"status": "queued", "intent_id": "pace"}
    task = {"status": "running", "metadata": {"performance": slow}, "result_refs": []}
    view = generation_receipt_view(
        receipt, task, workspace="default", workspace_dir=str(tmp_path),
    )
    assert view["receipt"]["performance"] == slow
    assert view["receipt"]["status"] == "queued"
    assert "performance" not in receipt
    untouched = {"status": "queued"}
    plain = generation_receipt_view(
        untouched, {"status": "completed", "result_refs": []},
        workspace="default", workspace_dir=str(tmp_path),
    )
    assert plain["receipt"] == untouched
    assert "performance" not in plain["receipt"]
    payload = {"job_id": "job-1", "status": "running"}
    status = include_performance(payload, {"performance": assess_pace(1.5, 1.0)})
    assert status["performance"]["degraded"] is False
    assert status["job_id"] == "job-1"
    assert payload == {"job_id": "job-1", "status": "running"}
    assert include_performance({"status": "queued"}, {"status": "running"}) == {"status": "queued"}


def test_note_inference_step_measures_only_after_the_denoising_anchor():
    book = {}
    job = {"params": {"model_type": "t2v"}}
    assert note_inference_step(job, step=0, now=10.0, message="Loading model", book=book) == {}
    assert note_inference_step(job, step=0, now=10.0, message="Denoising", book=book) == {}
    assert "performance" not in job
    job["inference_started_at"] = 10.0
    job["inference_start_step"] = 0
    update = note_inference_step(job, step=2, now=14.0, message="Denoising | 4s", book=book)
    assert update["performance"]["s_per_step"] == 2.0
    assert update["performance"]["degraded"] is False
    later = note_inference_step(job, step=4, now=26.0, message="denoising", book=book)
    assert later["performance"]["s_per_step"] == 4.0
    assert later["performance"]["degraded"] is True
    assert later["performance"]["baseline_s_per_step"] == 2.0
    assert job["performance"]["degraded"] is True


def test_default_unloader_releases_only_a_loaded_inactive_family(monkeypatch):
    released = []
    fake = types.SimpleNamespace(
        transformer_type="flux",
        release_model=lambda: released.append("released"),
    )
    monkeypatch.setattr("services.generation.runtime.get_wgp", lambda: fake)
    result = prepare_queued_model(
        "minimax_h3", available_bytes=1, release_cache=lambda: released.append("cache"),
    )
    assert result["families"] == ["image", "tts", "music"]
    assert released == ["released", "cache"]
    released.clear()
    fake.transformer_type = "t2v"
    prepare_queued_model(
        "ltx2_22B", available_bytes=1, release_cache=lambda: released.append("cache"),
    )
    assert released == ["cache"]


def test_large_video_catalog_covers_h3_ltx23_and_wan14():
    ids = set(large_video_model_ids())
    for model in (
        "minimax_h3",
        "minimax_h3_full",
        "minimax_h3_legacy",
        "minimax_h3_ref2va",
        "minimax_h3_ref2va_full",
        "minimax_h3_fused_turbo",
        "minimax_h3_ref2va_fused_turbo",
        "ltx2_22B",
        "ltx2_22B_distilled",
        "t2v",
        "i2v",
        "phantom_14B",
        "sky_df_14B",
        "lynx_lite",
        "vace_lynx_lite_14B",
        "alpha_lynx",
    ):
        assert model in ids
        assert is_large_video_model(model)
    for model in ("flux", "t2v_1.3B", "ltx2_19B", "h3_advanced_fl2va", "ovi"):
        assert model not in ids


def test_catalog_members_are_large_and_probe_can_force_a_release():
    assert all(is_large_video_model(model) for model in large_video_model_ids())
    calls = []
    prepare_queued_model(
        "wanmove",
        probe=lambda: 1,
        unload=calls.append,
        release_cache=lambda: None,
    )
    assert calls == ["image", "tts", "music"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
