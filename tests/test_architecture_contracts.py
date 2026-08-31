from __future__ import annotations

import ast
import json
from pathlib import Path

from scripts.architecture_contracts import (
    ROOT,
    ROUTE_FIXTURE,
    WIRE_FIXTURE,
    extract_route_table,
    extract_wire_inventory,
)


WGP_ALLOWLIST = {
    ("app/_launch_runtime.py", "<module>", "import wgp"),
    ("app/_launch_runtime.py", "rejoin_clips", "from wgp import concatenate_multi_clip_videos"),
    ("app/services/alternative_songs.py", "remount_clips", "from wgp import concatenate_multi_clip_videos"),
    ("app/services/director/prompt_polish.py", "load_lora_guides", "import wgp"),
    ("app/services/director/prompt_polish.py", "polish_prompts_third_pass._build_lora_hints", "import wgp"),
    ("app/services/director_pipeline.py", "_run_pipeline", "import wgp as _wgp_mod"),
    ("app/services/enhance_guides.py", "get_enhance_guide", "from wgp import get_model_def"),
    ("app/services/llm_service.py", "enhance_prompt", "from wgp import get_model_def"),
    ("app/services/model3d_service.py", "_active_profile", "import wgp"),
    ("app/services/model3d_service.py", "_minimax_api_key", "import wgp"),
    ("app/services/model3d_service.py", "_services", "import wgp"),
    ("app/shared/magic_mask.py", "_ensure_sam3_assets", "import wgp"),
    ("app/shared/magic_mask.py", "_video_to_numpy", "from wgp import get_resampled_video"),
}

IGNORED_WGP_TREES = (
    "app/models/",
    "app/plugins/",
    "app/postprocessing/mmaudio/",
    "app/postprocessing/seedvc/",
    "app/postprocessing/rife/",
    "app/postprocessing/flashvsr/",
    "app/preprocessing/sam3/",
)


def _wgp_imports() -> set[tuple[str, str, str]]:
    found = set()
    for path in (ROOT / "app").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(IGNORED_WGP_TREES) or "/env/" in relative or "/vendor/" in relative:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            is_wgp = isinstance(node, ast.Import) and any(alias.name == "wgp" for alias in node.names)
            is_wgp = is_wgp or isinstance(node, ast.ImportFrom) and node.module == "wgp"
            if not is_wgp:
                continue
            scopes = []
            current = node
            while current in parents:
                current = parents[current]
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    scopes.append(current.name)
            scope = ".".join(reversed(scopes)) or "<module>"
            found.add((relative, scope, ast.unparse(node)))
    return found


def test_static_route_table_matches_launch_and_mounted_router_order() -> None:
    fixture = json.loads(ROUTE_FIXTURE.read_text(encoding="utf-8"))
    assert fixture == {"version": 1, "routes": extract_route_table()}
    assert [route["ordinal"] for route in fixture["routes"]] == list(range(len(fixture["routes"])))


def test_architecture_wire_inventory_has_no_unclassified_readers() -> None:
    fixture = json.loads(WIRE_FIXTURE.read_text(encoding="utf-8"))
    assert fixture == {"version": 1, "entries": extract_wire_inventory()}
    assert all(entry["classification"] in {
        "behavior", "symbol_importable", "architecture_rule", "fragile_source",
    } for entry in fixture["entries"])


def test_first_party_wgp_imports_are_named_and_cannot_grow() -> None:
    found = _wgp_imports()
    generation_imports = {item for item in found if item[0].startswith("app/services/generation/")}
    assert found - generation_imports == WGP_ALLOWLIST, (
        "First-party WanGP imports changed. Add no new site; Step 1 must remove named entries "
        f"from the allowlist. Added={sorted(found - generation_imports - WGP_ALLOWLIST)!r}, "
        f"removed={sorted(WGP_ALLOWLIST - found)!r}"
    )
