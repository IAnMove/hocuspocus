# Lyrics language contract

Status: library only (2026-09-05). MiniMax-Music3 (#135) is on `main`; wiring
the guard into write-song/generate remains a follow-up so this PR stays
outside `_launch_runtime.py`.

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

`canonical_lyrics_language` / `canonicalLyricsLanguage` resolve Story Lab
spoken-language names without prefix traps:

1. exact folded aliases (`es`, `espanol`, `spanish`, `en`, `english`, …);
2. BCP-47 prefixes via the token before `-` (`es-MX`, `en-US`);
3. tokens longer than two letters so `Español de España` is Spanish and
   `en español` is Spanish, while `en` and `English` stay English.

Do not use `startswith("es")` / `startswith("en")`: `English` starts with
`es`, and `en español` starts with `en`.

A valid WAV is not proof of language fidelity. CI runs these tests without
GPU. Real smoke should call the same guard after a local song is written.

## Follow-up

Call the guard from Story Lab generate and `/api/v1/llm/write-song`. Do not
silently replace user-authored Spanish lines.
