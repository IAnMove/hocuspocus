"""The voice sounds like the place: rooms for recorded Series lines, their cache, their digests and their DSP."""
import hashlib
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from services import series_voice_rooms as rooms
from services.audio_levels import integrated_lufs
from services.series_ambience import shot_sound_design
from services.series_guide import audio_files
from services.series_library import normalize_series_project
from services.series_native_render import NativeRenderDeps, SeriesNativeRender
from services.series_script import ScriptError, apply_script
from services.series_shot_plan import build_shot_spec, normalize_layout2d
from services.series_take_inputs import render_inputs, stale_shot_ids
from services.series_voice_rooms import MAX_RING, PRESETS, ROOMS, RoomError, apply_room, room_filename, room_filter, roomed, shot_room
from tests import test_series_native_render as native
from tests.test_series_script_produce import FILES, KITS as SCRIPT_KITS, SCRIPT, Series

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
RATE = 44100
LIBRARY = native.library


# Planning ---------------------------------------------------------------------

def test_the_presets_and_what_each_plans():
    assert PRESETS == ("none", "small_room", "room", "hall", "cathedral", "cockpit", "outdoor", "radio")
    assert "none" not in ROOMS and set(ROOMS) == set(PRESETS) - {"none"}
    for preset, room in ROOMS.items():
        graph = room_filter(preset)
        assert graph.startswith("[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono") and graph.endswith("[out]")
        assert room.tone in graph
        if rooms.has_tail(room):
            ring = rooms.ring_seconds(preset)
            assert 0 < ring <= MAX_RING
            assert f"apad=pad_dur={ring:.3f}" in graph and f"volume={room.wet}dB[wet]" in graph
            makeup = 20 * math.log10(float(np.sum(np.abs(rooms.impulse_response(preset)))))
            assert rooms.ir_makeup_db(preset) == pytest.approx(makeup) and makeup > 0
            assert f"afir,volume={makeup:.6f}dB" in graph, \
                "afir's default division by the sum of the taps is given back: the response is used at unit energy"
            assert "gtype" not in graph and "irnorm" not in graph, "ffmpeg 6.x has no irnorm and 7.0 and later ignore gtype"
            assert f"areverse,afade=t=in:d={ring * rooms.FADE_SHARE:.3f}:curve=qsin,areverse[out]" in graph, "the ring fades out"
        else:
            assert "afir" not in graph and "apad" not in graph


def test_a_tail_is_bounded_and_a_room_without_one_adds_nothing():
    assert rooms.ring_seconds("none") == 0.0 and rooms.ring_seconds("radio") == 0.0
    assert rooms.ring_seconds("cathedral") == rooms.ring_seconds("hall") == MAX_RING, "a big room rings no longer than the cap"
    assert rooms.ring_seconds("small_room") < rooms.ring_seconds("room") < MAX_RING
    assert 0 < rooms.ring_seconds("cockpit") < 0.2 and 0 < rooms.ring_seconds("outdoor") < 0.15


def test_the_presets_have_the_character_they_are_named_for():
    cathedral, cockpit, outdoor, radio = (ROOMS[name] for name in ("cathedral", "cockpit", "outdoor", "radio"))
    times = [ROOMS[name].rt60 for name in ("small_room", "room", "hall", "cathedral")]
    assert times == sorted(times) and len(set(times)) == 4, "bigger rooms ring longer"
    assert cathedral.wet > ROOMS["small_room"].wet, "and sit further in front of the voice"
    assert cathedral.damping < ROOMS["small_room"].damping, "a stone room is darker"
    assert cockpit.rt60 < 0.2 and max(ms for ms, _ in cockpit.early) < 11 and any(gain < 0 for _, gain in cockpit.early)
    assert outdoor.rt60 == 0 and len(outdoor.early) == 1 and "highpass" in outdoor.tone and outdoor.wet <= -15, "a touch of air, no reverb"
    assert not rooms.has_tail(radio) and all(word in radio.tone for word in ("highpass", "lowpass", "asoftclip"))


def test_the_places_are_felt_under_the_voice_not_in_front_of_it():
    places = [ROOMS[name] for name in ("small_room", "room", "hall", "cathedral", "outdoor")]
    assert all(room.wet <= -14 for room in places), "a place sits 14 dB or more under the voice"
    assert all(room.band[0] >= 200 for room in places), "and carries no low end to mask the words"
    assert all(0 < room.band[1] <= 6000 for room in places if room.rt60), "nor the highs that smear the consonants"
    assert all(room.late <= 0 for room in places if room.rt60), "it is mostly early reflections, which the ear fuses with the voice"
    assert ROOMS["cathedral"].rt60 <= 2.5 and ROOMS["cathedral"].predelay >= 40, "a short tail that starts after the syllable"
    assert rooms.TRANSMISSIONS == {"radio"} and "radio" in ROOMS
    for preset, room in ROOMS.items():
        graph = room_filter(preset)
        if room.band != (0.0, 0.0):
            assert f"dB{rooms.wet_band(room)},volume={room.wet}dB[wet]" in graph, "the band is on the room alone"
    assert rooms.wet_band(ROOMS["cathedral"]) == ",highpass=f=350:poles=2,lowpass=f=4000:poles=2"
    assert rooms.wet_band(ROOMS["outdoor"]) == ",highpass=f=200:poles=2" and rooms.wet_band(ROOMS["cockpit"]) == ""


def test_the_tail_sits_under_the_early_reflections_by_its_late_level():
    cathedral = rooms.impulse_response("cathedral")
    room = ROOMS["cathedral"]
    tail_from = int(RATE * (max(ms for ms, _ in room.early) + 2) / 1000)
    early, late = float(np.sum(cathedral[:tail_from] ** 2)), float(np.sum(cathedral[tail_from:] ** 2))
    assert 10 * math.log10(late / early) == pytest.approx(room.late, abs=1.0)


def _energy_curve_seconds(response, low=-5, high=-25):
    """Reverberation time from the backward energy integral (Schroeder), between two levels of decay."""
    energy = np.cumsum((response ** 2)[::-1])[::-1]
    decay = 10 * np.log10(energy / energy[0] + 1e-30)
    return (np.argmax(decay < high) - np.argmax(decay < low)) / RATE * 60 / (low - high)


def test_an_impulse_response_is_deterministic_unit_energy_and_decays_as_planned():
    for preset in ("small_room", "room", "hall", "cathedral", "cockpit", "outdoor"):
        first, second = rooms.impulse_response(preset), rooms.impulse_response(preset)
        assert np.array_equal(first, second) and np.isfinite(first).all()
        assert float(np.sum(first ** 2)) == pytest.approx(1.0)
    for preset in ("small_room", "room", "hall", "cathedral"):
        measured = _energy_curve_seconds(rooms.impulse_response(preset))
        assert measured == pytest.approx(ROOMS[preset].rt60, rel=0.12), preset
    assert not np.array_equal(rooms.impulse_response("room"), rooms.impulse_response("hall")), "each preset has its own noise"
    cathedral = rooms.impulse_response("cathedral")
    assert np.abs(cathedral[:int(0.010 * RATE)]).max() < 1e-6, "nothing arrives before the first reflection (14 ms)"
    assert len(cathedral) / RATE == pytest.approx(0.05 + 1.3 * 2.2, abs=0.01)


def test_the_cockpit_is_early_reflections_and_the_outdoor_room_one_slap():
    cockpit = rooms.impulse_response("cockpit")
    assert float(np.sum(cockpit[:int(0.012 * RATE)] ** 2)) > 0.4, "a small metal room is mostly its first reflections"
    outdoor = rooms.impulse_response("outdoor")
    assert abs(int(np.argmax(np.abs(outdoor))) / RATE - 0.082) < 0.002, "one slap, 82 ms behind the voice"
    assert float(np.sum(outdoor[:int(0.06 * RATE)] ** 2)) < 0.01, "nothing before it"
    with pytest.raises(ValueError, match="no tail"):
        rooms.impulse_response("radio")


def test_the_impulse_response_is_written_once_as_a_float_wav(tmp_path):
    path = rooms.ensure_impulse_response(str(tmp_path), "hall")
    assert os.path.basename(path) == f"ln-room-hall-ir-v{rooms.VERSION}.wav", "ln- keeps it out of the series guide's sounds"
    data = Path(path).read_bytes()
    assert data[:4] == b"RIFF" and data[8:16] == b"WAVEfmt " and struct.unpack("<HHI", data[20:28]) == (3, 1, RATE)
    assert np.frombuffer(data[44:], "<f4") == pytest.approx(rooms.impulse_response("hall"), abs=1e-6)
    before = os.stat(path).st_mtime_ns
    assert rooms.ensure_impulse_response(str(tmp_path), "hall") == path and os.stat(path).st_mtime_ns == before
    assert sorted(os.listdir(tmp_path)) == [os.path.basename(path)], "no scratch files are left"
    assert audio_files([os.path.basename(path), room_filename("ln-ep-b0.wav", "hall")]) == {"music": [], "sfx": [], "other": []}, \
        "neither is offered to an agent as a sound to use"


# Which room a shot is in, and the lines it plays ---------------------------------

def _series(**design):
    return {"id": "show", "spokenLanguage": "English",
            "locations": [{"id": "nave", "name": "Nave"}, {"id": "deck", "name": "Deck"}],
            "characters": [{"id": "ana", "voiceProfile": {"characterKitRef": {"id": "kit-ana", "workspace": "ws"}}},
                           {"id": "leo", "voiceProfile": {"characterKitRef": {"id": "kit-leo", "workspace": "ws"}}}],
            "soundDesign": design}


KITS = {"kit-ana": {"id": "kit-ana", "voice": {"model": "qwen3_tts_customvoice", "voiceId": "ryan"}, "updatedAt": "x"},
        "kit-leo": {"id": "kit-leo", "voice": {"model": "qwen3_tts_customvoice", "voiceId": "dylan"}}}
TALK = {"id": "s1", "order": 1, "locationId": "nave", "productionMethod": "animation_2d", "visibleCharacterIds": ["ana", "leo"],
        "dialogueBeats": [{"id": "s1_b0", "characterId": "ana", "text": "Hi.", "emotion": "calm"},
                          {"id": "s1_b1", "characterId": "leo", "text": "Hello there.", "delivery": "whisper"}],
        "layout2d": {"framing": "two", "camera": "push", "music": {"file": "mus-a.wav", "volume": 0.4}}}
CARD = {"id": "s2", "order": 2, "locationId": "deck", "productionMethod": "animation_2d", "durationSeconds": 5,
        "layout2d": {"card": {"kind": "title", "title": "T", "body": "B"}}}
NAVE_CARD = {**CARD, "id": "s4", "order": 4, "locationId": "nave"}
DECK = {"id": "s3", "order": 3, "locationId": "deck", "productionMethod": "animation_3d", "visibleCharacterIds": ["ana"],
        "dialogueBeats": [{"id": "s3_b0", "characterId": "ana", "text": "Up here."}],
        "scene3d": {"template": "user-deck", "cast": [{"characterId": "ana", "objectId": "ana"}], "quality": "draft"}}
RECORDED = {"s1_b0": {"key": "k0", "filename": "ln-ep-s1_b0-k0.wav", "duration": 1.1, "cues": [{"start": 0, "end": 0.3, "value": "D"}]},
            "s1_b1": {"key": "k1", "filename": "ln-ep-s1_b1-k1.wav", "duration": 1.6, "cues": [{"start": 0, "end": 0.5, "value": "B"}]}}


def test_a_shot_is_in_its_own_room_else_its_locations():
    series = _series(roomByLocation={"nave": "cathedral", "deck": "outdoor"})
    assert shot_room(series, TALK) == "cathedral" and shot_room(series, DECK) == "outdoor"
    assert shot_room(series, {**TALK, "layout2d": {"voiceRoom": "radio"}}) == "radio", "the shot overrides its location"
    assert shot_room(series, {**TALK, "layout2d": {"voiceRoom": "none"}}) is None, "none keeps a shot dry"
    assert shot_room(series, {**TALK, "locationId": "elsewhere"}) is None
    assert shot_room(series, {**TALK, "locationId": None}) is None
    assert shot_room(_series(roomByLocation={"nave": "none"}), TALK) is None
    assert shot_room(_series(), TALK) is None and shot_room({"id": "bare"}, TALK) is None
    assert shot_room({"soundDesign": {"roomByLocation": "hall"}}, TALK) is None
    assert shot_room(_series(roomByLocation={"nave": "catedral"}), TALK) is None, "a value that slipped past validation is dry"
    assert shot_room({"id": "bare"}, {**TALK, "layout2d": {"voiceRoom": "hall"}}) == "hall", "a shot can set its own room alone"


def test_a_roomed_shot_plays_the_processed_copy_of_each_line_and_keeps_the_dry_timing():
    made = []

    def process(filename, preset):
        made.append((filename, preset))
        return room_filename(filename, preset)

    series = _series(roomByLocation={"nave": "cathedral"})
    episode = {"id": "ep", "title": "T", "shots": [TALK]}
    dry = build_shot_spec(series, episode, TALK, workspace="cast", recorded=RECORDED)
    heard = roomed(series, TALK, RECORDED, process)
    spec = build_shot_spec(series, episode, TALK, workspace="cast", recorded=heard)
    assert [line["filename"] for line in spec["lines"]] == [f"ln-ep-s1_b0-k0.room-cathedral-v{rooms.VERSION}.wav", f"ln-ep-s1_b1-k1.room-cathedral-v{rooms.VERSION}.wav"]
    assert [line["filename"] for line in dry["lines"]] == ["ln-ep-s1_b0-k0.wav", "ln-ep-s1_b1-k1.wav"]
    assert made == [("ln-ep-s1_b0-k0.wav", "cathedral"), ("ln-ep-s1_b1-k1.wav", "cathedral")]
    for key in ("duration", "cast", "framing", "audioTracks"):
        assert spec[key] == dry[key], "the shot is timed by the dry line"
    assert [(line["start"], line["end"], line["cues"]) for line in spec["lines"]] == [
        (line["start"], line["end"], line["cues"]) for line in dry["lines"]], "lip-sync stays the dry line's"
    assert RECORDED["s1_b0"]["filename"] == "ln-ep-s1_b0-k0.wav", "the recording itself is not touched"


def test_a_shot_without_a_room_plays_the_dry_lines_and_asks_for_nothing():
    asked = []
    process = lambda filename, preset: asked.append(filename) or filename
    assert roomed(_series(), TALK, RECORDED, process) is RECORDED
    assert roomed(_series(roomByLocation={"deck": "hall"}), TALK, RECORDED, process) is RECORDED, "another location's room"
    assert roomed(_series(roomByLocation={"nave": "hall"}), {**TALK, "layout2d": {"voiceRoom": "none"}}, RECORDED, process) is RECORDED
    assert asked == []
    stale = {**RECORDED, "s1_old": {"filename": "ln-gone.wav", "duration": 1.0}}
    assert roomed(_series(roomByLocation={"nave": "hall"}), TALK, stale, process)["s1_old"] == stale["s1_old"], "only the shot's lines"
    assert asked == ["ln-ep-s1_b0-k0.wav", "ln-ep-s1_b1-k1.wav"]


NARRATOR = {"id": "s1_b2", "characterId": "narrator", "text": "Meanwhile, in the nave."}
NARRATED = {**TALK, "dialogueBeats": [*TALK["dialogueBeats"], NARRATOR]}
NARRATED_RECORDED = {**RECORDED, "s1_b2": {"key": "k2", "filename": "ln-ep-s1_b2-k2.wav", "duration": 2.0, "cues": []}}


def test_a_place_reaches_only_the_speakers_in_the_shot():
    cathedral = _series(roomByLocation={"nave": "cathedral"})
    assert rooms.line_rooms(cathedral, NARRATED) == {"s1_b0": "cathedral", "s1_b1": "cathedral"}, "the narrator is not in the church"
    assert rooms.on_screen(TALK) == {"ana", "leo"}
    cast = {**NARRATED, "layout2d": {**TALK["layout2d"], "cast": [{"characterId": "leo", "x": 60}]}}
    assert rooms.on_screen(cast) == {"leo"} and rooms.line_rooms(cathedral, cast) == {"s1_b1": "cathedral"}, \
        "the 2D cast says who stands there, before visibleCharacterIds"
    assert rooms.line_rooms(cathedral, {**NARRATED, "layout2d": {"framing": "title"}}) == {}, "nobody stands in a title shot"
    deck = {**DECK, "visibleCharacterIds": ["ana", "leo"],
            "dialogueBeats": [*DECK["dialogueBeats"], {"id": "s3_b1", "characterId": "leo", "text": "Over."}]}
    assert rooms.on_screen(deck) == {"ana"}, "a 3D shot's people are its scene's cast; the others are heard over it"
    assert rooms.line_rooms(_series(roomByLocation={"deck": "hall"}), deck) == {"s3_b0": "hall"}
    blank = {**TALK, "dialogueBeats": [{"id": "s1_b0", "characterId": "ana", "text": "  ", "voiceRoom": "hall"}]}
    assert rooms.line_rooms(cathedral, blank) == {}, "a line without words is not recorded"


def test_a_transmission_reaches_every_line_of_its_shot():
    everyone = {"s1_b0": "radio", "s1_b1": "radio", "s1_b2": "radio"}
    assert rooms.line_rooms(_series(), {**NARRATED, "layout2d": {**TALK["layout2d"], "voiceRoom": "radio"}}) == everyone
    assert rooms.line_rooms(_series(roomByLocation={"nave": "radio"}), NARRATED) == everyone, "from its location too"


def test_a_line_names_its_own_room_and_it_wins_on_screen_or_off():
    beats = [{**TALK["dialogueBeats"][0], "voiceRoom": "none"}, TALK["dialogueBeats"][1], {**NARRATOR, "voiceRoom": "radio"}]
    shot = {**TALK, "dialogueBeats": beats}
    assert rooms.line_rooms(_series(roomByLocation={"nave": "cathedral"}), shot) == {"s1_b1": "cathedral", "s1_b2": "radio"}, \
        "ana is dry in the cathedral and the narrator a voice on the radio"
    assert rooms.line_rooms(_series(), shot) == {"s1_b2": "radio"}, "in a dry place too"
    assert rooms.line_rooms(_series(), {**TALK, "dialogueBeats": [{**NARRATOR, "voiceRoom": "hall"}]}) == {"s1_b2": "hall"}, \
        "an off-screen speaker can be given a place (a voice from the next room)"
    radio = {**shot, "layout2d": {**TALK["layout2d"], "voiceRoom": "radio"}}
    assert rooms.line_rooms(_series(), radio) == {"s1_b1": "radio", "s1_b2": "radio"}, "none keeps one line off the radio"
    assert rooms.line_rooms(_series(), {**TALK, "dialogueBeats": [{**NARRATOR, "voiceRoom": "church"}]}) == {}, \
        "a value that slipped past validation is dry"


def test_each_line_plays_the_copy_of_its_own_room():
    made = []

    def process(filename, preset):
        made.append((filename, preset))
        return room_filename(filename, preset)

    series = _series(roomByLocation={"nave": "cathedral"})
    heard = roomed(series, NARRATED, NARRATED_RECORDED, process)
    assert [heard[beat]["filename"] for beat in ("s1_b0", "s1_b1", "s1_b2")] == [
        room_filename("ln-ep-s1_b0-k0.wav", "cathedral"), room_filename("ln-ep-s1_b1-k1.wav", "cathedral"), "ln-ep-s1_b2-k2.wav"]
    assert made == [("ln-ep-s1_b0-k0.wav", "cathedral"), ("ln-ep-s1_b1-k1.wav", "cathedral")], "the narrator is not processed"
    made.clear()
    own = {**NARRATED, "dialogueBeats": [*TALK["dialogueBeats"], {**NARRATOR, "voiceRoom": "radio"}]}
    assert roomed(series, own, NARRATED_RECORDED, process)["s1_b2"]["filename"] == room_filename("ln-ep-s1_b2-k2.wav", "radio")
    assert sorted(preset for _name, preset in made) == ["cathedral", "cathedral", "radio"]
    voice_over = {**TALK, "dialogueBeats": [NARRATOR]}
    assert roomed(series, voice_over, NARRATED_RECORDED, process) is NARRATED_RECORDED, "a narrated shot in the church is dry"


# Validation -------------------------------------------------------------------

def test_an_unknown_room_is_refused_in_a_series_and_in_a_shot():
    rooms.check_voice_rooms(None)
    rooms.check_voice_rooms({"roomByLocation": {"nave": "cathedral", "deck": "none"}})
    for bad in ({"nave": "Cathedral"}, {"nave": "church"}, {"nave": None}, {"nave": ["hall"]}, "hall", ["hall"]):
        with pytest.raises(ValueError, match="roomByLocation"):
            rooms.check_voice_rooms({"roomByLocation": bad})
    with pytest.raises(ValueError, match="cathedral, cockpit, outdoor, radio"):
        normalize_series_project({"id": "show", "soundDesign": {"roomByLocation": {"nave": "church"}}}, "show", "default")
    saved = normalize_series_project({"id": "show", "soundDesign": {"roomByLocation": {"nave": "cathedral", "deck": "none"}}}, "show", "default")
    assert saved["soundDesign"] == {"roomByLocation": {"nave": "cathedral", "deck": "none"}}
    assert normalize_layout2d({"framing": "wide", "voiceRoom": "radio"}) == {"framing": "wide", "voiceRoom": "radio"}
    assert normalize_layout2d({"voiceRoom": None}) is None, "null clears the override"
    for bad in ("church", "", 3, ["hall"]):
        with pytest.raises(ValueError, match="layout2d.voiceRoom"):
            normalize_layout2d({"voiceRoom": bad})
    shot = {"id": "e1s1", "sceneId": "sc", "productionMethod": "animation_2d", "layout2d": {"framing": "wide", "voiceRoom": "hall"}}
    project = {"id": "show", "allowedProductionMethods": ["animation_2d"],
               "episodesById": {"ep1": {"id": "ep1", "number": 1, "script": [{"id": "sc"}], "shots": [shot]}}}
    assert normalize_series_project(project, "show", "default")["episodesById"]["ep1"]["shots"][0]["layout2d"]["voiceRoom"] == "hall"
    shot["layout2d"]["voiceRoom"] = "church"
    with pytest.raises(ValueError, match="layout2d.voiceRoom"):
        normalize_series_project(project, "show", "default")


def test_a_line_room_is_kept_on_its_beat_and_an_unknown_one_is_refused():
    def saved(beat):
        shot = {"id": "e1s1", "sceneId": "sc", "productionMethod": "animation_2d", "dialogueBeats": [beat]}
        project = {"id": "show", "allowedProductionMethods": ["animation_2d"], "characters": [{"id": "narrator", "name": "Narrator"}],
                   "episodesById": {"ep1": {"id": "ep1", "number": 1, "script": [{"id": "sc"}], "shots": [shot]}}}
        return normalize_series_project(project, "show", "default")["episodesById"]["ep1"]["shots"][0]["dialogueBeats"][0]

    beat = {"id": "e1s1_b0", "characterId": "narrator", "text": "Meanwhile."}
    assert saved({**beat, "voiceRoom": "radio"})["voiceRoom"] == "radio"
    assert "voiceRoom" not in saved({**beat, "voiceRoom": None}), "null clears it"
    for bad in ("church", "", 3):
        with pytest.raises(ValueError, match="dialogueBeats.voiceRoom must be one of"):
            saved({**beat, "voiceRoom": bad})


def test_a_script_line_names_its_own_room():
    tools = Series()
    talk = SCRIPT["shots"][1]
    lines = [{**talk["lines"][0], "voiceRoom": "radio"}, talk["lines"][1]]
    apply_script(tools, tools.read, SCRIPT_KITS, FILES, "cast", {**SCRIPT, "shots": [{**talk, "lines": lines}]})
    beats = tools.calls[1][1]["episode"]["shots"][0]["dialogueBeats"]
    assert beats[0]["voiceRoom"] == "radio" and "voiceRoom" not in beats[1]
    with pytest.raises(ScriptError, match="shot 0 .*line 1 voiceRoom must be one of none, small_room"):
        apply_script(Series(), tools.read, SCRIPT_KITS, FILES, "cast",
                     {**SCRIPT, "shots": [{**talk, "lines": [talk["lines"][0], {**talk["lines"][1], "voiceRoom": "church"}]}]})


def test_a_script_names_a_shots_room_and_a_typo_is_listed_with_the_other_problems():
    tools = Series()
    script = {**SCRIPT, "shots": [{**SCRIPT["shots"][1], "voiceRoom": "radio"}, SCRIPT["shots"][2]]}
    apply_script(tools, tools.read, SCRIPT_KITS, FILES, "cast", script)
    talk, mars = tools.calls[1][1]["episode"]["shots"]
    assert talk["layout2d"]["voiceRoom"] == "radio" and "voiceRoom" not in mars["layout2d"]
    with pytest.raises(ScriptError, match="shot 0 .*voiceRoom must be one of none, small_room"):
        apply_script(Series(), tools.read, SCRIPT_KITS, FILES, "cast", {**SCRIPT, "shots": [{**SCRIPT["shots"][1], "voiceRoom": "church"}]})


# Take digests -----------------------------------------------------------------

DESIGN = {"stinger": {"file": "sfx-s.wav", "volume": 0.6}, "ambienceByLocation": {"nave": {"file": "sfx-n.wav", "volume": 0.3}}}


def test_a_series_without_rooms_keeps_the_digests_its_takes_were_rendered_with():
    # Talk and deck were computed before rooms existed. The card is silent, so its digest
    # uses the 0.05 s grid of the length the planner renders. Five seconds stays five seconds.
    golden = {
        "none": ("26ba124fa2ad4168", "e4abf0454c0cdc82", "c58ca4383e385ee5", _bare()),
        "empty": ("edf4104106d3dd77", "ca183ad0311f49c8", "6abe8a02e2b260b9", _series()),
        "design": ("026426c8d5189725", "c15bd0ec6e2ae96c", "ae9e31571f0323e7", _series(**DESIGN)),
        "shot mode": ("026426c8d5189725", "c15bd0ec6e2ae96c", "ae9e31571f0323e7", _series(**DESIGN, ambienceMode="shot")),
        "episode mode": ("0014231dd234edae", "f6fccada07049bb7", "01b4663bbb4cb53e", _series(**DESIGN, ambienceMode="episode")),
    }
    for name, (talk, card, deck, series) in golden.items():
        assert [render_inputs(series, shot, KITS) for shot in (TALK, CARD, DECK)] == [talk, card, deck], name
    # Nothing a room adds shows while no shot hears one.
    for series in (_series(**DESIGN, roomByLocation={}), _series(**DESIGN, roomByLocation={"nave": "none", "attic": "hall"})):
        assert [render_inputs(series, shot, KITS) for shot in (TALK, CARD, DECK)] == [
            "026426c8d5189725", "c15bd0ec6e2ae96c", "ae9e31571f0323e7"]


def _bare():
    series = _series()
    del series["soundDesign"]
    return series


def test_a_shot_whose_room_changes_is_out_of_date_and_the_others_are_not():
    def digests(**design):
        series = _series(**DESIGN, **design)
        return {shot["id"]: render_inputs(series, shot, KITS) for shot in (TALK, CARD, DECK, NAVE_CARD)}

    dry = digests()
    nave = digests(roomByLocation={"nave": "cathedral"})
    assert nave["s1"] != dry["s1"], "the nave's voices changed"
    assert (nave["s2"], nave["s3"], nave["s4"]) == (dry["s2"], dry["s3"], dry["s4"]), "a title card has no lines to hear it; the deck is elsewhere"
    assert digests(roomByLocation={"nave": "hall"})["s1"] not in (nave["s1"], dry["s1"])
    assert digests(roomByLocation={"nave": "cathedral", "deck": "outdoor"}) == {**nave, "s3": digests(roomByLocation={"deck": "outdoor"})["s3"]}
    assert digests(roomByLocation={"deck": "outdoor"})["s3"] != dry["s3"] and digests(roomByLocation={"deck": "outdoor"})["s1"] == dry["s1"]
    assert digests(roomByLocation={"nave": "none"}) == dry, "none is dry"
    override = render_inputs(_series(**DESIGN, roomByLocation={"nave": "cathedral"}), {**TALK, "layout2d": {**TALK["layout2d"], "voiceRoom": "radio"}}, KITS)
    assert override not in (nave["s1"], dry["s1"])
    assert render_inputs(_series(**DESIGN), {**TALK, "layout2d": {**TALK["layout2d"], "voiceRoom": "radio"}}, KITS) == override, \
        "the same room from the shot or from its location is the same take"


def test_a_narrator_over_a_roomed_place_keeps_the_dry_digest_and_a_line_room_renders_only_its_shot():
    roomed_series, dry_series = _series(**DESIGN, roomByLocation={"nave": "cathedral"}), _series(**DESIGN)
    voice_over = {**TALK, "dialogueBeats": [NARRATOR]}
    assert render_inputs(roomed_series, voice_over, KITS) == render_inputs(dry_series, voice_over, KITS), \
        "a voice-over across a church plate renders as it would dry"
    talk = render_inputs(roomed_series, TALK, KITS)
    narrated = render_inputs(roomed_series, NARRATED, KITS)
    radio_line = {**TALK, "dialogueBeats": [TALK["dialogueBeats"][0], {**TALK["dialogueBeats"][1], "voiceRoom": "radio"}]}
    assert render_inputs(roomed_series, radio_line, KITS) not in (talk, narrated), "a line given its own room renders its shot again"
    same = {**TALK, "dialogueBeats": [TALK["dialogueBeats"][0], {**TALK["dialogueBeats"][1], "voiceRoom": "cathedral"}]}
    assert render_inputs(roomed_series, same, KITS) == talk, "naming the room a line already hears changes nothing"
    dry_line = {**TALK, "dialogueBeats": [{**beat, "voiceRoom": "none"} for beat in TALK["dialogueBeats"]]}
    assert render_inputs(dry_series, dry_line, KITS) == render_inputs(dry_series, TALK, KITS), "none in a dry place changes nothing"
    assert render_inputs(roomed_series, dry_line, KITS) == render_inputs(dry_series, TALK, KITS), "a shot of dry lines is a dry take"


def test_a_new_version_of_the_rooms_renders_again_only_the_shots_that_hear_one(monkeypatch):
    from services import series_take_inputs
    series = _series(**DESIGN, roomByLocation={"nave": "cathedral"})
    before = [render_inputs(series, shot, KITS) for shot in (TALK, CARD, DECK, {**TALK, "dialogueBeats": [NARRATOR]})]
    monkeypatch.setattr(series_take_inputs, "ROOM_VERSION", rooms.VERSION + 1)
    after = [render_inputs(series, shot, KITS) for shot in (TALK, CARD, DECK, {**TALK, "dialogueBeats": [NARRATOR]})]
    assert after[0] != before[0] and after[1:] == before[1:], "retuned presets reach the shots that hear them"


def test_only_the_shots_whose_room_changed_are_stale():
    kits = KITS
    series = {**_series(**DESIGN, roomByLocation={"nave": "cathedral"}), "assets": {}}
    shots = [{**shot, "attempts": [{"id": f"a-{shot['id']}", "outputAssetIds": [f"take-{shot['id']}"]}], "approvedAttemptId": f"a-{shot['id']}"}
             for shot in (TALK, CARD, DECK, NAVE_CARD)]
    for shot in shots:
        series["assets"][f"take-{shot['id']}"] = {"metadata": {"renderInputs": render_inputs(series, shot, kits)}}
    episode = {"id": "ep", "shots": shots}
    assert stale_shot_ids(series, episode, kits) == []
    series["soundDesign"]["roomByLocation"] = {"nave": "hall", "deck": "none"}
    assert stale_shot_ids(series, episode, kits) == ["s1"]
    series["soundDesign"]["roomByLocation"] = {"nave": "cathedral", "deck": "radio"}
    assert stale_shot_ids(series, episode, kits) == ["s3"]
    del series["soundDesign"]["roomByLocation"]
    assert stale_shot_ids(series, episode, kits) == ["s1"], "taking the rooms away renders the voices dry again"


def test_the_rooms_are_not_part_of_the_sound_a_shot_depends_on():
    assert shot_sound_design({"stinger": 1, "roomByLocation": {"nave": "hall"}}) == {"stinger": 1}
    assert shot_sound_design({"ambienceMode": "episode", "stinger": 1, "ambienceByLocation": {}, "roomByLocation": {"a": "room"}}) == {"stinger": 1}
    assert shot_sound_design({"ambienceMode": "shot", "ambienceByLocation": {"a": 1}, "roomByLocation": {}}) == {"ambienceByLocation": {"a": 1}}
    design = {"stinger": 1}
    assert shot_sound_design(design) is design


# The native render ------------------------------------------------------------

def _rendered(tmp_path, monkeypatch, design, edit=lambda library: None, **deps):
    made, raised = [], deps.pop("raises", None)

    def room(root, filename, preset):
        if raised:
            raise raised
        made.append((root, filename, preset))
        return room_filename(filename, preset)

    def library():
        data = LIBRARY()
        data["seriesById"]["uv"]["soundDesign"] = design
        edit(data)
        return data

    monkeypatch.setattr(native, "library", library)
    tools, compiled = native.Tools(tmp_path), []
    render = native.service(tmp_path, tools, compiled, room=room, **deps)
    return render, made, compiled


def test_the_server_render_plays_each_line_in_the_room_of_its_location(tmp_path, monkeypatch):
    def second_shot_is_dry(data):
        data["seriesById"]["uv"]["episodesById"]["ep1"]["shots"][2]["layout2d"] = {"voiceRoom": "none"}

    (tmp_path / "dry").mkdir()
    plain, _made, plain_compiled = _rendered(tmp_path / "dry", monkeypatch, {})
    native.finished(plain, plain.start("cast", "uv", "ep1")["jobId"], tmp_path)
    render, made, compiled = _rendered(tmp_path, monkeypatch, {"roomByLocation": {"garage": "cathedral"}}, second_shot_is_dry)
    done = native.finished(render, render.start("cast", "uv", "ep1", approve=True)["jobId"], tmp_path)
    assert done["status"] == "completed", done
    first, second = (document["shot"]["lines"] for document in compiled)
    recorded = done["items"][0]["lines"]
    assert [line["filename"] for line in first] == [f"{recorded[beat]['filename'][:-4]}.room-cathedral-v{rooms.VERSION}.wav"
                                                    for beat in ("s01_d0", "s01_d1")], "the first shot is in the garage's room"
    assert [(root, preset) for root, _name, preset in made] == [(str(tmp_path), "cathedral")] * 2, "the shot with voiceRoom none is dry"
    assert [line["filename"] for line in second] == [done["items"][1]["lines"]["s03_d0"]["filename"]]
    assert all(line["cues"] for line in first), "the cues are the dry lines'"
    assert recorded["s01_d0"]["filename"].endswith(f"-{recorded['s01_d0']['key']}.wav"), "the job keeps the dry recording"
    assert [document["shot"]["duration"] for document in compiled] == [document["shot"]["duration"] for document in plain_compiled], "dry timing"


def test_the_server_render_keeps_a_voice_over_dry_and_gives_a_line_its_own_room(tmp_path, monkeypatch):
    def edit(data):
        shots = data["seriesById"]["uv"]["episodesById"]["ep1"]["shots"]
        shots[0]["visibleCharacterIds"] = ["kevin"]
        shots[2]["dialogueBeats"][0]["voiceRoom"] = "radio"

    render, made, compiled = _rendered(tmp_path, monkeypatch, {"roomByLocation": {"garage": "cathedral"}}, edit)
    done = native.finished(render, render.start("cast", "uv", "ep1")["jobId"], tmp_path)
    assert done["status"] == "completed", done
    first, second = (document["shot"]["lines"] for document in compiled)
    recorded = {**done["items"][0]["lines"], **done["items"][1]["lines"]}
    assert [line["filename"] for line in first] == [room_filename(recorded["s01_d0"]["filename"], "cathedral"), recorded["s01_d1"]["filename"]], \
        "kevin is in the garage's cathedral, gary is heard over the shot, dry"
    assert [line["filename"] for line in second] == [room_filename(recorded["s03_d0"]["filename"], "radio")], "a line's own room wins"
    assert [preset for _root, _name, preset in made] == ["cathedral", "radio"]


def test_a_series_without_rooms_never_asks_for_a_copy(tmp_path, monkeypatch):
    render, made, compiled = _rendered(tmp_path, monkeypatch, {"ambienceByLocation": {}})
    native.finished(render, render.start("cast", "uv", "ep1")["jobId"], tmp_path)
    assert made == [] and all(".room-" not in line["filename"] for document in compiled for line in document["shot"]["lines"])


def test_a_room_that_cannot_be_made_fails_its_shot_clearly(tmp_path, monkeypatch):
    render, _made, compiled = _rendered(tmp_path, monkeypatch, {"roomByLocation": {"garage": "hall"}}, raises=RoomError("ffmpeg failed: boom"))
    done = native.finished(render, render.start("cast", "uv", "ep1")["jobId"], tmp_path)
    assert done["status"] == "failed" and compiled == []
    assert "Voice room: ffmpeg failed: boom" in done["items"][0]["error"], "a take must not claim a room it does not have"


def test_a_3d_shot_hears_the_room_too_and_its_narrator_stays_dry(tmp_path):
    calls = []

    def call(tool, arguments):
        calls.append((tool, arguments["input"]))
        scene = {"sceneId": "scene-1", "revision": len(calls), "document": {"layers": []}}
        return {"result": {"scene": scene, "file": "scene.world3d.json"}}

    series = LIBRARY()["seriesById"]["uv"]
    series["soundDesign"] = {"roomByLocation": {"garage": "cockpit"}}
    shot = {"id": "s9", "order": 1, "sceneId": "x", "productionMethod": "animation_3d", "locationId": "garage",
            "dialogueBeats": [{"id": "s9_d0", "characterId": "kevin", "text": "Hola."}, {"id": "s9_d1", "characterId": "gary", "text": "Voz."}],
            "scene3d": {"template": "user-moon-base", "cast": [{"characterId": "kevin", "objectId": "kevin"}]}}
    episode = {"id": "ep1", "shots": [shot]}
    lines = {"s9_d0": {"filename": "ln-a.wav", "duration": 1.2, "cues": [{"start": 0, "end": 0.4, "value": "D"}]},
             "s9_d1": {"filename": "ln-b.wav", "duration": 1.0, "cues": []}}
    heard = []
    render = SeriesNativeRender(NativeRenderDeps(call=call, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: {},
                                                 read_kits=lambda _ws: {}, room=lambda root, name, preset: heard.append(name) or room_filename(name, preset)))
    job = {"jobId": "native-1", "workspace": "cast", "seriesId": "uv", "episodeId": "ep1", "language": "spanish", "items": []}
    item = {"shotId": "s9", "stage": "scene", "lines": lines}
    render._scene3d("cast", job, item, series, episode, shot, {})
    talk = next(arguments for tool, arguments in calls if tool == "world3d.scene.talk")
    assert [line["audio"] for line in talk["lines"]] == [f"/api/v1/file/ln-a.room-cockpit-v{rooms.VERSION}.wav?workspace=cast"]
    assert talk["lines"][0]["cues"] == lines["s9_d0"]["cues"]
    patch = next(arguments for tool, arguments in calls if tool == "world3d.scene.patch" and "voiceOver" in arguments)
    assert [line["audio"] for line in patch["voiceOver"]] == ["/api/v1/file/ln-b.wav?workspace=cast"], \
        "gary has no object in the scene: a voice over it, not a voice in the cockpit"
    assert heard == ["ln-a.wav"] and lines["s9_d0"]["filename"] == "ln-a.wav"


# The DSP ----------------------------------------------------------------------

def _write(path, samples):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(np.round(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def _read(path):
    with wave.open(str(path)) as handle:
        assert handle.getframerate() == RATE and handle.getnchannels() == 1
        return np.frombuffer(handle.readframes(handle.getnframes()), "<i2").astype(float) / 32768


def _burst(seconds=1.0):
    """A voiced-sounding burst: three partials with a slow tremolo, hard edges, nothing after it."""
    t = np.arange(int(RATE * seconds)) / RATE
    tone = np.sin(2 * np.pi * 220 * t) + 0.7 * np.sin(2 * np.pi * 880 * t) + 0.5 * np.sin(2 * np.pi * 1800 * t)
    return 0.25 * tone * (1 + 0.4 * np.sin(2 * np.pi * 4 * t))


def _db(samples):
    return 20 * math.log10(float(np.sqrt(np.mean(samples ** 2))) + 1e-9)


@needs_ffmpeg
def test_a_cathedral_rings_on_after_the_line_and_without_a_room_nothing_does(tmp_path):
    _write(tmp_path / "ln-dry.wav", _burst())
    burst = int(RATE * 1.0)
    name = apply_room(str(tmp_path), "ln-dry.wav", "cathedral")
    assert name == f"ln-dry.room-cathedral-v{rooms.VERSION}.wav"
    heard = _read(tmp_path / name)
    assert (len(heard) - burst) / RATE == pytest.approx(MAX_RING, abs=0.01), "it rings on for the bound, no longer"
    early, late = _db(heard[burst + 2000:burst + 14000]), _db(heard[burst + 20000:burst + 32000])
    assert early > -40, "the tail is there after the line ends"
    assert early - late > 6, "and it dies away"
    assert np.abs(heard[-200:]).max() < 0.002, "faded out, not cut"
    assert len(_read(tmp_path / "ln-dry.wav")) == burst, "the dry line ends with the burst"
    assert apply_room(str(tmp_path), "ln-dry.wav", "none") == "ln-dry.wav", "no room, no copy"
    assert not any("none" in item for item in os.listdir(tmp_path))


@needs_ffmpeg
def test_every_place_is_felt_but_keeps_the_voice_clear(tmp_path):
    """C50 (direct and first 50 ms against the rest) and the room's level of a click heard through each preset, as rendered.
    The presets before 2026-10 measured C50 5.1 dB in the cathedral and 7.7 dB in the hall."""
    click = np.zeros(RATE * 4)
    click[RATE // 10] = 0.25
    _write(tmp_path / "ln-click.wav", click)
    for preset in sorted(set(ROOMS) - rooms.TRANSMISSIONS):
        response = _read(tmp_path / apply_room(str(tmp_path), "ln-click.wav", preset))[RATE // 10 - 50:] ** 2
        direct = float(np.sum(response[:150]))
        early = float(np.sum(response[:int(0.05 * RATE)]))
        c50, direct_to_room = 10 * math.log10(early / (float(np.sum(response)) - early)), 10 * math.log10(direct / (float(np.sum(response)) - direct))
        assert c50 >= 18, f"{preset}: the words stay clear ({c50:.1f} dB)"
        assert direct_to_room <= 25, f"{preset}: and the room is still there ({direct_to_room:.1f} dB under the voice)"
        assert abs(direct_to_room + ROOMS[preset].wet) < 3, \
            f"{preset}: at its own level ({direct_to_room:.1f} dB under), as the band and the tone leave it: the response is at unit energy"


@needs_ffmpeg
def test_the_rooms_without_a_reverb_tail_keep_the_length_of_the_line(tmp_path):
    _write(tmp_path / "ln-dry.wav", _burst(1.5))
    radio = _read(tmp_path / apply_room(str(tmp_path), "ln-dry.wav", "radio"))
    assert len(radio) == len(_read(tmp_path / "ln-dry.wav")), "a radio has no tail"
    outdoor = _read(tmp_path / apply_room(str(tmp_path), "ln-dry.wav", "outdoor"))
    assert 0.05 < (len(outdoor) - len(radio)) / RATE < 0.15, "the slap rings for a moment"


@needs_ffmpeg
@pytest.mark.parametrize("preset", sorted(ROOMS))
def test_a_room_never_changes_how_loud_the_voice_is(tmp_path, preset):
    _write(tmp_path / "ln-dry.wav", _burst(2.0))
    heard = apply_room(str(tmp_path), "ln-dry.wav", preset)
    wanted, got = integrated_lufs(str(tmp_path / "ln-dry.wav")), integrated_lufs(str(tmp_path / heard))
    assert wanted is not None and got is not None
    assert abs(got - wanted) < 1.0, (preset, wanted, got)
    assert np.abs(_read(tmp_path / heard)).max() <= 0.96, "limited, never clipped"


@needs_ffmpeg
def test_the_voice_starts_where_the_dry_one_does(tmp_path):
    click = np.zeros(RATE)
    click[RATE // 2:RATE // 2 + 8] = 0.6
    _write(tmp_path / "ln-click.wav", click)
    for preset in ROOMS:
        heard = _read(tmp_path / apply_room(str(tmp_path), "ln-click.wav", preset))
        assert abs(int(np.argmax(np.abs(heard[:RATE]))) - RATE // 2) < 22, f"{preset}: within half a millisecond"


@needs_ffmpeg
def test_a_copy_is_made_once_and_never_replaces_the_recording(tmp_path, monkeypatch):
    _write(tmp_path / "ln-dry.wav", _burst())
    digest = hashlib.sha1((tmp_path / "ln-dry.wav").read_bytes()).hexdigest()
    runs = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda command, *args, **kwargs: runs.append(command[0]) or real(command, *args, **kwargs))
    name = apply_room(str(tmp_path), "ln-dry.wav", "hall")
    assert runs and {os.path.basename(command) for command in runs} == {"ffmpeg"}, "ffmpeg did the work"
    made = (tmp_path / name).stat().st_mtime_ns
    runs.clear()
    assert apply_room(str(tmp_path), "ln-dry.wav", "hall") == name and runs == [] and (tmp_path / name).stat().st_mtime_ns == made
    assert hashlib.sha1((tmp_path / "ln-dry.wav").read_bytes()).hexdigest() == digest, "the dry recording is untouched"
    assert sorted(os.listdir(tmp_path)) == sorted(["ln-dry.wav", name, rooms.impulse_response_filename("hall")]), "no scratch files"
    other = apply_room(str(tmp_path), "ln-dry.wav", "room")
    assert other != name and (tmp_path / name).is_file() and runs, "each preset has its own copy"
    # A recording made again is not heard through the old copy.
    later = (tmp_path / name).stat().st_mtime + 10
    os.utime(tmp_path / "ln-dry.wav", (later, later))
    runs.clear()
    apply_room(str(tmp_path), "ln-dry.wav", "hall")
    assert runs, "newer than its copy: made again"


def test_a_copy_is_named_by_its_recording_its_preset_and_the_version(monkeypatch):
    assert room_filename("ln-ep1-s01_d0-1a2b3c.wav", "cathedral") == f"ln-ep1-s01_d0-1a2b3c.room-cathedral-v{rooms.VERSION}.wav"
    assert room_filename("ln-a.wav", "hall") != room_filename("ln-a.wav", "room") != room_filename("ln-b.wav", "room")
    before = room_filename("ln-a.wav", "hall")
    monkeypatch.setattr(rooms, "VERSION", rooms.VERSION + 1)
    assert room_filename("ln-a.wav", "hall") != before, "a new version of the processing makes new copies"
    assert rooms.impulse_response_filename("hall") != f"ln-room-hall-ir-v{rooms.VERSION - 1}.wav"


def test_a_missing_recording_or_missing_ffmpeg_is_an_error_not_a_dry_take(tmp_path, monkeypatch):
    with pytest.raises(RoomError, match="ln-gone.wav is not in the workspace"):
        apply_room(str(tmp_path), "ln-gone.wav", "hall")
    (tmp_path / "ln-a.wav").write_bytes(b"x")
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(RoomError, match="ffmpeg is not installed"):
        apply_room(str(tmp_path), "ln-a.wav", "hall")
    monkeypatch.setenv("FFMPEG_BINARY", str(tmp_path / "no-such-ffmpeg"))
    with pytest.raises(RoomError, match="did not run"):
        apply_room(str(tmp_path), "ln-a.wav", "hall")
    assert sorted(os.listdir(tmp_path)) == ["ln-a.wav", rooms.impulse_response_filename("hall")], "a failed copy leaves nothing half made"
