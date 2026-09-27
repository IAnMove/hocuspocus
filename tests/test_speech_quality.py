import base64
import json
from pathlib import Path

import pytest

from services import scene3d_speech as speech
from services.speech_analysis_request import speech_request
from services.character_kit_library import normalize_character_kit
from tests.test_scene3d_speech import wav


def test_script_envelope_preserves_unicode_and_rejects_unbounded_or_invalid_input():
    raw = wav()
    data, options = speech_request(json.dumps({"wavBase64": base64.b64encode(raw).decode(), "dialogue": "¿Qué ocurrió?", "language": "es"}).encode(), "application/json")
    assert data == raw and options == {"dialogue": "¿Qué ocurrió?", "language": "es"}
    for body in ({"wavBase64": "!!!"}, {"wavBase64": "", "dialogue": "x" * 4001}, [], {"language": 42}):
        with pytest.raises(speech.SpeechAnalysisError):
            speech_request(json.dumps(body).encode(), "application/json")


def test_english_uses_audio_and_script_and_cache_separates_changed_scripts(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEECH_ANALYSIS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(speech, "rhubarb_executable", lambda: "/configured/rhubarb")
    calls = []

    def run(command, **kwargs):
        assert kwargs["shell"] is False and kwargs["timeout"] == 90
        transcript = Path(command[command.index("--dialogFile") + 1]).read_text()
        calls.append((command[command.index("-r") + 1], transcript))
        Path(command[command.index("-o") + 1]).write_text(json.dumps({"mouthCues": [{"start": 0, "end": .5, "value": "A"}, {"start": .5, "end": 1, "value": "X"}]}))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(speech.subprocess, "run", run)
    for _ in range(2):
        assert speech.analyze_voice(wav(), dialogue="Move now", language="en-US")["recognizer"] == "pocketSphinx"
    speech.analyze_voice(wav(), dialogue="Different words", language="en")
    assert speech.analyze_voice(wav(), dialogue="Vamos", language="es")["recognizer"] == "phonetic"
    assert calls == [("pocketSphinx", "Move now"), ("pocketSphinx", "Different words"), ("phonetic", "Vamos")]


def test_library_roundtrips_extended_mouths_and_resting_still_without_approving_the_base():
    asset = {"id": "base", "name": "Base", "source": "/base.png", "reviewState": "pending", "alphaStatus": "transparent", "kind": "image"}
    kit = {"id": "actor", "name": "Actor", "base": asset, "mouth": {state: {**asset, "id": state, "kind": "overlay"}
           for state in ("closed", "pressed", "medium", "pucker", "bite", "tongue")},
           "restPose": {"asset": {**asset, "id": "rest", "source": "/rest.png"}, "fingerprint": "source-key"}}
    result = normalize_character_kit(kit)
    assert result["restPose"]["asset"]["source"] == "/rest.png"
    assert result["base"]["reviewState"] == "pending"
    assert set(result["mouth"]) == set(kit["mouth"])


def test_offline_installer_respects_custom_binary_and_does_not_block_other_architectures(tmp_path, monkeypatch):
    from services import install_speech_tools as installer
    binary = tmp_path / "native-rhubarb"
    binary.touch()
    monkeypatch.setenv("RHUBARB_EXECUTABLE", str(binary))
    monkeypatch.setattr(installer.platform, "machine", lambda: "arm64")
    assert installer.install() == binary
    monkeypatch.delenv("RHUBARB_EXECUTABLE")
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    monkeypatch.setattr(installer, "ROOT", tmp_path / "runtime")
    assert installer.install() is None
    assert not installer.ROOT.exists()


def test_offline_installer_rejects_modified_archive_before_unpacking(tmp_path, monkeypatch):
    import io
    from services import install_speech_tools as installer
    monkeypatch.delenv("RHUBARB_EXECUTABLE", raising=False)
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    monkeypatch.setattr(installer, "ROOT", tmp_path / "runtime")
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"changed archive"))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        installer.install()
    assert not installer.bundled_executable().exists()
    assert list(installer.ROOT.iterdir()) == []
