# Making an episode in HocusPocus Series Lab (guide for agents)

How an agent with only these MCP tools makes an episode of a 2D cutout animated series, all of it locally (images,
voices, lip-sync, Video 2D/3D, export, assembly): cast, voices in each language, effects and a cut with subtitles.
The bible sent with this guide lists the series' real characters, kits, poses, locations, music and sounds: use only
those ids and file names, never invent one.

## The shape of the work

1. **Read:** `series.guide` (this), then `series.episode.get` for an earlier episode to copy its style.
2. **Cast and places (only if the story needs new ones):**
   - character: `characters.styles` (prompt in the series style; painted art: `graphic-novel`, below) →
     `generation.image` (base, then each pose with the base as `image_refs`) → `studio.key` → `characters.save`
     (approved assets) → `characters.rig.flat` (with the style's `rig` as `style`) → design a voice per
     language (`generation.speech` with `voxcpm2_voicedesign`, the default: 48 kHz, 30 languages, no `model_mode`;
     `qwen3_tts_voicedesign` is the alternative; check with `qa.speech`) → `characters.save` with `voicesByLanguage`
     (a reference voice whose model is `voxcpm2_base`, optionally with style `instructions`, or `qwen3_tts_base`) →
     add the character to the series (`series.update`) with `voiceProfile.characterKitRef`.
     Check the pitch with `qa.speech` and `pitch_range`: an adult man sits at 85–155 Hz, an adult woman at 165–255 Hz.
     The series render only notes a line outside the character's range (`pitch_out_of_range`) and keeps the take;
   - rig check: look at the review image `characters.rig.flat` returns. A face with realistic proportions (small
     eyes in a wide head: graphic-novel or tenebrist art, eye bags, spectacles, moustaches) is detected, and its mouth
     is the thin line about one eye-pair width under the eyes: rig that art with warp mouths (`style: {"mouthStyle":
     "warp"}`, or the `graphic-novel` style; the painted section below has the `mouthLine` checks and `hints`).
     `"ink"` keeps the painted mouth as the rest shape and draws the open shapes in its own ink. Eyes found in the
     wrong place: rig again with `hints: {"<pose id>": {"eyes": [x, y]}}`, in % of that pose's keyed image; later
     rigs reuse the hints, and `null` clears a pose's hints;
   - location: `generation.image` 1920x1088 in the series style → `series.update` (new location) → `series.asset.import`
     (owner_type location, reference_role environment); for depth, its planes as separate keyed images (a pillar in
     front, columns behind the cast) listed in its `layout2d.layers` (below).
     Paint the plate empty of anything that must move (boats, waves, crowds, rain): a frozen wave reads as broken.
     Animate that motion afterwards, as an H3 loop (`image_start` and `image_end` the same image) or a Video 3D scene;
   - 3D background: `world3d.templates.suggest` (below) → `world3d.scene.instantiate` → `series.location.plate3d` (a silent loop).
   After changing characters or locations, `series.canon.approve`.
3. **Write the episode:** `series.episode.from_script` with the whole script (format below), every language in the
   same lines. Send it with `check: true` first: it lists every unknown character, pose, location, file or effect at
   once. It assigns the ids, writes the shots and a language version for every other language.
4. **Make it:** `series.episode.produce`: renders the original and every language version on the server (voices checked
   with `qa.speech`, up to three takes per line; failed shots retried once), approves the takes and cuts each language
   with subtitles burned in. Poll `series.episode.produce.status` every minute or two; `chapters` lists the files.
   Before that full render, make 10–13 key shots with `series.episode.render_native` and `shot_ids`, or use `preview`
   mode, and look at those takes first.
5. **Look and fix:** `series.episode.get` lists each take's editable scene (`sceneFilename`): `scenes.video2d.preview`
   it, or open it with `scenes.document.get`. Fix one shot with `series.shot.update` (by id or its number, below), or
   change the script and send it again with `episode_id` (takes are kept by shot id), then `series.episode.produce` again: it renders only the shots whose script, kits or
   location changed since their approved take, and recuts. `rerender: true` renders every shot again; a 3D template
   edited in place is not detected, so render those shots with `series.episode.render_native` and `shot_ids`.

The lower-level tools (`series.episode.create`/`update`, `series.episode.language_version.set`,
`series.episode.render_native`, `series.assembly.start`) do the same steps one by one.

## The user's review (production modes)

Three modes, set by the user in Series Lab (Validation) or with `series.episode.review.set` `mode`:

- `direct` (default): steps 4–5 above, nothing waits.
- `plan`: the user approves each shot's plan (cast, poses, lines, framing, camera, set) before it renders;
  `render_native` and `produce` render only approved shots and list the rest as `waiting`.
- `preview`: plan approval, then a preview render the user approves or sends back with notes, then the final. A 2D
  preview is its normal render, a 3D one is exported at `draft`. An approved 2D (or draft 3D) preview becomes the
  final take without rendering again; a 3D shot at `final` quality renders its final.

Working with it:

1. `series.episode.review.get`: the mode, the steps left and, per shot, `plan`/`preview` (`pending | approved |
   changes`), its `step` and every note `{stage, text, by}`. Shots in `changes` are the user's requests.
2. Fix each requested shot (`series.shot.update` for one shot, `series.episode.update`, or the script again with
   `episode_id`). Changing a shot's content puts its approvals back to pending (notes stay); a new take, its preview.
3. Answer on the shot: `series.shot.review.set` with `note: {text: "what I changed", by: "agent"}` (and `plan` or
   `preview: "pending"` if you changed nothing the review can see). Never approve on the user's behalf unless asked.
4. `series.episode.produce` (or `render_native`) renders what the review lets through and stops `waiting` before the
   cut while shots wait; `resume` it once the user approved. `series.assembly.start` refuses a staged episode
   that is not fully approved (409 `review_pending`) unless `force: true`.

## Painted / graphic-novel characters that talk

For painted art (graphic novel: bold ink, flat black shadows) use the `graphic-novel` character style. Its warp
mouths are the drawing's own: the upper lip stays, lower lip, chin and beard move down over a flat dark gap in the
character's ink.

1. **Generate for the rig.** `characters.styles` with `style: "graphic-novel"`, `kind: "character"` (then `"pose"`)
   and the description. The prompt asks for what the rig must find: both eyes with clean white sclera, never in the
   shadow, and the closed mouth painted as one short dark line. Key in the screen colour `characters.styles` returns:
   magenta when the character or object is green, so green cloth is not keyed away, and green otherwise.
2. **Save and rig.** Save the kit with `provenance: [{"method": "character-style-create", "style": "graphic-novel"}]`;
   `characters.rig.flat` then uses the style's rig, `{"mouthStyle": "warp"}`, with no `style`. Later rigs of the kit (a pose added, a mouth line
   placed) keep warp mouths; only `style.mouthStyle` changes them. The result's `style` is the look used.
3. **Check every pose.** Look at the review image and each pose's `mouthLine` (`mouth`, `mouthWidth`, `found`,
   `from`: hint, landmarks, painted or guess). Warning `mouth_line_guessed` (no painted line where the mouth was
   put) or `mouth_line_unsure` (unsure face points, a mouth under a moustache) means: see it with
   `characters.rig.flat.preview` and rig again with `hints: {"<pose>": {"mouth": [x, y], "mouthWidth": w}}`, a point
   on the line between the lips and the width corner to corner, in % of the pose image. In the app a user does the
   same in Characters › Prepare 2D speech › Face Rig › **Mouth line**. Only a hint with `"exact": true` is followed as
   given, so add it only after looking at the preview. Otherwise landmarks sure of the lips place the mouth
   (`mouth_hint_ignored` when your point was far off) and unsure ones take your point, snapped onto the painted lips.
   Never type mouth points you have not looked at: a wrong one moved mouths onto a cheek and a chin.
4. **Make a bust for dialogue.** In a full figure the face is small and the moving lips read less: add a bust pose
   (`"bust, head and shoulders, ..."`) and use it in `medium` and `close` shots (`"cast": [["ana", "bust", 50]]`).
5. **Nothing else changes.** `from_script` and `produce` show each pose its own mouths; after a re-rig, `produce`
   renders again the shots that use that kit.

## The script

```json
{"title": {"es": "La grapadora", "en": "The Stapler"}, "premise": {"es": "...", "en": "..."},
 "scenes": [{"id": "cold_open", "location": "office", "variant": "office_day", "purpose": "Ana finds her desk empty"}],
 "shots": [
  {"scene": "cold_open", "framing": "title", "duration": 7,
   "card": {"kind": "title", "es": ["MI SERIE", "Episodio 3"], "en": ["MY SERIES", "Episode 3"]},
   "music": {"file": "mus-theme-es.wav", "en": "mus-theme-en.wav", "volume": 0.9}},
  {"scene": "cold_open", "framing": "two", "camera": "push",
   "cast": [["ana", "base", 32], {"characterId": "leo", "poseId": "wave", "x": 68, "enterFrom": "right", "enterGait": "walk"}],
   "lines": [{"who": "ana", "es": "¿Quién se ha llevado mi grapadora?", "en": "Who took my stapler?"},
    {"who": "leo", "es": "...Nadie.", "en": "...Nobody.", "pauseBefore": 1.0}],
   "sfx": [{"file": "sfx-door.wav", "at": 0.2}, {"file": "sfx-ping.wav", "line": 1, "anchor": "end", "offset": 0.1},
    {"file": "sfx-step.wav", "anchor": "enter", "cast": 1, "repeat": "steps", "volume": 0.5}],
   "fx": [{"kind": "confetti", "line": 1, "duration": 1.5, "x": 70, "y": 30, "size": 40}],
   "props": [{"file": "prop-stapler.png", "x": 12, "y": 74, "scale": 0.2}],
   "timing": {"intro": 0.6, "tail": 1.0}},
  {"scene": "moon", "kind": "3d", "lines": [{"who": "robot", "es": "...", "en": "..."}],
   "scene3d": {"template": "user-moon-base", "quality": "final",
    "cast": [{"characterId": "robot", "objectId": "robot", "poseId": "wave"}]},
   "foley": {"prompt": "servo whirs, metal footsteps on gravel", "volume": 0.5}}]}
```

The first language is the series' own (its `spokenLanguage`; `es` or `spanish` for this Spanish series); every other
language in the lines becomes a version. A series created without `language` is English, so name it in `series.create`.
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
 "dialogueBeats": [{"id": "e3s05_b0", "characterId": "ana", "text": "...", "emotion": "", "delivery": ""},
  {"id": "e3s05_b1", "characterId": "narrator", "text": "...", "emotion": "", "delivery": "", "voiceRoom": "radio"}],
 "layout2d": {
   "framing": "two", "camera": "static",
   "cast": [{"characterId": "ana", "poseId": "base", "x": 32},
    {"characterId": "leo", "poseId": "wave", "x": 68, "enterFrom": "right", "enterAt": 0.5, "enterDuration": 2.4,
     "enterGait": "walk", "enterStep": 0.6}],
   "sfx": [{"file": "sfx-step.wav", "anchor": "enter", "cast": "leo", "repeat": "steps", "volume": 0.5}],
   "props": [{"file": "prop-stapler.png", "x": 12, "y": 74, "scale": 0.2}, {"file": "prop-robot.png", "x": 80, "scale": 0.5, "ground": true}],
   "layers": [{"file": "fg-plant.png", "depth": 0.95, "front": true, "x": 8, "y": 62, "scale": 0.9},
    {"file": "bg-crowd.mp4", "depth": 0.2, "start": 2.5, "loop": "pingpong", "speed": 0.5}],
   "music": {"file": "mus-bumper.wav", "volume": 0.6, "start": 0},
   "card": {"kind": "title", "title": "SERIES", "body": "Episode 3 · Title"}, "voiceRoom": "cathedral"}}
```

- **framing:** `wide` (everyone, full body), `two` (two characters), `medium` (one, waist up), `close` (one face),
  `insert`/`title` (no cast; cards).
- **camera:** `static` or `push` (slow push-in; use it on punchlines and reveals).
- **cast:** `x` is the horizontal position in % of the frame. Keep each character on the same side within a scene,
  as in the bible's `homes`. One kit per character, with every pose it uses. The line belongs to the character whose
  kit is on screen; anyone else is voice-over and the mouth does not move. `motion`: `idle` (default bob), `still`,
  `shake` (panic). `enterFrom`: `left`/`right`
  walks in, from 0.2 s to 1.4 s unless `enterAt` (s, when it starts) and `enterDuration` (s, how long it takes; a
  slow walk-in is 2–4 s) say otherwise; both stay inside the shot. `enterGait`: `hop` (default, a quick hop) or
  `walk`: the body bobs once per step, down on every footfall and up mid-step, and sways `enterSway`
  degrees (default 1.5, 0 for none). `enterStep` is the step in seconds (default 0.5; a slow monk 0.6–0.7): the walk
  takes a whole number of steps (stretched a little to fit), so its feet land on its start, every step and its end. `poseId` must be one of the kit's poses.
- **look room:** stand a character on the side away from where they look (the bible's `facing` per pose): facing
  `left` right of centre, facing `right` left of it; two people face each other. `from_script` moves a 2D cast member
  who looks out of the frame (`lookRoom` in the reply); `"lookRoom": false` on a cast entry or a shot keeps your `x`.
- **cut poses (edge snap):** a pose cut by its image border (a bust cut at the chest and one side) never shows the
  cut. A cut is a run of opaque pixels on the left or right border at least 8 % of the image height, or on the bottom
  at least 15 % of its width (a stray pixel, hair or feet on the border are not cuts; the top is not read). A side cut
  slides the cutout, same size, until the cut is just past the frame edge; a bottom cut goes below the frame (slid
  down in a wide shot, else enlarged with the eyes on the framing's eye line); cut on both sides, it is enlarged until
  both cuts are out (at most 2.5×). A cut already out of the frame moves nothing; a mirrored pose is cut on the other
  side. Give a bust cut on its left an `x` on the left (it lands there anyway) and keep two cut busts on their cut
  sides in a two-shot. `"edgeSnap": false` on a cast entry keeps its `x`, cut and all; an entry with a `transform`, or
  a perched character, is never moved.
- **perched characters:** a bible entry with `layout2d.perch` (a laptop on a desk) is placed on that prop in every
  framing. Give it no transform.
- **props:** a workspace image (`file`, keyed with `studio.key`) or a series asset (`assetId`), at `x`/`y` (%) and
  `scale` (fraction of the frame height), or on a location `anchor` from the bible (that point in every framing).
  `"ground": true` (or `"grounded": true`, as on a 3D object) stands a figure or object on the floor: its lowest
  opaque row goes on the cast's feet line (94 % of the frame height in a wide shot or a vertical two-shot; elsewhere
  the set's floor through that framing's zoom, below the frame in a medium or close shot, like the cast's feet), or
  on its `anchor`. `y` is then ignored (an anchor stands it further back); without `ground`, `y` is its centre.
- **layers (a set in depth):** a location's `layout2d.layers` (`series.update`, at most 8) are drawn over its
  background in every 2D shot there: `{"assetId" | "file", "depth": 0.3, "front": false, "opacity": 1, "x": 50, "y": 50,
  "scale": 1, "drift": 0}`. `depth` 0 is the background's far plane, 1 the nearest; the cast stands at `castDepth`
  (default 0.6, on the location or the shot). `front: true` draws it in front of the cast (a pillar, a candle, foreground
  fog; default depth 0.9); the others go behind, farthest first (default 0.3). Use PNGs with alpha
  (`studio.key`) or looping mp4/webm videos. `x`/`y` (%) put the layer's centre on the background (its spot in every
  framing); `scale` is a fraction of the frame height (1: a frame-sized image fills the frame). A `push` moves every
  plane by its depth: the far wall grows less than the cast, the pillar in front more. `drift` (frame px/s, negative
  to the left) slides a layer on its own, also in a static shot: fog or smoke, `scale` 1.2 or more so its edge stays
  out of the frame. A video layer loops from its first frame in every shot unless it has any of `start` (the clip second shown
  at the shot's first frame, 0–3600), `speed` (0.1–4) and `loop`: `"loop"` (start again, the default), `"hold"`
  (keep the last frame) or `"pingpong"` (play back and forth). A 5 s clip behind many shots: give it `"loop":
  "pingpong"` and `"speed": 0.5` so it never visibly restarts, and a different `start` in each shot (its own
  `layers`) so they show different seconds. A shot's `layers` replace its location's (in a script, `"layers"` and
  `"castDepth"` on the shot) and `[]` turns them off. A bad layer is refused. Changing a location's layers renders again only its 2D shots that draw them.
- **music:** one music track per shot (a bumper at the start of a scene, a theme); a language can have its own file.
- **sfx:** sound effects at a line's `start`/`end` (`line`, `anchor`, `offset` s) or at a second (`at`), `volume`
  0–1. Files from the bible only. `{"anchor": "enter", "cast": 1}` plays it when that cast member's entrance starts
  (`cast`: an index into the shot's `cast` or a character id; plus `offset`), so footsteps or a door start with the
  walk; for one who does not enter, at the start of the shot. A cue plays its whole file unless it has `in` (the
  file second it starts at) and/or `length` (seconds): `{"file":
  "sfx-steps.wav", "in": 2.4, "length": 0.35, "anchor": "enter", "cast": 1, "repeat": "steps"}` plays one footstep
  of an 8 s walk on every footfall. The part is written once as `<file>-cut-<hash>.wav` (with its provenance), the
  file the take's scene names. Footsteps lasting exactly the entrance: one footstep and `"repeat": "steps"`, or a
  loop cut to `enterDuration`. `fx` take the same `anchor`/`cast`.
- **video takes (`kind: "video"` in the script = `imported_video`, `"generated"` = a MiniMax H3 `generated_video`
  shot):** import the clip with `series.asset.import` (`as_take: true`). Its shot's `sfx` (at `at` + `offset` s: no
  lines to anchor on), `music` and `foley` go on the take at `series.assembly.start`, over the clip's own sound
  (`"clipAudio": "drop"` drops it, `"clipVolume"` 0-2 sets it). A clip whose size, frame rate or pixel aspect differ
  from the episode's (1920x1080 or 1080x1920, 24 fps) is conformed at the cut: scaled and centre-cropped when its
  shape is within 6 % of the frame's, else fitted with bars (`"clipFit": "cover" | "contain"` forces it). The take
  file never changes, and a new sound only recuts. Do not mux sound or re-encode clips with ffmpeg before importing.
  An H3 clip made here (a `video` shot with a `video` request, or a Series Lab render) takes its shot's
  `"resolution": "480p" | "540p" | "720p" | "768p"`. Without it, a `video` request follows the series'
  `videoShotResolution` (480p when absent) and a Series Lab render `provider.videoSettings.resolution`. The next
  `produce` makes a `video` request again when its size changes; `series.shot.update` with a new `resolution` also
  clears that shot's take approval.
- **transitionIn** (optional, on the shot): `{kind, seconds}` is how this shot enters from the previous one. `kind` is `cut` (the default), `fade_black`, `dissolve` or `dip_white`; `seconds` is from 0.2 to 2. A `cut` holds the previous shot's last frame 0.5 s and dissolves 0.4 s into this one, also when other shots have transitions. A `dissolve` overlaps picture and sound and shortens the cut by that much; `fade_black` and `dip_white` fade the previous shot out and this one in and do not overlap. A shot before any of these three ends on its own last frame, with no held frame.
- **foley** (on the shot, not in `layout2d` or `scene3d`; same key in the script)**:** `{"prompt": "wooden airship
  creaking, wind, cannon shots", "volume": 0.5}`. After the export, MMAudio (`generation.sfx` with the export as
  `video_guide`) makes sound that follows the shot's picture, mixed under the lines, music and `sfx` at `volume` (above
  0 up to 2, relative to the dialogue, default 0.5). Use it where hand-placed `sfx` cannot follow the motion (ships,
  swords, creatures, explosions; 3D shots above all) and describe sounds only: the take has its voices and music. It
  is an extra: without MMAudio, or when it fails or takes over 30 min, the take is made without it and the render item
  has a `warning`; fix it and render that shot again by id. A new prompt or volume makes `produce` render that shot again. On a video take the render makes
  only the sound (`foley-<episode>-<shot>-<key>.wav`, from that take's picture), laid under the take at the cut: make
  it with `series.shot.update` (`render: true`) or `render_native` with its `shot_ids`; until then the cut goes without
  it and its `preparedClips` says so.
- **fx:** screen effects at the same kind of time: `kind` from `scenes.effects.catalog` (confetti, manga_impact,
  speedlines…), `duration` (seconds, 0.1–30, default 1; a value outside that range is clamped, never reset to 1;
  `"shot"` lasts until the end of the shot), `x`/`y`/`size` in %, `color`, `rotation` (degrees; a `laser` drawn across `x`/`y`
  points right at 0). A `laser` or `lightning` fired by someone starts at `from`: `{"cast": 0, "point": [95, 46]}` is a point
  in % of that cast member's pose image (`cast`: its index in the shot's `cast`, or a character id), so the beam leaves
  the muzzle wherever the cutout is drawn, at any size, even under a push; `{"point": [70, 40]}` is a frame point.
  The beam runs from `from` to `x`/`y` (where it lands); `rotation` is not used. A `cast` naming no
  one in the shot fails the render; a 3D shot keeps only a frame point. Keep effects off faces: a small burst to one
  side. Light for dark, painted frames: `shockwave` is a ring of light from `x`/`y` (`size` its reach) with a flash, a
  soft halo, trailing echoes and sparks; `shield` is a dome of light around someone (`size` its height) that reads even at
  `intensity` 0.4 and stays see-through; `embers` rise and cool from the bottom of their box; all keep `color`.
  `impact_flash` (a white frame, then ink focus lines) and `impact_invert` (the negative of the frame) cover the
  whole picture: give them 2–4 frames (`duration` 0.08–0.17 s at 24 fps) right on the hit. `code_rain` (falling
  green code; `size` the glyph height in %, default 3) covers it too, faces included: for code behind the cast, render
  a location plate from the `anime-code-rain` Video 3D shot instead.
  The cinematic grades also cover the whole picture: `candlelight` (warm flickering key light, `x`/`y` the flame,
  `size` its radius), `vignette`, `film_grain`, `light_rays` (`x`/`y` the window, `rotation` where the light
  goes), `glitch` (bursts of digital tearing) and `canvas` (a painted-canvas texture). Give a grade the whole shot
  (`at` 0 and `"duration": "shot"`); it repeats over its cue, so a plate as long as the cue loops.
- **timing:** `intro` (silence before the first line, default 0.35 s), `gap` (between lines, 0.22), `tail` (after the
  last, 0.45). A line's `pauseBefore` adds a dramatic beat.
- **voiceRoom:** the room this shot's voices are heard in, instead of its location's (see Sound design): `none`,
  `small_room`, `room`, `hall`, `cathedral`, `cockpit`, `outdoor` or `radio`. In a script, `"voiceRoom"` on the shot.
  A place reaches only the speakers in the shot (its `cast`, else `visibleCharacterIds`; a 3D shot's `scene3d.cast`):
  a narrator or anyone else heard over the shot stays dry. `radio` is not a place: a transmission or a thought over
  the radio reaches every line of the shot. `none` keeps a shot dry in a roomed location. A
  line can carry its own `voiceRoom` (a dialogue beat's, or a script line's: `{"who": "narrator", "es": "...",
  "voiceRoom": "radio"}`), which wins over the shot and the location for that line, on screen or not.
- **card:** `title` (opening), `end` (credits), `disclaimer` (white text on dark; also news flashes). A card shot has
  no cast, a `durationSeconds` (4–7 s) and usually the `locationId` of a dark or title location.
- **durationSeconds** (`duration`)**:** only for shots without dialogue. With dialogue, the render sets it from the voices.
- **3D dialogue (`kind: "3d"` in the script, `productionMethod: animation_3d` + `scene3d` on a shot):** a Video 3D
  template (`world3d.templates.suggest`, or a personal one) or a saved scene file, and which object each speaking
  character is (`objectId`). The server render records the lines as for a 2D shot, makes each object talk as its
  Character Kit, exports and imports the take. A speaker with no object in the cast is heard over the shot (a
  narrator, a radio voice). `quality`: `draft` (fast) or `final`. `sfx` and `fx` play as in a 2D shot (screen effects
  over the 3D frame), on a line or at a second (`at`).
  The template's own effects, texts and clip cues are stretched to the shot's length (`"retime": false` keeps their
  seconds). `objects` places what does not speak: a 3D model from `model3d.generate`/`model3d.animate` (`file`, its
  `clip` by name, `clipPlayback` {speed, start, loop}) or an image cutout (`"media": "image"`), on a template object
  (`objectId`) or added to the scene (`"add": true`), with `position`/`scale`/`rotationY` (radians, metres),
  `grounded: true` for a character standing on the floor, and a `motion` {to, via, points, faceTravel, headingOffset,
  easing}. `faceTravel` turns the model's +Z along the path; a generated ship or airship whose nose is its -X needs
  `headingOffset: 1.5708` (+X: -1.5708, -Z: 3.1416):
  `{"objectId": "zep", "file": "zeppelin.glb", "add": true, "clip": "Fly", "position": [-6, 3, -8],
  "motion": {"to": [6, 3, -8], "faceTravel": true}}`.
  `"renderLook": "toon"` draws the 3D models as cel anime with an ink outline (`toon` {steps 2-4, outline 0-8 px,
  ink #rrggbb}) so they sit with the flat cutouts and painted backgrounds; images and cutouts keep their look.
  An object also takes:
  - **Clip sequence:** `clips` instead of `clip`: `[{clip (name), start (shot seconds), duration?, fade? (0.3 s), speed?
    0.1-4, offset? (clip seconds), loop?}]`, crossfaded, up to 32.
  - **In a hand:** `hold` `{carrier, hand: "left" | "right", offset? [x, y, z] m, rotation? [x, y, z] radians}`
    carries the object in another model's whole hand, through every clip. The carrier is another 3D object of the
    shot, a template model object, or the object of a cast member who does not speak in that shot (a speaker is its
    Kit cutout, with no hands). `rotation` is Euler XYZ in the hand bone's frame after the bone's rotation: it aligns
    the prop without editing its file and replaces `rotationY`.
  - **Rig axes:** in a T pose every bone's axes are the character's: +X its left, +Y up, +Z forward. In the rig's `Aim`
    clip, a prop modelled along +X (top +Y) lies level along the aim with `rotation: [-1.65, 0.11, 2.76]`.
  - **Appearance:** `appearance` `{start, duration? 0.9, color? #rrggbb}` hides the object until `start`, then it
    materializes.
  - **Size:** a model is 1.7 m × `scale` tall: its bounding-box height, whatever its length. A rifle modelled lying flat
    (0.99 long, 0.32 high) is 4.7 m long at 0.9, so it needs about 0.16.
  - **Checks:** `from_script` checks each object's model file, clip names, sequence, hold and appearance before
    writing anything; a carrier that is unknown or talks fails the render with a clear message.

## 3D sets: molds, skins and props

1. Read `scene3d.sets.catalog` to choose a mold, size, camera, character marks and prop anchors.
2. Call `series.location.set3d` with a version 1 envelope and a new `intent_id`:
   `input: {workspace, series_id, location_id, mold: "despacho", size: "medium", skin, props: []}`.
   For example, `skin = {wall_back: {image: "straight-on shelves and framed plans"}, floor: {texture: "oak parquet", tile_m: 1}, wall_left: {color: "#b9aa94"}}`.
   `wall_back: {image: "location"}` reuses the approved location picture. Asset skins: `{image: {asset: "wall.png"}}`,
   `{texture: {asset: "tile.png"}}` or `{video: {asset: "screen.mp4"}}`. Poll `series.location.set3d.status` until
   completed (a failed status carries its error). A `texture` that will not tile is painted once over its surface
   instead (`metrics.fallback: "image"`): the set is still built.
3. The location's 3D shots inherit its set; `scene3d.roomCamera` selects `two_shot`, `ots_a`, `ots_b`, `wide`, `close_1`, `close_2` or `entrance`.
   In `series.episode.from_script`, use `kind: "3d", cast: [["pedro", "base", "behind_desk"]]`; unknown marks warn and use a valid fallback.
4. Create a prop with `props.create`: `input: {workspace, name: "lamp", description: "small brass desk lamp", heightM: 0.4, style: "layered paper cutouts"}`.
   Poll `props.status` with `job_id`, look at the candidate PNGs, then `props.approve` the chosen `id`.
   `props.list` filters by `style` and `query`; `props.import` accepts an existing PNG and `heightM`.
   For an image outside the library, `image.remove_background` takes `source, method: "auto" | "screen" | "u2net", crop: true` and returns `file`, `bbox`, `method` and halo report.
5. Add an approved prop to one shot with `scene3d.item.add`:
   `input: {workspace, target: {series_id, episode_id, shot: 1}, item: {prop: "<approved-id>"}, at: {anchor: "desk_left"}}`.
   A working Video 3D scene uses `target: {scene_id}`; direct media uses `item: {image: "lamp.png"}` or an existing `{glb: "lamp.glb"}` with `heightM`.
   `scene3d.item.list` returns object ids; move one with `scene3d.item.update` and `id, at: {position: [x, y, z]}` (metres).
   Remove it with `scene3d.item.remove` and `id`; updates can change `heightM`, `rotationY` (radians), `billboard` and `shadow`.
   For every shot at the location, put `{prop: "<approved-id>", anchor: "desk_left"}` in `set3d.props`.
6. Every mutation takes a new `intent_id` (the same one only to retry the identical call); read each result first.
   The back wall's straight-on painting, in the series style, carries the detail. Real heights on the mold's anchors
   rest objects on their surfaces (a tall object at a low anchor warns `item_too_tall`). At most 12 objects per shot,
   inherited set props included; look at the previews before approving.
7. Molds carry a `kind` and `title`. Shape molds (`sala`, `sala_ventana`, `mostrador`, `filas`, `pasillo`, `umbral`, `escalera`,
   `escenario_publico`, `vehiculo`) and exteriors (`calle`, `plaza`, `orilla`, `azotea`: no ceiling, the view on `wall_back`, a sun
   preset) sit beside the named interiors. A `kind: "3d"` shot may name a stage card, `scene3d: {template: "stage-sala",
   roomCamera: "ots_a"}`: the mold in its own colours, with dust and a breathing key light; a location set still brings the skin.

## How to choose a 3D shot

Cards are chosen on axes: `uses` (dialogue, talk, reaction, figure, establishing, action, speed, impact, reveal,
product, music, drive, transition, title, look, plate), `kind`, `place`, `shot`, `moves`, `still`, `subjects`,
`travel`. `world3d.templates.suggest` first (`line`, `speakers`, `place`, `mood`, `beat`…): up to three cards with
a `reason`, the filters it derived and `unknown_words` (words no card knows). Then `world3d.templates.list` with
those filters or words in either language; `match: partial` means no card had every known word: pick an id from the reply. A stage is
`stage-<mold>` (28, `stage-sala`, `stage-cocina`…): two speaking marks and the cameras `two_shot`, `ots_a`, `ots_b`,
`wide`, `close_1`, `close_2`, `entrance` (`roomCamera`); five are `far` from `two_shot`: shoot their lines from a
closer camera. Packs: `dialogue-*` (`ots-a`/`ots-b` keep the eyelines, `table`, `triangle`, `embrace`,
`phone-split`), `reaction-*`, `speed-*`, `group-*`, `title-*` and `transition-*` (a shot of its own, 0.6–2.5 s;
`transitionIn` is the join between two takes and needs no card). Modifiers go on the scene, not on the shot:
`world3d.scene.instantiate` → `world3d.scene.patch` with `light` (`noon`… `dawn`), `grade` (`natural`… `film`),
`lens` (`14mm`–`200mm`) or `camera_template` (a `kind: camera` card) → `world3d.scene.publish` → `scene3d:
{"scene": "<file>"}`. What the production dry run warns ruins a series shot too: `template_still` (a `still` card
with no clip, motion, camera or world), `stage_unskinned` (a stage in its mold colours: give the location a set
skin), `looks_samey` (one template and place in more than four shots in a row), `template_reused` (one card in
more than four shots).

## Edit one shot ("the fifth shot")

`series.shot.get {workspace, series_id, episode_id, shot}` reads one shot and `series.shot.update` edits it, by id
(`"e3s04"`) or by its number (`5`: the fifth shot, the `#5` Series Lab shows; `from_script` ids count from `s00`, so
it is `e3s04`). Send only what changes, in the script keys above:

```json
{"workspace": "ws", "series_id": "uv", "episode_id": "ep3", "shot": 5,
 "changes": {"camera": "push", "timing": {"tail": 1.0}},
 "append": {"fx": [{"kind": "manga_impact", "line": 1, "x": 70}], "props": [{"file": "prop-hat.png", "x": 30, "y": 22, "scale": 0.1}]},
 "render": true}
```

`changes` replaces keys (`null` removes one), `append` adds to `cast`, `lines`, `sfx`, `fx`, `props` or `layers`.
The shot is checked like a script shot and only the changed fields are written; the takes stay. A shot whose take no
longer fits loses its approval in every language (a video take keeps it when only its cut sound changed). Lines in
other languages update those versions. `check: true` only checks; `render: true` renders just that shot (approved;
`approve: false` keeps it pending); `produce: true` renders what changed in every language and recuts. Without
`changes`, `instruction: "put a hat on Kevin"` has the server's LLM write the edit from the shot, the cast's poses
and the workspace files (the reply's `instruction` says what it wrote). Prefer it to resending the script for a one-shot fix. The Wizard
does the same with `edit_series_shot`.

One line's voice, without rendering the shot: `series.shot.voices {…, shot}` lists each line with its recording
(the `ln-*.wav` the next render reuses: `recorded`, `url`, `room`, and `newerThanTake` when it was recorded after the
shot's latest take). `series.shot.voice {…, shot, line}` (`line`: the beat id or its number in the shot, 1 = the
first) records it now the way the render does, as a job followed with `series.shot.voice.status`. A line recorded
with that text and voice is kept; `retake: true` records with another seed and replaces the recording only once it
is good. Change the text first with `series.shot.update` (`lines`), record the line, listen to
it, then render the shot (`render: true`) to hear it in the take; the render reuses the recording. Nothing records
while the episode renders on the server. The Wizard does it with `regenerate_series_line_voice`.

## Media steps inside HocusPocus

Do these in the app, never with scripts: every file made has a `.meta.json` naming its source and tool, so
it can be found, reused and redone.

- **Cutouts:** `studio.key` reads the screen colour from the image border (`adaptive`, default true), keys against
  it and clears the backdrop touching the border (which colour: `characters.styles`, above); `despill` (default true)
  takes it off the edges. Check `result.report`: `semiTransparentShare` is the residual haze (alpha 6-199); `haze: true` (20 % or
  more) means the screen did not key: try another `mode` or generate the image again. Do not re-key with scipy.
- **A frame of a clip:** `media.frame {workspace, source, at: seconds | "first" | "last", output_name}` saves it as
  a PNG (for an image-to-video start frame, or a reference).
- **A still from layers:** `media.compose {workspace, base (an image, or a video with base_at), layers: [{file, x, y,
  scale, anchor: "bottom", flip, rotation, opacity}], output_name}` pastes keyed cutouts over a frame or a canvas. A
  whole Video 2D scene at one time: `scenes.video2d.preview` with one time, `still: true` and `output_name` (full
  size, kept as an image).
- **Part of a sound:** a cue's `in`/`length` (above), or `audio.trim {workspace, source, start, length | end,
  output_name}` for a new audio file (an exact cut, keeps the sample rate and channels).
- **Files from another workspace:** `assets.import_from_workspace {workspace, source_workspace, file,
  destination_filename}` copies a GLB, image, audio or video with its metadata and records its origin.
  Do not `cp` between workspaces.
- **A stable name for an export:** `scenes.world3d.export` and `scenes.video2d.export` take `output_name`
  (`"set-crane-loop"` publishes `set-crane-loop.mp4`). Exporting again under that name replaces the file once the new
  render is encoded (a layer or prop naming it shows the new render) and keeps the old one as
  `set-crane-loop.previous.mp4`. Name it in `layers` (`{"file": "set-crane-loop.mp4", "depth": 0.2}`) instead of
  copying the export. A file changed under the same name is not seen as a change: render the shots that show it
  again (`series.shot.update` with `render`, or `series.episode.render_native` with their `shot_ids`).
- **A new name per variant:** every `generation.image`, `generation.speech` and `generation.video` variant gets its
  own `output_name`. A name in use keeps the old file and saves the new one as `name(2)` (warning
  `output_name_taken`): use the path the result returns.

## Sound design

`soundDesign` on the series (`series.update`, replaced as one object: see Known pitfalls) is the sound every shot gets
without the script naming it:
`stinger` (`{file, volume}`) under the first shot of each scene, `ambienceByLocation`
(`{"<locationId>": {"file": "sfx-rain.wav", "volume": 0.22}}`, volume 0–2 relative to the dialogue, default 0.22) and
`roomByLocation` (below).
`ambienceMode` says where the ambience is mixed:

- `"shot"` (default): each shot mixes its location's ambience from its own start. It restarts at every cut, and a
  new file or level renders every shot of that series again.
- `"episode"`: the shots leave it out and `series.assembly.start` lays one bed per run of consecutive shots in the
  same location, looped with a 1 s crossfade, faded in and out over 0.8 s, crossfading into the next location's bed.
  A location without an entry (a dark title card) gets none. Changing the beds renders no shot: `produce` only
  recuts. Switching the mode renders every shot once. `ambienceDuckDb` (0–24,
  default 0 = off) lowers the beds that many dB while someone speaks, like the score below.

**Score.** A shot's `music` plays only in that shot. `score` on the episode (`series.episode.update` with `episode: {"score": [...]}`) lays music cues
across runs of shots at assembly: `{"fromShotId": "e3s04", "toShotId": "e3s12", "file": "mus-theme.wav",
"volume": 0.18, "fadeIn": 1.5, "fadeOut": 2.0, "duck": true}`, or `{"sceneId": "e3_bar", "file": ...}` for a
scene's shots. Use the ids `series.episode.get` shows (Ids, above). Only `file` and the shots are required; the
numbers shown are the defaults (volume 0–2 relative to the dialogue, fades 0–30 s). Cues may not overlap (two cues
may meet at a cut).

- A cue plays from the cut before its first shot to the cut after its last (looped with a crossfade when the file
  is shorter, faded in and out inside the cue), in every clip kind and language version.
- With `duck` it dips 9 dB under every recorded line (0.25 s down before the line, 0.6 s back up after it; lines
  less than 1.5 s apart share one dip). A shot with its own `music` keeps it and the score is silent under it.
- The score is in no take: changing it needs only `series.assembly.start` (or `series.episode.produce`, which
  only recuts). `"score": []` removes it.
- A cue naming a shot the episode does not have is refused; one left behind when a rewrite removed its shots is
  skipped by the assembly, which says so in the cut's `score.skipped`.

Every assembly checks each take's sound against its pictures: `series.assembly.status` returns `sync` (`inSync`,
`maxLagMs`, `late` with each off clip's `index` and `lagMs`, `unsure` for takes too quiet to place). With `inSync:
false` the lips are visibly off from the first clip in `late`: report it, do not deliver it as finished.

`roomByLocation` (`{"<locationId>": "<preset>"}`) makes the voice sound like the place. Lines are recorded dry; a
room plays a processed copy of each line (the dry recording is kept; lip-sync and timing stay the dry line's):

| preset | what it does |
| --- | --- |
| `none` | dry (the default; also overrides a location's room on one shot or one line) |
| `small_room` | a closet or cabin: tight reflections and 0.28 s of tail, 17 dB under the voice |
| `room` | an office or kitchen: 0.45 s, 16 dB under |
| `hall` | a corridor, a lobby, a gym: 1.1 s, 15 dB under |
| `cathedral` | stone, a cave, a vault: early reflections, then a 2.2 s dark tail after 50 ms, 14 dB under (it rings on past the line for at most 0.8 s) |
| `cockpit` | small, metallic and close: dense reflections within 10 ms, a band-limited voice with a presence peak |
| `outdoor` | no reverb: a gentle low cut and one very slight, dark slap |
| `radio` | telepathy, transmissions, a phone: 420 Hz to 3.3 kHz, lightly distorted |

The places are subtle on purpose: felt mostly as early reflections, never costing a word. A room has no low end
(cut at 200–350 Hz) and no sibilance (cut at 4–6 kHz), its tail starts after a predelay, and it keeps the voice's
speech transmission index above 0.9 and clarity (C50, 500 Hz–2 kHz) above 12 dB. Each copy is levelled to the dry
line: a room never changes how loud a voice is. Who hears a place: `voiceRoom`
above. Changing a room renders again only the shots with lines that hear it. The tail of the last line is cut where the shot
ends (0.45 s after it): give a shot in a big room `timing: {"tail": 1.0}` to let it ring out.

## Writing for quality

- One idea per line; short lines land better and lip-sync better. Write numbers and acronyms as they are spoken.
- Judge lip-sync on 12 frames of one long line, with the mouth enlarged. The contact sheet hides a mouth that barely opens.
- Every scene starts on a `wide` that shows who is there, then `two`/`medium`/`close` for the exchange, and a
  `close` + `push` on the punchline.
- Use the bible's rules (running gags, how each character speaks, how episodes end); its voice traits give each
  character's rhythm.
- Cold open (30–60 s), title card (7 s, theme), 3–4 scenes, ending with the moral, credits card (6 s): 5–6 minutes,
  45–55 shots.
- Parody of public figures: satirise their public persona only; every voice is synthetic and described by traits.

## Known pitfalls

- Episodes freeze the approved canon: add characters and locations, then `series.canon.approve`, then create the episode.
- `series.update` keeps every top-level field you omit and replaces every top-level field you send, as a whole.
  A `soundDesign` with only `ambienceByLocation` drops `stinger`, `roomByLocation`, `ambienceMode` and `ambienceDuckDb`.
  A `characters` list with one character drops the others and saves that one as sent (missing traits become
  defaults, not the stored ones); so do `canon`, `locations` and `assets`. Send `[]` or
  `{}` to clear a field. Each episode's review stays the stored one. Read with `series.get` (it returns the whole
  project, assets included), edit a copy, send it with `base_revision`, and keep a JSON copy before a large change.
- A language version keeps its own takes, lengths and music; approve its takes with `series.take.approve` + `language`.
- Effects and sounds placed by hand in a take's scene are lost when the shot renders again: declare them in the
  script (`sfx`, `fx`).
- Image references for `generation.image` are workspace URLs `/api/v1/file/<name>?workspace=<ws>`.
- A `generation.*` receipt can stay `queued` after the job finished: wait with `jobs.wait` and read the files from
  its `task.result_refs`.
- `qa.export` flags cards and pauses as problems; judge an episode by its takes.
- In `plan` or `preview` mode a render or production that seems to do nothing waits for the user's approvals: read `job.waiting`
  or `series.episode.review.get` instead of rendering again.
