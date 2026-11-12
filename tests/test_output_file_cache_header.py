"""An output file served by name must be revalidated: the same name is rewritten by a re-render or a repainted texture, and a heuristically cached copy shows the old picture."""
import hashlib
from services import output_listing


def test_workspace_output_is_revalidated_and_a_pinned_hash_is_not(tmp_path, monkeypatch):
    path = tmp_path / "texture.png"
    path.write_bytes(b"first")
    monkeypatch.setattr(output_listing, "_resolve_output_file", lambda filename, workspace: str(path))
    assert output_listing.serve_file("texture.png", "ws").headers["cache-control"] == "no-cache"
    pinned = output_listing.serve_file("texture.png", "ws", hashlib.sha256(b"first").hexdigest())
    assert "cache-control" not in pinned.headers
