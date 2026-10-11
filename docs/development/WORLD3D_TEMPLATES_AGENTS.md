# Video 3D templates for agents

The editor's shot library is the only library. MCP, Ask the Wizard, the production planner and a Series `kind: "3d"` shot search the same short cards: the 801 cards of `app/shared/world3d_templates.json` plus the 28 `stage-*` cards that `app/services/world3d_stage_cards.py` builds from the room molds, 829 in all. A card has the exact id, both titles, format, duration, playback speed, roles, one line and the derived traits below. The full scene document is loaded only for the id that was chosen.

Regenerate the cards from the UI with `node --import ./node_modules/tsx/dist/loader.mjs scripts/export-world3d-catalog.mjs` inside `ui`. `--check` fails when the JSON drifts from the editor. The contract behind every field, filter and warning is [TEMPLATE_LIBRARY_MODEL.md](TEMPLATE_LIBRARY_MODEL.md).

## Kinds and intents

A shot is chosen on axes, never from a flat list. The two shelves: a **signature scene** keeps its motion and its place (the `atmos-*` worlds, the `pixel-*` worlds, the action sets, the anime shots, the `motion-*` native sets, the drive and music sets); a **stage** is place geometry with speaking marks and dialogue cameras whose skin arrives later (a Qwen painting, a texture, a video). Take a scene when the spectacle is the point and a stage when people talk or live in a place.

| axis | field | values (cards that carry each one) |
| --- | --- | --- |
| kind | `kind` | `scene` 362, `camera` 263, `look` 161, `stage` 28, `transition` 11, `title` 4 |
| intent | `uses` | `figure` 455, `establishing` 283, `talk` 269, `look` 161, `action` 91, `reaction` 81, `dialogue` 74, `plate` 74, `speed` 51, `title` 47, `reveal` 41, `impact` 40, `product` 17, `drive` 17, `music` 15, `transition` 12 |
| place | `place` | 133 ids: a dressing (`citadel`, `chase-street`, `treadmill`, `retro-lab`), an `atmos-*` or `pixel-*` world, a `motion-*` set, a mold (`cocina`, `plaza`) |
| camera | `shot`, `distance`, `moves` | see the table below |
| cast | `subjects`, `props`, `screens`, `travel`, `authoredFor` | counts, whether a subject crosses the set, the media the slots were authored with |

Every value is derived from the built document (`ui/src/features/scene3d/templateTraits.ts`) or from the mold; nothing is hand-written per card. `kind` is read like this: `look` for the lighting, colour, lens, genre, viral and atmosphere families; `camera` for a technique of the generic citadel set (`camera-movement`, `framing`, `camera-angles`, `composition`, `editing`, `time-and-motion`, `effects`); `transition` for a cut piece of 3 s or less carried by its effects, or any `transition-*` id; `title` for a `title-*` id, or no subject slot and kinetic texts; `stage` for a `stage-*` card; `scene` for everything else. In `uses`, `speed` means the drive category, a chase, pursuit, hood or wing camera, a treadmill or `drive-*` dressing, a subject that travels while the camera tracks, rides or slides, or a `speed-*` id; `impact` a camera shake or an explosive world effect (`action` keeps it too); `dialogue` two subject slots that are not `far`, not a product, not a chase family and without an impact beat; `reaction` one subject, `close`, with a push, an arc or a still frame that is not a look.

## Search

`POST /api/v1/world3d/templates/commands` with `{"operation","version":1,"input":{"workspace",...}}`. Mutations also send `intent_id`. The same operations are MCP tools. With a query, `world3d.templates.list` and `world3d.templates.catalog` are the same bounded search (default 8, maximum 24). Without a query, `world3d.templates.list` pages the library in id order (default and maximum 50, `offset`, `total`) and `catalog` keeps catalogue order. Both languages are always searched; a language other than `es` or `en`, or a limit above the maximum, is rejected. An unknown id returns `unknown_template` and does not open another shot.

A query is a handful of words in Spanish or English, matched one by one through `app/services/world3d_template_vocabulary.py`. Each group there is one meaning («diálogo», «conversación», «two people» reach `uses: dialogue`; «contraplano», «hombro», «shoulder», «ots» the over-the-shoulder pair; «plano general» reaches `wide`; «girar alrededor» the arcs and orbits; «triste», «llora», «laugh» reach `reaction`; «camina» reaches `travel`; «sentados» the seated stages; «hacia» is a direction, so «correr hacia cámara» prefers `speed-run-toward`; «cocina», «azotea», «bosque», «hospital», «escalera» their own place group) and a word belongs to one group only. Number words («tres», «five») count only as literals. Words that name the search itself (plano, toma, shot, scene, template, video…) are dropped. Plurals match singulars through stems of four letters or more.

- **`unknown_words`.** Every reply lists the query words that no card of the whole library knows. They never count against the match: `diálogo xyzzy` returns the cards that know «diálogo» as `full` (`duo-diagonal` 15, `speech-dialogue` 15, `two-shot` 12…) with `unknown_words: ["xyzzy"]`. A query whose words are all unknown (`xyzzy`) returns nothing and the list says why.
- **`match`.** `full` when every known word is in the card. When no card has them all, the best cards with at least half of the known words (one of two is enough) come back as `partial` and the reply says `partial: true`. Partial cards never mix with full ones: `beso bajo la lluvia` has no card with both the kiss and the rain, so it returns `atmos-neon-rain-wide` (22), `night-rain-pursuit` (21), `atmos-neon-rain-low` (20) and `anime-code-rain` (14), all `partial`.
- **Score.** A literal word scores 8 in the id, 6 in the title, 6 in the traits (`shot`, `moves`, `uses`, `kind`, `place`, `travel`, tags, roles, the stage words `seated`, `entrance`, `crowd`) and 2 in a line; a synonym 4, 3, 4 and 1. A trait therefore outranks a stray word in a line, and a synonym in a line alone is not a hit. An exact title adds 80 and an exact id 40: `dolly zoom` gives `cine-dolly-zoom` 120 over `cine-dolly-zoom-in` and `-out` at 64. A literal word of three letters or fewer («bar», «pov», «off») in an id or title earns the synonym points, not the literal ones. A stage's camera names are one token each (`close_1` is not «close»).
- **Tie-break**, in order: higher score, more hits, a card that moves before a still one, a base template before a variant, the shorter id, catalogue order. `whip pan` gives `transition-whip-pan` (106, moves) before `cine-whip-pan` (102, still).
- **Filters** narrow the library before the words are scored: `roles` (every listed role present), `setting` (`studio`, `city`, `sea`, `stage`, `space`, `interior`, `exterior`…), `category` (a category: `cinema`, `action`, `product`, `drive`, `music`, `space`; or a tag: `animated`, `psx`, `dark-fantasy`, `creative`, `pixel`, `stage`, `perspective`, `anime`, `transition`), and the trait filters `shot`, `use`, `move`, `kind`, `place` (a dressing, mold or world id, folded exact match), `travel` (true or false), `subjects` (at least that many subject slots, 0–2) and `format` (`landscape`, `portrait`). A value outside the enum fails with `invalid_shot`, `invalid_use`, `invalid_move`, `invalid_kind`, `invalid_place`, `invalid_travel`, `invalid_subjects` or `invalid_format`.

Real replies (`search_report` in `app/services/world3d_template_catalog.py`, the same code the tools call):

| query | reply |
| --- | --- |
| `persecución a pie` | `speed-foot-chase` 98, the only card |
| `cocina` | `stage-cocina` 102, the only card |
| `nieve` | `cine-snow` 96, `snow-compound` 40, `atmos-snow-low` 13, `atmos-snow-wide` 13, `pixel-blizzard` 12 |
| `plano general bosque` | `atmos-clearing-wide` 26, `atmos-meadow-wide` 20, `atmos-snow-wide` 19, `atmos-temple-wide` 19… |
| `órbita` | `pixel-orbit` 94 (its exact Spanish title), `dance-orbit` 40, `vehicle-roof-orbit` 40 |
| `girar alrededor` | `cine-orbit-360`, `face-reaction-arc`, `reaction-orbit-face`, all 25: a tie |
| `{"kind": "stage"}` (list, no query) | 28 cards in id order, `stage-aula` first |
| `{"kind": "transition"}` | 11 cards: `anime-eyecatch`, `anime-impact-frame`, `anime-snap-zoom` and the eight `transition-*` |
| `{"place": "cocina"}` | 1 card; `{"travel": true}` 65 cards |

`world3d.scene.apply_query` instantiates a scene only when the top card is a full match and its score is strictly higher than the second. A tie or a partial match returns `needs_choice` with the cards and creates nothing; the reply carries `unknown_words` as well. The same `intent_id` with the same payload returns the stored result. A different payload is a conflict. `world3d.receipt` reads that stored result.

### `world3d.templates.suggest`

The shot as a writer phrases it: `{line?, speakers? (0–4), place?, mood?, beat?, format?, kind?, limit? (default 3, at most 8)}`. `speakers` becomes the `use` filter (0: `establishing`; 1: `talk`; 2 or more: `dialogue`) and `subjects` (at most 2); `beat` (`dialogue`, `reaction`, `establishing`, `action`, `speed`, `impact`, `reveal`, `transition`, `title`, `music`, `product`) is the `use` and wins over the speakers' one; `line`, `place` and `mood` are joined as the query words. The reply is the same cards and the same `match` rule as `list`, each with a `reason` in plain words, plus `unknown_words` and the `filters` it derived. It never instantiates. Without a line, a place or a mood the cards come in catalogue order at score 0, so give it words or use `list` with `kind`.

| input | reply |
| --- | --- |
| `{"line": "dos amigos discuten", "speakers": 2, "place": "cocina", "mood": "tenso"}` | filters `{use: dialogue, subjects: 2}`, `unknown_words: ["amigos", "tenso"]`; `stage-cocina` 32: «two subjects, wide, moves on its own, uses: dialogue, talk, figure; place: cocina; cameras: two_shot, ots_a, ots_b, wide, close_1, close_2, entrance» |
| `{"speakers": 0, "place": "rooftop"}` | filters `{use: establishing}`; `atmos-rooftop-night-wide` 46 «one subject, far, moves: push, uses: establishing; place: atmos-rooftop-night», `rooftop-run` 45, `atmos-rooftop-night-low` 45 |
| `{"line": "she looks up", "speakers": 1, "mood": "sad", "beat": "reaction"}` | filters `{use: reaction, subjects: 1}`, `unknown_words: ["she"]`; `reaction-look-up` 35 «one subject, close, moves: push, rise, uses: talk, reaction; place: citadel» |
| `{"speakers": 3, "place": "bar"}` | filters `{use: dialogue, subjects: 2}`; `stage-bar` 95, `cafe-duet` 12, `stage-mostrador` 12 |
| `{"line": "persecución a pie", "beat": "speed"}` | `speed-foot-chase` 98 «two subjects, wide, moves: track, shake, uses: figure, action, speed, impact; place: chase-street; the subject crosses the set» |
| `{"line": "xyzzy blorf"}` | no cards, `unknown_words: ["xyzzy", "blorf"]`, filters `{}` |

The Series profile and the Wizard reach `suggest` too; a Series `scene3d.template` takes any id it returns, `stage-*` included.

## What a card says

Besides its id, titles, one line in each language, format, duration, roles, `required` holes, `dependencies` and `tags`, every shipped card carries traits that the exporter reads from the built document (`ui/src/features/scene3d/templateTraits.ts`) or that the stage builder measures from the mold. They are estimates of the authored scene, never hand-written claims, and the same numbers the editor's gallery search uses.

| field | values | read it as |
| --- | --- | --- |
| `shot` | `close`, `medium`, `wide`, `far`, `plate` | how much of a person the frame holds at mid-shot: head and shoulders or tighter, to the waist, the whole figure, the figure under a third of the frame, or no subject slot at all. `distance` is the metres from the camera to the subject (null on a plate). |
| `moves` | `push`, `pull`, `slide`, `rise`, `descend`, `arc`, `orbit`, `zoom`, `roll`, `ride`, `track`, `shake` | what the camera does over the shot. Empty: the camera holds still. `ride` is the sway of a chase or hood camera; `track` means the camera follows a subject the template already moves. |
| `moving` | `camera`, `subjects`, `props`, `screens`, `effects`, `backdrop`, `texts` | what the template itself animates: a camera move, authored clips or paths on the cast or the props, a video screen, world or screen effects, a set that moves (endless road, treadmill, procedural weather, pixel sky, native motion set, a scrolling plate), kinetic text. |
| `still` | boolean | true when `moving` is empty: only the cast's own clip, a talking cutout or an override you add can move the picture. 158 cards are still; most are the lighting, colour and lens looks. No stage is still. |
| `subjects`, `props`, `screens` | counts | the subject slots (`subject_1`, `subject_2`), the prop slots that are not screens, and the screens. |
| `travel` | boolean | a subject slot has a motion path: the figure crosses the set (65 cards). |
| `authoredFor` | `model`, `cutout`, `mixed`, `none` | the media the subject slots were authored with. A production may bind the other kind: a GLB in a cutout's place becomes a model, a picture in a model's place a cutout. |
| `floor` | `tiles`, `none`, `backdrop`, `mirror`, `road` | `none`: there is no ground under the cast; frame waist-up or against the sky, or play the shot in a `world`. `backdrop`: the background picture is projected onto the floor. |
| `uses` | the sixteen intents above | what the shot is good for. `talk` is close enough for a speaking cutout; `figure` holds the whole body; `establishing` shows a place (far, a plate, or a wide shot with a painted or moving set); `look` is a lighting, colour or lens preset that wants a move or a clip from you. |
| `kind`, `place` | see Kinds and intents | the shelf and the place id. Filters. |
| `reference` | URL or null | a film still of the real technique, for inspiration only (424 cards). It is **not** our render. `preview` is null on every card until the library renders its own thumbnails. |
| `cameras` | list | stage cards only: the mold's named cameras (`two_shot`, `ots_a`, `ots_b`, `wide`, `close_1`, `close_2`, `entrance`). |
| `notesEs`, `notesEn` | text | the authored requirement list of the action, campaign and anime shots («GLB lead car; GLB pursuer car; optional street plate»). |

A personal template (`user-…`) reports `subjects`, `props`, `screens`, `authoredFor`, `floor`, `moving` and `travel` from its stored document; `shot`, `distance`, `moves` and `uses` stay unknown because they need the editor's camera. Its `place` is its dressing.

## Choosing a shot that will not look frozen

- **Ask `suggest` first, then `list` with filters.** `suggest` turns the line, the speakers, the place and the mood into the filters and the words for you and says why each card fits. `list` with `{"use": "dialogue", "subjects": 2}` or `{"kind": "stage", "place": "bar"}` is the long list behind it.
- **Read `moving` before `uses`.** A `still` card plus a picture, or plus a GLB with no clip, exports a photograph held for the whole shot. Give it a clip (`cast[].clip`, `clips`), a `motion`, a `camera`, a `frame`, or play it in a `world` whose set moves; or take a card whose `moves` are not empty. Production dry runs warn `template_still` for exactly that case.
- **Match the shot to the line.** `talk` and `dialogue` for speech (`dialogue-ots-a`/`-b`, `dialogue-table`, `face-to-face`, `cine-over-the-shoulder-frame`, any `stage-*`); `reaction` for a beat on one face (`reaction-push-face`, `reaction-look-up`, `face-reaction-arc`); `figure` and `establishing` to show a body or a place; `action`, `speed` and `impact` when something must travel, hit or explode (`speed-foot-chase`, `anime-sword-clash`); `transition` for a cut of 3 s or less (`transition-*`, `anime-eyecatch`).
- **Count the people.** `subjects` is how many the template seats; a third person is `add: true` as a prop, or a `group-*` card whose extra places are prop slots (`person_3`…). Two subjects on a `far` card are tiny: five stages are `far` from `two_shot`, so pick `roomCamera: ots_a` or `close_1` for their lines.
- **Mind the floor.** `floor: none` under a full-body cast shows feet on nothing: frame from the waist up, shoot against the sky, or give the shot a `world` or a painted `background`.
- **Vary.** One template in more than four shots is `template_reused`; the same template and background in more than four shots in a row is `looks_samey`; a stage shown in its mold colours is `stage_unskinned`. The looks (`uses: look`) change the light, not the composition, so pair them with a move, or name them as a `light`, `grade` or `lens` modifier on a moving card instead.
- **Keep the frame.** `frame: close|medium|wide|far` moves any template's camera nearer or farther without changing its move; `camera_template` gives any shot another card's camera; `duration` with `retime: true` stretches effects and cues with the shot.

## Stages

A **mold** is a shape, not a place. Thirteen shape molds (`sala`, `sala_ventana`, `mostrador`, `filas`, `pasillo`, `umbral`, `escalera`, `escenario_publico`, `vehiculo`, and the exteriors `calle`, `plaza`, `orilla`, `azotea`) sit beside the fifteen named interiors that ship as **recipes**, a shape with furniture blocks and a default skin (`aula`, `bar`, `cabina_avion`, `coche_interior`, `cocina`, `despacho`, `dormitorio`, `hemiciclo`, `hospital`, `juzgado`, `oficina_diafana`, `plato_tv`, `sala_prensa`, `salon`, `vagon`). Exteriors have no ceiling, keep their view on `wall_back` and are lit by a sun preset (`daylight`, `dusk`, `night_sky`).

Every mold is a card `stage-<mold>` built by `app/services/world3d_stage_cards.py`: `kind: stage`, `place: <mold>`, `setting` `interior` or `exterior`, the tag `stage`, `cameras` (always `two_shot`, `ots_a`, `ots_b`, `wide`, `close_1`, `close_2`, `entrance`), `subjects` 2 with roles `subject_1`/`subject_2` and `prop` for every further speaking mark, `shot` and `distance` measured from `two_shot` to the first mark's face, `uses` `dialogue` (two or more marks and not `far`), `talk` and `figure`, `moving: ["effects"]` so no stage is `still`, and the search words `seated`, `entrance` and `crowd` read from the marks and the blocks. The document is the mold staged on `two-shot` with its default skin, exactly what `stageRoomSet` builds in the editor, with low dust motes (`room-dust`) and a key light that breathes ±8 % over 6 s; a mold may set `"ambient": false`. `world3d.templates.get`, `world3d.scene.instantiate`, `world3d.scene.apply_query`, the production `scene3d.template` and a Series `kind: "3d"` shot accept a `stage-*` id; `roomCamera` picks another camera and a `sets` entry of `kind: room` (or the Series location's `set3d`) brings a Qwen skin.

| card | from `two_shot` | marks | words |
| --- | --- | --- | --- |
| `stage-aula`, `stage-cocina`, `stage-dormitorio`, `stage-hospital`, `stage-pasillo`, `stage-plato_tv`, `stage-sala_prensa` | wide, 4.4 / 3.5 / 3.7 / 2.6 / 3.3 / 3.8 / 4.3 m | 2 standing + entrance | `entrance` |
| `stage-bar`, `stage-coche_interior`, `stage-salon` | wide, 3.8 / 2.9 / 2.9 m | 2 seated + entrance | `seated`, `entrance` |
| `stage-despacho` | wide, 4.4 m | `behind_desk` seated, `visitor`, `door` | `seated` |
| `stage-sala`, `stage-sala_ventana`, `stage-mostrador`, `stage-umbral`, `stage-escalera`, `stage-calle`, `stage-orilla`, `stage-azotea` | wide, 3.5 / 3.5 / 3.9 / 3.7 / 3.6 / 4.1 / 4.1 / 4.1 m | 3 standing + entrance | `entrance` |
| `stage-escenario_publico` | wide, 4.3 m | 3 standing + entrance, audience seats | `entrance`, `crowd` |
| `stage-filas` | wide, 4.2 m | 3 (2 seated) + entrance, benches | `seated`, `entrance`, `crowd` |
| `stage-plaza` | wide, 4.1 m | 4 standing + entrance | `entrance`, `crowd` |
| `stage-vehiculo` | wide, 2.2 m | 3 seated + entrance | `seated`, `entrance` |
| `stage-cabina_avion`, `stage-oficina_diafana`, `stage-vagon` | **far**, 5.3 / 5.4 / 5.4 m | 2 seated + entrance | `seated`, `entrance` (+ `crowd` in the carriage) |
| `stage-hemiciclo`, `stage-juzgado` | **far**, 6.5 / 5.4 m | 2 standing + entrance | `entrance`, `crowd` |

The five `far` stages carry `talk` and `figure` but not `dialogue`, so `{"use": "dialogue"}` does not list them: ask for them by `place` or `kind` and shoot the lines from `ots_a`, `ots_b` or `close_1`. A stage shot whose skin is only colours warns `stage_unskinned` in the dry run.

## Packs by intent

Six packs of short cards, one file each under `ui/src/features/scene3d/` (`transitionTemplates.ts`, `speedTemplates.ts`, `dialogueTemplates.ts`, `reactionTemplates.ts`, `groupTemplates.ts`, `titleTemplates.ts`), registered like the anime pack. Every card comes out of `templateTraits` with its `uses` and `kind`; none is `still`. Transitions last 0.6–2.5 s, the rest 4–7 s.

| id | s | shot, moves | uses | what happens |
| --- | --- | --- | --- | --- |
| `transition-whip-pan` | 0.7 | medium; slide, roll, shake | action, impact, transition | a very fast slide with a roll over radial speed lines; lands centred on the figure |
| `transition-iris-in` | 1.2 | close; push | talk, reaction, transition | a fast push to the centre while a vignette closes in four steps |
| `transition-flash-white` | 0.6 | close; push | talk, reaction, transition | three white frames, then two more, over a tight push on the face; plain colours |
| `transition-wipe-prop` | 1.5 | wide; props | figure, transition | a prop crosses the frame close to the lens and covers it at mid-shot: a door, a bus, a cloud |
| `transition-match-shape` | 2 | close; pull | talk, transition | a centred close frame holds a second, then snaps out to the whole figure |
| `transition-eyecatch` | 2.5 | wide; subjects (travel) | figure, action, transition | a scene-change card in two plain tones; an optional title lands under the figure |
| `transition-smash-in` | 0.6 | medium; push, shake | action, impact, transition | an abrupt snap from the whole figure to the face in a fifth of a second |
| `transition-rise-off` | 2 | medium; pull, rise | talk, reveal, transition | the camera lifts off the figure into a blank backdrop; the next shot can start on anything |
| `speed-run-toward` | 6 | medium; push | talk, action, speed | a low lens creeps in on a figure running on the spot (bind a GLB with a run clip) |
| `speed-foot-chase` | 7 | wide; track, shake | figure, action, speed, impact | two figures sprint down the street; the camera tracks the runner and shakes as the chaser closes in |
| `speed-flyby` | 6 | wide; slide | figure, action, speed | a craft crosses the sky left to right trailing smoke; the camera pans with it over a figure |
| `speed-rush-lines` | 5 | close; push, shake | reaction, action, speed, impact | a hard push from a medium shot to the face over radial speed lines |
| `speed-side-dash` | 5 | wide; slide, track | figure, action, speed | the figure dashes ten metres across the set while the frame slides with it |
| `dialogue-ots-a` / `dialogue-ots-b` | 6 | close; push, slide | dialogue, talk | over the left (A) or right (B) speaker's shoulder onto the other's face, same distance and push, so cutting A and B keeps the eyelines |
| `dialogue-table` | 6 | medium; slide | dialogue, talk | two figures across a table at seated eye height (needs a seated clip or seated cutouts; a table GLB on the table slot) |
| `dialogue-triangle` | 7 | wide; arc | dialogue, figure | three figures in a triangle, a master shot with a slow arc; the third is the prop slot `person_3` |
| `dialogue-embrace` | 6 | close; push, arc | dialogue, talk | a tight two-shot at head height: a kiss, a hug, a farewell |
| `dialogue-phone-split` | 6 | medium; push | dialogue, talk | two halves of the frame with a thin divider, a symmetric push: a phone or video call |
| `reaction-push-face` | 5 | close; push | talk, reaction | after a short hold the camera pushes from medium-close to a close-up |
| `reaction-orbit-face` | 6 | close; arc | talk, reaction | a slow arc of a tenth of a turn around the head |
| `reaction-turn-to-camera` | 5 | close; push, track (travel) | talk, reaction, action | the figure turns from profile to face the camera |
| `reaction-look-up` | 5 | close; push, rise | talk, reaction | a low angle on the face that rises and tilts up as it pushes in |
| `reaction-impact` | 5 | close; push, shake | reaction, action, impact | two white frames, a short shake and a snap push to the face over plain colours |
| `group-arc-five` | 7 | wide; push | figure | one figure in front and four behind in an arc (`person_2`…`person_5`) |
| `group-line-four` | 6 | wide; slide | dialogue, figure | four figures in a line, a lateral slide at chest height (`person_3`, `person_4`) |
| `group-audience` | 7 | wide; push, rise | figure, reveal, music | a performer on a platform and a crowd of six cutouts from behind (`crowd_1`…`crowd_6`); the camera cranes up toward the stage |
| `group-circle` | 7 | wide; arc | dialogue, figure | five figures in a circle; the camera orbits slowly above (`person_3`…`person_5`) |
| `title-lower-third` | 5 | medium; push, texts | talk, title | a name on a bar and a role line slide in, hold under the figure and slide out |
| `title-kinetic-stage` | 6 | wide; push, texts | figure, title | one big word per beat punches in over a dark mirror stage (up to eight words) |
| `title-chapter` | 4 | medium; push, texts | talk, title | a chapter card: the kicker types in, a rule draws itself, the title wipes on |
| `title-end-card` | 5 | medium; slide, texts | talk, title | a title rises and a pulsing call to action lands under it over faint stars |

A `transition-*` card is its own short shot between two others. A Series shot's `transitionIn` (`cut`, `fade_black`, `dissolve`, `dip_white`) is the join itself and needs no card.

## Modifiers

Named presets that change a shot without changing its card. The tables are `app/shared/world3d_modifiers.json`, read by `app/services/world3d_modifiers.py`, `world3d_grades.py` and `ui/src/features/scene3d/modifiers.ts`, so the production compiler and `world3d.scene.patch` resolve the same name to the same numbers. The production `scene3d` accepts `light`, `grade`, `lens`, `camera_template` and `frame` next to `template`; `world3d.scene.patch` accepts the first four on a working scene. A Series `scene3d` does not carry them: patch the scene, publish it and name the file as `scene3d.scene`.

- `light`: `noon`, `golden`, `overcast`, `night`, `neon`, `stage`, `campfire`, `rembrandt`, `butterfly`, `split`, `low_key`, `high_key`, `candle`, `backlight`, `window`, `moonlight`, `under`, `hard`, `soft`, `dusk`, `dawn`. A name replaces the document's sun (direction, intensity, colour) and sets the ambient share; the rest of the lighting stays. A light object `{kind: directional, direction: [x, y, z], intensity 0–10, color: #rrggbb}` is accepted too. Unknown: `invalid_light`.
- `grade`: `natural`, `teal_orange`, `bleach`, `noir`, `sepia`, `flashback`, `dream`, `giallo`, `cold`, `warm`, `vhs`, `film`. A grade is the document `look` (tone mapping and exposure), a gel over the lamp (the ungraded colour is kept as `untinted`, so the next grade tints the lamp and not the earlier tint) and screen effects that already exist (`vignette`, `film_grain`, `light_rays`, `vhs`, `scanline`) with ids `grade-*`: a later grade replaces them and the template's and the shot's own effects stay. Unknown: `invalid_grade`.
- `lens`: `14mm` (fov 96), `24mm` (74), `35mm` (54), `50mm` (40), `85mm` (28), `135mm` (18), `200mm` (12). It sets the camera `fov`; a framing's `fovFrom`/`fovTo` keep their move, scaled by the same ratio within 10–130. Unknown: `invalid_lens`.
- `camera_template`: the id of a `kind: camera` card (`cine-dolly-in`, `cine-low-angle`, `cine-orbit-360`…) whose camera and framing are copied onto the shot, the symmetric of `world`; the shot keeps its duration, cast and place and the framing target is re-read. An unknown id is `unknown_template`, another kind `invalid_camera_template`; a card authored for the other frame format warns `camera_template_format`.
- The patch applies `light`, then `lens`, then `grade`, so a grade tints the light it finds.
- The honest effect cards gained the screen effect that does the thing when one exists: `cine-film-grain` and `cine-vignette` now carry `moving: ["effects"]`, `cine-lens-flare` light rays over its push. `cine-bokeh` stays `still`: there is no blur effect, and its line says it is the framing where blur would live.

## Planner

A brief field `world3d` or `toma` selects one shot (`app/services/production_plan.py`). The planner runs the same `search_report` with a limit of 8: no card, or a top card that is only `partial`, fails with `unknown_template` and names the `unknown_words`; a top card whose score equals the second's fails with `ambiguous_template` and lists the tied ids instead of inventing a path. `dolly zoom` becomes `scene3d.template = cine-dolly-zoom` (120 over 64). `girar alrededor` is a tie at 25 (`cine-orbit-360`, `face-reaction-arc`, `reaction-orbit-face`) and fails. `órbita` is not a tie: it is the exact Spanish title of `pixel-orbit` (94 over 40). `world3d_subject` or `sujeto_3d` is the subject URL. The shot lasts the card's duration over its playback speed, at least 1 s and at most the song. Briefs without the field stay on the normal shot list.

## Starter deck

Forty-four real ids an agent can reach for before searching, grouped by intent. Every one moves (`still: false`); the stages and the signature scenes are both here. The line is the card's own.

**Dialogue**
- `stage-cocina`: Kitchen: interior with a counter, table; 2 marks, standing, with an entrance; wide shot from two_shot.
- `stage-bar`: Bar: interior with a counter, bottles, tv, stool; 2 marks, seated, with an entrance; wide shot from two_shot.
- `stage-despacho`: Office: interior with a desk, shelf; 3 marks, 1 seated; wide shot from two_shot.
- `dialogue-ots-a`: Two figures face each other 1.7 m apart; the camera looks over the left speaker's shoulder onto the right one's face, medium-close with a slow push.
- `dialogue-ots-b`: The reverse of A: the same two figures, the camera over the right speaker's shoulder onto the left one's face, at the same distance and with the same push.
- `dialogue-table`: Two figures sit across a table, three-quarter to the camera, at seated eye height (1.15 m) with a gentle slide.
- `face-to-face`: Two faces sharing a close framing.

**Reaction**
- `reaction-push-face`: One figure; after a short hold the camera pushes slowly from a medium-close to a close-up on the face.
- `reaction-look-up`: A low angle on the face that rises and tilts up as it pushes in, close.
- `face-reaction-arc`: A short arc around the face for a reaction shot.
- `cine-crash-zoom-in`: Camera movement. A very fast snap onto the eyes.

**Establishing**
- `atmos-rooftop-night-wide`: A procedural rooftop at night. The city skyline glows behind it, and the character spot stays on the open roof.
- `atmos-clearing-wide`: A procedural sunlit clearing. A character placed in the open takes the same light and shadow as the trunks.
- `atmos-neon-rain-wide`: A procedural neon alley at night. Wet pavement reflects the signs, rain falls, and steam rises.
- `stage-plaza`: Square: exterior with a fountain; 4 marks, standing, with an entrance; wide shot from two_shot.
- `stage-calle`: Street: exterior with no furniture; 3 marks, standing, with an entrance; wide shot from two_shot.

**Action, speed, impact**
- `speed-foot-chase`: Two figures sprint down the street on parallel lanes; the camera tracks the runner from ahead and shakes lightly as the chaser closes in.
- `speed-rush-lines`: A hard push from a medium shot to the face over radial speed lines; the camera shakes where the push lands.
- `night-rain-pursuit`: Head-on pursuit through a flooded street as lightning hits the block.
- `anime-sword-clash`: Two fighters rush in from both edges and cross at the centre: a slash, a shockwave, a white impact frame and a hard shake.
- `anime-impact-frame`: A hit lands: two negative frames, three white frames with ink focus lines, a starburst and a camera shake that dies away.

**Reveal**
- `crane-reveal`: Rise from a low viewpoint into a wide composition.
- `boots-to-face`: The camera rises from the feet to the face.
- `drive-coast-reveal`: A crane shot reveals the car against the coastal road.
- `group-audience`: A performer on a low platform and a crowd of six cutouts seen from behind at the bottom of the frame; the camera cranes up over the crowd toward the stage.

**Music**
- `dance-orbit`: A half orbit that keeps the performer legible.
- `dance-stage`: A wide street set with an unhurried musical arc.
- `motion-music-machine`: A choreographed 3D mechanism strikes bars and drums. Original local notes follow the same deterministic contact timeline.

**Product**
- `product-orbit`: A measured turn around the product with a warm key light.
- `product-detail`: Close oblique framing to inspect the object surface.
- `product-pedestal`: Place a product above a supporting prop and reveal it from below.

**Title**
- `title-lower-third`: A name on a bar and a role line slide in from the left, hold under the figure and slide out, over a slow push.
- `title-chapter`: A centred chapter card: the kicker types in, a rule draws itself and the title wipes on, over a vignette and a slow push.
- `title-kinetic-stage`: One big word per beat punches in over a dark mirror stage under a shaft of light, with a slow push on the figure.
- `title-end-card`: A title rises and a pulsing call to action lands under it while the camera drifts sideways over faint stars.

**Transition**
- `transition-whip-pan`: A very fast slide with a roll over radial speed lines; the camera lands centred on the figure with a short settle.
- `transition-flash-white`: Three white frames, then two more, over a tight push on the face; plain colours, no ink lines.
- `transition-smash-in`: An abrupt snap from the whole figure to the face in a fifth of a second, with a burst of lines and a shake that dies away.
- `transition-eyecatch`: A scene-change card in two plain tones: the figure spins in from the distance over focus lines, and an optional title lands under it.

**Plate**
- `pixel-moon-lake`: Hand-drawn pixel night over a still lake: a haloed moon, aurora, shooting stars and a rippling reflection.
- `pixel-storm-lake`: Rain lashes a dark pixel lake while lightning strikes the far ranges; every bolt lights the whole painted world for an instant.
- `pixel-orbit`: High above a planet: its curved horizon glows with atmosphere, city lights dot the night side, nebula clouds breathe among dense stars.
- `drive-hood`: Immersive forward view with a restrained road bump.
- `motion-lighthouse-story`: A geometric keeper climbs a coastal lighthouse; the beacon rotates over a volumetric sea and island.

## Present a robot

Search `dolly zoom`. The exact title is `cine-dolly-zoom`. Apply it, then patch by object id:

- bind the `subject_1` object to `/api/v1/file/robot.glb?workspace=studio`
- bind the `background` object to a workspace image
- send `base_revision` from the scene you just read

For a cel look, add `"renderLook": "toon"` to the same patch, optionally with `"toon": {"steps": 3, "outline": 3, "ink": "#141018"}`. Only 3D model objects change: images and cutouts keep their look. `"renderLook": "none"` returns to the authored materials; `n64` is the retro look.

The dolly `fovTo` and the framing target stay on the document. `world3d.scene.preview` paints that revision, not the template thumbnail. `world3d.scene.publish` writes the gallery file the editor and the exporter already share.

The Wizard action is `world3d_templates` with operation `world3d.scene.apply_query` and `input.query`. The server picks the id. The action does not invent one. The reply lists the real card ids so the next turn can choose.

## Anime shots

Nine shots of classic TV-anime and film tricks carry the tag `anime` (search `anime`, or the library's **Anime** filter). They are 1920×1080 at 24 fps, have no set (the floor is off) and paint their look behind the world with `screenBackdrop`. Every character object starts as an empty flat cutout (`media: image`, `surface: cutout`, `imageLook.unlit`); vehicles start as empty GLBs. Every shot also has an optional `background` image (`surface: environment`): bound, it becomes the picture under the speed lines; empty, the backdrop colour shows. It is listed in `pending` like any empty object.

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
| `anime-code-rain` | 6 | `subject` → subject_1, image (optional) | Green code rain (`code_rain`, two layers) on a black backdrop for the whole shot, behind a green-tinted cutout; a slow push from a medium shot to the chest. |

`anime-code-rain` with no figure is a plate: an export draws nothing for an image cutout with no picture, and the rain repeats exactly over each backdrop cue, which spans the shot. For a `series.location.plate3d` of N seconds, patch the working scene first with `{"duration": N, "retime": true}` so the cues span N seconds, then render the plate with `seconds: N`; it loops with no seam. With a figure, a Character Kit cutout can talk in front of the rain (`world3d.scene.talk`, or a Series `scene3d` shot whose cast uses `objectId: "subject"`).

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
- `camera.framing.track`: `rest` (the default) measures the target once, as its model mounts and before any clip moves it, and then follows only where the slot places and turns the model, so a dance's arms or a nod never move the camera; `pose` re-reads the head bone or the live bounding box every frame, for a close-up that must stay on a moving face. `anchor` (`head`, `center`, `feet`) picks the point in either mode.
- `screenBackdrop`: `{"color": "#1c2f86", "sfx": [<screen cue>, ...]}` is painted as the frame background, behind every object. Its cues are ordinary screen effects; radial `speedlines` there are focus lines behind the characters. It is set by the template or in the document; `world3d.scene.patch` does not edit it.

## Native motion sets

Eight complete native motion sets (musical contacts, sunset flight, seasonal
carriage, data assembly, lighthouse journey, volumetric poster and particle
typography) use no external assets. Their `motionLab` controls are shared by
the editor and `world3d.scene.patch`; see
[native motion templates](WORLD3D_MOTION_LAB.md) for ids, bounds and timing.

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
- `reference` is a still of the real technique from a film, never a frame of ours; `preview` is null on every shipped card.
