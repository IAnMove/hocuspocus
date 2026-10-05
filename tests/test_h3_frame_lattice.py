"""One H3 frame lattice for the sidecar, Series, the Director and the handler."""
from services import h3_frame_lattice as lattice
from services.minimax_h3_duration import DEFAULT_WORDS_PER_SECOND, words_budget
from services.series_render import quantize_h3_frames


def test_the_lattice_is_17n_plus_5_between_124_and_345():
    assert [lattice.align_up(value) for value in (1, 5, 6, 124, 125, 345, 346)] == [5, 5, 22, 124, 141, 345, 362]
    assert [lattice.align_nearest(value) for value in (124, 132, 133, 141, 350)] == [124, 124, 141, 141, 345]
    assert lattice.clamp(5) == 124 and lattice.clamp(362) == 345 and lattice.clamp(243) == 243
    assert lattice.frames_for_seconds(10) == 243 and lattice.frames_for_seconds(15) == 345 and lattice.frames_for_seconds(1) == 124
    assert lattice.frames_for_seconds("x") == lattice.frames_for_seconds(float("inf")) == 243
    assert lattice.seconds_for_frames(345) == 14.375


def test_every_path_reads_the_same_numbers():
    from models.minimax_h3 import minimax_h3_handler as handler
    from services import director_pipeline, minimax_h3_service
    definition = minimax_h3_service.MODEL_DEFINITION if hasattr(minimax_h3_service, "MODEL_DEFINITION") else None
    source = open(minimax_h3_service.__file__, encoding="utf-8").read()
    assert '"frames_maximum": h3_frame_lattice.MAX_FRAMES' in source and '"frame_alignment_mode": "ceil"' in source
    assert "362" not in source.replace("17 * 21 + 5", ""), "the sidecar no longer carries its own 362 cap"
    assert (handler._H3_MIN_FRAMES, handler._H3_MAX_FRAMES, handler._H3_FRAME_STEP) == (124, 345, 17)
    assert quantize_h3_frames(15, reference_mode=False) == 345 and quantize_h3_frames(10.0, reference_mode=True) == 243
    segments = director_pipeline._minimax_h3_frame_segments(45.0)
    assert all(124 <= frames <= 345 and frames % 17 == 5 for frames in segments)
    del definition


def test_one_speech_rate_for_planners_and_validators():
    from services.director.planners import short_film
    assert short_film._H3_DIALOGUE_WORDS_PER_SECOND == DEFAULT_WORDS_PER_SECOND == 2.16
    assert words_budget(14.375) == 31 and words_budget(5) == 10 and words_budget(0) == 0
