"""Meshy 3D generation: options reach the request, 429 waits, cancel refunds. No network, no credits."""
from pathlib import Path

import pytest

from services import meshy_http, meshy_3d_service
from services.meshy_3d_service import Meshy3DError, generate_model
from tests.support.fake_meshy import FakeMeshy, error


@pytest.fixture
def fake(monkeypatch):
    meshy = FakeMeshy().install(monkeypatch)
    meshy.slept = []
    monkeypatch.setattr(meshy_http.time, "sleep", meshy.slept.append)
    monkeypatch.setattr(meshy_3d_service, "local_image_data_uri", lambda path: "data:image/png;base64,eHg=")
    return meshy


def text(tmp_path, **kwargs):
    return generate_model(api_key="msy-key", output_dir=str(tmp_path), prompt="a brass robot", filename_stem="robot", **kwargs)


def test_text_generation_sends_the_options_to_preview_and_refine(fake, tmp_path):
    result = text(tmp_path, model="meshy-6", options={
        "pose_mode": "t-pose", "enable_pbr": True, "texture_resolution": "4k", "auto_size": True, "texture_prompt": "brushed brass"})
    preview, refine = fake.posts("preview")[0], fake.posts("refine")[0]
    assert preview == {
        "mode": "preview", "prompt": "a brass robot", "target_formats": ["glb"], "ai_model": "meshy-6",
        "pose_mode": "t-pose", "auto_size": True, "origin_at": "bottom", "should_remesh": True, "target_polycount": 30000}
    assert refine == {
        "mode": "refine", "preview_task_id": "preview-1", "target_formats": ["glb"], "ai_model": "meshy-6",
        "enable_pbr": True, "texture_resolution": "4k", "texture_prompt": "brushed brass", "auto_size": True, "origin_at": "bottom"}
    assert Path(result["path"]).read_bytes()[:4] == b"glTF"
    assert result["filename"] == "robot.glb" and result["provider"] == "meshy"


def test_defaults_keep_the_mesh_light_and_the_prompt_is_capped_at_800(fake, tmp_path):
    generate_model(api_key="k", output_dir=str(tmp_path), prompt="x" * 900)
    preview = fake.posts("preview")[0]
    assert len(preview["prompt"]) == 800
    assert preview["should_remesh"] is True and preview["target_polycount"] == 30000
    assert preview["ai_model"] == "latest" and "origin_at" not in preview and "pose_mode" not in preview


def test_image_generation_takes_the_options_and_reports_what_it_cost(fake, tmp_path):
    result = generate_model(api_key="k", output_dir=str(tmp_path), image_path="ref.png", filename_stem="lamp",
                            options={"model_type": "smart-topology", "target_polycount": 8000, "geometry_resolution": "standard"})
    body = fake.posts("image")[0]
    assert body["image_url"].startswith("data:image/png")
    assert body["model_type"] == "smart-topology" and body["ai_model"] == "meshy-t2.5" and body["target_polycount"] == 8000
    assert "should_remesh" not in body and "geometry_resolution" not in body
    meshy = result["meshy"]
    assert meshy["task_ids"] == {"image": "image-1"} and meshy["consumed_credits"] == 30
    assert meshy["expires_at"] == 1_900_000_000_000 and meshy["ai_model"] == "meshy-t2.5"
    assert "thumbnail_url" not in result


def test_the_signed_thumbnail_is_saved_as_the_gallery_picture(fake, tmp_path):
    generate_model(api_key="k", output_dir=str(tmp_path), image_path="ref.png", filename_stem="lamp")
    assert (tmp_path / "lamp.preview.png").read_bytes().startswith(b"\x89PNG")
    assert not list(tmp_path.glob("*.part"))


def test_text_generation_adds_preview_and_refine_credits(fake, tmp_path):
    meshy = text(tmp_path)["meshy"]
    assert meshy["task_ids"] == {"preview": "preview-1", "refine": "refine-2"}
    assert meshy["consumed_credits"] == 30 and "expires_at" not in meshy   # text-to-3D reports no expiry


@pytest.mark.parametrize("options,message", [
    ({"pose_mode": "z-pose"}, "pose_mode must be one of"),
    ({"colour": "red"}, "Unknown Meshy option"),
    ({"target_polycount": 50}, "from 100 to 300000"),
    ({"should_remesh": False, "target_polycount": 5000}, "need should_remesh"),
    ({"origin_at": "center"}, "needs auto_size"),
    ({"geometry_resolution": "4k", "ai_model": "meshy-6"}, "meshy-7.1 or latest"),
    ({"texture_resolution": "8k", "ai_model": "meshy-6-lite"}, "not available with meshy-6-lite"),
    ({"model_type": "lowpoly"}, "model_type must be one of"),
    ({"model_type": "smart-topology", "ai_model": "meshy-6"}, "meshy-t2 or meshy-t2.5"),
    ({"ai_model": "meshy-t2"}, "needs model_type smart-topology"),
    ({"enable_pbr": "yes"}, "true or false"),
])
def test_invalid_options_are_refused_before_any_request(fake, tmp_path, options, message):
    with pytest.raises(ValueError, match=message):
        text(tmp_path, options=options)
    assert fake.calls == []


def test_a_rate_limit_waits_for_retry_after_and_tries_again(fake, tmp_path):
    fake.errors["POST /v2/text-to-3d"] = [error(429, "Rate limit exceeded", **{"Retry-After": "7"})]
    text(tmp_path)
    assert sum(fake.slept) == pytest.approx(7)
    assert len(fake.posts("preview")) == 1


def test_the_concurrent_task_limit_waits_and_then_gives_up(fake, tmp_path):
    fake.errors["POST /v1/image-to-3d"] = [error(429, "NoMorePendingTasks: wait") for _ in range(2)]
    generate_model(api_key="k", output_dir=str(tmp_path), image_path="r.png")
    assert sum(fake.slept) == pytest.approx(5 + 10)
    fake.errors["POST /v1/image-to-3d"] = [error(429, "NoMorePendingTasks: wait") for _ in range(30)]
    with pytest.raises(Meshy3DError) as raised:
        generate_model(api_key="k", output_dir=str(tmp_path), image_path="r.png")
    assert raised.value.code == "meshy_busy"


def test_a_rate_limit_that_never_clears_stops_with_a_clear_error(fake, tmp_path):
    fake.errors["POST /v2/text-to-3d"] = [error(429, "Rate limit exceeded") for _ in range(10)]
    with pytest.raises(Meshy3DError, match="rate limit") as raised:
        text(tmp_path)
    assert raised.value.code == "meshy_rate_limited" and fake.created == []


@pytest.mark.parametrize("status,code,words", [
    (401, "meshy_invalid_key", "API key"), (402, "meshy_insufficient_credits", "credits"), (400, "meshy_bad_request", "bad prompt")])
def test_errors_carry_meshys_own_message(fake, tmp_path, status, code, words):
    fake.errors["POST /v2/text-to-3d"] = [error(status, "bad prompt")]
    with pytest.raises(Meshy3DError) as raised:
        text(tmp_path)
    assert raised.value.code == code and words in str(raised.value) and raised.value.status_code == status
    if status == 400:
        assert "bad prompt" in str(raised.value)


def test_a_failed_task_reports_meshys_reason_and_writes_nothing(fake, tmp_path):
    fake.script["image"] = [{"status": "FAILED", "task_error": {"message": "The image has no subject"}, "consumed_credits": 0}]
    with pytest.raises(Meshy3DError, match="no subject"):
        generate_model(api_key="k", output_dir=str(tmp_path), image_path="r.png")
    assert list(tmp_path.iterdir()) == []


def test_missing_key_points_at_settings(fake, tmp_path):
    with pytest.raises(Meshy3DError, match="Settings") as raised:
        generate_model(api_key=" ", output_dir=str(tmp_path), prompt="x")
    assert raised.value.code == "meshy_key_missing" and fake.calls == []


def _cancel_after_first_poll(fake):
    return lambda: any(call[0] == "GET" for call in fake.calls)


def test_cancelling_a_pending_task_deletes_it_to_get_the_credits_back(fake, tmp_path):
    fake.script["image"] = [{"status": "PENDING", "progress": 0}]
    with pytest.raises(Meshy3DError, match="cancelled") as raised:
        generate_model(api_key="k", output_dir=str(tmp_path), image_path="r.png", cancelled=_cancel_after_first_poll(fake))
    assert fake.deleted == ["/v1/image-to-3d/image-1"] and raised.value.status_code == 499
    assert list(tmp_path.iterdir()) == []


def test_cancelling_a_running_task_only_stops_polling(fake, tmp_path):
    fake.script["preview"] = [{"status": "IN_PROGRESS", "progress": 40}]
    with pytest.raises(Meshy3DError, match="cancelled"):
        text(tmp_path, cancelled=_cancel_after_first_poll(fake))
    assert fake.deleted == [] and fake.made("refine") == []


class _RunNow:
    def __init__(self, target=None, args=(), **_kw):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def _remote_service(monkeypatch):
    from services import model3d_service
    monkeypatch.setattr(model3d_service.execution_mode, "validate_generation", lambda *_a, **_k: None)
    monkeypatch.setattr(model3d_service.execution_mode, "validate_remote_provider", lambda *_a, **_k: None)
    monkeypatch.setattr(model3d_service, "_active_profile", lambda: {"model3d_provider": "meshy", "model3d_model": "meshy-6"})
    monkeypatch.setattr(model3d_service, "_services", lambda: {"meshy_api_key": "msy-key"})
    monkeypatch.setattr(model3d_service.threading, "Thread", _RunNow)
    return model3d_service


def test_a_full_server_job_carries_the_options_and_records_meshy_in_the_manifest(fake, monkeypatch, tmp_path):
    import json
    service = _remote_service(monkeypatch)
    job = service.start_job(
        body={"provider": "meshy", "prompt": "a brass robot", "meshy": {"pose_mode": "a-pose", "auto_size": True}},
        image_paths={}, output_dir=str(tmp_path), workspace="studio")
    done = service.get_job(job["job_id"])
    assert done["status"] == "completed", done
    preview = fake.posts("preview")[0]
    assert preview["ai_model"] == "meshy-6" and preview["pose_mode"] == "a-pose" and preview["origin_at"] == "bottom"
    manifest = json.loads((tmp_path / done["filename"]).with_suffix(".meta.json").read_text(encoding="utf-8"))
    meshy = manifest["params"]["meshy"]
    assert manifest["params"]["provider"] == "meshy"
    assert meshy["task_ids"] == {"preview": "preview-1", "refine": "refine-2"} and meshy["consumed_credits"] == 30
    assert meshy["options"]["pose_mode"] == "a-pose" and meshy["ai_model"] == "meshy-6"
    assert "thumbnail_url" not in json.dumps(manifest)


def test_a_bad_option_is_a_400_at_submission_and_spends_nothing(fake, monkeypatch, tmp_path):
    service = _remote_service(monkeypatch)
    with pytest.raises(ValueError, match="pose_mode"):
        service.start_job(body={"provider": "meshy", "prompt": "x", "meshy": {"pose_mode": "dance"}},
                          image_paths={}, output_dir=str(tmp_path), workspace="studio")
    assert fake.calls == []


def test_the_core_server_job_uses_the_same_options(fake, monkeypatch, tmp_path):
    import json
    from services import core_remote_3d
    monkeypatch.setattr(core_remote_3d.threading, "Thread", _RunNow)
    monkeypatch.setattr(core_remote_3d.core, "services_raw", lambda: {"meshy_api_key": "msy-key"})
    monkeypatch.setattr("services.core_production.production_profile_response", lambda: {"profile": {"model3d": {"provider": "meshy", "model": "latest"}}})
    monkeypatch.setattr("services.execution_mode.validate_remote_provider", lambda *_a, **_k: None)
    job = core_remote_3d.start_job({"provider": "meshy", "prompt": "a lamp", "meshy": {"enable_pbr": True}},
                                   workspace="default", output_dir=str(tmp_path))
    done = core_remote_3d.get_job(job["job_id"])
    assert done["status"] == "completed", done
    assert fake.posts("refine")[0]["enable_pbr"] is True
    manifest = json.loads((tmp_path / done["filename"]).with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert manifest["params"]["meshy"]["task_ids"]["refine"] == "refine-2"
    with pytest.raises(ValueError, match="Unknown Meshy option"):
        core_remote_3d.start_job({"provider": "meshy", "prompt": "a lamp", "meshy": {"bogus": 1}},
                                 workspace="default", output_dir=str(tmp_path))
