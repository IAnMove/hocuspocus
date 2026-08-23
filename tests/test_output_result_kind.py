import os
import sys

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services.output_result_kind import (  # noqa: E402
    classify_output_result_kind,
    result_kind_for_pipeline,
)


def test_series_assembly_filename_is_an_episode_result():
    assert classify_output_result_kind(
        "2026-08-21-00h00m00s_ep1_series_assembly.mp4",
        {},
    ) == "series_episode"


def test_component_clip_is_not_a_result():
    assert classify_output_result_kind("minimax_h3_aefe293b.mp4", {}) is None


def test_music_video_concat_uses_pipeline_type():
    assert classify_output_result_kind(
        "minimax_h3_dcd06270_multiclip.mp4",
        {"pipeline_type": "music_video", "director_pipeline_id": "dcd06270"},
    ) == "music_video"


def test_trailer_concat_uses_production_kind():
    assert classify_output_result_kind(
        "minimax_h3_abc_multiclip.mp4",
        {"pipeline_type": "short_film_story", "production_kind": "trailer"},
    ) == "trailer"


def test_legacy_multiclip_with_director_id_counts_as_music_video():
    assert classify_output_result_kind(
        "minimax_h3_dcd06270_multiclip.mp4",
        {"director_pipeline_id": "dcd06270", "source_clips": ["a.mp4"]},
    ) == "music_video"


def test_unassembled_clip_stays_out_of_mix_tabs():
    assert classify_output_result_kind(
        "minimax_h3_813f5ea0.mp4",
        {"pipeline_type": "short_film_story", "result_kind": "series_episode"},
    ) is None


def test_pipeline_params_detect_trailer_brief():
    assert result_kind_for_pipeline({
        "pipeline_type": "short_film_story",
        "scene_description": "CREATE AN EPIC CINEMATIC STORY TRAILER — NOT A SHORT FILM",
    }) == "trailer"


def test_short_film_mix_is_a_chapter():
    assert classify_output_result_kind(
        "overnight_moria_multiclip.mp4",
        {"pipeline_type": "short_film_story", "result_kind": "series_episode"},
    ) == "series_episode"
    assert classify_output_result_kind(
        "overnight_moria_multiclip.mp4",
        {"pipeline_type": "short_film_story"},
    ) == "chapter"
    assert result_kind_for_pipeline({"pipeline_type": "short_film_story"}) == "chapter"


def test_music_video_mux_filename_is_a_videoclip():
    assert classify_output_result_kind(
        "overnight_fangorn_mv.mp4",
        {"result_kind": "music_video", "pipeline_type": "music_video"},
    ) == "music_video"


def test_chapter_filter_includes_episodes_and_chapters():
    from services.output_result_kind import result_kind_matches_filter
    assert result_kind_matches_filter("chapter", "series_episode")
    assert result_kind_matches_filter("series_episode", "series_episode")
    assert not result_kind_matches_filter("music_video", "series_episode")
    assert not result_kind_matches_filter(None, "music_video")
