import copy
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from routers.series_episode import apply_series_episode_update
from services.series_library import normalize_series_library


EXAMPLE = Path(__file__).parents[1] / "docs" / "series-lab" / "example-series-library-v1.json"


def _series():
    library = normalize_series_library(json.loads(EXAMPLE.read_text(encoding="utf-8")), "default")
    return library["seriesById"]["series_signal"]


def test_stale_episode_put_returns_structured_409_and_keeps_server_attempt():
    series = _series()
    episode = series["episodesById"]["episode_1"]
    stale = copy.deepcopy(episode)
    stale_revision = series["revision"]
    server_attempt = {
        "id": "attempt-server", "status": "queued", "prompt": "server prompt",
        "negativePrompt": "", "model": "minimax_h3", "referenceManifest": {},
        "seed": 12, "settings": {}, "startTimeSeconds": 0, "endTimeSeconds": 10,
        "createdAt": "2026-08-16T09:00:00Z", "elapsedMs": 0,
        "outputAssetIds": [], "retryCount": 0,
    }
    episode["shots"][0]["attempts"].append(server_attempt)
    episode["updatedAt"] = "2026-08-16T09:00:00Z"
    series["revision"] += 1
    stale["title"] = "Stale tab edit"
    stale["shots"][0]["attempts"] = []

    with pytest.raises(HTTPException) as captured:
        apply_series_episode_update(
            "series_signal",
            "episode_1",
            {"episode": stale, "baseSeriesRevision": stale_revision},
            series,
            updated_at="2026-08-16T10:00:00Z",
        )

    assert captured.value.status_code == 409
    assert captured.value.detail == {
        "code": "series_episode_conflict",
        "message": "Series revision changed from 1 to 2; reload before saving",
        "seriesId": "series_signal",
        "episodeId": "episode_1",
        "currentSeriesRevision": 2,
        "currentEpisodeUpdatedAt": "2026-08-16T09:00:00Z",
    }
    assert series["episodesById"]["episode_1"]["shots"][0]["attempts"][-1] == server_attempt


def test_current_episode_put_changes_editor_fields_and_preserves_runtime():
    series = _series()
    episode = series["episodesById"]["episode_1"]
    current_shot = copy.deepcopy(episode["shots"][0])
    stale_shot = {**copy.deepcopy(current_shot), "prompt": "Edited prompt", "attempts": []}

    updated = apply_series_episode_update(
        "series_signal",
        "episode_1",
        {
            "episode": {"id": "episode_1", "title": "Edited title", "shots": [stale_shot]},
            "baseEpisodeUpdatedAt": episode["updatedAt"],
        },
        series,
        updated_at="2026-08-16T10:00:00Z",
    )
    saved = updated["episodesById"]["episode_1"]

    assert saved["title"] == "Edited title"
    assert saved["shots"][0]["prompt"] == "Edited prompt"
    assert saved["shots"][0]["attempts"] == current_shot["attempts"]
    assert saved["shots"][0]["approvedAttemptId"] == current_shot["approvedAttemptId"]
