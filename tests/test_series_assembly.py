import pytest

from services.series_assembly import episode_assembly_plan


def _series():
    return {
        "assets": {
            "asset-1": {"id": "asset-1", "kind": "video", "uri": "outputs/one.mp4"},
            "asset-2": {"id": "asset-2", "kind": "video", "uri": "outputs/two.mp4"},
        },
    }


def test_episode_assembly_uses_approved_attempts_in_shot_order():
    episode = {"shots": [{
        "id": "shot-2", "order": 2, "approvedAttemptId": "attempt-2",
        "attempts": [{"id": "attempt-2", "status": "completed", "outputAssetIds": ["asset-2"]}],
    }, {
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "attempts": [{"id": "attempt-old", "status": "completed", "outputAssetIds": ["asset-2"]},
                     {"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"]}],
    }]}

    plan = episode_assembly_plan(_series(), episode)

    assert [item["shotId"] for item in plan] == ["shot-1", "shot-2"]
    assert [item["assetId"] for item in plan] == ["asset-1", "asset-2"]


def test_episode_assembly_requires_every_shot_to_be_approved():
    episode = {"shots": [{"id": "shot-1", "order": 1, "attempts": []}]}
    with pytest.raises(ValueError, match="Approve shot 1"):
        episode_assembly_plan(_series(), episode)


def test_episode_assembly_never_falls_back_to_a_rejected_or_newer_attempt():
    episode = {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-approved",
        "attempts": [
            {"id": "attempt-approved", "status": "completed", "outputAssetIds": ["asset-1"]},
            {"id": "attempt-newer", "status": "completed", "reviewDecision": "rejected", "outputAssetIds": ["asset-2"]},
        ],
    }]}
    assert episode_assembly_plan(_series(), episode)[0]["attemptId"] == "attempt-approved"
