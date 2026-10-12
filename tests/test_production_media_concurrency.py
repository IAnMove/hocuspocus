"""Transport retries and simultaneous CPU media writes must preserve their own result."""
import asyncio
import threading
from pathlib import Path

import pytest

from services.production_media_common import handler
from tests.media_tool_fixtures import Install


def test_simultaneous_handler_retries_execute_one_intent(tmp_path):
    started, release = threading.Event(), threading.Event()
    calls = []

    def run(arguments):
        calls.append(arguments)
        started.set()
        assert release.wait(3)
        return {"file": f"frame-{len(calls)}.png"}

    execute = handler("media.frame", run, lambda _: str(tmp_path))
    command = {"version": 1, "intent_id": "frame-1", "input": {"workspace": "show"}}

    async def requests():
        first = asyncio.create_task(execute(command))
        assert await asyncio.to_thread(started.wait, 3)
        second = asyncio.create_task(execute(command))
        await asyncio.sleep(0.1)
        release.set()
        return await asyncio.gather(first, second)

    results = asyncio.run(requests())
    assert len(calls) == 1
    assert [reply["result"]["file"] for reply in results] == ["frame-1.png"] * 2
    assert sum(reply["result"].get("replayed", False) for reply in results) == 1


def test_a_failed_attempt_releases_its_intent_and_output_reservation(tmp_path):
    from fastapi import HTTPException
    from services.production_media_common import MediaToolError, output_destination

    calls = []

    def run(arguments):
        with output_destination(str(tmp_path), "still", "unused", ".png") as destination:
            calls.append(destination)
            Path(destination).write_bytes(b"partial" if len(calls) == 1 else b"complete")
            if len(calls) == 1:
                raise MediaToolError("compose_failed", "injected write failure")
            return {"file": Path(destination).name}

    execute = handler("media.compose", run, lambda _: str(tmp_path))
    command = {"version": 1, "intent_id": "retry", "input": {"workspace": "show"}}
    with pytest.raises(HTTPException):
        asyncio.run(execute(command))
    assert not (tmp_path / "still.png").exists()
    assert asyncio.run(execute(command))["result"]["file"] == "still.png"
    assert (tmp_path / "still.png").read_bytes() == b"complete"
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(execute({**command, "input": {"workspace": "show", "different": True}}))
    assert conflict.value.status_code == 409
    assert len(calls) == 2


def test_output_reservation_keeps_sidecar_stems_separate_across_formats(tmp_path):
    from services.production_media_common import output_destination

    with output_destination(str(tmp_path), "still", "unused", ".png") as first:
        Path(first).write_bytes(b"png")
        Path(first).with_suffix(".meta.json").write_text('{"format":"png"}')
    with output_destination(str(tmp_path), "still", "unused", ".jpg") as second:
        assert Path(second).name == "still(2).jpg"
    assert Path(first).with_suffix(".meta.json").read_text() == '{"format":"png"}'


@pytest.mark.parametrize("operation", ["media.frame", "media.compose", "audio.trim"])
def test_simultaneous_named_outputs_never_overwrite(tmp_path, monkeypatch, operation):
    from services import audio_trim, media_compose, media_frame
    from PIL import Image

    install = Install(tmp_path)
    folder = install.folder("show")
    started, release = threading.Event(), threading.Event()
    writes = []

    def write(destination):
        number = len(writes) + 1
        writes.append(destination)
        if number == 1:
            started.set()
            assert release.wait(3)
        Path(destination).write_bytes(str(number).encode())

    def capture(source, destination, at):
        write(destination)
        return {"time": 0, "width": 1, "height": 1}

    monkeypatch.setattr(media_frame, "capture", capture)
    monkeypatch.setattr(media_compose, "compose", lambda *_: (Image.new("RGBA", (1, 1)), []))
    monkeypatch.setattr(media_compose, "_save", lambda canvas, destination, *_: write(destination))
    monkeypatch.setattr(audio_trim, "cut", lambda source, destination, *_: write(destination))
    monkeypatch.setattr(audio_trim, "probe_audio_stream", lambda _: {"duration": 2, "sample_rate": 44100, "channels": 1})
    module = {"media.frame": media_frame, "media.compose": media_compose, "audio.trim": audio_trim}[operation]
    monkeypatch.setattr(module, "resolve_source", lambda *_: str(folder / "source.mp4"))
    monkeypatch.setattr(module, "source_ref", lambda *_: {})
    payload = {"workspace": "show", "output_name": "same"}
    payload.update({"layers": []} if operation == "media.compose" else {"source": "source.mp4"})
    if operation == "audio.trim":
        payload.update(start=0, length=1)

    async def requests():
        execute = install.handlers[operation]
        first = asyncio.create_task(execute({"version": 1, "input": payload}))
        assert await asyncio.to_thread(started.wait, 3)
        second = asyncio.create_task(execute({"version": 1, "input": payload}))
        await asyncio.sleep(0.1)
        release.set()
        return await asyncio.gather(first, second)

    results = asyncio.run(requests())
    names = [reply["result"]["file"] for reply in results]
    assert len(set(names)) == 2
    assert {(folder / name).read_bytes() for name in names} == {b"1", b"2"}
    assert all((folder / name).with_suffix(".meta.json").is_file() for name in names)
