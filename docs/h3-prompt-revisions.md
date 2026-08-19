# H3 prompt revisions

Log of prompt-compiler changes so we can revert a step if quality drops.
Each entry names the files and the previous behaviour.

## 2026-08-20 — Compact compile and mute undescribed sound

**Why:** A hand-written 1.8k prompt (job `aa7b3e3f`) looked right. Director
compile was emitting 8–10k of language contracts, speaker-visibility
boilerplate, delivery essays, and lists of sounds that should *not* be heard.

**New behaviour**

- Default `h3_audio_prompt`: only explicitly described sounds; otherwise silent.
- `overall_soundscape` drops absence lists (`no hay coches`, `no bells`…).
- If nothing audible remains, soundscape is `Silence`.
- Compiled visual body drops `SPOKEN LANGUAGE CONTRACT`, `SPEAKER VISIBILITY`,
  and long “speaks with a Cadencia…” delivery. Language stays in `<d>[Spanish]`.
- Identity lock shortened to “Same faces and wardrobe throughout.”
- Music-video singing shots drive from the song slice; mute shots get no vocal.
- Music-video planner no longer puts transcribed lyrics in `<d>`.

**Revert**

```
git revert <this-commit>
```

Key files: `app/services/director/h3_dialogue.py`,
`app/services/director/minimax_h3_prompting.py`,
`app/services/director/policies.py`,
`app/services/minimax_h3_service.py`,
`app/services/director/planners/music_video.py`,
`app/services/director/planners/short_film.py`,
`app/services/director_pipeline.py`.

Previous default audio direction:

```
Natural synchronized production sound matching the visible environment
and actions; include explicitly described dialogue or music, otherwise
use ambience and sound effects only; clear, audible stereo mix.
```

Previous empty soundscape fallback: `Natural scene-appropriate stereo ambience`.
