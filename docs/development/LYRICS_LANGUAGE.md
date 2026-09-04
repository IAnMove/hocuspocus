# Lyrics language contract

Status: library only (2026-09-04). Not yet wired into write-song or generate
endpoints; those files are reserved by MiniMax-Music3 (#135).

User conversation language, authored lyric language and the provider-facing
technical prompt are three different decisions:

- the user may speak any language;
- the technical style/caption may be generated in English when the model
  guide says so;
- sung lyrics, quoted dialogue and other verbatim spans must keep the
  language the user asked for.

English structural tags such as `[Verse]` and `[Chorus]` are allowed.
Quoted segments registered on `LanguageIntent.verbatimSegments` are kept
character-for-character and are not scored as contamination.

## API

Python: `app/services/lyrics_language.py`

- `validate_lyrics_language(lyrics, lyrics_language, protected_segments=..., instrumental=...)`
- `repair_lyrics_language(...)` — strips unrequested Han/Arabic/Cyrillic/Hangul/Kana runs; never translates English into Spanish
- `assert_lyrics_language(...)` — raises if the lyric still mismatches

TypeScript: `ui/src/lib/lyricsLanguageGuard.ts` (same rules for Wizard tests).

A valid WAV is not proof of language fidelity. CI runs these tests without
GPU. Real smoke should call the same guard after a local song is written.

## Follow-up

Call the guard from Story Lab generate and `/api/v1/llm/write-song` after
#135 no longer owns those hotspots. Do not silently replace user-authored
Spanish lines.
