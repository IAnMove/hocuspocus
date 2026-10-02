"""Monotonic CTC alignment and native mouth shapes, including held sung vowels."""
from __future__ import annotations

import numpy as np


def align_states(logp, tokens, blank=0):
    """Viterbi over CTC blank/phone states; repeated phones must cross a blank."""
    if not tokens or logp.ndim != 2 or not len(logp) or not np.isfinite(logp).all():
        raise ValueError("Use finite phoneme emissions and a nonempty transcript.")
    labels = np.full(2 * len(tokens) + 1, blank, dtype=int)
    labels[1::2] = tokens
    score = np.full(len(labels), -np.inf)
    score[0], score[1] = logp[0, blank], logp[0, tokens[0]]
    trace = np.zeros((len(logp), len(labels)), dtype=np.uint8)
    skip = np.zeros(len(labels), dtype=bool)
    skip[3::2] = labels[3::2] != labels[1:-2:2]
    for frame in range(1, len(logp)):
        step = np.r_[-np.inf, score[:-1]]
        jump = np.where(skip, np.r_[-np.inf, -np.inf, score[:-2]], -np.inf)
        options = np.stack((score, step, jump))
        trace[frame] = np.argmax(options, axis=0)
        score = np.max(options, axis=0) + logp[frame, labels]
    state = len(labels) - 1 - int(score[-2] > score[-1])
    if not np.isfinite(score[state]):
        raise ValueError("The transcript cannot fit this audio window.")
    path = np.empty(len(logp), dtype=int)
    for frame in range(len(logp) - 1, -1, -1):
        path[frame] = state
        state -= int(trace[frame, state])
    return path


def timed_phones(logp, tokens, vocabulary, hop, center, duration):
    path = align_states(logp, tokens)
    result = []
    for index, token in enumerate(tokens):
        frames = np.flatnonzero(path == index * 2 + 1)
        if not len(frames):
            raise ValueError("A transcript phoneme has no acoustic support.")
        result.append({"phoneme": vocabulary[token],
                       "start": min(duration, max(0, float(frames[0] * hop + center))),
                       "emission_end": min(duration, float((frames[-1] + 1) * hop + center)),
                       "confidence": round(float(np.exp(logp[frames, token]).mean()), 5)})
    for index, phone in enumerate(result):
        phone["end"] = result[index + 1]["start"] if index + 1 < len(result) else duration
    return result


def shapes(phone):
    """Rhubarb-compatible alphabet; times come from the acoustic phoneme model."""
    if phone.startswith(("p", "b", "m")):
        return ("A",)
    if phone.startswith(("f", "v", "ʋ")):
        return ("G",)
    if phone.startswith(("aɪ", "ɑɪ")):
        return ("D", "B")
    if phone.startswith(("aʊ", "ɑu")):
        return ("D", "F")
    if phone.startswith(("eɪ", "əɪ")):
        return ("C", "B")
    if phone.startswith(("oʊ", "əʊ")):
        return ("E", "F")
    if phone.startswith(("o", "ɔ", "ɒ", "œ", "ø")):
        return ("E",)
    if phone.startswith(("u", "ʊ", "w", "ʉ", "ɯ")):
        return ("F",)
    if phone.startswith(("i", "ɪ", "y", "ɨ", "ᵻ", "j")):
        return ("B",)
    if phone.startswith(("ɛ", "e", "ɜ")):
        return ("C",)
    if phone.startswith(("a", "ɑ", "æ", "ʌ", "ə", "ɐ", "ä")):
        return ("D",)
    if phone.startswith(("l", "ɫ", "ɭ", "ʎ", "t", "d", "n", "ɲ")):
        return ("H",)
    return ("B",)


def mouth_cues(phones, quiet, duration):
    intervals = []
    for phone in phones:
        values = shapes(phone["phoneme"])
        # Diphthongs retain the first vowel for the sustain, then close into the second.
        edges = [phone["start"], phone["end"]] if len(values) == 1 else [
            phone["start"], phone["start"] + .75 * (phone["end"] - phone["start"]), phone["end"]]
        intervals.extend((edges[i], edges[i + 1], value) for i, value in enumerate(values))
    boundaries = sorted({0., duration, *(x for a, b, _ in intervals for x in (a, b)),
                         *(x for a, b in quiet for x in (a, b))})
    result = []
    for a, b in zip(boundaries, boundaries[1:]):
        if b - a < 1e-7:
            continue
        middle = (a + b) / 2
        value = next((v for start, end, v in intervals if start <= middle < end), "X")
        if any(start <= middle < end for start, end in quiet):
            value = "X"
        if result and result[-1]["value"] == value:
            result[-1]["end"] = b
        else:
            result.append({"start": a, "end": b, "value": value})
    return result
