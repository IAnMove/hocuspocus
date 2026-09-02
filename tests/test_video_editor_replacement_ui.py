"""Source contracts for replacing one Montage clip through Video Creation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "ui" / "src" / "features" / "video-editor" / "VideoEditorPanel.tsx"
HANDOFF = ROOT / "ui" / "src" / "features" / "video-editor" / "replacementHandoff.ts"
MAIN = ROOT / "ui" / "src" / "components" / "MainContent" / "MainContent.tsx"
FEED = ROOT / "ui" / "src" / "components" / "MainContent" / "MediaFeedItem.tsx"


def test_selected_montage_clip_can_be_opened_in_video_creation():
    editor = EDITOR.read_text(encoding="utf-8")

    assert "Rehacer en Creación de vídeo" in editor
    assert "fetchOutputMetadata(outputName, activeWorkspace)" in editor
    assert "loadSettingsFromOutput()" in editor
    assert "writeVideoEditorReplacementTarget" in editor
    assert "setMediaFilter('videos')" in editor
    assert "persistEditorDraft(clips, projectName, resolution, fps, draftWorkspaceRef.current)" in editor


def test_generated_video_can_replace_only_the_original_timeline_slot():
    editor = EDITOR.read_text(encoding="utf-8")
    handoff = HANDOFF.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    feed = FEED.read_text(encoding="utf-8")

    assert "maestro-video-editor-replacement-target-v1" in handoff
    assert "maestro-video-editor-replacement-result-v1" in handoff
    assert "t('montage.useInPosition'" in feed
    assert '"useInPosition": "Usar en posición {{n}}"' in (
        ROOT / "ui" / "src" / "i18n" / "locales" / "es" / "activity.json"
    ).read_text(encoding="utf-8")
    assert "writeVideoEditorReplacementResult" in feed
    assert "clearVideoEditorReplacementTarget" in main
    assert "readVideoEditorReplacementResult" in editor
    assert "clip.id === replacement.clipId" in editor
    assert "clearVideoEditorReplacementResult()" in editor
    assert "clearVideoEditorReplacementTarget()" in editor
    assert "persistEditorDraft(next, projectName, resolution, fps, draftWorkspaceRef.current)" in editor
