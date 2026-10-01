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

The dolly `fovTo` and the framing target stay on the document. `world3d.scene.preview` paints that revision, not the template thumbnail. `world3d.scene.publish` writes the gallery file the editor and the exporter already share.

The Wizard action is `world3d_templates` with operation `world3d.scene.apply_query` and `input.query`. The server picks the id. The action does not invent one. The reply lists the real card ids so the next turn can choose.

## Planner

A brief field `world3d` or `toma` selects one shot. `world3d_subject` or `sujeto_3d` is the subject URL. `dolly zoom` becomes `scene3d.template = cine-dolly-zoom`. `girar alrededor` is a tie and the plan fails with `ambiguous_template` instead of inventing a path. `órbita` is not a tie: it is the exact Spanish title of `pixel-orbit`. Briefs without the field stay on the normal shot list.

## Personal templates

`world3d.templates.user.put` stores `world3d-user-templates.json` in the workspace. Ids start with `user-`. Browser `localStorage` is left untouched and stays invisible until a template is copied into that file.

## Honest limits

- The production compiler drops the template soundtrack. The song belongs to the production.
- The software preview does not fetch GLB bytes. Model slots draw colored boxes. Image slots are not drawn. A bound URL does not change those pixels. An empty `sourceUrl` stays a marker in `pending`; it is not a finished character.
- A follow camera keeps its subject centered, so translating that subject does not move its box. Changing `camera.fov`, or moving the subject while the camera stays put, changes the preview hash. Dolly zoom's lens change is stored on `camera.framing` and is kept through save; the software eye for a follow shot does not play that lens move, so the start, middle, and end boxes can match. MCP appends PNG image blocks after the text summary. A client that only reads the text still gets the revision, the hashes, and the pending markers.
- Video 2D `scenes.catalog` and particle rain are not the Video 3D shot `cine-rain`.
- A crash after the scene file is written and before the intent file is stored can still leave a duplicate. A transport retry in the same process does not.
- Two objects with the same role, such as the two props in `dark-still-salt-sea`, must be named by object id. The role resolves only when exactly one slot has it.
- A two-character shot keeps `subject_2`. Supplying one subject does not remove the other hole.
