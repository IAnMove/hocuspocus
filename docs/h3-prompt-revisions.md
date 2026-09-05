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

## 2026-08-20 — Pencil loads one clip, not the sequence

**Why:** Load settings on a single H3 clip reconstructed `multi_prompts_gen_type=3`
into every newline as a Studio clip. The sidebar became unusable and the
next generate glued the old monster prompt to the new one.

**New behaviour**

- Pencil / “edit this video” on a normal clip → one prompt, one image, one duration.
- Only `*_multiclip.mp4` still opens the full sequence.
- Structured H3 prompts are never split on `\n`.
- Multi-clip Studio shows one expanded shot; the rest are a Shot 1 / 2 / 3 list.

**Revert**

```
git revert <this-commit>
```

Key files: `ui/src/features/studio/studioRestore.ts`,
`ui/src/stores/useStore.ts`,
`ui/src/components/Sidebar/MultiClipEditor.tsx`.
