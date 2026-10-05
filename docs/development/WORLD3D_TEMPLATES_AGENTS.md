# Video 3D templates for agents

The editor's shot library is the only library. MCP, Ask the Wizard, and the production planner search the same short cards in `app/shared/world3d_templates.json`. A card has the exact id, both titles, format, duration, playback speed, roles, and one line. The full scene document is loaded only for the id that was chosen.

Regenerate the cards from the UI with `node --import ./node_modules/tsx/dist/loader.mjs scripts/export-world3d-catalog.mjs` inside `ui`. `--check` fails when the JSON drifts from the editor.

## Search

`POST /api/v1/world3d/templates/commands` with `{"operation","version":1,"input":{"workspace",...}}`. Mutations also send `intent_id`. The same operations are MCP tools. `world3d.templates.list` and `world3d.templates.catalog` are the same bounded search (default 8, maximum 24). Both languages are searched. A limit above 24 or a language other than `es` or `en` is rejected. An unknown id returns `unknown_template` and does not open another shot.

`world3d.scene.apply_query` instantiates a scene only when the top score is strictly higher than the second. A tie returns `needs_choice` and creates nothing. The same `intent_id` with the same payload returns the stored result. A different payload is a conflict. `world3d.receipt` reads that stored result.

## Present a robot

Search `dolly zoom`. The exact title is `cine-dolly-zoom`. Apply it, then patch by object id:

- bind the `subject_1` object to `/api/v1/file/robot.glb?workspace=studio`
- bind the `background` object to a workspace image
- send `base_revision` from the scene you just read

For a cel look, add `"renderLook": "toon"` to the same patch, optionally with `"toon": {"steps": 3, "outline": 3, "ink": "#141018"}`. Only 3D model objects change: images and cutouts keep their look. `"renderLook": "none"` returns to the authored materials; `n64` is the retro look.

The dolly `fovTo` and the framing target stay on the document. `world3d.scene.preview` paints that revision, not the template thumbnail. `world3d.scene.publish` writes the gallery file the editor and the exporter already share.

The Wizard action is `world3d_templates` with operation `world3d.scene.apply_query` and `input.query`. The server picks the id. The action does not invent one. The reply lists the real card ids so the next turn can choose.

## Anime shots

Eight shots of classic 1980s TV-anime tricks carry the tag `anime` (search `anime`, or the library's **Anime** filter). They are 1920×1080 at 24 fps, have no set (the floor is off) and paint their look behind the world with `screenBackdrop`. Every character object starts as an empty flat cutout (`media: image`, `surface: cutout`, `imageLook.unlit`); vehicles start as empty GLBs. Every shot also has an optional `background` image (`surface: environment`): bound, it becomes the picture under the speed lines; empty, the backdrop colour shows. It is listed in `pending` like any empty object.

| id | s | objects (id → role, media) | what happens |
| --- | --- | --- | --- |
| `anime-speedline-charge` | 4 | `subject` → subject_1, image | Focus lines behind the figure and an aura; the camera snaps from a medium shot to head and shoulders between 0.72 and 2.2 s, then shakes until 2.75 s. |
| `anime-impact-frame` | 3 | `subject` → subject_1, image | The hit at 1.25 s: two negative frames (`impact_invert`), three flash frames (`impact_flash`), a starburst, focus lines appear behind, and a shake that dies away by 2.6 s. |
| `anime-snap-zoom` | 2.5 | `subject` → subject_1, image | The full figure, then a crash push to the eyes between 0.75 and 1.05 s with speed lines; a small shake on landing. |
| `anime-sword-clash` | 4 | `subject` → subject_1, image; `rival` → subject_2, image | Both rush in from the edges and cross at 2.5 s: slash, shockwave, a white impact frame and a hard shake to 3.6 s. |
| `anime-face-off` | 4 | `subject` → subject_1 (left), image; `rival` → subject_2 (right), image | Close-ups on the left and right halves over red focus lines, lightning between the eyes from 1.4 s, a slow push, and a flash at 3.6 s. |
| `anime-airship-flyby` | 6 | `vehicle` → subject_1, model3d | The vehicle flies a gentle arc from x −16 to 16 m; the camera tracks it while clouds stream past. |
| `anime-fleet-approach` | 6 | `vehicle_1` … `vehicle_4` → prop, model3d | Four copies leave a cloud bank at about 2 s in a staggered formation and come at the camera; a rumble from 4.6 s. |
| `anime-eyecatch` | 3 | `subject` → subject_1, image | A scene-change card: the figure spins in twice from the distance over yellow focus lines and stars. |

Bind a cutout (a transparent full-body PNG works best; the camera frames the head at 86% of the image height):

```json
{"bindings": [{"objectId": "subject", "sourceUrl": "/api/v1/file/hero.png?workspace=studio"}]}
```

Bind a GLB in a cutout's place, static or with a clip. Send the media with the URL:

```json
{"bindings": [{"objectId": "subject", "media": "model3d", "sourceUrl": "/api/v1/file/hero.glb?workspace=studio",
               "clip": {"index": 0, "name": "Run"}}]}
```

Patch `"renderLook": "toon"` as well to draw GLBs in cel bands with an ink outline next to the flat cutouts. A GLB faces +Z. In the clash, turn a GLB toward its run (`"rotationY": 1.5708` for `subject`, `-1.5708` for `rival`); a cutout stays at 0 and faces the camera. `"rotationY": 3.1416` mirrors a cutout. The anime cameras use `relativeToFacing: false`, so turning or mirroring an object never moves the camera behind it. Vehicles fly nose first (`faceTravel`). The fleet's four objects share the role `prop`, so bind each id: four bindings with the same URL. `applyAnimeTemplate(id, { roles: { vehicle: url } })` in the UI binds the whole family, and `{ text }` adds a title to the eyecatch, which has none by default.

In a production, `scene3d.subject` may be a GLB or a picture: the subject object becomes a model for `.glb`/`.gltf` and a cutout for a picture in a model's place.

Cue times are absolute seconds. Patching `duration` alone rescales the camera move and object motion but leaves effects, flashes and shake windows at their seconds; send `"retime": true` with it to stretch them with the shot, backdrop effects and shake windows included (a shake's `decay` is scaled back so it keeps its shape). Series 3D shots retime by default.

## Camera shake, framing windows and screen backdrop

These are plain document fields, for any Video 3D shot.

- `camera.shake`: up to 16 windows `{"start": 1.25, "end": 2.6, "amplitude": 0.09, "frequency": 20, "seed": 7, "decay": 3.2}`. Seconds, metres of sideways and vertical travel, oscillations per second, an integer seed (0–1 000 000) and an exponential fall-off per second (0–60; absent keeps full strength). Bounds: 0 ≤ start < end ≤ 600, 0 < amplitude ≤ 2, 0 < frequency ≤ 60. It is a pure function of time, zero outside its windows, added after the camera pose: eye and look move together across the view, and the camera rolls about 2° per 0.1 m. The editor, MP4 exports and the software preview all shake. `world3d.scene.patch` accepts it in `camera` (`"shake": []` removes it); a bad window fails with `invalid_camera_shake`.
- `camera.framing.moveStart` / `moveEnd` (fractions of the shot, 0–1) hold the camera at `from` before the move and at `to` after it. `ease: "snap"` leaves at full speed and settles, like a crash zoom; `smooth` (the default) eases in and out. Without them a framing move takes the whole shot, as before. Framing is ignored on the `fixed` family.
- `screenBackdrop`: `{"color": "#1c2f86", "sfx": [<screen cue>, ...]}` is painted as the frame background, behind every object. Its cues are ordinary screen effects; radial `speedlines` there are focus lines behind the characters. It is set by the template or in the document; `world3d.scene.patch` does not edit it.

## Planner

A brief field `world3d` or `toma` selects one shot. `world3d_subject` or `sujeto_3d` is the subject URL. `dolly zoom` becomes `scene3d.template = cine-dolly-zoom`. `girar alrededor` is a tie and the plan fails with `ambiguous_template` instead of inventing a path. `órbita` is not a tie: it is the exact Spanish title of `pixel-orbit`. Briefs without the field stay on the normal shot list.

## Personal templates

`world3d.templates.user.put` stores `world3d-user-templates.json` in the workspace. Ids start with `user-`. Browser `localStorage` is left untouched and stays invisible until a template is copied into that file.

## Honest limits

- The production compiler drops the template soundtrack. The song belongs to the production.
- The software preview does not fetch GLB bytes. Model slots draw colored boxes. Image slots are not drawn. A bound URL does not change those pixels. `renderLook` does not change them either; it shows in the editor and in the export. An empty `sourceUrl` stays a marker in `pending`; it is not a finished character.
- A follow camera keeps its subject centered, so translating that subject does not move its box. Changing `camera.fov`, or moving the subject while the camera stays put, changes the preview hash. Dolly zoom's lens change is stored on `camera.framing` and is kept through save; the software eye for a follow shot does not play that lens move, so the start, middle, and end boxes can match. MCP appends PNG image blocks after the text summary. A client that only reads the text still gets the revision, the hashes, and the pending markers.
- Video 2D `scenes.catalog` and particle rain are not the Video 3D shot `cine-rain`.
- A crash after the scene file is written and before the intent file is stored can still leave a duplicate. A transport retry in the same process does not.
- Two objects with the same role, such as the two props in `dark-still-salt-sea`, must be named by object id. The role resolves only when exactly one slot has it.
- A two-character shot keeps `subject_2`. Supplying one subject does not remove the other hole.
