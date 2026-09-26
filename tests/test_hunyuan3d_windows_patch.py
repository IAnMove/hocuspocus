"""Hunyuan3D-2.1 rasterizer sources get Hunyuan3D-2's MSVC fixes."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "patch_windows_sources", ROOT / "app/services/hunyuan3d/patch_windows_sources.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def test_grid_neighbor_sizes_are_cast_and_long_pointers_become_int64():
    source = (
        "    texture_positions[0] = torch::zeros({seq2pos.size() / 3, 3}, float_options);\n"
        "        long* nptr = grid_neighbors[i].data_ptr<long>();\n"
    )
    patched = patch.patch_source("grid_neighbor.cpp", source)
    assert "torch::zeros({static_cast<int64_t>(seq2pos.size() / 3), static_cast<int64_t>(3)}" in patched
    assert "int64_t* nptr = grid_neighbors[i].data_ptr<int64_t>();" in patched
    assert patch.patch_source("grid_neighbor.cpp", patched) == patched


def test_rasterizer_uses_int64_depth_buffer_pointers():
    source = ("auto z_min = torch::ones({height, width}, INT64_options) * (long)maxint;\n"
              "(INT64*)z_min.data_ptr<long>(), width\n")
    patched = patch.patch_source("rasterizer_gpu.cu", source)
    assert "(int64_t)maxint" in patched and "data_ptr<int64_t>()" in patched
    assert "torch::ones({height, width}" in patched  # Only grid_neighbor sizes are recast.
