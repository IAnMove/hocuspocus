# Making an episode in HocusPocus Series Lab (guide for agents)

This is how an agent with only these MCP tools makes an episode of a 2D cutout animated series: cast, voices in
each language, lip-sync, effects and a finished cut with subtitles. Everything runs locally: images, voices, lip-sync, Video 2D/3D, export and assembly.
The bible that comes with this guide lists the series' real characters, kits, poses, locations, music and sounds:
use only those ids and file names, never invent one.

## The shape of the work

1. **Read:** `series.guide` (this), then `series.episode.get` for an earlier episode to copy its style.
2. **Cast and places (only if the story needs new ones):**
   - character: `characters.styles` (prompt in the series style; painted art: `graphic-novel`, below) →
     `generation.image` (base, then each pose with the base as `image_refs`) → `studio.key` → `characters.save`
     (approved assets) → `characters.rig.flat` (with the style's `rig` as `style`) → design a voice per
     language (`generation.speech` with `qwen3_tts_voicedesign`, check with `qa.speech`) → `characters.save` with
     `voicesByLanguage` → add the character to the series (`series.update`) with `voiceProfile.characterKitRef`.
     Check the pitch with `qa.speech` and `pitch_range`: an adult man sits at 85–155 Hz, an adult woman at 165–255 Hz.
     The series render does not apply that range on its own yet;
   - rig check: look at the review image `characters.rig.flat` returns. A face with realistic proportions (small
     eyes in a wide head: graphic-novel or tenebrist art, eye bags, spectacles, moustaches) is detected, and its mouth
     is the thin line about one eye-pair width under the eyes. For that art rig with `style: {"mouthStyle": "warp"}`
     (the `graphic-novel` style does it for you, see below):
     each pose talks with its own drawing (the lower lip, chin and beard move down, the gap is inked); check each
     pose's mouth line with `characters.rig.flat.preview` (warnings `mouth_line_guessed`, `mouth_line_unsure`) and
     pass a better one as `hints.<pose>.mouth` (a point on the line between the lips) and `mouthWidth`.
     `"ink"` keeps the painted mouth as the rest shape and draws the open shapes in its own ink. If a pose's mouth or
     eyes are still found in the wrong place, rig again with `hints: {"<pose id>": {"mouth": [x, y]}}` (or `"eyes"`),
     in % of that pose's keyed image; later rigs reuse the hints, and `null` clears a pose's hints;
   - location: `generation.image` 1920x1088 in the series style → `series.update` (new location) → `series.asset.import`
     (owner_type location, reference_role environment); for depth, also make its planes as separate keyed images (a
     pillar or a bed frame in front, columns behind the cast) and list them in its `layout2d.layers` (below).
     Paint the plate empty of anything that must move (boats, waves, crowds, rain): a frozen wave reads as broken.
     Animate that motion afterwards, as an H3 loop or a Video 3D scene;
   - 3D background: `world3d.templates.list` → `world3d.scene.instantiate` → `series.location.plate3d` (a silent loop).
     An H3 loop sets `image_start` and `image_end` to the same image. If the seam is about three times one normal
     step, blend the last 14 frames;
   After changing characters or locations, `series.canon.approve` (episodes freeze the approved canon).
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

An episode is made in one of three modes, chosen by the user in Series Lab (Validation) or with
`series.episode.review.set` `mode`:

- `direct` (default): steps 4–5 above, nothing waits.
- `plan`: each shot's plan (cast, poses, lines, framing, camera, set) is approved by the user before it renders.
  `series.episode.render_native` and `produce` render only approved shots; the rest are listed as `waiting`.
- `preview`: plan approval, then a preview render the user approves or sends back with notes, then the final. The
  preview of a 2D shot is its normal render; a 3D shot's preview is exported at `draft` quality. An approved 2D (or
  draft 3D) preview becomes the final take without rendering again; a 3D shot at `final` quality renders its final.

Work with the user's review like this:

1. `series.episode.review.get`: the mode, the steps left and, per shot, `plan`/`preview` (`pending | approved |
   changes`), its `step` and every note `{stage, text, by}`. Shots in `changes` are the user's requests.
2. Fix each requested shot (`series.shot.update` for one shot, `series.episode.update`, or the script again with
   `episode_id`). Changing a shot's content
   puts its approvals back to pending (notes stay), so the user looks at it again; a new take of a shot puts its
   preview back to pending.
3. Answer on the shot: `series.shot.review.set` with `note: {text: "what I changed", by: "agent"}` (and `plan` or
   `preview: "pending"` if you changed nothing the review can see). Never approve on the user's behalf unless asked.
4. `series.episode.produce` (or `render_native`): it renders what the review lets through and stops `waiting` before
   the cut while shots wait; `resume` it after the user approved. `series.assembly.start` refuses a staged episode
   that is not fully approved (409 `review_pending`) unless `force: true`.

## Painted / graphic-novel characters that talk

For painted art (graphic novel: bold ink, flat black shadows) use the `graphic-novel` character style. Its mouths
are the drawing's own (warp mouths): the upper lip stays, the lower lip, chin and beard move down, the gap is a flat
dark mouth in the character's ink.

1. **Generate for the rig.** `characters.styles` with `style: "graphic-novel"`, `kind: "character"` (then `"pose"`)
   and the description. The prompt asks for what the rig must find: both eyes with clean white sclera, never in the
   shadow, and the closed mouth painted as one short dark line. Key in the screen colour `characters.styles` returns:
   magenta when the character or object is green, so green cloth is not keyed away, and green otherwise.
2. **Save and rig.** Save the kit with `provenance: [{"method": "character-style-create", "style": "graphic-novel"}]`;
   `characters.rig.flat` then uses the style's rig, `{"mouthStyle": "warp"}`, with no `style` (passing it does the
   same). Later rigs of the kit (a pose added, a mouth line placed) keep warp mouths: only `style.mouthStyle`
   changes them. The result's `style` is the look used.
3. **Check every pose.** Look at the review image and each pose's `mouthLine` (`mouth`, `mouthWidth`, `found`,
   `from`: hint, landmarks, painted or guess). Warning `mouth_line_guessed` (no painted line where the mouth was
   put) or `mouth_line_unsure` (unsure face points, a mouth under a moustache) means: see it with
   `characters.rig.flat.preview` and rig again with `hints: {"<pose>": {"mouth": [x, y], "mouthWidth": w}}`, a point
   on the line between the lips and the width corner to corner, in % of the pose image. In the app a user does the
   same in Characters › Prepare 2D speech › Face Rig › **Mouth line**. Only a hint with `"exact": true` is followed as
   given: add it only after looking at the preview. Without it, face landmarks that are sure of the lips place the
   mouth (`mouth_hint_ignored` when your point was far off them) and unsure ones let your point in, snapped onto the
   painted lips. Never type mouth points you have not looked at: a wrong one moved mouths onto a cheek and a chin.
4. **Make a bust for dialogue.** In a full figure the face is small and the moving lips read less: add a bust pose
   (`"bust, head and shoulders, ..."`) and use it in `medium` and `close` shots (`"cast": [["ana", "bust", 50]]`).
5. **Nothing else changes.** `series.episode.from_script` and `series.episode.produce` show each pose its own mouths.
   After a re-rig, `series.episode.produce` renders again the shots that use that kit.

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
  slow walk-in is 2–4 s) say otherwise; both stay inside the shot. `enterGait`: `hop` (default, a quick paper-puppet
  hop) or `walk`: the body bobs once per step, down on every footfall and up mid-step, and sways `enterSway`
  degrees (default 1.5, 0 for none). `enterStep` is the step in seconds (default 0.5; a slow monk 0.6–0.7): the walk
  takes a whole number of steps, so its feet land on the entrance's start, every step after it and its end, and
  the step is stretched a little to fit. `poseId` must be one of the kit's poses.
- **look room:** stand a character on the side away from where they look (the bible's `facing` per pose): facing
  `left` right of centre, facing `right` left of it; two people face each other. `from_script` moves a 2D cast member
  who looks out of the frame (`lookRoom` in the reply); `"lookRoom": false` on a cast entry or a shot keeps your `x`.
- **cut poses (edge snap):** a pose whose figure is cut by its image border (a bust cut at the chest and on one
  side) never shows that cut in the frame. The render reads the pose's alpha: a cut is a run of opaque pixels along
  the left or right border at least 8 % of the image height long, or along the bottom at least 15 % of its width (a
  stray pixel, a strand of hair or feet resting on the border are not cuts; the top is not read). A side cut that
  would show slides the cutout until that cut is just past the frame edge, at the same size; a bottom cut goes past
  the frame bottom (slid down in a wide shot, enlarged with the eyes on the framing's eye line otherwise); cut on both
  sides, it is enlarged proportionally until both cuts are out of the frame (at most 2.5×). A cut already outside the
  frame, or below it, moves nothing. The cut is read from the pose image itself, so a mirrored copy of a pose is cut
  on the other side. Give a bust cut on its left an `x` on the left of the frame (it lands on that edge anyway), and
  keep two cut busts on their cut sides in a two-shot. `"edgeSnap": false` on a cast entry keeps it where `x` puts it,
  cut and all; an entry with a `transform`, or a perched character, is never moved.
- **perched characters:** a character whose bible entry has `layout2d.perch` (a laptop on a desk) is placed on that
  prop in every framing automatically. Give it no transform.
- **props:** a workspace image (`file`, keyed with `studio.key`) or a series asset (`assetId`), at `x`/`y` (%) and
  `scale` (fraction of the frame height), or on a location `anchor` from the bible (it then stands on that point in
  every framing). `"ground": true` (or `"grounded": true`, as on a 3D object) stands a standing figure or object on
  the floor: its lowest opaque row goes on the line the cast's feet stand on (94 % of the frame height in a wide
  shot or a vertical two-shot; in the other framings the set's floor through that framing's zoom, below the frame in
  a medium shot or a close-up, like the cast's feet), or on its `anchor` when it has one. `y` is then ignored; use an
  anchor to stand it further back. Without `ground`, `y` is the prop's centre, as before.
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
  frame. A video layer loops from its first frame in every shot unless it has any of `start` (the clip second shown
  at the shot's first frame, 0–3600), `speed` (0.1–4) and `loop`: `"loop"` (start again, the default), `"hold"`
  (keep the last frame) or `"pingpong"` (play back and forth). A 5 s clip behind many shots: give it `"loop":
  "pingpong"` and `"speed": 0.5` so it never visibly restarts, and a different `start` in each shot (its own
  `layers`) so the shots do not all show the same seconds. A shot's `layers` replace its location's (in a script, `"layers"` and `"castDepth"` on the shot) and `[]`
  turns them off. A bad layer is refused. Changing a location's layers renders again only its 2D shots that draw them.
- **music:** one music track per shot (a bumper at the start of a scene, a theme); a language can have its own file.
- **sfx:** sound effects at a line's `start`/`end` (`line`, `anchor`, `offset` s) or at a second (`at`), `volume`
  0–1. Files from the bible only. `{"anchor": "enter", "cast": 1}` plays it when that cast member's entrance starts
  (`cast` is an index into the shot's `cast` or a character id; plus `offset`), so footsteps or a door start with
  the walk instead of after it; a cast member who does not enter plays it at the start of the shot. A cue plays
  its whole file unless it has `in` (the second of the file it starts at) and/or `length` (seconds): `{"file":
  "sfx-steps.wav", "in": 2.4, "length": 0.35, "anchor": "enter", "cast": 1, "repeat": "steps"}` plays one footstep
  of an 8 s walk on every footfall. The part is written once as `<file>-cut-<hash>.wav` (with its provenance) and
  the take's scene names that file. To make footsteps last exactly the entrance, give one footstep and `"repeat":
  "steps"`, or cut a loop to `enterDuration`. `fx` take the same `anchor`/`cast`.
- **video takes (`kind: "video"` in the script = `imported_video`, `"generated"` = a MiniMax H3 `generated_video`
  shot):** import the clip with `series.asset.import` (`as_take: true`). Its shot's `sfx` (at `at` + `offset`
  seconds; it has no lines to anchor on), `music` and `foley` are laid on the take at `series.assembly.start`, over
  the clip's own sound: `"clipAudio": "drop"` drops it, `"clipVolume"` (0-2) sets it. Every clip whose size, frame
  rate or pixel aspect differ from the episode's (1920x1080 or 1080x1920, 24 fps) is conformed at the cut: scaled
  and centre-cropped when its shape is within 6 % of the frame's, else fitted with bars (`"clipFit": "cover" |
  "contain"` forces it). The take file is never changed and changing its sound only recuts. Do not mux sound or
  re-encode clips with ffmpeg before importing them.
- **transitionIn** (optional, on the shot): `{kind, seconds}` is how this shot enters from the previous one. `kind` is `cut` (the default, the same join as today), `fade_black`, `dissolve` or `dip_white`; `seconds` is from 0.2 to 2. A `dissolve` overlaps picture and sound and shortens the cut by that much; `fade_black` and `dip_white` fade the previous shot out and this one in and do not overlap, so the episode stays the sum of the shot lengths.
- **foley** (on the shot, not in `layout2d` or `scene3d`; same key in the script)**:** `{"prompt": "wooden airship
  creaking, wind, cannon shots", "volume": 0.5}`. After the shot is exported, MMAudio (`generation.sfx` with the
  export as `video_guide`) makes sound that follows the shot's own picture, and it is mixed under the lines, music
  and `sfx` at `volume` (above 0 up to 2, relative to the dialogue, default 0.5). Use it where hand-placed `sfx`
  cannot follow the motion (ships, swords, creatures, explosions; 3D shots above all) and describe sounds only: the
  take already has its voices and music. It is an extra: without MMAudio installed, or when it fails or takes over
  30 min, the take is made without it and the render item has a `warning`; fix it and render that shot again by id.
  A new prompt or volume makes `series.episode.produce` render that shot again. On a video take the render makes
  only the sound (`foley-<episode>-<shot>-<key>.wav`, from that take's picture) and the cut lays it under the take:
  make it with `series.shot.update` (`render: true`) or `series.episode.render_native` with its `shot_ids` (a render
  of every shot makes it too); until then the cut goes without it and its `preparedClips` says so.
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
  A place reaches only the speakers who are in the shot (its `cast`, else `visibleCharacterIds`; a 3D shot's
  `scene3d.cast`): a narrator or anyone else heard over the shot stays dry. `radio` is not a place: a transmission or
  a thought heard over the radio reaches every line of the shot. `none` keeps a shot dry in a roomed location. A
  line can carry its own `voiceRoom` (a dialogue beat's, or a script line's: `{"who": "narrator", "es": "...",
  "voiceRoom": "radio"}`), which wins over the shot and the location for that line, on screen or not.
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
  An object also takes:
  - **Clip sequence:** `clips` instead of `clip`: `[{clip (name), start (shot seconds), duration?, fade? (0.3 s), speed?
    0.1-4, offset? (clip seconds), loop?}]`, crossfaded, up to 32.
  - **In a hand:** `hold` `{carrier, hand: "left" | "right", offset? [x, y, z] m, rotation? [x, y, z] radians}`
    carries the object in another model's whole hand, through every clip. The carrier is another 3D object of the
    shot, a model object of the template, or a cast member's object in a shot where that character does not speak. A
    speaker is drawn as its Character Kit cutout, which has no hands. `rotation` is Euler XYZ in the hand bone's frame,
    applied after the bone's rotation. It aligns the prop without editing its file, and it replaces `rotationY`.
  - **Rig axes:** in a T pose every bone's axes are the character's: +X its left, +Y up, +Z forward. In the rig's `Aim`
    clip, a prop modelled along +X (top +Y) lies level along the aim with `rotation: [-1.65, 0.11, 2.76]`.
  - **Appearance:** `appearance` `{start, duration? 0.9, color? #rrggbb}` keeps the object hidden until `start`, then
    it materializes.
  - **Size:** a model is 1.7 m × `scale` tall: its bounding-box height, whatever its length. A rifle modelled lying flat
    (0.99 long, 0.32 high) is 4.7 m long at 0.9, so it needs about 0.16.
  - **Checks:** `from_script` checks each object's model file, clip names, sequence, hold and appearance before it
    writes anything. A carrier that is unknown or talks fails the render with a clear message.
  - **Example:** `{"objectId": "guard", "file": "guard.glb", "add": true, "grounded": true, "clips": [{"clip": "Idle",
    "start": 0}, {"clip": "Aim", "start": 1.5, "fade": 0.4}]}, {"objectId": "rifle", "file": "rifle.glb", "add": true,
    "scale": 0.16, "hold": {"carrier": "guard", "hand": "right", "offset": [-0.146, 0.013, -0.038], "rotation": [-1.65,
    0.11, 2.76]}, "appearance": {"start": 1.5}}`.

## Edit one shot ("the fifth shot")

`series.shot.get {workspace, series_id, episode_id, shot}` reads one shot, and `series.shot.update` edits it, by id
(`"e3s04"`) or by its number in the episode (`5` is the fifth shot, the `#5` Series Lab shows; ids from
`from_script` count from `s00`, so the fifth shot is `e3s04`). Send only what changes, in the script keys above:

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
and the workspace files (the reply's `instruction` says what it wrote). Use it instead of sending the whole script
again for a one-shot fix. The Wizard does the same with `edit_series_shot` ("edita el quinto plano y ponle X").

One line's voice, without rendering the shot: `series.shot.voices {…, shot}` lists each line with its recording
(the `ln-*.wav` the next render reuses: `recorded`, `url`, `room`, and `newerThanTake` when it was recorded after the
shot's latest take). `series.shot.voice {…, shot, line}` (`line` is the beat id or its number in the shot, 1 = the
first) records it now with the render's own path, as a job you follow with `series.shot.voice.status`. A line already
recorded with that text and voice is kept; `retake: true` records another take with another seed and replaces the
recording only once it is good. Change the text first with `series.shot.update` (`lines`), record the line, listen to
it, then render the shot (`render: true`) to hear it in the take; the render reuses the recording. Nothing records
while the episode renders on the server. The Wizard does it with `regenerate_series_line_voice`.

## Media steps inside HocusPocus

Do these in the app, never with scripts: every file they make has a `.meta.json` that names its source and tool, so
it can be found, reused and redone.

- **Cutouts:** `studio.key` reads the screen colour from the image border (`adaptive`, default true), keys relative
  to it and clears the backdrop connected to the border. If the character or object has green, the screen is magenta
  (`characters.styles` already chooses it); key in that colour. `despill` (default true) takes the screen colour off
  the edges. Check `result.report`: `semiTransparentShare` is the residual haze (alpha 6-199); `haze: true` (20 % or
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
  destination_filename}` copies a GLB, image, audio or video with its metadata and records where it came from
  (Hunyuan3D models made on the main install, for example). Do not `cp` between workspaces.
- **A stable name for an export:** `scenes.world3d.export` and `scenes.video2d.export` take `output_name`
  (`"set-crane-loop"` publishes `set-crane-loop.mp4`). Exporting again with the same name replaces that file once the
  new render is encoded, so a layer or prop that names it shows the new render; the replaced file is kept as
  `set-crane-loop.previous.mp4`. Name it in `layers` (`{"file": "set-crane-loop.mp4", "depth": 0.2}`) instead of
  copying the export. A file changed under the same name is not seen as a change: render the shots that show it
  again (`series.shot.update` with `render`, or `series.episode.render_native` with their `shot_ids`).
- **A new name per variant:** every `generation.image`, `generation.speech` and `generation.video` variant gets its
  own `output_name`. Reusing a name replaces the previous file.

## Sound design

`soundDesign` on the series (`series.update`) is replaced as one object. Sending only `ambienceByLocation` drops
`stinger`, `roomByLocation`, `ambienceMode` and `ambienceDuckDb`. It is the sound every shot gets without the script
naming it:
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

Every assembly checks that each take's sound plays where its pictures do: `series.assembly.status` returns `sync`
(`inSync`, `maxLagMs`, `late` with each off clip's `index` and `lagMs`, `unsure` for takes too quiet to place). A cut
with `inSync: false` has lips visibly off from the first clip in `late`: report it, do not deliver it as finished.

`roomByLocation` (`{"<locationId>": "<preset>"}`) makes the voice sound like the place. Lines are recorded dry, so a
monk in a stone cathedral and a captain on an open deck would sound the same; with a room the render plays a processed
copy of each line (the dry recording is kept, and lip-sync and timing stay the dry line's):

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

The places are subtle on purpose: the room is felt, mostly as early reflections, and never costs a word. Its
sound has no low end (cut at 200–350 Hz) and no sibilance (cut at 4–6 kHz), and its tail starts after a predelay.
Every place keeps the voice's speech transmission index above 0.9 and its clarity (C50, 500 Hz–2 kHz) above 12 dB.
Every copy is levelled to the dry line, so a room never changes how loud a voice is. A place reaches only the
speakers in the shot, a `radio` every line, and a line's own `voiceRoom` wins (see `voiceRoom` above). A shot
overrides its location with `layout2d.voiceRoom`. Changing a room renders again only the shots with lines that hear
it; a series without `roomByLocation` renders exactly as before. The tail of the last line is cut where the shot
ends (0.45 s after it): give a shot in a big room `timing: {"tail": 1.0}` to let it ring out.

## Writing for quality

- One idea per line; short lines land better and lip-sync better. Write numbers and acronyms as they are spoken.
- Judge lip-sync on 12 frames of one long line, with the mouth enlarged. The contact sheet hides a mouth that barely opens.
- Every scene starts on a `wide` that shows who is there, then `two`/`medium`/`close` for the exchange, and a
  `close` + `push` on the punchline.
- Use the bible's rules (running gags, how each character speaks, how episodes end). The voice traits in the bible
  tell you each character's rhythm.
- Cold open (30–60 s), title card (7 s, theme), 3–4 scenes, ending with the moral, credits card (6 s): 5–6 minutes,
  45–55 shots.
- Parody of public figures: satirise their public persona only; every voice is synthetic and described by traits.

## Known pitfalls

- Episodes freeze the approved canon: add characters and locations, then `series.canon.approve`, then create the episode.
- `series.update` keeps every top-level field you omit and replaces every top-level field you send, as a whole.
  A `soundDesign` with only `ambienceByLocation` drops `stinger`, `roomByLocation`, `ambienceMode` and `ambienceDuckDb`.
  A `characters` list with one character drops the others, and that character is saved from what you sent (missing
  traits become defaults, not the stored ones). The same is true of `canon`, `locations` and `assets`. Send `[]` or
  `{}` to clear a field. Each episode's review stays the stored one. Read with `series.get` (it returns the whole
  project, assets included), edit a copy, send it with `base_revision`, and keep a JSON copy before a large change.
- Before queueing image, speech or video while another instance is running, check `nvidia-smi`. If another process
  holds more than 2 GB, wait. Do not restart that instance.
- A language version keeps its own takes, lengths and music; approve its takes with `series.take.approve` + `language`.
- Effects and sounds placed by hand in a take's scene are lost when the shot renders again: declare them in the
  script (`sfx`, `fx`) instead.
- Image references for `generation.image` are workspace URLs `/api/v1/file/<name>?workspace=<ws>`.
- `generation.*` receipts can stay `queued` while the job finished: wait with `jobs.wait` and read the files from the
  receipt's `task.result_refs`.
- `qa.export` flags cards and pauses as problems; judge an episode by looking at its takes.
- In `plan` or `preview` mode a render or production that seems to do nothing is waiting for the user's approvals:
  read `job.waiting` or `series.episode.review.get` instead of rendering again.
