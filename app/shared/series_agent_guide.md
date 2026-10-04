# Making an episode in HocusPocus Series Lab (guide for agents)

This is how an agent with only these MCP tools makes an episode of a 2D cutout animated series at the quality of
*Uncanny Valley* 1x01–1x02. Everything runs locally: images, voices, lip-sync, Video 2D/3D, export and assembly.
The bible that comes with this guide lists the series' real characters, kits, poses, locations, music and sounds:
use only those ids and file names, never invent one.

## The shape of the work

1. **Read:** `series.guide` (this), then `series.episode.get` for an earlier episode to copy its style.
2. **Cast and places (only if the story needs new ones):**
   - character: `characters.styles` (prompt in the series style) → `generation.image` (base, then each pose with the
     base as `image_refs`) → `studio.key` → `characters.save` (approved assets) → `characters.rig.flat` → design a voice per
     language (`generation.speech` with `qwen3_tts_voicedesign`, check with `qa.speech`) → `characters.save` with
     `voicesByLanguage` → add the character to the series (`series.update`) with `voiceProfile.characterKitRef`;
   - location: `generation.image` 1920x1088 in the series style → `series.update` (new location) → `series.asset.import`
     (owner_type location, reference_role environment);
   - 3D background: `world3d.templates.list` → `world3d.scene.instantiate` → `series.location.plate3d` (a silent loop).
   After changing characters or locations, `series.canon.approve` (episodes freeze the approved canon).
3. **Write the episode:** `series.episode.create`, then `series.episode.update` with `script` (scenes) and `shots`
   (format below), in the series' own language.
4. **Other languages:** `series.episode.language_version.set` with every line (`dialogue` beat id → text), the card
   texts (`cards`) and, for a sung theme, `music` (shot id → file). `series.episode.translate` drafts it with the local LLM.
5. **Render:** `series.episode.render_native` (approve true) for the original, then again with `language`. Poll
   `series.episode.render_native.status`. Voices are checked automatically (up to three takes per line).
6. **Look:** `scenes.video2d.preview` or the take files; fix a shot by changing it and rendering only that shot
   (`shot_ids`). A take's editable scene is in its asset's `metadata.sceneFilename` (`scenes.document.get`).
7. **Finish:** `series.assembly.start` (burn_subtitles true) per language → `series.assembly.status`.

## Ids

Ids are unique in the whole series: characters, locations, scenes and shots of every episode share one namespace.
Prefix an episode's scene and shot ids with its number: scenes `e3_cold_open`, shots `e3s00`, `e3s01`, …; dialogue
beats `e3s01_b0`, `e3s01_b1`. Never reuse a character or location id as a scene id.

## A shot

```json
{"id": "e3s05", "order": 6, "sceneId": "e3_street", "locationId": "street", "locationVariantId": "street_day",
 "productionMethod": "animation_2d", "visibleCharacterIds": ["kevin", "mark"], "speakingCharacterIds": ["kevin", "mark"],
 "dialogueBeats": [{"id": "e3s05_b0", "characterId": "kevin", "text": "...", "emotion": "", "delivery": ""}],
 "layout2d": {
   "framing": "two", "camera": "static",
   "cast": [{"characterId": "kevin", "poseId": "base", "x": 32}, {"characterId": "mark", "poseId": "wave", "x": 68, "enterFrom": "right"}],
   "props": [{"file": "prop-truck-s8-key.png", "x": 12, "y": 74, "scale": 0.36}],
   "music": {"file": "mus-bumper-a.wav", "volume": 0.6, "start": 0},
   "card": {"kind": "title", "title": "SERIES", "body": "Episode 3 · Title"}}}
```

- **framing:** `wide` (everyone, full body), `two` (two characters), `medium` (one, waist up), `close` (one face),
  `insert`/`title` (no cast; cards).
- **camera:** `static` or `push` (slow push-in; use it on punchlines and reveals).
- **cast:** `x` is the horizontal position in % of the frame. Keep each character on the same side within a scene,
  as in the bible's `homes`. `motion`: `idle` (default bob), `still`, `shake` (panic). `enterFrom`: `left`/`right`
  walks in. `poseId` must be one of the kit's poses.
- **perched characters:** a character whose bible entry has `layout2d.perch` (a laptop on a desk, a pet on a shelf)
  needs that prop and an explicit transform in every shot; copy them from an earlier episode's shot with the same
  framing (`series.episode.get`).
- **props:** a workspace image (`file`, keyed with `studio.key`) or a series asset (`assetId`), at `x`/`y` (%) and
  `scale` (fraction of the frame height), or on a location `anchor` from the bible (it then stands on that point in
  every framing).
- **music:** one extra audio track per shot: a bumper at the start of a scene, a sting, an ambience, or a sound effect
  (a truck, a pen). Files from the bible only.
- **card:** `title` (opening), `end` (credits), `disclaimer` (white text on dark; also used for news flashes). A card
  shot has no cast and a `durationSeconds` (4–7 s) and usually `locationId` of a dark or title location.
- **durationSeconds:** only for shots without dialogue. With dialogue, the render sets it from the voices.
- **productionMethod:** `animation_2d` for everything the server renders. `animation_3d` shots are made in Video 3D
  (`world3d.scene.talk` for a talking cutout) and imported with `series.asset.import` (as_take) +
  `series.take.approve` (with `language` for a version).

## Writing for quality

- One idea per line; short lines land better and lip-sync better. Write numbers and acronyms as they are spoken.
- Every scene starts on a `wide` that shows who is there, then `two`/`medium`/`close` for the exchange, and a
  `close` + `push` on the punchline.
- Use the bible's rules (running gags, how each character speaks, how episodes end). The voice traits in the bible
  tell you each character's rhythm.
- Cold open (30–60 s), title card (7 s, theme), 3–4 scenes, ending with the moral, credits card (6 s): 5–6 minutes,
  45–55 shots.
- Parody of public figures: satirise their public persona only; every voice is synthetic and described by traits.

## Known pitfalls

- Episodes freeze the approved canon: add characters and locations, then `series.canon.approve`, then create the episode.
- `series.update` replaces the whole project at a revision: read, change, send back with `base_revision`.
- A language version keeps its own takes, lengths and music; approve its takes with `series.take.approve` + `language`.
- Image references for `generation.image` are workspace URLs `/api/v1/file/<name>?workspace=<ws>`.
- `generation.*` receipts can stay `queued` while the job finished: wait with `jobs.wait` and read the files from the
  receipt's `task.result_refs`.
- `qa.export` flags cards and pauses as problems; judge an episode by looking at its takes.
