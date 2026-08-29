import json
import struct
from pathlib import Path

from services.hunyuan3d.weight_integrity import (
    purge_truncated_safetensors,
    safetensors_expected_size,
    truncated_safetensors,
)


def _write_safetensors(path: Path, tensors: dict[str, tuple[int, int]], payload: bytes) -> None:
    header = json.dumps({
        "__metadata__": {"format": "pt"},
        **{name: {"dtype": "F32", "shape": [size], "data_offsets": list(offsets)} for name, (size, offsets) in tensors.items()},
    }).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)


def test_truncated_safetensors_are_detected_and_purged(tmp_path: Path):
    complete = tmp_path / "complete.safetensors"
    truncated = tmp_path / "truncated.safetensors"
    payload = b"\x00" * 16
    _write_safetensors(complete, {"w": (4, (0, 16))}, payload)
    _write_safetensors(truncated, {"w": (4, (0, 16))}, payload[:4])

    assert safetensors_expected_size(complete) == complete.stat().st_size
    assert truncated_safetensors(tmp_path) == [truncated] or truncated_safetensors(tmp_path)[0] == truncated
    removed = purge_truncated_safetensors(tmp_path)
    assert truncated.name in " ".join(removed)
    assert complete.exists()
    assert not truncated.exists()
