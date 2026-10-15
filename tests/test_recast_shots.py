"""Contracts of the Recast shot code (planning, manifest, assembly) that no other test pins.

Recorded against the shot functions while they still lived in ``app/_launch_runtime.py`` (the reviewed C7 head
e393f5746). The loader follows a function into the service module that defines it now, so the same assertions run
before and after the move. Collaborators are the real Recast helpers unless a test says otherwise. Nothing here
downloads a model or opens a network connection.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import numpy as np
import pytest
from PIL import Image

from tests.test_recast_helpers import ROOT, _block_network, _load

RECAST_MODULES = (
    "recast_masks",
    "recast_matte",
    "recast_reference_compose",
    "recast_reference_prepare",
    "recast_shot_planning",
    "recast_shot_manifest",
    "recast_shot_run",
    # The Recast routes (C8b) import the helper and shot modules directly.
    "recast_endpoint",
    "recast_preview",
)

PLANNING = (
    "_recast_probe_needs_bystander_tracking",
    "_detect_recast_shot_ranges",
    "_summarize_recast_mapping_mask",
    "_select_recast_timeline_anchor",
    "_normalize_recast_tracking_target",
    "_find_recast_unmapped_shots",
    "_recover_recast_unmapped_shots",
    "_plan_recast_shot_segments",
)
MANIFEST = (
    "_resample_recast_tracking_timeline",
    "_remap_recast_shot_mask",
    "_quantize_recast_shot_frame_count",
    "_build_recast_shot_prompt",
    "_resize_recast_shot_frames",
    "_write_recast_shot_video",
    "_build_recast_shot_reference_conditioning",
    "_build_recast_shot_manifest",
    "_write_recast_shot_aware_sidecar",
)


def _shot_code(extra: dict | None = None) -> dict:
    """The planning and manifest functions in one namespace, with the Recast helpers launch imported for them."""
    from services.recast_masks import _RECAST_MASK_COLORS, _RECAST_PROTECTION_COLORS, _recast_mask_region
    from services.recast_reference_compose import (
        _build_recast_mapping_appearance_prototypes,
        _build_recast_source_scene_reference,
        _compose_recast_cast_reference_frame,
        _compose_recast_group_reference_frame,
        _compose_recast_native_people_masks,
        _recast_appearance_descriptor,
    )
    from services.recast_reference_prepare import (
        _load_recast_reference_pair,
        _normalize_recast_person_count,
        _save_recast_reference_pair,
    )

    namespace = {
        "os": os,
        "time": time,
        "_RECAST_MASK_COLORS": _RECAST_MASK_COLORS,
        "_RECAST_PROTECTION_COLORS": _RECAST_PROTECTION_COLORS,
        "_recast_mask_region": _recast_mask_region,
        "_build_recast_mapping_appearance_prototypes": _build_recast_mapping_appearance_prototypes,
        "_build_recast_source_scene_reference": _build_recast_source_scene_reference,
        "_compose_recast_cast_reference_frame": _compose_recast_cast_reference_frame,
        "_compose_recast_group_reference_frame": _compose_recast_group_reference_frame,
        "_compose_recast_native_people_masks": _compose_recast_native_people_masks,
        "_recast_appearance_descriptor": _recast_appearance_descriptor,
        "_load_recast_reference_pair": _load_recast_reference_pair,
        "_normalize_recast_person_count": _normalize_recast_person_count,
        "_save_recast_reference_pair": _save_recast_reference_pair,
    }
    namespace.update(extra or {})
    return _load(PLANNING + MANIFEST, namespace)


def _presence(frame_count: int, visible: dict[int, int], size: int = 8) -> np.ndarray:
    """A T/H/W mapping mask: ``visible`` maps a frame index to how many pixels of the first rows are set."""
    mask = np.zeros((frame_count, size, size), dtype=np.uint8)
    for frame, pixels in visible.items():
        mask[frame].reshape(-1)[:pixels] = 1
    return mask


@pytest.mark.parametrize("module", RECAST_MODULES)
def test_each_recast_module_imports_on_its_own(module):
    """recast_masks and recast_shot_planning import each other. Each takes the other's names at the bottom of its
    file, so whichever a fresh interpreter imports first, the names the other asks for are already defined."""
    if not (ROOT / "app" / "services" / f"{module}.py").is_file():
        pytest.skip(f"{module} is not a module on this tree")
    result = subprocess.run(
        [sys.executable, "-c", f"import services.{module}"],
        cwd=ROOT / "app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


# -- shot planning ---------------------------------------------------------------------------------------------------
def test_a_group_shot_whose_characters_never_meet_anchors_on_the_largest_frame():
    """Two mapped characters in one camera shot, never in the same frame: no shared frame, the anchor is the frame
    with the most visible characters, then the largest total area (the later one on a tie)."""
    plan = _shot_code()["_plan_recast_shot_segments"]
    first = _presence(8, {0: 20, 1: 20, 2: 20, 3: 20})
    second = _presence(8, {4: 25, 5: 25, 6: 25, 7: 25})
    (segment,) = plan([first, second], [(0, 8)])
    assert segment == {
        "shot_index": 0,
        "camera_shot_index": 0,
        "cast_segment_index": 0,
        "segment_reason": "camera_shot",
        "start_frame": 0,
        "end_frame": 8,
        "frame_count": 8,
        "anchor_frame_index": 7,
        "first_all_active_frame_index": None,
        "active_mapping_indices": [0, 1],
        "initial_active_mapping_indices": [0],
        "starts_with_all_active_mappings": False,
        "cooccurring": False,
        "mode": "group",
    }


def test_a_brief_overlap_of_two_tracks_folds_into_the_longer_neighbour():
    """With cast transitions split, two frames where both tracks overlap are shorter than the hold and join the
    longer neighbouring cast (the second character's ten frames, not the first's eight)."""
    plan = _shot_code()["_plan_recast_shot_segments"]
    first = _presence(20, {frame: 30 for frame in range(10)})
    second = _presence(20, {frame: 30 for frame in range(8, 20)})
    segments = plan([first, second], [(0, 20)], split_cast_transitions=True, min_cast_run_frames=4)
    assert [(item["start_frame"], item["end_frame"], item["active_mapping_indices"], item["segment_reason"],
             item["cast_segment_index"], item["mode"], item["anchor_frame_index"], item["cooccurring"])
            for item in segments] == [
        (0, 8, [0], "camera_shot", 0, "solo", 7, True),
        (8, 20, [1], "cast_change", 1, "solo", 19, True),
    ]
    assert [item["shot_index"] for item in segments] == [0, 1]
    assert [item["camera_shot_index"] for item in segments] == [0, 0]


def test_short_presence_runs_at_either_end_take_their_only_neighbour():
    """A flicker at the start and at the end of a track, each shorter than the hold, takes the value of its single
    neighbouring run; the track then never counts as present and the camera shot passes the source through."""
    plan = _shot_code()["_plan_recast_shot_segments"]
    flicker = _presence(12, {0: 40, 1: 40, 11: 40})
    steady = _presence(12, {})
    segments = plan([flicker, steady], [(0, 12)], split_cast_transitions=True, min_cast_run_frames=4)
    assert [(item["start_frame"], item["end_frame"], item["active_mapping_indices"], item["mode"],
             item["anchor_frame_index"]) for item in segments] == [(0, 12, [], "passthrough", 0)]
    # Without the split, the same flicker is enough to make the track active in its camera shot.
    (whole,) = plan([flicker, steady], [(0, 12)])
    assert whole["active_mapping_indices"] == [0]
    assert whole["anchor_frame_index"] == 11
    assert whole["first_all_active_frame_index"] == 0


def test_planning_refuses_bad_timelines_and_reads_rgb_masks_and_bad_ranges():
    plan = _shot_code()["_plan_recast_shot_segments"]
    with pytest.raises(ValueError, match="needs tracked mapping masks"):
        plan([], [(0, 1)])
    with pytest.raises(ValueError, match="empty timeline"):
        plan([np.zeros((0, 4, 4), dtype=np.uint8)], [])
    with pytest.raises(ValueError, match="differ in length"):
        plan([_presence(4, {}), _presence(5, {})], [])
    with pytest.raises(ValueError, match="Unsupported Recast mapping-mask shape"):
        plan([np.zeros((4, 16), dtype=np.uint8)], [])

    rgb = np.zeros((6, 8, 8, 3), dtype=np.uint8)
    rgb[:, :4, :, 2] = 31  # 32 pixels over the 30 threshold in every frame
    dim = np.zeros((6, 8, 8, 3), dtype=np.uint8)
    dim[:, :, :, 0] = 30  # never over the threshold
    segments = plan([rgb, dim], [(4, 2), (-3, 2), (2, 99)], min_cast_run_frames="many",
                    split_cast_transitions=True)
    assert [(item["start_frame"], item["end_frame"], item["camera_shot_index"], item["active_mapping_indices"])
            for item in segments] == [(0, 2, 0, [0]), (2, 6, 1, [0])]
    # Ranges that select nothing fall back to the whole timeline.
    (whole,) = plan([rgb], [(3, 3), (9, 12)])
    assert (whole["start_frame"], whole["end_frame"]) == (0, 6)


def test_a_bad_hold_falls_back_to_four_frames():
    """``min_cast_run_frames`` that is not a number holds a presence run for four frames."""
    plan = _shot_code()["_plan_recast_shot_segments"]
    track = _presence(12, {frame: 30 for frame in (0, 1, 2, 6, 7, 8, 9, 10, 11)})
    other = _presence(12, {frame: 30 for frame in range(12)})
    held = plan([track, other], [(0, 12)], split_cast_transitions=True, min_cast_run_frames=None)
    four = plan([track, other], [(0, 12)], split_cast_transitions=True, min_cast_run_frames=4)
    three = plan([track, other], [(0, 12)], split_cast_transitions=True, min_cast_run_frames=3)
    assert held == four
    # With a four-frame hold the shortest short run is folded first: the three-frame start joins the three-frame
    # gap, which is then six frames long, so the track starts at frame 6. A three-frame hold keeps all three runs.
    assert [(item["start_frame"], item["end_frame"]) for item in four] == [(0, 6), (6, 12)]
    assert [item["active_mapping_indices"] for item in four] == [[1], [0, 1]]
    assert [(item["start_frame"], item["end_frame"]) for item in three] == [(0, 3), (3, 6), (6, 12)]


def test_summary_anchor_and_unmapped_shots_on_small_timelines():
    code = _shot_code()
    summarize = code["_summarize_recast_mapping_mask"]
    select = code["_select_recast_timeline_anchor"]
    find = code["_find_recast_unmapped_shots"]

    with pytest.raises(ValueError, match="Unsupported Recast mapping-mask shape"):
        summarize(np.zeros((4, 4), dtype=np.uint8))
    assert summarize(_presence(5, {})) is None
    summary = summarize(_presence(10, {1: 3, 2: 5, 6: 9, 7: 2}), fps=None)
    assert summary == {
        "first_frame_index": 1,
        "last_frame_index": 7,
        "anchor_frame_index": 6,
        "first_time_seconds": 0.04,
        "anchor_time_seconds": 0.24,
        "appearance_ranges": [[1, 3], [6, 8]],
        "anchor_area": 9,
        "present_frame_count": 4,
    }

    assert select([]) == (None, None)
    with pytest.raises(ValueError, match="different lengths"):
        select([_presence(3, {}), _presence(4, {})])
    shared = select([_presence(6, {1: 5, 2: 9, 4: 20}), _presence(6, {2: 4, 3: 30, 4: 1})])
    # Frames 2 and 4 hold both mappings; 4 has the larger total (20 + 1 against 9 + 4), so it is the shared anchor.
    assert shared == (4, 4)
    apart = select([_presence(6, {0: 5}), _presence(6, {5: 7})])
    assert apart == (None, 5)

    assert find([], [(0, 4)]) == []
    masks = [_presence(9, {0: 20, 1: 20, 6: 10}), _presence(9, {7: 15})]
    assert find(masks, [(0, 3), (3, 3), (3, 6), (6, 9), (8, 20)]) == [
        {"shot_index": 2, "start_frame": 3, "end_frame": 6},
        {"shot_index": 3, "start_frame": 6, "end_frame": 9},
        {"shot_index": 4, "start_frame": 8, "end_frame": 9},
    ]


def test_shot_detection_refuses_a_bad_shape_and_keeps_a_single_frame():
    detect = _shot_code()["_detect_recast_shot_ranges"]
    with pytest.raises(ValueError, match="T/H/W/RGB"):
        detect(np.zeros((3, 8, 8), dtype=np.uint8))
    assert detect(np.zeros((0, 8, 8, 3), dtype=np.uint8)) == []
    assert detect(np.zeros((1, 8, 8, 3), dtype=np.uint8)) == [(0, 1)]


def test_shot_detection_keeps_only_local_peaks_far_enough_from_the_edges():
    """A cut must be a local maximum of the change score and leave at least ``min_shot_frames`` on each side."""
    detect = _shot_code()["_detect_recast_shot_ranges"]
    rng = np.random.default_rng(7)
    colors = [rng.integers(0, 256, size=3) for _ in range(4)]

    def clip(cuts: list[int], frames: int) -> np.ndarray:
        out = np.zeros((frames, 36, 64, 3), dtype=np.uint8)
        color = 0
        for index in range(frames):
            if index in cuts:
                color += 1
            out[index] = colors[color % len(colors)]
        return out

    assert detect(clip([6], 12)) == [(0, 6), (6, 12)]
    # Too close to the start, too close to the end.
    assert detect(clip([2], 12)) == [(0, 12)]
    assert detect(clip([10], 12)) == [(0, 12)]
    # Two cuts closer than the minimum: only the first one counts.
    assert detect(clip([5, 7], 14)) == [(0, 5), (5, 14)]
    assert detect(clip([5, 7], 14), min_shot_frames=2) == [(0, 5), (5, 7), (7, 14)]


def test_a_two_frame_dissolve_cuts_where_the_change_peaks():
    """Both frames of a short dissolve change more than the cut threshold; the cut is the larger change, not the
    first frame over the threshold."""
    detect = _shot_code()["_detect_recast_shot_ranges"]
    frames = np.zeros((14, 36, 64, 3), dtype=np.uint8)
    frames[6] = 76  # 30% of the way to white
    frames[7:] = 255
    assert detect(frames) == [(0, 7), (7, 14)]


def test_the_bystander_probe_is_conservative_on_a_bad_frame_or_a_failed_segmentation(monkeypatch):
    probe = _shot_code()["_recast_probe_needs_bystander_tracking"]
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    assert probe(frame[0], frame, 1) is True
    assert probe(frame, frame[:4], 1) is True

    from shared import magic_mask

    def explode(*_args, **_kwargs):
        raise RuntimeError("SAM3 is not here")

    monkeypatch.setattr(magic_mask, "generate_keyword_masks", explode)
    assert probe(frame, frame, 1) is True


# -- unmapped-shot recovery ------------------------------------------------------------------------------------------
def _recovery(descriptors: dict[int, list[float] | None], prototypes: list[list[list[float]]]):
    """The recovery function with appearance stubs. A generic person is told apart by its area on the anchor frame:
    a person of ``n`` pixels has the descriptor ``descriptors[n]``; mapping ``m`` has the prototypes
    ``prototypes[m]``."""
    calls = []

    def build_prototypes(frames, masks, ranges):
        calls.append(("prototypes", len(masks), [tuple(item) for item in ranges]))
        return [[np.asarray(vector, dtype=np.float32) for vector in mapping] for mapping in prototypes]

    def descriptor(frame, region):
        area = int(region.sum())
        calls.append(("descriptor", area))
        value = descriptors.get(area)
        return None if value is None else np.asarray(value, dtype=np.float32)

    code = _shot_code({
        "_build_recast_mapping_appearance_prototypes": build_prototypes,
        "_recast_appearance_descriptor": descriptor,
    })
    return code["_recover_recast_unmapped_shots"], calls


def _people(frames: int, candidates: dict[int, int]) -> np.ndarray:
    """A compact people mask: candidate ``i`` painted in palette color ``i`` over ``candidates[i]`` pixels."""
    from services.recast_masks import _RECAST_MASK_COLORS

    people = np.zeros((frames, 8, 8, 3), dtype=np.uint8)
    flat = people.reshape(frames, -1, 3)
    offset = 0
    for index, pixels in candidates.items():
        flat[:, offset:offset + pixels] = _RECAST_MASK_COLORS[index]
        offset += pixels
    return people


def _painted(mask: np.ndarray, color) -> int:
    return int(np.all(mask == np.asarray(color, dtype=np.uint8), axis=-1).sum())


def test_recovery_gives_a_mapping_to_one_person_only():
    """Two generic people both look most like mapping 0. The better score takes it (score before area); the other
    person is not given mapping 0 a second time, and mapping 1, which nobody resembles, stays empty."""
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    recover, calls = _recovery({10: [1.0, 0.0], 6: [0.95, 0.1]}, [[[1.0, 0.0]], [[0.0, 1.0]]])
    frames = np.zeros((4, 8, 8, 3), dtype=np.uint8)
    masks = [np.zeros((4, 8, 8, 3), dtype=np.uint8) for _ in range(2)]
    people = _people(2, {0: 10, 1: 6})
    shot = [{"shot_index": 1, "start_frame": 2, "end_frame": 4}]
    out, recovered = recover(frames, masks, [(0, 2), (2, 4)], shot, people, [(0, 2)])
    assert recovered == [{"shot_index": 1, "mapping_index": 0, "similarity": 1.0, "margin": 1.0}]
    assert calls == [("prototypes", 2, [(0, 2), (2, 4)]), ("descriptor", 10), ("descriptor", 6)]
    assert (_painted(out[0][:2], colors[0]), _painted(out[0][2:], colors[0])) == (0, 2 * 10)
    assert not out[1].any()

    # The higher score wins even when that person is smaller.
    recover, _calls = _recovery({10: [0.9, 0.0], 6: [1.0, 0.0]}, [[[1.0, 0.0]], [[0.0, 1.0]]])
    masks = [np.zeros((4, 8, 8, 3), dtype=np.uint8) for _ in range(2)]
    out, recovered = recover(frames, masks, [(0, 2), (2, 4)], shot, people, [(0, 2)])
    assert recovered == [{"shot_index": 1, "mapping_index": 0, "similarity": 1.0, "margin": 1.0}]
    assert _painted(out[0][2:], colors[0]) == 2 * 6


def test_recovery_pairs_two_people_with_two_mappings_in_one_shot():
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    recover, _calls = _recovery({10: [1.0, 0.0], 6: [0.6, 0.8]}, [[[1.0, 0.0]], [[0.0, 1.0]]])
    frames = np.zeros((2, 8, 8, 3), dtype=np.uint8)
    masks = [np.zeros((2, 8, 8, 3), dtype=np.uint8) for _ in range(2)]
    people = _people(2, {0: 10, 1: 6})
    out, recovered = recover(frames, masks, [(0, 2)], [{"shot_index": 0, "start_frame": 0, "end_frame": 2}],
                             people, [(0, 2)])
    assert recovered == [
        {"shot_index": 0, "mapping_index": 0, "similarity": 1.0, "margin": 1.0},
        {"shot_index": 0, "mapping_index": 1, "similarity": 0.8, "margin": 0.2},
    ]
    assert (_painted(out[0], colors[0]), _painted(out[1], colors[1])) == (20, 12)
    # The masks are painted in place: the job's own arrays carry the recovery.
    assert _painted(masks[1], colors[1]) == 12


def test_recovery_skips_a_shot_whose_compact_range_does_not_match_and_a_person_with_no_descriptor():
    recover, calls = _recovery({4: None, 5: [0.0, 1.0]}, [[[1.0, 0.0]], [[0.0, 1.0]]])
    frames = np.zeros((6, 8, 8, 3), dtype=np.uint8)
    masks = [np.zeros((6, 8, 8, 3), dtype=np.uint8) for _ in range(2)]
    people = _people(3, {0: 4, 1: 5})
    shots = [{"shot_index": 0, "start_frame": 0, "end_frame": 2}, {"shot_index": 1, "start_frame": 3, "end_frame": 6}]
    # Shot 0 spans two source frames but three compact frames, shot 1's compact range is empty: both skipped.
    _out, recovered = recover(frames, masks, [(0, 3), (3, 6)], shots, people, [(0, 3), (3, 3)])
    assert recovered == []
    assert [call for call in calls if call[0] == "descriptor"] == []
    # Shot 1 with a matching range: the four-pixel person has no descriptor; the five-pixel one is mapping 1.
    _out, recovered = recover(frames, masks, [(0, 3), (3, 6)], shots[1:], people, [(0, 3)])
    assert recovered == [{"shot_index": 1, "mapping_index": 1, "similarity": 1.0, "margin": 1.0}]


def test_recovery_needs_the_similarity_the_margin_and_a_prototype():
    recover, _calls = _recovery({9: [0.75, 0.5]}, [[[1.0, 0.0]], [[0.0, 1.0]]])
    frames = np.zeros((2, 8, 8, 3), dtype=np.uint8)
    people = _people(2, {0: 9})
    shot = [{"shot_index": 0, "start_frame": 0, "end_frame": 2}]

    def run(**kwargs):
        masks = [np.zeros((2, 8, 8, 3), dtype=np.uint8) for _ in range(2)]
        return recover(frames, masks, [(0, 2)], shot, people, [(0, 2)], **kwargs)[1]

    # 0.75 against 0.5: similarity 0.75 >= 0.72 and margin 0.25 >= 0.06 (both exact in float32).
    assert run() == [{"shot_index": 0, "mapping_index": 0, "similarity": 0.75, "margin": 0.25}]
    assert run(minimum_similarity=0.76) == []
    assert run(minimum_margin=0.26) == []
    # Both limits are inclusive.
    assert run(minimum_similarity=0.75, minimum_margin=0.25) == run()
    # A mapping with no prototype is never chosen, even when the person is closer to it.
    recover, _calls = _recovery({9: [0.0, 1.0]}, [[[1.0, 0.0]], []])
    assert run() == []


# -- shot manifest helpers -------------------------------------------------------------------------------------------
def test_shot_length_quantisation_and_prompt_edges():
    code = _shot_code()
    quantize = code["_quantize_recast_shot_frame_count"]
    prompt = code["_build_recast_shot_prompt"]
    with pytest.raises(ValueError, match="at least one frame"):
        quantize(0, 5, 4)
    assert quantize(9, 1, 4) == (9, 0)
    assert quantize(10, 1, 4) == (13, 3)
    # A minimum that is not on the latent grid is lifted to the next valid length.
    assert quantize(3, 10, 4) == (13, 10)
    assert quantize(3, 0, 0) == (3, 0)

    assert prompt(2, finished_video_prompt="Two friends dance", total_mapping_count="two").startswith(
        "2 clearly defined characters"
    )
    assert prompt(2, finished_video_prompt="Two friends dance", total_mapping_count=2) == "Two friends dance"
    assert prompt(2, finished_video_prompt=" ... ", total_mapping_count=2).startswith("2 clearly defined")
    assert prompt(9, total_mapping_count=9).startswith("5 clearly defined")
    assert prompt(0).startswith("A clearly defined character")


def test_timeline_resampling_refuses_bad_counts_and_keeps_every_shot():
    resample = _shot_code()["_resample_recast_tracking_timeline"]
    frames = np.arange(10, dtype=np.uint8).reshape(10, 1, 1, 1).repeat(3, axis=-1)
    with pytest.raises(ValueError, match="must be positive"):
        resample(frames, [], [], 0)
    with pytest.raises(ValueError, match="do not match"):
        resample(frames, [np.zeros((9, 1, 1))], [], 5)
    source, masks, ranges = resample(frames, [np.arange(10).reshape(10, 1, 1)], [(0, 3), (3, 4), (4, 10)], 5)
    assert source[:, 0, 0, 0].tolist() == [0, 2, 4, 6, 8]
    assert masks[0][:, 0, 0].tolist() == [0, 2, 4, 6, 8]
    # Every shot keeps at least one frame, even the one-frame shot.
    assert ranges == [(0, 2), (2, 3), (3, 5)]
    # Frames are taken by flooring the source position: 10 -> 4 reads 0, 2.5, 5, 7.5 as 0, 2, 5, 7.
    source, _masks, ranges = resample(frames, [], [(0, 10)], 4)
    assert source[:, 0, 0, 0].tolist() == [0, 2, 5, 7]
    assert ranges == [(0, 4)]
    # More shots than frames: the extra shots are dropped.
    _source, _masks, ranges = resample(frames, [], [(0, 2), (2, 4), (4, 6), (6, 10)], 3)
    assert ranges == [(0, 1), (1, 2), (2, 3)]


def test_shot_mask_remap_moves_global_colors_to_local_slots():
    code = _shot_code()
    remap = code["_remap_recast_shot_mask"]
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    with pytest.raises(ValueError, match="H/W/RGB or T/H/W/RGB"):
        remap(np.zeros((2, 2, 4), dtype=np.uint8), [0])
    mask = np.zeros((2, 2, 3), dtype=np.uint8)
    mask[0, 0] = colors[2]
    mask[0, 1] = colors[4]
    mask[1, 0] = colors[0]
    out = remap(mask, [4, 2])
    assert [tuple(int(v) for v in out[0, 0]), tuple(int(v) for v in out[0, 1]),
            tuple(int(v) for v in out[1, 0]), tuple(int(v) for v in out[1, 1])] == [
        tuple(colors[1]), tuple(colors[0]), (255, 255, 255), (255, 255, 255),
    ]
    black = remap(mask, [], background_color=(0, 0, 0))
    assert not black.any()


def test_the_sidecar_keeps_upload_names_of_lists_and_drops_the_private_keys(monkeypatch):
    published = []
    import services.asset_manifest as asset_manifest

    monkeypatch.setattr(asset_manifest, "publish_generation_sidecar",
                        lambda path, sidecar, **kwargs: published.append((path, sidecar, kwargs)))
    write = _shot_code()["_write_recast_shot_aware_sidecar"]
    job = {
        "id": "job-7",
        "workspace": "ws",
        "params": {
            "prompt": "p",
            "generation_mode": "recast",
            "video_guide": "/tmp/in/source.mp4",
            "audio_guide": ["/a/one.wav", "", None, 3],
            "image_start": "",
            "_recast_shot_manifest": [1],
            "_recast_shot_temp_dir": "/tmp/x",
            "_recast_final_out_dir": "/tmp/y",
            "_recast_shot_bundle": {},
            "_defer_output_publication": True,
            "_recast_source_video": "/tmp/in/source.mp4",
            "_recast_protect_bystanders": True,
        },
    }
    write(job, "/out/final.mp4", {"frame_count": "24", "resolved_seed": "7", "published_shots": [{"id": 1}]}, 2.6)
    ((path, sidecar, kwargs),) = published
    assert path == "/out/final.mp4"
    assert kwargs == {"workspace_id": "ws", "tool": "recast"}
    assert sidecar["upload_filenames"] == {"video_guide": "source.mp4", "audio_guide": ["one.wav", "", "", ""]}
    # edit-11: the worker-private source path and protection flag are dropped like the other private keys.
    assert sorted(sidecar["params"]) == [
        "audio_guide", "edit_recast_shot_aware", "edit_recast_shot_plan", "generation_mode",
        "image_start", "prompt", "seed", "video_guide", "video_length",
    ]
    assert (sidecar["params"]["video_length"], sidecar["params"]["seed"]) == (24, 7)
    assert sidecar["params"]["edit_recast_shot_plan"] == [{"id": 1}]
    assert (sidecar["generation_time"], sidecar["job_id"], sidecar["output_filename"]) == (3, "job-7", "final.mp4")
    assert sidecar["generation_mode"] == "recast"
    # The job's own params are untouched.
    assert "_recast_shot_manifest" in job["params"]


# -- shot reference conditioning --------------------------------------------------------------------------------------
def _reference_stubs(calls: list, *, group_fails: bool = False):
    def load(image, mask, global_index, local_index):
        calls.append(("load", os.path.basename(image), os.path.basename(mask), global_index, local_index))
        return np.full((4, 4, 3), 10 + global_index, dtype=np.uint8), np.full((4, 4, 3), local_index, dtype=np.uint8)

    def group(frame, semantic, layers, count):
        calls.append(("group", int(frame[0, 0, 0]), len(layers), count))
        if group_fails:
            raise ValueError("no slot fits")
        return np.full((4, 4, 3), 1, dtype=np.uint8), np.full((4, 4, 3), 2, dtype=np.uint8)

    def cast(layers, count, canvas):
        calls.append(("cast", len(layers), count, tuple(canvas)))
        return np.full((4, 4, 3), 3, dtype=np.uint8), np.full((4, 4, 3), 4, dtype=np.uint8)

    def save(output_dir, stem, image, mask):
        calls.append(("save", stem, int(image[0, 0, 0]), int(mask[0, 0, 0])))
        return os.path.join(output_dir, f"{stem}.png"), os.path.join(output_dir, f"{stem}_mask.png")

    def scene(frame, semantic, count, output_dir, job_id, output_size=None):
        calls.append(("scene", count, job_id, output_size))
        return {"image": f"scene_{job_id}.png", "mask": f"scene_{job_id}_mask.png"}

    return {
        "_load_recast_reference_pair": load,
        "_compose_recast_group_reference_frame": group,
        "_compose_recast_cast_reference_frame": cast,
        "_save_recast_reference_pair": save,
        "_build_recast_source_scene_reference": scene,
    }


def _prepared(colors):
    return {
        "image_refs": ["a0.png", "b0.png", "a1.png", "", "a2.png", "a3.png"],
        "primary_mask": "a0_mask.png",
        "additional_masks": ["b0_mask.png", "a1_mask.png", "x_mask.png", "a2_mask.png", "a3_mask.png"],
        "expected_colors": [list(colors[0]), list(colors[1]), list(colors[0]), list(colors[0]), None, ["x", 1, 2]],
        "primary_target_refs": [
            {"mapping_index": 0, "image": "p0.png", "mask": "p0_mask.png"},
            {"mapping_index": 1, "image": "p1.png", "mask": "p1_mask.png"},
            "not a dict",
        ],
    }


def test_a_group_shot_whose_characters_never_share_a_frame_uses_a_cast_sheet(tmp_path, capsys):
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    calls: list = []
    build = _shot_code(_reference_stubs(calls))["_build_recast_shot_reference_conditioning"]
    frame = np.full((4, 4, 3), 9, dtype=np.uint8)
    out = build(_prepared(colors), [1, 0], frame, frame, str(tmp_path), "j", 2,
                cooccurring=False, reference_canvas=[32, 48])
    stem = "recast_shot_ref_j_3"
    assert calls == [
        ("load", "p1.png", "p1_mask.png", 1, 0),
        ("load", "p0.png", "p0_mask.png", 0, 1),
        ("cast", 2, 2, (32, 48)),
        ("save", stem, 3, 4),
        ("scene", 2, "j_shot_3", (32, 48)),
    ]
    assert out == {
        "image_refs": [os.path.join(str(tmp_path), f"{stem}.png")],
        "primary_mask": os.path.join(str(tmp_path), f"{stem}_mask.png"),
        "additional_masks": [],
        "expected_colors": [None],
        "clip_identity_ref": os.path.join(str(tmp_path), f"{stem}.png"),
        "source_scene_reference": {"image": "scene_j_shot_3.png", "mask": "scene_j_shot_3_mask.png"},
        "primary_mode": "cast_sheet",
    }
    printed = capsys.readouterr().out
    assert "[Recast] Shot 3 has no usable shared layout; using a balanced cast sheet: active characters never " \
           "share one frame in this shot" in printed
    assert "[Recast] Shot 3 uses one balanced 2-character reference; omitted 3 separate identity view(s)" in printed


def test_a_group_shot_falls_back_to_a_cast_sheet_when_no_slot_fits(tmp_path, capsys):
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    calls: list = []
    build = _shot_code(_reference_stubs(calls, group_fails=True))["_build_recast_shot_reference_conditioning"]
    frame = np.full((4, 4, 3), 9, dtype=np.uint8)
    out = build(_prepared(colors), [0, 1], frame, frame, str(tmp_path), "j", 0,
                cooccurring=True, reference_canvas=(16, 16))
    assert [call[0] for call in calls] == ["load", "load", "group", "cast", "save", "scene"]
    assert calls[2] == ("group", 9, 2, 2)
    assert out["primary_mode"] == "cast_sheet"
    assert "using a balanced cast sheet: no slot fits" in capsys.readouterr().out


def test_a_solo_shot_keeps_its_identity_views_and_skips_broken_ones(tmp_path):
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    calls: list = []
    build = _shot_code(_reference_stubs(calls))["_build_recast_shot_reference_conditioning"]
    frame = np.full((4, 4, 3), 9, dtype=np.uint8)
    out = build(_prepared(colors), [0], frame, frame, str(tmp_path), "s", 0,
                cooccurring=True, reference_canvas=(16, 16))
    stem = "recast_shot_ref_s_1"
    # Views of mapping 0: a0 and a1 (b0 is mapping 1, the empty path and the None/bad colors are skipped).
    assert out["image_refs"] == [os.path.join(str(tmp_path), f"{stem}.png"), "a0.png", "a1.png"]
    assert out["additional_masks"] == [os.path.join(str(tmp_path), f"{stem}_identity_1_mask.png"),
                                       os.path.join(str(tmp_path), f"{stem}_identity_2_mask.png")]
    assert out["expected_colors"] == [list(colors[0])] * 3
    assert out["clip_identity_ref"] == "a0.png"
    assert out["primary_mode"] == "shot_layout"
    assert [call for call in calls if call[0] == "load"] == [
        ("load", "p0.png", "p0_mask.png", 0, 0),
        ("load", "a0.png", "a0_mask.png", 0, 0),
        ("load", "a1.png", "a1_mask.png", 0, 0),
    ]
    saved = np.asarray(Image.open(tmp_path / f"{stem}_identity_2_mask.png"))
    assert saved.shape == (4, 4, 3) and int(saved.max()) == 0


def test_shot_references_refuse_no_cast_unsynced_pairs_and_a_missing_primary(tmp_path):
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    calls: list = []
    build = _shot_code(_reference_stubs(calls))["_build_recast_shot_reference_conditioning"]
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    kwargs = {"cooccurring": True, "reference_canvas": (8, 8)}
    with pytest.raises(ValueError, match="needs an active character"):
        build(_prepared(colors), [], frame, frame, str(tmp_path), "e", 0, **kwargs)
    broken = dict(_prepared(colors), expected_colors=[None])
    with pytest.raises(ValueError, match="out of sync"):
        build(broken, [0], frame, frame, str(tmp_path), "e", 0, **kwargs)
    with pytest.raises(ValueError, match="Missing primary reference for Recast mapping 3"):
        build(_prepared(colors), [2], frame, frame, str(tmp_path), "e", 0, **kwargs)
    assert calls == []


# -- the whole manifest, with the real resize, video writer and reference helpers -------------------------------------
def _reference_pair(folder, name: str, color) -> tuple[str, str]:
    image = np.zeros((48, 32, 3), dtype=np.uint8)
    image[8:40, 8:24] = (200, 150, 120)
    mask = np.zeros((48, 32, 3), dtype=np.uint8)
    mask[8:40, 8:24] = color
    image_path, mask_path = folder / f"{name}.png", folder / f"{name}_mask.png"
    Image.fromarray(image).save(image_path)
    Image.fromarray(mask).save(mask_path)
    return str(image_path), str(mask_path)


def _decoded_frames(path: str) -> int:
    import imageio.v2 as imageio

    reader = imageio.get_reader(path)
    try:
        return sum(1 for _ in reader)
    finally:
        reader.close()


@pytest.mark.parametrize("cast", ["solo then empty", "two together then solo"])
def test_the_shot_manifest_writes_guides_masks_and_references_for_each_camera_shot(tmp_path, monkeypatch, cast):
    """Two camera shots, written with the real helpers: each generated shot gets a guide, a semantic mask and its
    references at the canvas size, padded to the model length; a shot nobody is mapped in is passed through."""
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    _block_network(monkeypatch)
    build = _shot_code()["_build_recast_shot_manifest"]
    frames = np.zeros((12, 24, 16, 3), dtype=np.uint8)
    frames[:6] = (40, 80, 120)
    frames[6:] = (120, 60, 30)
    first = np.zeros((12, 24, 16), dtype=np.uint8)
    second = np.zeros((12, 24, 16), dtype=np.uint8)
    first[:, 4:20, 2:7] = 1
    if cast == "two together then solo":
        second[:6, 4:20, 9:14] = 1
    else:
        first[6:] = 0
    refs = tmp_path / "refs"
    refs.mkdir()
    pairs = [_reference_pair(refs, f"card{index}", colors[index]) for index in range(2)]
    prepared = {
        "image_refs": [pairs[0][0], pairs[1][0]],
        "primary_mask": pairs[0][1],
        "additional_masks": [pairs[1][1]],
        "expected_colors": [list(colors[0]), list(colors[1])],
        "primary_target_refs": [
            {"mapping_index": index, "image": pairs[index][0], "mask": pairs[index][1]} for index in range(2)
        ],
    }
    out_dir = tmp_path / "shots"
    manifest = build(
        {"prompt": "Two friends talk", "custom_settings": {"scail2_recast_warmup_frames": "x", "keep": 1}},
        {"source_frames": frames, "mapping_masks": [first, second], "shot_ranges": [(0, 6), (6, 12)]},
        prepared, str(out_dir), "m", reference_canvas=(32, 48), target_frame_count=12, generation_fps=8,
        minimum_frames=5, latent_size=4,
    )
    assert (manifest["frame_count"], manifest["fps"], manifest["camera_shot_count"]) == (12, 8.0, 2)
    assert manifest["cast_transition_count"] == 0
    published = manifest["published_shots"]
    tasks = manifest["tasks"]
    if cast == "solo then empty":
        assert [shot["generation_mode"] for shot in published] == ["scail2", "source_passthrough"]
        assert [task["shot_index"] for task in tasks] == [0]
        assert manifest["shots"][1]["passthrough_path"] == str(out_dir / "recast_m_shot_2_source.mp4")
        assert _decoded_frames(manifest["shots"][1]["passthrough_path"]) == 6
    else:
        assert [shot["generation_mode"] for shot in published] == ["scail2", "scail2"]
        assert [task["shot_index"] for task in tasks] == [0, 1]
    task = tasks[0]["params"]
    assert task["video_length"] == 9 and task["trim_tail_frames"] == 3
    assert published[0]["generated_frame_count"] == 9 and published[0]["trim_tail_frames"] == 3
    assert task["video_guide"] == str(out_dir / "recast_m_shot_1_guide.mp4")
    assert task["video_mask"] == str(out_dir / "recast_m_shot_1_mask.mp4")
    assert _decoded_frames(task["video_guide"]) == 9
    assert _decoded_frames(task["video_mask"]) == 9
    assert task["output_filename"] == "recast_m_shot_1.mp4"
    assert task["force_fps"] == "control"
    assert task["_recast_protect_bystanders"] is False
    assert (task["audio_prompt_type"], task["audio_guide"], task["audio_source"]) == ("", None, None)
    settings = task["custom_settings"]
    assert settings["keep"] == 1
    assert settings["scail2_primary_reference_people"] == len(published[0]["active_mapping_indices"])
    assert settings["scail2_dynamic_source_scene_reference"] is True
    assert settings["scail2_timeline_source_scene_reference"] is False
    assert settings["scail2_identity_latent_reference_index"] == 0
    for key in ("scail2_reference_mask_path", "scail2_source_scene_reference_path", "scail2_source_scene_mask_path"):
        assert os.path.isfile(settings[key]), key
    with Image.open(task["image_refs"][0]) as primary:
        assert primary.size == (32, 48)
    if cast == "solo then empty":
        assert task["prompt"].startswith("A clearly defined character")
        assert task["video_prompt_type"] == "V01AI"
        assert published[0]["reference_mode"] == "shot_layout"
        assert task["image_refs"][1:] == [pairs[0][0]]
    else:
        assert task["prompt"] == "Two friends talk"
        assert task["video_prompt_type"] == "V02AI"
        assert published[0]["active_mapping_indices"] == [0, 1]
        assert len(task["image_refs"]) == 1
        assert tasks[1]["params"]["video_prompt_type"] == "V01AI"


def test_a_late_entrant_gets_a_latent_aligned_pre_roll_from_its_shot_and_the_first_mapping_keeps_overlaps():
    """The second camera shot starts at frame 4 and its second character enters at frame 10. The hidden identity
    pre-roll is the requested 8 frames rounded up to the 3-frame latent grid, anchored on the shot's own timeline.
    Where two tracked mappings cover the same pixel, the first mapping keeps it."""
    from services.recast_masks import _RECAST_MASK_COLORS as colors

    captured: list = []
    written: list = []
    guides: list = []

    def references(prepared, active, frame, mask, output_dir, job_id, shot_index, *, cooccurring, reference_canvas):
        captured.append({"active": list(active), "mask": mask.copy(), "shot": shot_index, "cooccurring": cooccurring})
        return {"image_refs": [f"ref{shot_index}.png"], "primary_mask": f"ref{shot_index}_mask.png",
                "additional_masks": [], "expected_colors": [None], "clip_identity_ref": "clip.png",
                "source_scene_reference": {"image": "scene.png", "mask": "scene_mask.png"}, "primary_mode": "stub"}

    def write(path, frames, fps, *, semantic=False):
        written.append((os.path.basename(path), len(frames), semantic))
        if not semantic:
            guides.append([int(frame[0, 0, 0]) for frame in frames])
        return path

    code = _shot_code()
    # The loaded functions share one namespace: replacing two of its names after loading reaches the manifest.
    code.update(_build_recast_shot_reference_conditioning=references, _write_recast_shot_video=write)
    build = code["_build_recast_shot_manifest"]
    frames = (np.arange(16, dtype=np.uint8) * 10).reshape(16, 1, 1, 1).repeat(8, 1).repeat(8, 2).repeat(3, 3)
    first = np.zeros((16, 8, 8), dtype=np.uint8)
    second = np.zeros((16, 8, 8), dtype=np.uint8)
    first[:, :, :5] = 1  # 40 pixels in every frame
    second[10:, :, 3:] = 1  # 40 pixels from frame 10, overlapping the first in columns 3 and 4
    second[12, :, 2:] = 1  # its largest frame
    manifest = build(
        {"prompt": "", "custom_settings": {"scail2_recast_warmup_frames": 8}},
        {"source_frames": frames, "mapping_masks": [first, second], "shot_ranges": [(0, 4), (4, 16)]},
        {}, "unused", "w", reference_canvas=(8, 8), target_frame_count=16, generation_fps=16,
        minimum_frames=1, latent_size=3,
    )
    late = manifest["published_shots"][1]
    assert (late["start_frame"], late["end_frame"], late["active_mapping_indices"]) == (4, 16, [0, 1])
    assert (late["anchor_frame_index"], late["first_all_active_frame_index"]) == (12, 10)
    assert late["identity_warmup_frames"] == 9
    assert late["identity_warmup_anchor_frame_index"] == 12
    settings = manifest["tasks"][1]["params"]["custom_settings"]
    assert settings["scail2_recast_warmup_frames"] == 9
    assert settings["scail2_recast_warmup_anchor_offset"] == 8
    assert "identity_warmup_frames" not in manifest["published_shots"][0]
    # The anchor mask of shot 2: the overlap (columns 3-4) is the first mapping's, the rest of the second's is its own.
    anchor = captured[1]["mask"]
    assert captured[1]["active"] == [0, 1] and captured[1]["cooccurring"] is True
    assert tuple(int(v) for v in anchor[0, 3]) == tuple(colors[0])
    assert tuple(int(v) for v in anchor[0, 6]) == tuple(colors[1])
    assert tuple(int(v) for v in anchor[0, 1]) == tuple(colors[0])
    assert [item for item in written if item[2]] == [("recast_w_shot_1_mask.mp4", 4, True),
                                                   ("recast_w_shot_2_mask.mp4", 13, True)]
    # Shot 1's anchor mask is black where nobody is mapped. Shot 2 (12 frames) is padded to 13 with its last frame.
    assert tuple(int(v) for v in captured[0]["mask"][0, 7]) == (0, 0, 0)
    assert guides == [[0, 10, 20, 30], [40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 150]]


def test_shot_videos_are_written_with_their_codec_settings(tmp_path, monkeypatch):
    """Guides are libx264 at quality 9 in yuv420p; semantic masks use the magic-mask codec settings."""
    import imageio.v2 as imageio
    from shared import magic_mask

    opened: list = []

    class Writer:
        def __init__(self, path, **kwargs):
            opened.append([os.path.basename(path), kwargs, 0])

        def append_data(self, frame):
            opened[-1][2] += 1

        def close(self):
            opened[-1].append("closed")

    monkeypatch.setattr(imageio, "get_writer", Writer)
    monkeypatch.setattr(magic_mask, "_magic_mask_video_codec_params", lambda: {"codec": "semantic-codec"})
    write = _shot_code()["_write_recast_shot_video"]
    frames = np.zeros((3, 4, 4, 3), dtype=np.uint8)
    assert write(str(tmp_path / "a" / "guide.mp4"), frames, 12) == str(tmp_path / "a" / "guide.mp4")
    write(str(tmp_path / "mask.mp4"), frames, "8", semantic=True)
    assert opened == [
        ["guide.mp4", {"fps": 12.0, "ffmpeg_log_level": "error", "codec": "libx264", "quality": 9,
                       "pixelformat": "yuv420p", "macro_block_size": 1}, 3, "closed"],
        ["mask.mp4", {"fps": 8.0, "ffmpeg_log_level": "error", "codec": "semantic-codec"}, 3, "closed"],
    ]
    assert (tmp_path / "a").is_dir()
