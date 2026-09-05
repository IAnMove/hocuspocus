# Music model contract (phase 6)

Status: one catalog decides availability and compilation. No GPU, no
provider calls, no weight downloads.

Guides: [MUSIC_SUBMISSION.md](MUSIC_SUBMISSION.md),
[MUSIC_FINALIZATION.md](MUSIC_FINALIZATION.md),
[LYRICS_LANGUAGE.md](LYRICS_LANGUAGE.md).

## Authority

`app/services/music_model_contract.py` is the server contract.
`ui/src/lib/musicGenerationSpec.ts` is the UI/Story/Wizard port. Limits and
`guide_revision` (`music-model-contract-v1`) must match.

Story, Wizard and Studio build the same spec shape through
`storyCueToMusicDraft` / `wizardSongToMusicDraft` / `studioParamsToMusicDraft`.

## Model states

`inspect_music_model` / `inspectMusicModel` classify a requested id as:

| State | Meaning |
|---|---|
| known | listed in the catalog |
| downloadable | local weights we can install |
| incomplete | downloadable but required assets are missing |
| installed | caller reported assets present (this module does not scan disk) |
| compatible | bundled backend can run it |
| configured | remote API key present, or local (no key) |
| available | enabled + compatible + configured + installed when local |

Community MiniMax ports (GGUF / MLX / WebGPU) are **known** and **not
compatible**. They stay unavailable until a validated adapter exists.

Unavailable models keep the requested id. There is no silent ACE-Step
fallback.

## Compile

The frozen spec stores the full caption and lyrics. Remote MiniMax's
300-character prompt cap is applied only on `compiled.prompt`. Local ACE-Step
and Music3 keep structured captions intact.

## Language guard

`submit_music_generation` runs the phase-2 lyrics guard before enqueue.
`invalid` is HTTP 400 with the original lyrics plus a repair proposal.
`unevaluable` is recorded on the spec and is never `ok`. The original text is
not overwritten.
