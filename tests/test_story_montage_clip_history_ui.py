from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TIMELINE = ROOT / "ui" / "src" / "features" / "stories" / "StoryProductionTimeline.tsx"
HANDOFF = ROOT / "ui" / "src" / "features" / "stories" / "directorClipHandoff.ts"
MEDIA = ROOT / "ui" / "src" / "components" / "MainContent" / "MediaFeedItem.tsx"
MAIN = ROOT / "ui" / "src" / "components" / "MainContent" / "MainContent.tsx"
CLIENT = ROOT / "ui" / "src" / "api" / "client.ts"
STORE = ROOT / "ui" / "src" / "stores" / "useStore.ts"


def test_story_montage_exposes_slot_history_and_explicit_remake_action():
    timeline = TIMELINE.read_text(encoding="utf-8")

    assert "Historial de esta posición" in timeline
    assert "En montaje:" in timeline
    assert "Rehacer este clip" in timeline
    assert "selectPipelineClipVideo" in timeline
    assert "directorClipCreatorMetadata" in timeline
    assert "writeDirectorClipReplacementTarget" in timeline
    assert "fetchOutputMetadata(" in timeline
    assert "switchWorkspace(targetWorkspace)" in timeline


def test_creator_handoff_reduces_multiclip_metadata_to_one_exact_slot():
    handoff = HANDOFF.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")

    assert "perClipFrames[clip.index]" in handoff
    assert "source.per_clip_minimax_h3_references" in handoff
    assert "params.prompt = attempt.prompt || clip.video_prompt" in handoff
    assert "delete params[key]" in handoff
    assert "params.repeat_generation = 1" in handoff
    assert "newParams.minimax_h3_references" in store
    assert "newParams.h3_model_profile" in store


def test_generated_video_can_be_selected_and_returns_to_story_montage():
    media = MEDIA.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")

    assert "Usar en Montaje · clip" in media
    assert "writeDirectorClipReplacementResult" in media
    assert "setMediaFilter('stories')" in media
    assert "Ajusta sus datos, genera una o varias versiones" in main
    assert "Cancelar reemplazo" in main
    assert "/video-selection" in client
