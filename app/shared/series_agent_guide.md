# Making an episode in HocusPocus Series Lab (guide for agents)

This is how an agent with only these MCP tools makes an episode of a 2D cutout animated series: cast, voices in
each language, lip-sync, effects and a finished cut with subtitles. Everything runs locally: images, voices, lip-sync, Video 2D/3D, export and assembly.
The bible that comes with this guide lists the series' real characters, kits, poses, locations, music and sounds:
use only those ids and file names, never invent one.

## The shape of the work

1. **Read:** `series.guide` (this), then `series.episode.get` for an earlier episode to copy its style.
2. **Cast and places (only if the story needs new ones):**
   - character: `characters.styles` (prompt in the series style) → `generation.image` (base, then each pose with the
     base as `image_refs`) → `studio.key` → `characters.save` (approved assets) → `characters.rig.flat` → design a voice per
     language (`generation.speech` with `qwen3_tts_voicedesign`, check with `qa.speech`) → `characters.save` with
     `voicesByLanguage` → add the character to the series (`series.update`) with `voiceProfile.characterKitRef`;
   - rig check: look at the review image `characters.rig.flat` returns. A face with realistic proportions (small
     eyes in a wide head: graphic-novel or tenebrist art, eye bags, spectacles, moustaches) is detected, and its mouth
     is the thin line about one eye-pair width under the eyes. For that art rig with `style: {"mouthStyle": "ink"}`:
     the painted mouth stays as the rest shape and the open shapes are drawn in its own ink. If a pose's mouth or
     eyes are still found in the wrong place, rig again with `hints: {"<pose id>": {"mouth": [x, y]}}` (or `"eyes"`),
     in % of that pose's keyed image; later rigs reuse the hints, and `null` clears a pose's hints;
   - location: `generation.image` 1920x1088 in the series style → `series.update` (new location) → `series.asset.import`
     (owner_type location, reference_role environment); for depth, also make its planes as separate keyed images (a
     pillar or a bed frame in front, columns behind the cast) and list them in its `layout2d.layers` (below);
   - 3D background: `world3d.templates.list` → `world3d.scene.instantiate` → `series.location.plate3d` (a silent loop).
   After changing characters or locations, `series.canon.approve` (episodes freeze the approved canon).
3. **Write the episode:** `series.episode.from_script` with the whole script (format below), every language in the
   same lines. Send it with `check: true` first: it lists every unknown character, pose, location, file or effect at
   once. It assigns the ids, writes the shots and a language version for every other language.
4. **Make it:** `series.episode.produce`: renders the original and every language version on the server (voices checked
   with `qa.speech`, up to three takes per line; failed shots retried once), approves the takes and cuts each language
   with subtitles burned in. Poll `series.episode.produce.status` every minute or two; `chapters` lists the files.
5. **Look and fix:** `series.episode.get` lists each take's editable scene (`sceneFilename`): `scenes.video2d.preview`
   it, or open it with `scenes.document.get`. Fix a shot by changing the script and sending it again with `episode_id`
   (takes are kept by shot id), then `series.episode.produce` again: it renders only the shots whose script, kits or
   location changed since their approved take, and recuts. `rerender: true` renders every shot again; a 3D template
   edited in place is not detected, so render those shots with `series.episode.render_native` and `shot_ids`.

The lower-level tools (`series.episode.create`/`update`, `series.episode.language_version.set`,
`series.episode.render_native`, `series.assembly.start`) do the same steps one by one.

## The script

```json
{"title": {"es": "La grapadora", "en": "The Stapler"}, "premise": {"es": "...", "en": "..."},
 "scenes": [{"id": "cold_open", "location": "office", "variant": "office_day", "purpose": "Ana finds her desk empty"}],
 "shots": [
  {"scene": "cold_open", "framing": "title", "duration": 7,
   "card": {"kind": "title", "es": ["MI SERIE", "Episodio 3"], "en": ["MY SERIES", "Episode 3"]},
   "music": {"file": "mus-theme-es.wav", "en": "mus-theme-en.wav", "volume": 0.9}},
  {"scene": "cold_open", "framing": "two", "camera": "push",
   "cast": [["ana", "base", 32], {"characterId": "leo", "poseId": "wave", "x": 68, "enterFrom": "right"}],
   "lines": [{"who": "ana", "es": "¿Quién se ha llevado mi grapadora?", "en": "Who took my stapler?"},
             {"who": "leo", "es": "...Nadie.", "en": "...Nobody.", "pauseBefore": 1.0}],
   "sfx": [{"file": "sfx-door.wav", "at": 0.2}, {"file": "sfx-ping.wav", "line": 1, "anchor": "end", "offset": 0.1}],
   "fx": [{"kind": "confetti", "line": 1, "duration": 1.5, "x": 70, "y": 30, "size": 40}],
   "props": [{"file": "prop-stapler.png", "x": 12, "y": 74, "scale": 0.2}],
   "timing": {"intro": 0.6, "tail": 1.0}},
  {"scene": "moon", "kind": "3d", "lines": [{"who": "robot", "es": "...", "en": "..."}],
   "scene3d": {"template": "user-moon-base", "quality": "final",
               "cast": [{"characterId": "robot", "objectId": "robot", "poseId": "wave"}]},
   "foley": {"prompt": "servo whirs, metal footsteps on gravel", "volume": 0.5}}]}
```

The first language is the series' own (`es` or `spanish`); every other language in the lines becomes a version.
`scenes[].id` is short (`cold_open`): the episode prefix is added for you. A shot can override the scene's place with
`location` and `variant`.

## Ids

Ids are unique in the whole series: characters, locations, scenes and shots of every episode share one namespace.
`series.episode.from_script` prefixes them with the episode number: scenes `e3_cold_open`, shots `e3s00`, `e3s01`,
…; dialogue beats `e3s01_b0`, `e3s01_b1`. Writing shots by hand, do the same and never reuse a character or location
id as a scene id.

## A shot in detail

What `from_script` writes on each shot, and what `series.episode.update` takes (script keys in brackets):

```json
{"id": "e3s05", "order": 6, "sceneId": "e3_cold_open", "locationId": "office", "locationVariantId": "office_day",
 "productionMethod": "animation_2d", "visibleCharacterIds": ["ana", "leo"], "speakingCharacterIds": ["ana", "leo"],
 "dialogueBeats": [{"id": "e3s05_b0", "characterId": "ana", "text": "...", "emotion": "", "delivery": ""}],
 "layout2d": {
   "framing": "two", "camera": "static",
   "cast": [{"characterId": "ana", "poseId": "base", "x": 32}, {"characterId": "leo", "poseId": "wave", "x": 68, "enterFrom": "right"}],
   "props": [{"file": "prop-stapler.png", "x": 12, "y": 74, "scale": 0.2}],
   "layers": [{"file": "fg-plant.png", "depth": 0.95, "front": true, "x": 8, "y": 62, "scale": 0.9}],
   "music": {"file": "mus-bumper.wav", "volume": 0.6, "start": 0},
   "card": {"kind": "title", "title": "SERIES", "body": "Episode 3 · Title"}, "voiceRoom": "cathedral"}}
```

- **framing:** `wide` (everyone, full body), `two` (two characters), `medium` (one, waist up), `close` (one face),
  `insert`/`title` (no cast; cards).
- **camera:** `static` or `push` (slow push-in; use it on punchlines and reveals).
- **cast:** `x` is the horizontal position in % of the frame. Keep each character on the same side within a scene,
  as in the bible's `homes`. `motion`: `idle` (default bob), `still`, `shake` (panic). `enterFrom`: `left`/`right`
  walks in. `poseId` must be one of the kit's poses.
- **perched characters:** a character whose bible entry has `layout2d.perch` (a laptop on a desk) is placed on that
  prop in every framing automatically. Give it no transform.
- **props:** a workspace image (`file`, keyed with `studio.key`) or a series asset (`assetId`), at `x`/`y` (%) and
  `scale` (fraction of the frame height), or on a location `anchor` from the bible (it then stands on that point in
  every framing).
- **layers (a set in depth):** a location's `layout2d.layers` (`series.update`) are drawn over its background in
  every 2D shot there, at most 8: `{"assetId" | "file", "depth": 0.3, "front": false, "opacity": 1, "x": 50, "y": 50,
  "scale": 1, "drift": 0}`. `depth` 0 is the background's far plane, 1 the nearest; the cast stands at `castDepth`
  (default 0.6, on the location or the shot). `front: true` draws the layer in front of the cast (a pillar, a candle,
  a bed frame, fog in the foreground; default depth 0.9); the others go behind it, farthest first (default 0.3). Use
  PNGs with alpha (`studio.key`) or looping mp4/webm videos. `x`/`y` (%) put the layer's centre on the background, so
  it keeps its spot in every framing; `scale` is a fraction of the frame height (1 fills the frame with a
  frame-sized image). With layers a `push` moves every plane by its depth: the far wall grows less than the cast,
  the pillar in front more, so the push reads as depth. `drift` (frame px per second, negative to the left) slides a
  layer on its own, also in a static shot: fog or smoke, with a `scale` of 1.2 or more so its edge stays out of the
  frame. A shot's `layers` replace its location's (in a script, `"layers"` and `"castDepth"` on the shot) and `[]`
  turns them off. A bad layer is refused. Changing a location's layers renders again only its 2D shots that draw them.
- **music:** one music track per shot (a bumper at the start of a scene, a theme); a language can have its own file.
- **sfx:** sound effects at a line's `start`/`end` (`line`, `anchor`, `offset` s) or at a second (`at`), `volume`
  0–1. Files from the bible only.
- **foley** (on the shot, not in `layout2d` or `scene3d`; same key in the script)**:** `{"prompt": "wooden airship
  creaking, wind, cannon shots", "volume": 0.5}`. After the shot is exported, MMAudio (`generation.sfx` with the
  export as `video_guide`) makes sound that follows the shot's own picture, and it is mixed under the lines, music
  and `sfx` at `volume` (above 0 up to 2, relative to the dialogue, default 0.5). Use it where hand-placed `sfx`
  cannot follow the motion (ships, swords, creatures, explosions; 3D shots above all) and describe sounds only: the
  take already has its voices and music. It is an extra: without MMAudio installed, or when it fails or takes over
  30 min, the take is made without it and the render item has a `warning`; fix it and render that shot again by id.
  A new prompt or volume makes `series.episode.produce` render that shot again.
- **fx:** screen effects at the same kind of time: `kind` from `scenes.effects.catalog` (confetti, manga_impact,
  speedlines…), `duration` (seconds, 0.1–30, default 1; a value outside that range is clamped, never reset to 1;
  `"shot"` lasts until the end of the shot), `x`/`y`/`size` in %, `color`, `rotation` (degrees; a `laser` drawn across `x`/`y`
  points right at 0). A `laser` or `lightning` fired by someone starts at `from`: `{"cast": 0, "point": [95, 46]}` is a point
  in % of that cast member's pose image (`cast`: the index in the shot's `cast`, or a character id), so the beam leaves the
  muzzle wherever the cutout stands, however big it is drawn and while the camera pushes in; `{"point": [70, 40]}` is a
  point of the frame. The beam then runs from `from` to `x`/`y` (where it lands) and `rotation` is not used. A `cast` that
  names no one in the shot fails the render; a 3D shot keeps only a frame point. Keep effects off faces: a small burst to
  one side. Light for dark, painted frames: `shockwave` is a ring of light from `x`/`y` (`size` its reach) with a flash, a
  soft halo, trailing echoes and sparks; `shield` is a dome of light around someone (`size` its height) that reads even at
  `intensity` 0.4 and stays see-through; `embers` rise and cool from the bottom of their box; all keep `color` (gold stays
  gold).
  `impact_flash` (a white frame, then ink focus lines) and `impact_invert` (the negative of the frame) cover the
  whole picture: give them 2–4 frames (`duration` 0.08–0.17 s at 24 fps) right on the hit. `code_rain` (falling
  green code; `size` is the glyph height in %, default 3) covers the whole picture too, faces included: for a
  code backdrop behind the cast, render a location plate from the `anime-code-rain` Video 3D shot instead.
  The cinematic grades also cover the whole picture: `candlelight` (warm flickering key light, `x`/`y` the flame,
  `size` its radius), `vignette`, `film_grain`, `light_rays` (`x`/`y` the window, `rotation` where the light
  goes), `glitch` (bursts of digital tearing) and `canvas` (a painted-canvas texture). Give a grade the whole shot
  (`at` 0 and `"duration": "shot"`); it repeats over its cue, so a plate as long as the cue loops.
- **timing:** `intro` (silence before the first line, default 0.35 s), `gap` (between lines, 0.22), `tail` (after the
  last, 0.45). A line's `pauseBefore` adds a dramatic beat before it.
- **voiceRoom:** the room this shot's voices are heard in, instead of its location's (see Sound design): `none`,
  `small_room`, `room`, `hall`, `cathedral`, `cockpit`, `outdoor` or `radio`. In a script, `"voiceRoom"` on the shot.
  A transmission or a thought heard over the radio is a shot with `radio`; `none` keeps a shot dry in a roomed location.
- **card:** `title` (opening), `end` (credits), `disclaimer` (white text on dark; also used for news flashes). A card
  shot has no cast and a `durationSeconds` (4–7 s) and usually `locationId` of a dark or title location.
- **durationSeconds** (`duration`)**:** only for shots without dialogue. With dialogue, the render sets it from the voices.
- **3D dialogue (`kind: "3d"` in the script, `productionMethod: animation_3d` + `scene3d` on a shot):** a Video 3D
  template (`world3d.templates.list`, or a personal one) or a saved scene file, and which object each speaking
  character is (`objectId`). The server render records the lines like a 2D shot, makes each object talk as its
  Character Kit, exports it and imports the take. A speaker with no object in the cast is heard over the shot
  (a narrator, a voice on the radio). `quality`: `draft` (fast) or `final`. Its `sfx` and `fx` play
  like in a 2D shot (screen effects drawn over the 3D frame), on a line or at a second (`at`).
  The template's own effects, texts and clip cues are stretched to the shot's length (`"retime": false` keeps their
  seconds). `objects` places what does not speak: a 3D model from `model3d.generate`/`model3d.animate` (`file`, its
  `clip` by name, `clipPlayback` {speed, start, loop}) or an image cutout (`"media": "image"`), on a template object
  (`objectId`) or added to the scene (`"add": true`), with `position`/`scale`/`rotationY` (radians, metres),
  `grounded: true` for a character standing on the floor, and a `motion` {to, via, points, faceTravel, headingOffset,
  easing}. `faceTravel` turns the model's +Z along the path; a generated ship or airship whose nose is its -X needs
  `headingOffset: 1.5708` (+X: -1.5708, -Z: 3.1416):
  `{"objectId": "zep", "file": "zeppelin.glb", "add": true, "clip": "Fly", "position": [-6, 3, -8],
  "motion": {"to": [6, 3, -8], "faceTravel": true}}`. Mix them: 2D cutouts talk, 3D models move.
  `"renderLook": "toon"` draws the 3D models as cel anime with an ink outline (`toon` {steps 2-4, outline 0-8 px,
  ink #rrggbb}) so they sit with the flat cutouts and painted backgrounds; images and cutouts keep their look.

## Sound design

`soundDesign` on the series (`series.update`) is the sound every shot gets without the script naming it:
`stinger` (`{file, volume}`) under the first shot of each scene, `ambienceByLocation`
(`{"<locationId>": {"file": "sfx-rain.wav", "volume": 0.22}}`, volume 0–2 relative to the dialogue, default 0.22) and
`roomByLocation` (below).
`ambienceMode` says where the ambience is mixed:

- `"shot"` (default): each shot mixes its location's ambience from its own start. It restarts at every cut, and a
  new file or level renders every shot of that series again.
- `"episode"`: the shots leave it out and `series.assembly.start` lays one continuous bed per run of consecutive
  shots in the same location, looped with a 1 s crossfade, faded in and out over 0.8 s and crossfading into the next
  location's bed. Shots in a location without an entry (a dark title card) get none. Changing the beds renders no
  shot: `series.episode.produce` only recuts. Switching the mode renders every shot once. `ambienceDuckDb` (0–24,
  default 0 = off) lowers the beds that many dB while someone speaks, like the score below.

**Score (music under the whole episode).** A shot's `music` plays only in that shot, so a dialogue scene is often
bare voices. `score` on the episode (`series.episode.update` with `episode: {"score": [...]}`) lays music cues
across runs of shots at assembly: `{"fromShotId": "e3s04", "toShotId": "e3s12", "file": "mus-theme.wav",
"volume": 0.18, "fadeIn": 1.5, "fadeOut": 2.0, "duck": true}`, or `{"sceneId": "e3_bar", "file": ...}` for a
scene's shots. Use the ids `series.episode.get` shows: `from_script` names episode 3's shots `e3s00`, `e3s01`…
and its scenes `e3_<scene id>`. Only `file` and the shots are required; the numbers shown are the defaults (volume
0–2 relative to the dialogue, fades 0–30 s). Cues may not overlap (two cues may meet at a cut).

- Each cue plays from the cut before its first shot to the cut after its last, looped with a crossfade if the file
  is shorter, faded in and out inside the cue. Every clip kind and language version gets it.
- With `duck` it dips 9 dB under every recorded line (0.25 s down before the line, 0.6 s back up after it; lines
  less than 1.5 s apart share one dip). A shot with its own `music` keeps it and the score is silent under it.
- The score is not part of any take: changing it needs only `series.assembly.start` (or `series.episode.produce`,
  which renders no shot for it and recuts). Send `"score": []` to remove it.
- A cue naming a shot the episode does not have is refused; one left behind when a rewrite removed its shots is
  skipped by the assembly, which says so in the cut's `score.skipped`.

`roomByLocation` (`{"<locationId>": "<preset>"}`) makes the voice sound like the place. Lines are recorded dry, so a
monk in a stone cathedral and a captain on an open deck would sound the same; with a room the render plays a processed
copy of each line (the dry recording is kept, and lip-sync and timing stay the dry line's):

| preset | what it does |
| --- | --- |
| `none` | dry (the default; also overrides a location's room on one shot) |
| `small_room` | a closet or cabin: 0.3 s of tight reverb, 12 dB under the voice |
| `room` | an office or kitchen: 0.55 s, 9 dB under |
| `hall` | a corridor, a lobby, a gym: 1.6 s, 7 dB under |
| `cathedral` | stone, a cave, a vault: 3.5 s dark tail, 5 dB under (the tail rings on past the line for at most 0.8 s) |
| `cockpit` | small, metallic and close: dense reflections within 10 ms, a band-limited voice with a presence peak |
| `outdoor` | no reverb: a gentle low cut and one very slight, dark slap |
| `radio` | telepathy, transmissions, a phone: 420 Hz to 3.3 kHz, lightly distorted |

Every copy is levelled to the dry line, so a room never changes how loud a voice is. A shot overrides its location with
`layout2d.voiceRoom`. Changing a room renders again only the shots with lines that hear it; a series without
`roomByLocation` renders exactly as before. The tail of the last line is cut where the shot ends (0.45 s after it):
give a shot in a big room `timing: {"tail": 1.0}` to let it ring out.

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
- Effects and sounds placed by hand in a take's scene are lost when the shot renders again: declare them in the
  script (`sfx`, `fx`) instead.
- Image references for `generation.image` are workspace URLs `/api/v1/file/<name>?workspace=<ws>`.
- `generation.*` receipts can stay `queued` while the job finished: wait with `jobs.wait` and read the files from the
  receipt's `task.result_refs`.
- `qa.export` flags cards and pauses as problems; judge an episode by looking at its takes.
