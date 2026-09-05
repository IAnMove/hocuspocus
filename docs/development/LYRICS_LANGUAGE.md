# Lyrics language contract

Status: library only (2026-09-05). Wiring into write-song/generate is phase 6.

This heuristic scores **written text**, not the audio a model later sings.
UI locale, conversation language, content language, spoken language and the
technical prompt are different decisions:

- the user may speak any language;
- the technical style/caption may be generated in English when the model
  guide says so;
- sung lyrics, quoted dialogue and other verbatim spans must keep the
  language the user asked for.

English structural tags such as `[Verse]` and `[Chorus]` are allowed.

## Verdicts

`valid` | `invalid` | `unevaluable`

`ok` is true only for `valid`. An unrecognized or unsupported language
(French, Estonian, …) is **unevaluable**, never a silent pass. An empty
vocal lyric is **invalid**. Instrumental empty/`[instrumental]` is valid.

Only `es` and `en` are scored. Aliases are exact folded keys, then BCP-47
prefix, then tokens longer than two letters. Never `startsWith("es")`.

## Repair

`repair_lyrics_language` / `repairLyricsLanguage` never overwrite the
original. They return `proposal` and `proposal_diffs`. Stripping foreign
scripts must not turn a vocal lyric into a valid empty song.
`assert_lyrics_language(..., repair=False)` is the default.

Required verbatim spans (`protected_segments`) must appear **exactly**,
including newlines. Missing spans are **invalid** even when the requested
language is unevaluable; the structural check runs before language scoring.

Shared corpus: `tests/fixtures/lyrics_language_corpus.json`, executed by
Python and TypeScript.

## Follow-up

Phase 6 wires this guard at the server enqueue boundary. Do not touch
`_launch_runtime.py` or `StoryLabPanel` here.
