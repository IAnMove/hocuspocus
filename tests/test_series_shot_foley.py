"""Shot foley: MMAudio sound made from the shot's own exported picture, mixed under the take before it is imported."""
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from routers.image_generation_commands import _generation_arguments
from services.series_guide import audio_files, compact_episode
from services.series_library import SHOT_EDITOR_FIELDS, normalize_series_project
from services.series_native_render import public_job
from services.series_script import ScriptError, apply_script
from services.series_shot_foley import (
    NEGATIVE_PROMPT,
    extract_audio,
    foley_seed,
    has_audio,
    mix_under,
    normalize_foley,
)
from services.series_take_inputs import render_inputs
from services.studio_sfx_spec import freeze_studio_sfx_spec
from tests.test_series_native_render import Tools, finished, library, service
from tests.test_series_script_produce import FILES, SCRIPT, Series
from tests.test_series_script_produce import KITS as SCRIPT_KITS

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
AIRSHIP = {"prompt": "wooden airship creaking, wind, cannon shots", "volume": 0.5}


class FoleyTools(Tools):
    """The series tools with real export files and an MMAudio ``generation.sfx`` that writes its clip.

    ``sfx``: ``ok``; ``missing`` (MMAudio not installed); ``failed`` (the job fails); ``slow`` (never finishes);
    ``hold`` (the first wait cancels the render, as a user would while MMAudio runs)."""

    def __init__(self, tmp_path, sfx="ok"):
        super().__init__(tmp_path)
        self.sfx, self.order, self.sfx_jobs, self.render = sfx, [], {}, None

    def __call__(self, tool, arguments):
        data = arguments.get("input") or {}
        if tool == "generation.sfx":
            self.calls.append((tool, arguments))
            self.order.append(tool)
            if self.sfx == "missing":
                return {"_is_error": True, "error": {"code": "model_unavailable", "status": 409,
                                                     "message": "Required MMAudio files are not installed; install them before submitting"}}
            intent = arguments["intent_id"]
            if intent not in self.sfx_jobs:  # a known intent replays its admission, like the server
                self.sfx_jobs[intent] = f"sfx-{len(self.sfx_jobs) + 1}"
                (self.root / f"{data['output_name']}.mp4").write_bytes(b"picture with foley")
                (self.root / f"{data['output_name']}.meta.json").write_text("{}")
            return {"receipt": {"result": {"job_id": self.sfx_jobs[intent]}}}
        if tool == "jobs.wait" and data["job_id"].startswith("sfx-"):
            self.calls.append((tool, arguments))
            if self.sfx == "failed":
                return {"_is_error": True, "error": {"job_id": data["job_id"], "status": "failed", "error": "CUDA out of memory"}}
            if self.sfx == "slow":
                self.now[0] += data["timeout_s"]
                return {"job_id": data["job_id"], "status": "running", "timed_out": True}
            if self.sfx == "hold":
                self.sfx = "ok"
                intent = next(key for key, value in self.sfx_jobs.items() if value == data["job_id"])
                self.render.cancel("cast", intent.split("-foley-")[0])
                return {"job_id": data["job_id"], "status": "running", "timed_out": True}
            intent = next(key for key, value in self.sfx_jobs.items() if value == data["job_id"])
            name = next(args["input"]["output_name"] for name, args in self.calls if name == "generation.sfx" and args["intent_id"] == intent)
            return {"job_id": data["job_id"], "status": "completed", "outputs": [{"path": f"/ws/cast/{name}.mp4"}]}
        result = super().__call__(tool, arguments)
        if tool == "scenes.video2d.export.receipt":
            for artifact in result["result"]["receipt"]["artifacts"]:
                # The same shot and scene give the same picture, whichever job exported it.
                shot, digest = data["intent_id"].split("-")[-3:-1]
                (self.root / artifact["name"]).write_bytes(f"picture of {shot} {digest}".encode())
        self.order.append(f"import {data['owner_id']}" if tool == "series.asset.import" else tool)
        return result


def project(**foley):
    data = library()
    for shot in data["seriesById"]["uv"]["episodesById"]["ep1"]["shots"]:
        if shot["id"] in foley:
            shot["foley"] = foley[shot["id"]]
    return data


def foley_render(tmp_path, tools, data, mixes, **deps):
    def extract(source, target):
        Path(target).write_bytes(b"sound of " + Path(source).read_bytes())

    def mix(take, foley, target, gain):
        tools.order.append("mix")
        mixes.append((os.path.basename(take), os.path.basename(foley), os.path.basename(target), gain))
        Path(target).write_bytes(Path(take).read_bytes() + b" + " + Path(foley).read_bytes())

    tools.now = [0.0]
    render = service(tmp_path, tools, [], extract_audio=extract, mix_foley=mix, clock=lambda: tools.now[0],
                     loudness_gain=lambda path: 0.5 if os.path.basename(path).startswith("foley-") else 1.0, **deps)
    render.deps.read_library = lambda _ws: data
    tools.render = render
    return render


def imports(tools):
    return {args["input"]["owner_id"]: args["input"] for name, args in tools.calls if name == "series.asset.import"}


def test_foley_is_generated_from_the_export_and_mixed_under_the_take_before_import(tmp_path):
    tools, mixes = FoleyTools(tmp_path), []
    render = foley_render(tmp_path, tools, project(s03=AIRSHIP), mixes)
    done = finished(render, render.start("cast", "uv", "ep1", approve=True)["jobId"], tmp_path)
    assert done["status"] == "completed", done
    plain, airship = done["items"]
    [(_, sfx)] = [(name, args) for name, args in tools.calls if name == "generation.sfx"]
    export = airship["foley"]["source"]
    assert export.endswith(".mp4") and "-s03-" in export and (tmp_path / export).is_file()
    assert sfx["version"] == 2 and sfx["intent_id"].startswith(done["jobId"]) and sfx["input"]["workspace"] == "cast"
    assert sfx["input"]["params"] == {
        "model_type": "mmaudio_v2", "prompt": AIRSHIP["prompt"], "MMAudio_neg_prompt": NEGATIVE_PROMPT,
        "duration_seconds": airship["duration"], "seed": foley_seed("s03", AIRSHIP["prompt"]),
        "video_guide": f"/api/v1/file/{export}?workspace=cast"}
    # The request is what the generation tool and its closed v2 schema take.
    _generation_arguments(sfx)
    frozen = freeze_studio_sfx_spec({**{key: sfx[key] for key in ("version", "intent_id")}, "operation": "generation.sfx",
                                     "input": {"workspace": "cast", "params": sfx["input"]["params"]}})
    assert frozen["effective"]["input"]["params"]["duration_source"] == "video"
    sound, take = airship["foley"]["file"], airship["video"]
    assert mixes == [(export, sound, take, 0.25)], "0.5 of the dialogue level for a sound 6 dB louder than dialogue"
    assert tools.order.index("generation.sfx") < tools.order.index("mix") < tools.order.index("import s03")
    taken = imports(tools)
    assert taken["s03"]["file"] == take and taken["s03"]["metadata"]["foley"] == {**AIRSHIP, "file": sound}
    assert taken["s01"]["file"] == plain["video"] and "foley" not in taken["s01"]["metadata"], "a shot without foley is as before"
    assert (tmp_path / sound).read_bytes() == b"sound of picture with foley"
    assert not list(tmp_path.glob("*-raw*")), "the generated clip and its sidecar are intermediates"
    assert airship["approved"] and "warning" not in airship and "warning" not in plain


@pytest.mark.parametrize("mode,reason", [
    ("missing", "generation.sfx: Required MMAudio files are not installed"),
    ("failed", "Foley failed: CUDA out of memory"),
    ("slow", "Foley was still running when its time ran out"),
])
def test_foley_that_cannot_be_made_leaves_the_take_as_rendered_with_a_warning(tmp_path, mode, reason):
    tools, mixes = FoleyTools(tmp_path, sfx=mode), []
    render = foley_render(tmp_path, tools, project(s03=AIRSHIP), mixes, foley_wait_seconds=600)
    done = public_job(finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path))
    assert done["status"] == "completed", done
    [item] = done["items"]
    assert item["status"] == "done" and item["warning"].startswith("Foley left out: ") and reason in item["warning"]
    assert "foley" not in item and not mixes
    assert imports(tools)["s03"]["file"] == item["video"] and "-s03-" in item["video"], "the take is the export itself"
    waits = [args["input"]["timeout_s"] for name, args in tools.calls if name == "jobs.wait" and args["input"]["job_id"].startswith("sfx-")]
    if mode == "slow":
        assert waits == [120, 120, 120, 120, 120], "the wait gives up at foley_wait_seconds"


def test_a_cancelled_foley_resumes_at_its_stage_and_the_same_picture_reuses_it(tmp_path):
    tools, mixes = FoleyTools(tmp_path, sfx="hold"), []
    data = project(s03=AIRSHIP)
    render = foley_render(tmp_path, tools, data, mixes)
    job = render.start("cast", "uv", "ep1", shot_ids=["s03"])
    stopped = finished(render, job["jobId"], tmp_path)
    assert stopped["status"] == "cancelled" and stopped["items"][0]["stage"] == "foley"
    counts = {name: [tool for tool, _ in tools.calls].count(name) for name in ("generation.speech", "scenes.video2d.export")}
    render.resume("cast", job["jobId"])
    done = finished(render, job["jobId"], tmp_path)
    assert done["status"] == "completed" and done["items"][0]["foley"]["gain"] == 0.25
    assert {name: [tool for tool, _ in tools.calls].count(name) for name in counts} == counts, "voices and export are kept"
    intents = [args["intent_id"] for name, args in tools.calls if name == "generation.sfx"]
    assert len(intents) == 2 and intents[0] == intents[1] and len(tools.sfx_jobs) == 1, "the resume replays the same generation"

    # A new render of the same picture reuses the mixed take; a new volume reuses the generated sound.
    again = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)["items"][0]
    assert again["foley"]["reused"] and again["video"] == done["items"][0]["video"] and len(mixes) == 1
    assert again["foley"]["source"] != done["items"][0]["foley"]["source"], "another export file, the same picture"
    data["seriesById"]["uv"]["episodesById"]["ep1"]["shots"][2]["foley"] = {**AIRSHIP, "volume": 1.0}
    louder = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)["items"][0]
    assert len(intents) == len([1 for name, _ in tools.calls if name == "generation.sfx"]), "no new generation"
    assert mixes[-1][1:] == (done["items"][0]["foley"]["file"], louder["video"], 0.5) and louder["video"] != again["video"]


SERIES = {"id": "show", "spokenLanguage": "English", "locations": [{"id": "sky", "name": "Sky"}],
          "characters": [{"id": "ana", "voiceProfile": {"characterKitRef": {"id": "kit-ana", "workspace": "ws"}}}]}
SHOT = {"id": "s7", "order": 7, "locationId": "sky", "productionMethod": "animation_3d", "visibleCharacterIds": ["ana"],
        "dialogueBeats": [{"id": "s7_b0", "characterId": "ana", "text": "Hold on!"}],
        "scene3d": {"template": "user-airship", "cast": [{"characterId": "ana", "objectId": "ana"}], "quality": "draft"}}
KITS = {"kit-ana": {"id": "kit-ana", "voice": {"model": "qwen3_tts_customvoice", "voiceId": "ryan"}}}


def test_a_shot_without_foley_keeps_the_digest_of_its_takes_and_foley_changes_it():
    # The digest takes rendered before foley existed carry: they stay up to date.
    assert render_inputs(SERIES, SHOT, KITS) == "317759c6a97468d9"
    assert render_inputs(SERIES, {**SHOT, "foley": None}, KITS) == "317759c6a97468d9"
    with_foley = render_inputs(SERIES, {**SHOT, "foley": AIRSHIP}, KITS)
    assert with_foley != "317759c6a97468d9", "adding foley renders the shot again"
    assert render_inputs(SERIES, {**SHOT, "foley": {**AIRSHIP, "volume": 0.8}}, KITS) != with_foley
    assert render_inputs(SERIES, {**SHOT, "foley": {**AIRSHIP, "prompt": "sword clash"}}, KITS) != with_foley


def test_foley_is_checked_where_shots_are_saved_and_scripted():
    assert normalize_foley(None) is None
    assert normalize_foley({"prompt": "  creak  ", "extra": 1}) == {"prompt": "creak", "volume": 0.5}
    for bad, message in [("creak", "object"), ({}, "prompt"), ({"prompt": "  "}, "prompt"), ({"prompt": "x" * 501}, "500"),
                         ({"prompt": "x", "volume": 0}, "volume"), ({"prompt": "x", "volume": 2.5}, "volume"),
                         ({"prompt": "x", "volume": True}, "volume"), ({"prompt": "x", "volume": "0.5"}, "volume")]:
        with pytest.raises(ValueError, match=message):
            normalize_foley(bad)

    def saved(**shot):
        episode = {"id": "ep1", "script": [{"id": "sc1"}], "shots": [{"id": "s1", "sceneId": "sc1", "productionMethod": "animation_3d", **shot}]}
        return normalize_series_project({"id": "show", "episodesById": {"ep1": episode}}, "show", "default")["episodesById"]["ep1"]["shots"][0]

    assert saved(foley={"prompt": "creak", "volume": 1})["foley"] == {"prompt": "creak", "volume": 1.0}
    assert "foley" not in saved() and "foley" not in saved(foley=None)
    with pytest.raises(ValueError, match="shot.foley.volume"):
        saved(foley={"prompt": "creak", "volume": 3})
    assert "foley" in SHOT_EDITOR_FIELDS, "an episode update keeps it"

    tools = Series()
    script = {**SCRIPT, "shots": [*SCRIPT["shots"][:2], {**SCRIPT["shots"][2], "foley": {"prompt": "rover wheels on gravel"}}]}
    apply_script(tools, tools.read, SCRIPT_KITS, FILES, "cast", script)
    shots = tools.calls[1][1]["episode"]["shots"]
    assert shots[2]["foley"] == {"prompt": "rover wheels on gravel", "volume": 0.5} and "foley" not in shots[1]
    broken, fresh = {**SCRIPT, "shots": [*SCRIPT["shots"][:2], {**SCRIPT["shots"][2], "foley": {"volume": 0.4}}]}, Series()
    with pytest.raises(ScriptError, match=r"shot 2 \(e2s02\): shot.foley.prompt"):
        apply_script(fresh, fresh.read, SCRIPT_KITS, FILES, "cast", broken, check_only=True)

    compact = compact_episode({"assets": {}}, {"id": "ep1", "shots": [{"id": "s1", "foley": AIRSHIP}]})
    assert compact["shots"][0]["foley"] == AIRSHIP, "an agent sees it with the shot"
    assert audio_files(["foley-ep1-s03-0123456789ab.wav", "sfx-door.wav"])["other"] == [], "generated foley is not a bible sound"


def _media(path: Path, seconds: float, tone: float | None, amplitude: float = 0.25) -> None:
    """A test card, with a stereo sine of ``tone`` Hz, or without any audio stream."""
    sound = ["-f", "lavfi", "-i", f"aevalsrc={amplitude}*sin(2*PI*{tone}*t)|{amplitude}*sin(2*PI*{tone}*t):s=48000"] if tone else []
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24", *sound,
               "-t", f"{seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               *(["-c:a", "aac"] if tone else ["-an"]), str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr[-400:]


def _samples(path: Path) -> np.ndarray:
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-af", "pan=mono|c0=c0", "-ar", "48000", "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, timeout=60, check=True).stdout, dtype=np.float32)


def _level(samples: np.ndarray, hertz: float) -> float:
    """Peak spectrum magnitude around ``hertz`` between 0.5 and 1.5 s."""
    window = samples[24000:72000] * np.hanning(48000)
    spectrum = np.abs(np.fft.rfft(window))
    return float(spectrum[int(hertz) - 5:int(hertz) + 6].max())


def _seconds(path: Path) -> float:
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30, check=True)
    return float(probe.stdout)


def _picture(path: Path) -> str:
    """A digest of the video packets: equal when the picture was stream-copied."""
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"]
    return subprocess.run(command, capture_output=True, text=True, timeout=60, check=True).stdout.strip()


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_the_foley_goes_under_the_take_at_its_volume_and_the_picture_is_copied(tmp_path):
    take, generated, sound, mixed = (tmp_path / name for name in ("take.mp4", "generated.mp4", "foley.wav", "mixed.mp4"))
    _media(take, 2.0, 440)
    _media(generated, 3.0, 1000, amplitude=0.4)  # MMAudio's clip: the picture again, with the new sound

    extract_audio(str(generated), str(sound))
    mix_under(str(take), str(sound), str(mixed), 0.5)

    assert has_audio(str(take)) and _picture(mixed) == _picture(take), "the picture is copied, not encoded"
    assert _seconds(mixed) == pytest.approx(_seconds(take), abs=0.05), "as long as the take, not the foley"
    original, foley, result = _samples(take), _samples(sound), _samples(mixed)
    assert _level(result, 440) == pytest.approx(_level(original, 440), rel=0.1), "the take's own sound is untouched"
    assert _level(result, 1000) == pytest.approx(0.5 * _level(foley, 1000), rel=0.1), "the foley at its volume"
    assert not list(tmp_path.glob("*.part.*"))

    silent, alone = tmp_path / "silent.mp4", tmp_path / "alone.mp4"
    _media(silent, 2.0, None)
    mix_under(str(silent), str(sound), str(alone), 0.5)
    assert has_audio(str(alone)) and _level(_samples(alone), 1000) == pytest.approx(0.5 * _level(foley, 1000), rel=0.1)
    with pytest.raises(RuntimeError, match="Foley audio extraction failed"):
        extract_audio(str(silent), str(tmp_path / "nothing.wav"))
    assert not list(tmp_path.glob("nothing*"))
