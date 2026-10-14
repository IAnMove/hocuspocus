"""Model3D and rig cheap paths: capabilities, validation, missing jobs, unload.

Generate itself needs Hunyuan3D or a paid remote and is not recorded here.
"""
from __future__ import annotations


def test_model3d_and_rig_cheap_paths(server, golden) -> None:
    server.check(golden, "model3d capabilities", "GET", "/api/v1/model3d/capabilities")
    server.check(golden, "model3d images must be an object", "POST", "/api/v1/model3d/generate", json={"images": "front"})
    server.check(
        golden, "model3d missing front image", "POST", "/api/v1/model3d/generate",
        json={"images": {"front": "not-a-real-photo.png"}},
    )
    server.check(golden, "model3d missing job", "GET", "/api/v1/model3d/status/missing-job")
    server.check(golden, "model3d cancel missing", "POST", "/api/v1/model3d/jobs/missing-job/cancel")
    server.check(golden, "model3d unload", "POST", "/api/v1/model3d/unload")
    server.check(golden, "rig capabilities", "GET", "/api/v1/rig/capabilities")
    server.check(golden, "rig source required", "POST", "/api/v1/rig/generate", json={})
    server.check(golden, "rig source must be glb", "POST", "/api/v1/rig/generate", json={"source": "prop.obj"})
    server.check(golden, "rig missing source", "POST", "/api/v1/rig/generate", json={"source": "missing.glb"})
    server.check(golden, "rig missing job", "GET", "/api/v1/rig/status/missing-job")
    server.check(golden, "rig cancel missing", "POST", "/api/v1/rig/jobs/missing-job/cancel")
