"""Music-video production: every decision is made by code and tested here without models."""
from __future__ import annotations

import numpy as np
import pytest

from services import lipsync_qa, song_analysis as audio_analysis
from services.music_production import (OMARCHY_THEMES, Production, ProductionError, contact_sheet_filter, failure_reason, h3_frames_for,
                                       lyric_span, pick_song, scene_fingerprint, segments, shot_windows, status_summary,
                                       title_span, validate_spec)
from services.video2d_edit import MAX_OPERATIONS, MAX_TEXTS, Video2dEditError, edit


def test_tempo_grid_finds_132_bpm_not_a_half_or_double():
    beat, sr_hop = 60 / 132, 0.01
    times = np.arange(0, 20, sr_hop)
    onset = np.zeros_like(times)
    for k in range(int((20 - 0.5) / beat) - 1):
        onset[int(round((0.25 + k * beat) / sr_hop))] = 1.0      # kicks on every beat
        onset[int(round((0.25 + (k + 0.5) * beat) / sr_hop))] = 0.35  # weaker off-beats
    bpm, phase = audio_analysis.tempo_grid(onset, times, 20.0, low=60, high=180)
    assert abs(bpm - 132) < 0.3 and abs(phase - 0.25) < 0.02


def test_align_lines_times_written_words_and_fills_gaps():
    heard = [[1.0, 1.3, "Hocus"], [1.3, 1.6, "pocus"], [2.0, 2.4, "move"]]
    lines, recall = audio_analysis.align_lines(["Hocus pocus, make it move"], heard)
    words = lines[0]["words"]
    assert [w["w"] for w in words] == ["Hocus", "pocus,", "make", "it", "move"]
    assert words[0]["t0"] == 1.0 and words[-1]["t1"] == 2.4
    assert 1.6 <= words[2]["t0"] <= 2.0 and recall == 0.6


def test_song_verdicts_and_pick():
    assert audio_analysis.verdict(0.95, 0.001) == "ok"
    assert audio_analysis.verdict(0.6, 0.001) == "retake"
    assert audio_analysis.verdict(0.95, 0.12) == "retake"      # cut mid-phrase
    songs = {"11": {"recall": 0.9, "tail_rms": 0.001}, "22": {"recall": 0.97, "tail_rms": 0.2}, "33": {"recall": 0.7, "tail_rms": 0.0}}
    assert pick_song(songs) == "11"                            # the clearer song is cut off, so it loses


def test_lipsync_lag_and_verdict():
    t = np.arange(120)
    envelope = np.clip(np.sin(t / 3.0), 0, None)
    mouth = np.roll(envelope, 3)                               # mouth 3 frames late
    r0, r, lag = lipsync_qa.best_lag(mouth, envelope)
    assert r > 0.9 and lag == pytest.approx(3 / 24, abs=1e-3) and r0 < r
    assert lipsync_qa.verdict(0.8, r, lag) == "ok"
    assert lipsync_qa.verdict(0.8, 0.2, 0.0) == "retake"
    assert lipsync_qa.verdict(0.3, 0.9, 0.0) == "unreliable"   # face not detected: never a misleading number


def _spec(**extra):
    spec = {"title": "t", "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120}, "style": {},
            "shots": [{"key": "intro", "kind": "still", "t0": 0, "still": "k"},
                      {"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"},
                      {"key": "s1", "kind": "still", "line": 1, "still": "k"}]}
    spec.update(extra)
    return spec


def test_validate_spec_rejects_what_the_run_cannot_do():
    assert validate_spec(_spec())["title"] == "t"
    with pytest.raises(ProductionError):
        validate_spec(_spec(shots=[{"key": "x", "kind": "h3", "frame": "f"}]))
    with pytest.raises(ProductionError):
        validate_spec(_spec(shots=[{"key": "x", "kind": "still"}, {"key": "x", "kind": "still"}]))
    with pytest.raises(ProductionError):
        validate_spec(_spec(style={"image_model": ""}))


def test_image_model_is_selected_for_cast_and_frames(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    requested = []
    production.image = lambda *args: requested.append(args) or "job"
    production.wait = lambda jobs: {key: "test.png" for key in jobs}
    production.upload = lambda name: (name, "/u/" + name)
    spec = _spec(style={"image": "riso", "image_model": "qwen_image_21", "image_steps": 40},
                 cast=[{"id": "dhh", "sheet_prompt": "David caricature", "seed": 8}])
    production.cast(spec)
    production.frames(spec, [{"key": "s0", "kind": "h3", "frame": "at a keyboard", "cast": ["dhh"], "seed": 9}])
    assert requested[0][5:7] == ("qwen_image_21", 40)
    assert requested[1][5:7] == ("qwen_image_21", 40)
    assert requested[1][2] == ["/u/test.png"]


def test_qwen_image_request_keeps_model_and_reference(tmp_path):
    calls = []
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, args: calls.append((tool, args)) or {"receipt": {"result": {"job_id": "j"}}})
    assert production.image("frame", "David at a keyboard", ["/api/v1/uploads/reference.png"], "1280x704", 17,
                            "qwen_image_21", 40) == "j"
    tool, request = calls[0]
    params = request["input"]["params"]
    assert tool == "generation.image"
    assert params["model_type"] == "qwen_image_21" and params["num_inference_steps"] == 40
    assert params["image_refs"] == ["/api/v1/uploads/reference.png"]


def test_preview_produces_three_urls_without_a_song(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.image = lambda *args: "job"
    production.wait = lambda jobs: {key: f"{key}.png" for key in jobs}
    production.upload = lambda name: (name, "/u/" + name)
    production.preview({"prompts": ["desktop one", "desktop two", "desktop three"]})
    summary = status_summary(production.state, "ws")
    assert summary["status"] == "preview_completed"
    assert summary["preview_frames"] == {"0": "/u/0.png", "1": "/u/1.png", "2": "/u/2.png"}
    assert summary["song"] is None


def test_frames_stage_stops_before_clips(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    called = []
    for name in ("song", "analyze", "cast", "frames", "clips"):
        setattr(production, name, lambda *args, name=name: called.append(name))
    production.score = lambda: {"duration": 30, "lines": []}
    production.run(_spec(), through="frames")
    assert called == ["song", "analyze", "cast", "frames"]
    assert production.state["status"] == "frames_ready"


def test_native_riso_titles_graphic_footer_and_mono_lyrics(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: edit(arguments))
    shot = {"key": "zine", "kind": "still", "still": "/examples/hero.png",
            "title": {"template": "ransom", "fields": {"line": "BUILD THE DESKTOP"}},
            "graphic": {"id": "shatter", "params": {"pieces": 12}}}
    style = {"lyric_template": "dymo", "lyric_style": {"font": "mono", "color": "#A9B1D6"},
             "title_style": {"trap": True}, "footer": "Fan-made parody, not affiliated with DHH, 37signals or Omarchy",
             "finish": {"preset": "risoPress"}}
    ops = production.scene_ops(shot, 0, 4, 4, {"lines": [{"t0": 1, "t1": 3, "text": "Love the machine"}]}, {}, style, {})
    doc = {"version": 1, "name": "zine", "width": 1920, "height": 1080, "fps": 24, "duration": 4, "layers": [], "texts": []}
    built = production.edit(doc, ops)
    texts = built["texts"]
    assert built["finish"]["riso"]["inks"]
    assert any(t.get("graphic", {}).get("id") == "shatter" and t.get("trap") for t in texts)
    assert any(t["id"] == "footer-social" and t["y"] == 96 for t in texts)
    assert any(t["text"] == "LOVE THE MACHINE" and t["font"] == "mono" for t in texts)


def test_clip_keeps_its_own_camera_and_title_can_use_shot_palette(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    shot = {"key": "hero", "kind": "h3", "title": {"template": "title-card", "fields": {"title": "OPEN"},
            "style": {"box": {"kind": "plate", "color": "#122337", "opacity": 1, "padding": 0}},
            "cues": {"title": {"color": "#f5d270"}}}}
    clips = {"hero": {"url": "/api/v1/file/hero.mp4", "qa": {"verdict": "ok"}}}
    ops = production.scene_ops(shot, 0, 4, 4, {"lines": []}, clips, {"title_style": {"font": "mono"}}, {})
    assert ops[0]["preset"] == "camera-locked"
    assert ops[1]["patch"]["animation"]["end"]["scale"] == 1.0
    title = next(op for op in ops if op.get("op") == "update_text" and op.get("id") == "tt-title")
    assert title["patch"]["font"] == "mono"
    assert title["patch"]["color"] == "#f5d270"
    assert title["patch"]["box"]["color"] == "#122337"


def test_windows_segments_and_instrumental_fill():
    score = {"duration": 30.0, "beat": 0.5, "lines": [{"t0": 1.0, "t1": 3.0}, {"t0": 20.0, "t1": 22.0}]}
    windows = shot_windows(_spec(), score)
    assert [(w["key"], w["t0"]) for w in windows] == [("intro", 0.0), ("s0", 0.75), ("s1", 19.75)]
    assert h3_frames_for(windows[1]["t1"] - windows[1]["t0"]) == 124
    fill = [{"kind": "still", "still": "k"}]
    segs = segments(windows, score, lambda key: key == "s0", fill)
    keys = [s["key"] for s, _, _ in segs]
    assert keys[:2] == ["intro", "s0"] and keys[2].startswith("s0_fill") and keys[-1] == "s1"
    assert all(b - a <= 4.0 + 1e-6 for s, a, b in segs if s["key"].startswith("s0_fill"))  # two bars max
    assert segs[-1][2] == 30.0 and all(abs(segs[i][2] - segs[i + 1][1]) < 1e-6 for i in range(len(segs) - 1))


def test_status_summary_is_short():
    state = {"status": "running", "song": {"file": "s.wav"}, "clips": {"a": {"qa": {"verdict": "ok"}}}, "scenes": {"a": {"file": "x.mp4"}},
             "log": [f"line {i}" for i in range(30)], "final": "v.mp4"}
    summary = status_summary(state, "ws")
    assert summary["clips"] == {"a": "ok"} and summary["video"] == "/api/v1/file/v.mp4?workspace=ws" and len(summary["log"]) == 8


def test_video_layer_can_skip_the_head_of_its_clip_for_the_whole_scene():
    doc = {"version": 1, "name": "p", "width": 1920, "height": 1080, "fps": 24, "duration": 4, "layers": [], "texts": []}
    ops = [{"op": "add_layer", "id": "v", "source": "/examples/clip.mp4", "type": "video"},
           {"op": "update_layer", "id": "v", "patch": {"animation": {"trimStart": 0.5, "duration": 4.5}}}]
    layer = edit({"version": 1, "input": {"document": doc, "operations": ops, "full": True}})["result"]["document"]["layers"][0]
    assert layer["animation"]["trimStart"] == 0.5 and layer["animation"]["duration"] == 4.5
    too_long = [ops[0], {"op": "update_layer", "id": "v", "patch": {"animation": {"duration": 4.5}}}]
    with pytest.raises(Exception):
        edit({"version": 1, "input": {"document": doc, "operations": too_long, "full": True}})


def test_wait_keeps_why_a_job_gave_nothing():
    replies = {"a": [{"status": "running"}, {"status": "completed", "output_files": ["a.mp4"]}],
               "b": [{"status": "failed", "error": "CUDA error:\n out of memory", "oom_info": None}],
               "c": [{"error": {"content": "Job not found"}}] * 5}
    production = Production.__new__(Production)
    production.mcp = lambda tool, arguments: replies[arguments["job_id"]].pop(0)
    names = production.wait({"a": "a", "b": "b", "c": "c", "d": None}, poll=0)
    assert names == {"a": "a.mp4", "b": None, "c": None, "d": None}
    assert production.failures["b"] == "CUDA error: out of memory" and production.failures["d"] == "not admitted"
    assert failure_reason({"status": "failed", "oom_info": {"frames": 192}}) == "out of GPU memory"


def test_failed_takes_keep_their_reason_and_get_new_seeds(tmp_path, monkeypatch):
    (tmp_path / "s.score.json").write_text('{"lines": [], "vocals_file": "v.wav"}')
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"score": "s.score.json", "frames": {"a": "f.png"}, "log": ["clip a take 1: no output"]}
    production.upload = lambda name: (name, "/u/" + name)
    seeds, outputs = [], iter([None, "a2.mp4"])
    production.clip_job = lambda spec, w, seed, take: seeds.append(seed) or f"job{seed}"

    def wait(jobs):
        production.failures = {"a": "out of GPU memory"}
        return {key: next(outputs) for key in jobs}
    production.wait = wait
    monkeypatch.setattr("services.music_production.lipsync_qa.measure", lambda *a: {"verdict": "ok", "best_r": 0.5})
    window = {"key": "a", "kind": "h3", "i": 0, "t0": 1.0, "t1": 4.0, "sing": True}
    production.clips({"max_takes": 3}, [window], pause=0)
    assert seeds == [7001, 7002]                     # the logged take 1 is not reshot with its old seed
    assert production.state["clips"]["a"]["file"] == "a2.mp4" and production.state["clip_failures"] == {}
    assert "clip a take 2: failed (out of GPU memory)" in production.state["log"][-2]
    summary = status_summary(production.state | {"clip_failures": {"b": "out of GPU memory"}}, "ws")
    assert summary["clips"] == {"b": "failed", "a": "ok"} and summary["failures"] == {"b": "out of GPU memory"}


def test_title_and_lyric_spans_fit_the_scene():
    assert title_span(0.15) == (0.0, 0.15)
    assert title_span(4.0) == (0.1, 3.8)
    assert title_span(0.0) is None
    assert lyric_span({"t0": 1.0, "t1": 2.0, "text": "x"}, 1.0, 1.2, 0.2) == (0.0, 0.2)
    assert lyric_span({"t0": 5.0, "t1": 6.0, "text": "x"}, 0.0, 1.0, 1.0) is None


def test_a_long_lyric_scene_is_edited_in_batches(tmp_path):
    """One still that covers a whole verse used to send 40+ add_title ops and fail too_many_operations
    after song/clips had already burned the GPU. Edit now applies 32-op chunks."""
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: edit(arguments))
    lines = [{"t0": float(i), "t1": i + 0.8, "text": f"line {i}"} for i in range(40)]
    shot = {"key": "verse", "kind": "still", "still": "/examples/hero.png",
            "title": {"template": "lower-third-date", "fields": {"date": "VERSE", "caption": "one"}}}
    ops = production.scene_ops(shot, 0.0, 45.0, 45.0, {"lines": lines}, {}, {}, {})
    assert sum(1 for op in ops if op["op"] == "add_title") == 41
    assert len(ops) > MAX_OPERATIONS
    doc = {"version": 1, "name": "verse", "width": 1920, "height": 1080, "fps": 24, "duration": 45, "layers": [], "texts": []}
    with pytest.raises(Video2dEditError) as error:
        edit({"version": 1, "input": {"document": doc, "operations": ops, "full": True}})
    assert error.value.code == "too_many_operations"
    built = production.edit(doc, ops)
    texts = built.get("texts") or []
    assert built["layers"][0]["source"] == "/examples/hero.png"
    assert any(item["id"] == "tt-date" for item in texts)
    assert sum(1 for item in texts if str(item["id"]).startswith("ly")) == 40


def test_short_titled_scene_does_not_send_a_negative_title(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: edit(arguments))
    shot = {"key": "intro", "kind": "still", "still": "/examples/hero.png",
            "title": {"template": "end-card", "fields": {"title": "Go", "cta": "now"}}}
    ops = production.scene_ops(shot, 0.0, 0.15, 0.15, {"lines": []}, {}, {}, {})
    title = next(op for op in ops if op["op"] == "add_title")
    assert title["start"] == 0.0 and title["duration"] == 0.15
    doc = {"version": 1, "name": "intro", "width": 1920, "height": 1080, "fps": 24, "duration": 0.15, "layers": [], "texts": []}
    built = production.edit(doc, ops)
    assert [item["id"] for item in built["texts"]] == ["tt-end", "tt-cta"]


def test_lyric_cues_stop_at_the_text_cap(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    lines = [{"t0": float(i), "t1": i + 0.5, "text": f"line {i}"} for i in range(MAX_TEXTS + 10)]
    ops = production.scene_ops({"key": "long", "kind": "still", "still": "/examples/hero.png"}, 0.0, 80.0, 80.0,
                               {"lines": lines}, {}, {}, {})
    titles = [op for op in ops if op["op"] == "add_title"]
    assert len(titles) == MAX_TEXTS
    assert any("dropped lyrics" in line for line in production.state.get("log") or [])


def test_a_new_clip_reexports_only_its_scene(tmp_path):
    (tmp_path / "s.score.json").write_text('{"duration": 6.0, "beat": 0.5, "lines": []}')
    exported = []

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": "c1"}}
        return {"receipt": {"artifacts": [{"name": "new-scene.mp4"}]}}
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    windows = [{"key": "a", "kind": "h3", "i": 0, "t0": 0.0, "t1": 3.0}, {"key": "b", "kind": "still", "still": "/k.png", "i": 1, "t0": 3.0, "t1": 7.0}]
    prior_b = scene_fingerprint(windows[1], {}, {}, {"duration": 6.0, "beat": 0.5, "lines": []}, 3.0, 6.0)
    production.state = {"score": "s.score.json", "clips": {"a": {"file": "new.mp4", "url": "/u/new.mp4"}},
                        "scenes": {"a": {"dur": 3.0, "file": "old-a.mp4", "clip": "old.mp4"},
                                   "b": {"dur": 3.0, "file": "b.mp4", "clip": None, "fingerprint": prior_b}}}
    production.scenes({"shots": []}, windows)
    assert exported == ["a"]
    assert production.state["scenes"]["a"]["file"] == "new-scene.mp4"
    assert production.state["scenes"]["b"]["file"] == "b.mp4"


def test_changed_style_reexports_an_existing_scene(tmp_path):
    score = {"duration": 5.0, "beat": 0.5, "lines": []}
    (tmp_path / "s.score.json").write_text('{"duration": 5.0, "beat": 0.5, "lines": []}')
    shot = {"key": "cover", "kind": "still", "still": "/cover.png", "i": 0, "t0": 0.0, "t1": 4.0}
    exported = []

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": "new"}}
        return {"receipt": {"artifacts": [{"name": "new-cover.mp4"}]}}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    production.state = {"score": "s.score.json", "scenes": {"cover": {"dur": 5.0, "file": "old-cover.mp4",
                        "clip": None, "fingerprint": scene_fingerprint(shot, {"lyric_style": {"y": 78}}, {}, score, 0.0, 5.0)}}}
    production.scenes({"style": {"lyric_style": {"y": 86}}}, [shot])
    assert exported == ["cover"]
    assert production.state["scenes"]["cover"]["file"] == "new-cover.mp4"


def test_a_shifted_fill_pad_is_not_reused(tmp_path):
    """A 2-bar fill keeps the same duration when its h3 shot slides, but lyrics are
    scene-relative. Reusing the old pad would keep the previous window's captions."""
    score = {"duration": 50.0, "beat": 0.5, "lines": [
        {"t0": 12.0, "t1": 14.0, "text": "old pad lyrics"},
        {"t0": 16.0, "t1": 18.0, "text": "new pad lyrics"},
    ]}
    (tmp_path / "s.score.json").write_text(
        '{"duration": 50.0, "beat": 0.5, "lines": ['
        '{"t0": 12.0, "t1": 14.0, "text": "old pad lyrics"},'
        '{"t0": 16.0, "t1": 18.0, "text": "new pad lyrics"}]}'
    )
    fill = [{"kind": "still", "still": "/art.png"}]
    before = [
        {"key": "intro", "kind": "still", "still": "/k.png", "i": 0, "t0": 0.0, "t1": 4.0},
        {"key": "verse", "kind": "h3", "i": 1, "t0": 8.0, "t1": 12.0, "frame": "f", "action": "a"},
        {"key": "outro", "kind": "still", "still": "/k.png", "i": 2, "t0": 30.0, "t1": 34.0},
    ]
    after = [
        {**before[0]},
        {**before[1], "t0": 10.0, "t1": 14.0},
        {**before[2]},
    ]
    old_fill0, old_a, old_b = next(
        (shot, a, b) for shot, a, b in segments(before, score, lambda key: key == "verse", fill)
        if shot["key"] == "verse_fill0"
    )
    new_fill0, new_a, new_b = next(
        (shot, a, b) for shot, a, b in segments(after, score, lambda key: key == "verse", fill)
        if shot["key"] == "verse_fill0"
    )
    assert old_fill0 == new_fill0 and round(old_b - old_a, 3) == round(new_b - new_a, 3)
    assert (round(old_a, 3), round(old_b, 3)) != (round(new_a, 3), round(new_b, 3))
    exported = []

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": "c"}}
        return {"receipt": {"artifacts": [{"name": "new-fill0.mp4"}]}}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    production.state = {"score": "s.score.json", "clips": {"verse": {"file": "verse.mp4", "url": "/u/verse.mp4"}},
                        "scenes": {"verse_fill0": {"dur": round(old_b - old_a, 3), "file": "old-fill0.mp4",
                                   "clip": None, "fingerprint": scene_fingerprint(old_fill0, {}, {}, score, old_a, old_b)}}}
    production.scenes({"style": {}, "fill": fill}, after)
    assert "verse_fill0" in exported
    assert production.state["scenes"]["verse_fill0"]["file"] == "new-fill0.mp4"


def test_contact_sheet_covers_a_long_song():
    frame_filter = contact_sheet_filter(76)
    rate = float(frame_filter.split(",", 1)[0].split("=", 1)[1])
    assert "tile=6x4" in frame_filter
    assert 23 / rate > 70  # the last cell reaches the ending of a 76-second video


def test_a_screen_shot_paints_the_desktop_and_the_theme_styles_the_lyrics(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: edit(arguments))
    style = {"theme": "gruvbox", "lyric_template": "ransom"}
    shot = {"key": "desk", "kind": "screen", "desktop": {"layout": "quad", "workspace": 2, "switch": "left"}}
    lines = [{"t0": 0.5, "t1": 2.0, "text": "keyboard first"}]
    ops = production.scene_ops(shot, 0.0, 4.0, 4.0, {"lines": lines}, {}, style, {})
    doc = {"version": 1, "name": "desk", "width": 1920, "height": 1080, "fps": 24, "duration": 4, "layers": [], "texts": []}
    built = production.edit(doc, ops)
    assert built["layers"] == []
    desktop = next(cue for cue in built["texts"] if cue["id"].startswith("desk"))
    assert desktop["graphic"] == {"id": "tiling", "params": {"theme": "gruvbox", "layout": "quad", "apps": "mixed", "focus": 0, "workspace": 2, "switch": "left"}}
    words = [cue for cue in built["texts"] if cue["id"].startswith("ly")]
    assert [cue["text"] for cue in words] == ["KEYBOARD", "FIRST"]
    assert all(cue["font"] == "mono" and cue["color"] == OMARCHY_THEMES["gruvbox"]["fg"] for cue in words)


def test_desktop_rejects_unknown_theme_or_layout():
    doc = {"version": 1, "name": "d", "width": 1920, "height": 1080, "fps": 24, "duration": 4, "layers": [], "texts": []}
    for fields in ({"theme": "vaporwave"}, {"layout": "grid"}, {"workspace": "12"}):
        with pytest.raises(Video2dEditError):
            edit({"version": 1, "input": {"document": doc, "operations": [{"op": "add_title", "template": "desktop", "fields": fields, "start": 0, "duration": 2}]}})
    assert validate_spec({"title": "t", "song": {"lyrics": "a", "caption": "b", "duration": 10, "bpm": 100}, "style": {}, "shots": [{"key": "s", "kind": "screen"}]})


def test_wait_marks_a_job_the_queue_forgot_as_lost(tmp_path, monkeypatch):
    monkeypatch.setattr("services.music_production.time.sleep", lambda _s: None)
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda tool, arguments: {})
    assert production.wait({"a": "job-a"}, poll=0) == {"a": None}
    assert production.lost == {"a"}
    production.mcp = lambda tool, arguments: {"status": "failed", "error": "boom"}
    assert production.wait({"a": "job-a"}, poll=0) == {"a": None}
    assert production.lost == set() and production.failures["a"] == "boom"


def _image_production(tmp_path, outcomes):
    """Production whose image jobs finish or fail as scripted; records every generation.image call."""
    calls = []

    def mcp(tool, arguments):
        if tool == "generation.image":
            calls.append(arguments)
            return {"receipt": {"result": {"job_id": f"job{len(calls)}"}}}
        return {}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    scripted = iter(outcomes)

    def wait(jobs, poll=6):
        production.failures = {}
        out = {}
        for key in jobs:
            name, reason = next(scripted)
            out[key] = name
            if not name:
                production.failures[key] = reason
        return out

    production.wait = wait
    production.state["cast"] = {"hero": "/api/v1/uploads/hero.png", "trio": "/api/v1/uploads/trio.png"}
    return production, calls


def test_a_missing_frame_is_asked_for_again_with_a_new_job_and_a_smaller_picture_after_oom(tmp_path):
    production, calls = _image_production(tmp_path, [(None, "out of GPU memory"), ("f.png", None)])
    spec = {"style": {"image": "look"}, "cast": [{"id": "hero", "sheet_prompt": "x"}]}
    production.frames(spec, [{"key": "a", "kind": "h3", "frame": "wide shot", "cast": ["hero"]}])
    assert production.state["frames"] == {"a": "f.png"} and production.state["frame_failures"] == {}
    first, second = (call["input"]["params"] for call in calls)
    assert first["resolution"] == "1280x704" and second["resolution"] == "1152x640"
    assert calls[0]["intent_id"] != calls[1]["intent_id"]                 # the journal would answer a repeated intent with the failed job
    assert first["seed"] != second["seed"]


def test_a_resumed_run_does_not_reuse_the_failed_intent_of_the_earlier_run(tmp_path):
    production, calls = _image_production(tmp_path, [("f.png", None)])
    production.state["log"] = ["frames: 4"]
    production.state["frame_failures"] = {"a": "out of GPU memory"}
    production.frames({"style": {}, "cast": []}, [{"key": "a", "kind": "h3", "frame": "wide shot"}])
    assert calls[0]["intent_id"].endswith("-r1")


def test_frames_that_never_arrive_stop_the_run_with_their_reasons(tmp_path):
    production, calls = _image_production(tmp_path, [(None, "out of GPU memory")] * 4)
    (tmp_path / "s.score.json").write_text('{"duration": 20, "beat": 0.5, "lines": [{"t0": 1.0, "t1": 3.0, "text": "a"}]}')
    production.state.update(song={"file": "s.wav"}, score="s.score.json")
    production.song = production.analyze = production.cast = lambda spec: None
    production.run({"title": "t", "song": {"lyrics": "a", "caption": "b", "duration": 20, "bpm": 120}, "style": {"image_model": "qwen_image_21"},
                    "shots": [{"key": "a", "kind": "h3", "line": 0, "frame": "f", "action": "a"}]})
    assert production.state["status"] == "failed"
    assert production.state["error"].startswith("ProductionError: no start frame for a (out of GPU memory)") or "frames_incomplete" in production.state["error"] or "no start frame for a" in production.state["error"]
    assert status_summary(production.state, "ws")["frame_failures"] == {"a": "out of GPU memory"}


def test_the_frame_prompt_says_how_many_subjects_the_references_stand_for(tmp_path):
    production, _calls = _image_production(tmp_path, [])
    spec = {"style": {"image": "look"}, "cast": [{"id": "hero", "sheet_prompt": "x"}, {"id": "trio", "sheet_prompt": "y", "count": 3}]}
    assert production.frame_prompt(spec, {"frame": "solo", "cast": ["hero"]}) == "look solo Exactly 1 distinct subject in the frame, no duplicated characters."
    assert "Exactly 3 distinct subjects" in production.frame_prompt(spec, {"frame": "group", "cast": ["trio"]})
    assert production.frame_prompt(spec, {"frame": "no cast"}) == "look no cast"
