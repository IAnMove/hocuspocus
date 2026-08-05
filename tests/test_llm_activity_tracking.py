from app.services import llm_service


def test_activity_tracking_accumulates_provider_reported_tokens():
    activity_id = "test-director-token-usage"
    llm_service.begin_activity_tracking(activity_id, phase="writing_scenes")

    def record_calls():
        llm_service._record_activity_usage({
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
        })
        llm_service._record_activity_usage({
            "input_tokens": 40,
            "output_tokens": 10,
        })

    llm_service.run_with_activity_tracking(activity_id, record_calls)
    state = llm_service.get_activity_tracking(activity_id)

    assert state["usage"] == {
        "prompt_tokens": 160,
        "completion_tokens": 40,
        "total_tokens": 200,
        "calls": 2,
    }


def test_activity_tracking_updates_internal_shot_progress():
    activity_id = "test-director-shot-progress"
    llm_service.begin_activity_tracking(activity_id, total=40)
    llm_service.update_activity_tracking(
        activity_id,
        phase="polishing_prompts",
        current=15,
        total=40,
        detail="A neon-lit close-up of Aria in the archive.",
    )

    state = llm_service.get_activity_tracking(activity_id)
    assert state["phase"] == "polishing_prompts"
    assert state["current"] == 15
    assert state["total"] == 40
    assert state["detail"].startswith("A neon-lit")
