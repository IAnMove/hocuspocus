from pathlib import Path

from services.media_refs import parse_media_ref

RUNTIME = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"


def test_video_editor_resolver_uses_parse_media_ref():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "from services.media_refs import parse_media_ref" in source
    assert "path, workspace = parse_media_ref(source, workspace)" in source



def test_parse_media_ref_strips_workspace_query_from_file_api_url():
    path, workspace = parse_media_ref(
        "/api/v1/file/minimax_h3_713afac9.mp4?workspace=default",
    )
    assert path == "/api/v1/file/minimax_h3_713afac9.mp4"
    assert workspace == "default"


def test_parse_media_ref_strips_workspace_query_from_bare_filename():
    path, workspace = parse_media_ref("minimax_h3_713afac9.mp4?workspace=default")
    assert path == "minimax_h3_713afac9.mp4"
    assert workspace == "default"


def test_parse_media_ref_accepts_absolute_http_file_url():
    path, workspace = parse_media_ref(
        "http://192.168.1.87:42004/api/v1/file/minimax_h3_713afac9.mp4?workspace=default",
    )
    assert path == "/api/v1/file/minimax_h3_713afac9.mp4"
    assert workspace == "default"


def test_parse_media_ref_keeps_explicit_workspace():
    path, workspace = parse_media_ref(
        "/api/v1/file/clip.mp4?workspace=other",
        workspace="films",
    )
    assert path == "/api/v1/file/clip.mp4"
    assert workspace == "films"


def test_parse_media_ref_passthrough_plain_filename():
    path, workspace = parse_media_ref("opening.mp4")
    assert path == "opening.mp4"
    assert workspace is None
