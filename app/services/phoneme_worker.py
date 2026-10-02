"""Isolated CPU inference process. Inputs are bounded native PCM, never paths/URLs."""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import wave

import numpy as np

from services.phoneme_ctc import mouth_cues, timed_phones
from services.phoneme_runtime import ROOT, REVISION


def quiet_spans(samples, duration):
    step = 160  # 10 ms; only sustained silence closes a held vowel.
    levels = np.array([np.sqrt(np.mean(samples[i:i + step] ** 2))
                       for i in range(0, len(samples), step)])
    quiet = levels < max(.001, float(np.quantile(levels, .95)) * .035)
    result, first = [], None
    for index, value in enumerate(np.r_[quiet, False]):
        if value and first is None:
            first = index
        if not value and first is not None:
            if index - first >= 8:
                result.append((first * .01, min(duration, index * .01)))
            first = None
    return result


def emissions(model, processor, samples):
    import torch
    # Pin a 20 ms lattice and 25 ms receptive field; overlap restores chunk context.
    frames = max(0, (len(samples) - 400) // 320 + 1)
    outputs = []
    for base in range(0, frames, 600):
        first, last = max(0, base - 25), min(frames, base + 625)
        chunk = samples[first * 320:(last - 1) * 320 + 400]
        inputs = processor(chunk, sampling_rate=16000, return_tensors="pt")
        with torch.inference_mode():
            logits = model(**inputs).logits[0].log_softmax(-1).cpu().numpy()
        if len(logits) != last - first:
            raise ValueError("Unexpected phoneme model frame geometry.")
        outputs.append(logits[base - first:min(frames, base + 600) - first])
    if not outputs:
        raise ValueError("Audio is too short to align phonemes.")
    return np.concatenate(outputs)


def transcript_tokens(tokenizer, dialogue, language):
    tokens, words = [], []
    for word in re.findall(r"\w+(?:[-']\w+)*", dialogue):
        ids = tokenizer(word, add_special_tokens=False, phonemizer_lang=language)["input_ids"]
        if not ids or any(token < 4 for token in ids):
            raise ValueError("Transcript contains an unsupported phoneme or word.")
        tokens.extend(ids)
        words.extend([word] * len(ids))
    return tokens, words


def analyze(data):
    import torch
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    torch.set_num_threads(2)
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    with wave.open(io.BytesIO(base64.b64decode(data["pcm"])), "rb") as audio:
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768
    duration = len(samples) / 16000
    processor = Wav2Vec2Processor.from_pretrained(ROOT, local_files_only=True)
    model = Wav2Vec2ForCTC.from_pretrained(ROOT, local_files_only=True).to("cpu").eval()
    logp = emissions(model, processor, samples)
    dialogue = data.get("dialogue", "").strip()
    tokens, words = transcript_tokens(processor.tokenizer, dialogue, data.get("language") or "en-us") if dialogue else ([], [])
    if not dialogue:
        previous = 0
        for token in logp.argmax(axis=1):
            if token >= 4 and token != previous:
                tokens.append(int(token))
            previous = token
    vocabulary = {value: key for key, value in processor.tokenizer.get_vocab().items()}
    phones = timed_phones(logp, tokens, vocabulary, .02, .0125, duration)
    if words:
        for phone, word in zip(phones, words):
            phone["word"] = word
    return {"mouthCues": mouth_cues(phones, quiet_spans(samples, duration), duration),
            "phonemes": phones, "duration": duration, "recognizer": "wav2vec2-phoneme",
            "alignment": "transcript-ctc" if dialogue else "recognized-ctc", "revision": REVISION,
            "quality": {"mean_confidence": round(float(np.mean([p["confidence"] for p in phones])), 5),
                        "low_confidence_phonemes": sum(p["confidence"] < .2 for p in phones),
                        "phonemes": len(phones), "review_required": True}, "device": "cpu"}


if __name__ == "__main__":
    result = analyze(json.load(sys.stdin))
    json.dump(result, sys.stdout)
