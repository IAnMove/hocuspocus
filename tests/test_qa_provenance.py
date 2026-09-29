"""Provenance is separate from format validation. Fake adapter only."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.publish_qa_check import RecordingAdapter, publish, stamp_provenance
from scripts.verify_qa_evidence import validate
from scripts.verify_qa_provenance import verify_provenance

ROOT = Path(__file__).resolve().parents[1]
HEAD = "b" * 40
BASE = "a" * 40
REPO = "IAnMove/hocuspocus"
RUN = "run-123"
IMPL = "impl-bot"


def _evidence(**overrides):
    payload = json.loads(
        (ROOT / "tests/fixtures/qa_evidence/valid_independent.json").read_text(encoding="utf-8")
    )
    payload.update(overrides)
    return payload


def _envelope(evidence=None, **provenance_overrides):
    provenance = {
        "kind": "github_actions_check",
        "repository": REPO,
        "workflow_file": ".github/workflows/qa-evidence.yml",
        "run_id": RUN,
        "head_sha": HEAD,
        "base_sha": BASE,
        "producer": {"login": "qa-bot", "session_id": "qa-session"},
    }
    provenance.update(provenance_overrides)
    return {"evidence": evidence or _evidence(), "provenance": provenance}


def _errors(envelope, **kwargs):
    return verify_provenance(
        envelope,
        head=kwargs.get("head", HEAD),
        base=kwargs.get("base", BASE),
        implementer=kwargs.get("implementer", IMPL),
        repository=kwargs.get("repository", REPO),
        run_id=kwargs.get("run_id", RUN),
        artifact_exists=kwargs.get("artifact_exists", lambda path: (ROOT / path).is_file()),
    )


def test_format_valid_json_without_provenance_is_not_authenticated():
    assert validate(
        _evidence(),
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        risk="routine",
        require_separation=False,
    ) == []
    errors = _errors({"evidence": _evidence()})
    assert any("missing provenance" in item for item in errors)


def test_publisher_stamps_provenance_and_ignores_file_claims(tmp_path: Path):
    forged = _envelope(run_id="forged-run", producer={"login": IMPL, "session_id": "x"})
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(forged), encoding="utf-8")
    adapter = RecordingAdapter()
    code, _summary = publish(
        envelope_path=path,
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        repository=REPO,
        run_id=RUN,
        adapter=adapter,
        artifact_root=ROOT,
    )
    assert code == 0
    assert adapter.calls[0]["conclusion"] == "success"
    stamped = stamp_provenance(
        _evidence(), repository=REPO, run_id=RUN, head=HEAD, base=BASE,
    )
    assert stamped["provenance"]["run_id"] == RUN
    assert stamped["provenance"]["producer"]["login"] == "github-actions[bot]"


def test_valid_envelope_with_verified_provenance_passes():
    assert _errors(_envelope()) == []


def test_falsely_attributed_producer_is_rejected():
    errors = _errors(_envelope(producer={"login": IMPL, "session_id": "qa-session"}))
    assert any("must not be the implementer" in item for item in errors)


def test_wrong_head_sha_is_rejected():
    errors = _errors(_envelope(), head="c" * 40)
    assert any("HEAD" in item for item in errors)


def test_stale_run_id_is_rejected():
    errors = _errors(_envelope(), run_id="run-old")
    assert any("run_id" in item for item in errors)


def test_untrusted_workflow_file_is_rejected():
    errors = _errors(_envelope(workflow_file=".github/workflows/ci.yml"))
    assert any("trusted publisher workflow" in item for item in errors)


def test_missing_artifact_is_rejected():
    evidence = _evidence(artifacts=["tests/fixtures/qa_evidence/does-not-exist.json"])
    errors = _errors(_envelope(evidence=evidence))
    assert any("artifact missing" in item for item in errors)


def test_open_blocking_finding_is_rejected():
    evidence = _evidence(findings=[{"severity": "blocking", "status": "open", "summary": "race"}])
    errors = _errors(_envelope(evidence=evidence))
    assert any("blocking" in item for item in errors)


def test_publisher_missing_envelope_is_pending_not_success(tmp_path: Path):
    adapter = RecordingAdapter()
    code, summary = publish(
        envelope_path=tmp_path / "absent.json",
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        repository=REPO,
        run_id=RUN,
        adapter=adapter,
    )
    assert code == 0
    assert adapter.calls[0]["conclusion"] == "neutral"
    assert "pending" in adapter.calls[0]["title"].lower() or "pending" in summary.lower()
    assert adapter.calls[0]["conclusion"] != "success"


def test_publisher_rejects_blocking_findings_after_stamping(tmp_path: Path):
    path = tmp_path / "blocked.json"
    path.write_text(json.dumps(_evidence(findings=[{
        "severity": "blocking", "status": "open", "summary": "race",
    }])), encoding="utf-8")
    adapter = RecordingAdapter()
    code, _summary = publish(
        envelope_path=path,
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        repository=REPO,
        run_id=RUN,
        adapter=adapter,
        artifact_root=ROOT,
    )
    assert code == 1
    assert adapter.calls[0]["conclusion"] == "failure"


def test_publisher_success_uses_adapter_not_json_role(tmp_path: Path):
    path = tmp_path / "ok.json"
    path.write_text(json.dumps(_envelope()), encoding="utf-8")
    adapter = RecordingAdapter()
    code, _summary = publish(
        envelope_path=path,
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        repository=REPO,
        run_id=RUN,
        adapter=adapter,
        artifact_root=ROOT,
    )
    assert code == 0
    assert adapter.calls[0]["name"] == "Independent QA"
    assert adapter.calls[0]["head_sha"] == HEAD
    assert adapter.calls[0]["conclusion"] == "success"


# Offline media-package evidence: kept in this already registered provenance
# suite so the shared CI shard manifest does not need concurrent edits.
def _production_package(root):
    from services.production_package import write_manifest, workspace_url

    scene = {"version": 1, "width": 1920, "height": 1080, "fps": 24,
             "duration": 4, "layers": [], "texts": []}
    (root / "a.scene.json").write_text(json.dumps(scene))
    for name in ("a.mp4", "final.mp4"):
        (root / name).write_bytes(b"placeholder, not generated media")
    row = {"key": "a", "kind": "still", "start": 0, "end": 4,
           "scene_doc": "a.scene.json", "scene_video": "a.mp4", "warnings": []}
    # On the first run package() precedes montage(); manifest.montage is null.
    write_manifest(root, "p", "Song", [row], None)
    montage = {"version": 1, "width": 1920, "height": 1080, "fps": 24,
               "clips": [{"id": "a", "source": workspace_url("a.mp4", "ws"),
                          "trimStart": 0, "trimEnd": 4, "transition": "none",
                          "origin": {"kind": "scene2d", "productionId": "p",
                                     "shotId": "a", "scene": "a.scene.json"}}],
               "soundtrack": {"source": "/api/v1/file/song.wav?workspace=ws"}}
    (root / "p.montage.json").write_text(json.dumps(montage))
    state = {"id": "p", "workspace": "ws", "status": "completed", "final": "final.mp4",
             "montage_file": "p.montage.json", "package": {"manifest": "p.shots.json"}}
    (root / "p.production.json").write_text(json.dumps(state))
    return root


def _package_probe(path):
    return {"duration_s": 4.0, "width": 1920, "height": 1080, "fps": 24.0,
            "has_audio": path.name == "final.mp4"}


def _package_report(root, probe=_package_probe):
    from scripts.evaluate_production_package import evaluate

    return evaluate(root, "p.production.json", probe=probe)


def _change_package_json(root, name, change):
    path = root / name
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def _package_codes(report):
    return {issue["code"] for issue in report["issues"]}


def test_package_evidence_never_turns_completed_or_clip_ok_into_artistic_approval(tmp_path):
    root = _production_package(tmp_path)
    _change_package_json(root, "p.production.json", lambda s: s.update(review={"verdict": "ok"}))
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    report = _package_report(root)
    assert report["execution"]["verdict"] == "pass"
    assert report["technical"]["verdict"] == "pass"
    assert report["artistic"]["verdict"] == "pending"
    assert report["publication"] == "requires_artistic_review"
    assert "full_decode" in report["technical"]["not_evaluated"]
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_completed_package_with_missing_editable_scene_is_blocked(tmp_path):
    root = _production_package(tmp_path)
    (root / "a.scene.json").unlink()
    report = _package_report(root)
    assert "missing_artifact" in _package_codes(report)
    assert report["technical"]["verdict"] == "fail" and report["publication"] == "blocked"


def test_completed_package_with_absent_scene_reference_is_blocked(tmp_path):
    root = _production_package(tmp_path)
    _change_package_json(root, "p.shots.json", lambda m: m["shots"][0].update(scene_doc=None))
    assert "missing_reference" in _package_codes(_package_report(root))


def test_package_evidence_records_hashes_of_actual_files(tmp_path):
    import hashlib

    root = _production_package(tmp_path)
    report = _package_report(root)
    evidence = report["artifacts"]["final.mp4"]
    assert evidence["sha256"] == hashlib.sha256((root / "final.mp4").read_bytes()).hexdigest()
    assert evidence["probe"]["duration_s"] == 4
    (root / "final.mp4").write_bytes(b"another export")
    assert _package_report(root)["artifacts"]["final.mp4"]["sha256"] != evidence["sha256"]
    assert "tokens" not in json.dumps(report)


def test_package_source_and_origin_must_correspond_to_the_manifest(tmp_path):
    root = _production_package(tmp_path)
    _change_package_json(root, "p.montage.json", lambda m: m["clips"][0]["origin"].update(shotId="other"))
    assert "origin_mismatch" in _package_codes(_package_report(root))
    _change_package_json(root, "p.montage.json", lambda m: m["clips"][0].update(source="/api/v1/file/other.mp4?workspace=ws"))
    assert "source_mismatch" in _package_codes(_package_report(root))


def test_package_probe_measures_truncation_even_when_status_is_completed(tmp_path):
    root = _production_package(tmp_path)
    def short_export(path):
        return {**_package_probe(path), "duration_s": 2.0}
    report = _package_report(root, short_export)
    assert "duration_mismatch" in _package_codes(report)
    assert report["technical"]["verdict"] == "fail"


def test_package_resolution_rate_and_master_audio_are_measured(tmp_path):
    root = _production_package(tmp_path)
    def wrong_export(path):
        return {**_package_probe(path), "width": 640, "fps": 12.0, "has_audio": False}
    codes = _package_codes(_package_report(root, wrong_export))
    assert {"resolution_mismatch", "fps_mismatch", "missing_audio"} <= codes


def test_package_timeline_gaps_duplicate_keys_and_missing_montage_clips_fail(tmp_path):
    root = _production_package(tmp_path)
    def bad_manifest(m):
        m["shots"][0]["start"] = 1
        m["shots"].append(dict(m["shots"][0]))
    _change_package_json(root, "p.shots.json", bad_manifest)
    codes = _package_codes(_package_report(root))
    assert {"timeline_discontinuity", "duplicate_shot", "shot_order_mismatch"} <= codes


def test_package_rejects_nonfinite_or_invalid_timing_without_crashing(tmp_path):
    root = _production_package(tmp_path)
    for value in (float("nan"), float("inf"), -1, None, True, "4", 2 ** 4096):
        _change_package_json(root, "p.shots.json", lambda m: m["shots"][0].update(end=value))
        assert "invalid_number" in _package_codes(_package_report(root))
    _change_package_json(root, "p.shots.json", lambda m: m["shots"][0].update(start=2 ** 4096, end=4))
    assert "invalid_number" in _package_codes(_package_report(root))


def test_package_rejects_outside_paths_and_symlinks_without_probing_them(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    _production_package(root)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"private")
    (root / "link.mp4").symlink_to(outside)
    seen = []
    def probe(path):
        seen.append(path)
        return _package_probe(path)
    for name in ("../outside.mp4", str(outside), "link.mp4", "https://host/movie.mp4"):
        _change_package_json(root, "p.production.json", lambda s: s.update(final=name))
        assert "unsafe_path" in _package_codes(_package_report(root, probe))
    assert outside not in seen


def test_package_changed_during_probe_invalidates_evidence(tmp_path):
    root = _production_package(tmp_path)
    def changed_export(path):
        if path.name == "final.mp4":
            path.write_bytes(b"changed while ffprobe runs")
        return _package_probe(path)
    assert "artifact_changed" in _package_codes(_package_report(root, changed_export))


def test_package_malformed_json_or_version_cannot_pass(tmp_path):
    root = _production_package(tmp_path)
    (root / "a.scene.json").write_text("{")
    assert "invalid_json" in _package_codes(_package_report(root))
    _change_package_json(root, "p.shots.json", lambda m: m.update(version=2))
    assert "unsupported_version" in _package_codes(_package_report(root))
    _change_package_json(root, "p.shots.json", lambda m: m.update(version=True))
    assert "unsupported_version" in _package_codes(_package_report(root))


def test_package_manifest_with_missing_montage_shot_cannot_pass(tmp_path):
    root = _production_package(tmp_path)
    _change_package_json(root, "p.montage.json", lambda m: m.update(clips=[]))
    assert "shot_order_mismatch" in _package_codes(_package_report(root))


def test_package_scene_duration_and_trim_must_cover_manifest_span(tmp_path):
    root = _production_package(tmp_path)
    _change_package_json(root, "a.scene.json", lambda s: s.update(duration=2))
    _change_package_json(root, "p.montage.json", lambda m: m["clips"][0].update(trimEnd=2))
    codes = _package_codes(_package_report(root))
    assert {"scene_duration_mismatch", "trim_mismatch"} <= codes


def test_package_without_master_soundtrack_does_not_invent_an_audio_requirement(tmp_path):
    root = _production_package(tmp_path)
    _change_package_json(root, "p.montage.json", lambda m: m.pop("soundtrack"))
    def silent(path):
        return {**_package_probe(path), "has_audio": False}
    assert _package_report(root, silent)["technical"]["verdict"] == "pass"


def test_package_does_not_silently_accept_unsupported_montage_transitions(tmp_path):
    root = _production_package(tmp_path)
    _change_package_json(root, "p.montage.json", lambda m: m["clips"][0].update(transition="fade"))
    assert "unsupported_transition" in _package_codes(_package_report(root))


def test_package_cli_is_fail_closed_and_prints_a_report(tmp_path, capsys, monkeypatch):
    from scripts import evaluate_production_package as evaluator

    root = _production_package(tmp_path)
    monkeypatch.setattr(evaluator, "probe_video", _package_probe)
    args = ["--workspace-dir", str(root), "--production-file", "p.production.json"]
    assert evaluator.main(args) == 0
    assert json.loads(capsys.readouterr().out)["artistic"]["verdict"] == "pending"
    (root / "a.scene.json").unlink()
    assert evaluator.main(args) == 1
    assert json.loads(capsys.readouterr().out)["publication"] == "blocked"


def test_package_real_state_does_not_need_id_or_workspace_fields(tmp_path):
    from scripts.evaluate_production_package import evaluate

    root = _production_package(tmp_path)
    def remove_extra_fields(s):
        del s["id"], s["workspace"]
    _change_package_json(root, "p.production.json", remove_extra_fields)
    assert evaluate(root, "p.production.json", workspace_id="ws", probe=_package_probe)["technical"]["verdict"] == "pass"


def test_package_external_or_other_workspace_source_is_not_local_provenance(tmp_path):
    root = _production_package(tmp_path)
    for source in ("http://host/api/v1/file/a.mp4?workspace=ws", "/api/v1/file/a.mp4?workspace=other", "http://[invalid"):
        _change_package_json(root, "p.montage.json", lambda m: m["clips"][0].update(source=source))
        assert "source_mismatch" in _package_codes(_package_report(root))


def test_package_malformed_row_shapes_are_rejected(tmp_path):
    root = _production_package(tmp_path)
    for value in (None, {}, [], [None], ["a"]):
        _change_package_json(root, "p.shots.json", lambda m: m.update(shots=value))
        assert "invalid_rows" in _package_codes(_package_report(root))


def test_package_missing_probe_is_infrastructure_failure(tmp_path, capsys, monkeypatch):
    from scripts import evaluate_production_package as evaluator

    root = _production_package(tmp_path)
    def unavailable(path):
        raise FileNotFoundError("ffprobe missing")
    monkeypatch.setattr(evaluator, "probe_video", unavailable)
    assert evaluator.main(["--workspace-dir", str(root), "--production-file", "p.production.json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["execution"]["verdict"] == "fail" and "probe_unavailable" in _package_codes(report)


def test_package_invalid_probe_measurement_never_passes(tmp_path):
    root = _production_package(tmp_path)
    for key in ("duration_s", "width", "height", "fps"):
        for value in (0, float("nan"), float("inf"), None):
            def invalid(path):
                return {**_package_probe(path), key: value}
            report = _package_report(root, invalid)
            assert "probe_failed" in _package_codes(report)
            json.dumps(report, allow_nan=False)


def test_ffprobe_uses_video_duration_rational_rate_and_local_protocols(tmp_path, monkeypatch):
    import subprocess
    from scripts import evaluate_production_package as evaluator

    def run(command, **kwargs):
        assert command[command.index("-threads") + 1] == "1"
        assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
        assert kwargs["timeout"] == 20 and kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "format": {"duration": "8"}, "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080,
                 "duration": "4", "avg_frame_rate": "24000/1001"},
                {"codec_type": "audio", "duration": "8"}]}))
    monkeypatch.setattr(evaluator.subprocess, "run", run)
    metadata = evaluator.probe_video(tmp_path / "file.mp4")
    assert metadata["duration_s"] == 4 and 23.97 < metadata["fps"] < 23.98 and metadata["has_audio"] is True


def test_ffprobe_timeout_is_not_an_execution_pass(tmp_path, monkeypatch):
    import subprocess
    from scripts import evaluate_production_package as evaluator

    root = _production_package(tmp_path)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 20)
    monkeypatch.setattr(evaluator.subprocess, "run", timeout)
    report = evaluator.evaluate(root, "p.production.json")
    assert report["execution"]["verdict"] == "fail" and "probe_failed" in _package_codes(report)


def test_real_ffprobe_rejects_placeholder_bytes_without_generating_media(tmp_path):
    import shutil
    import pytest
    from scripts.evaluate_production_package import evaluate

    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe unavailable; adapter tests still run")
    root = _production_package(tmp_path)
    report = evaluate(root, "p.production.json")
    assert report["execution"]["verdict"] == "fail" and "probe_failed" in _package_codes(report)
