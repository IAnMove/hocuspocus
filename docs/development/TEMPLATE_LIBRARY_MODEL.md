# Template library model

Date: 2026-10-11. Base: `development` 764ae7a8 (room sets #969–#978 and template traits #980 merged).

This is the contract every template change follows. A Video 3D shot is not one card picked from a flat list of 769.
It is chosen on axes, and the library, the search, the MCP tools and the production spec all name the same axes.

## 1. The two shelves

- **Signature scenes** keep their motion and their place: the atmos worlds, the pixel worlds, the action sets, the anime
  shots, the native motion sets, the drive and music sets. They stay finished cards. Nothing turns them into a box.
- **Generic stages** are place geometry with character marks, dialogue cameras and prop anchors (the room molds). The
  place arrives later as a skin: a colour, a seamless texture, a straight-on painted image or a view. Qwen paints the
  skin. One skin reused across shots is the continuity of a location.

An agent chooses a signature scene when the spectacle is the point, and a stage when people talk or live in a place.

## 2. The axes

| axis | field on a card or a shot | values |
| --- | --- | --- |
| intent | `uses` (a card) | `dialogue`, `talk`, `reaction`, `figure`, `establishing`, `action`, `speed`, `impact`, `reveal`, `product`, `music`, `drive`, `transition`, `title`, `look`, `plate` |
| kind | `kind` (a card) | `scene`, `stage`, `camera`, `look`, `transition`, `title` |
| place | `place` (a card), `world` or `background` (a shot) | a dressing id, an `atmos-*`/`pixel-*` id, a mold id, a painted set name |
| camera | `moves`, `shot`, `distance` (a card); `frame`, `camera_template` (a shot) | see WORLD3D_TEMPLATES_AGENTS.md |
| modifiers | `light`, `grade`, `lens`, `renderLook`, `frame` (a shot) | named presets, see §9 |
| cast | `subjects`, `props`, `travel`, `authoredFor` (a card); `cast` (a shot) | counts and media |

## 3. Card fields added by this model

Every field is derived from the built document or the mold. Nothing is hand-written per card.

| field | type | meaning |
| --- | --- | --- |
| `kind` | enum | `look`: a lighting, colour, lens, genre or viral look (families `lighting`, `color`, `lenses`, `genre-looks`, `viral-looks`, `atmosphere`). `camera`: a camera technique in the generic citadel set (families `camera-movement`, `framing`, `camera-angles`, `composition`, `editing`, `time-and-motion`, `effects`). `transition`: a cut piece of 3 s or less whose effects carry it, or any `transition-*` id. `title`: a `title-*` id, or no subject slot and kinetic texts. `stage`: a `stage-*` card built from a mold. `scene`: everything else. |
| `place` | string or null | the dressing id for a built template (`citadel`, `chase-street`, `atmos-reef`, `pixel-lake`…), the mold id for a stage. A filter; folded exact match. |
| `travel` | boolean | a subject slot has a motion path: the figure crosses the set. |
| `reference` | URL or null | a film still of the real technique, for inspiration only. It is **not** our render. |
| `preview` | URL or null | our own render of the built shot at mid-shot, `/api/v1/world3d/templates/<id>/thumbnail`, added when a card is read (the JSON keeps `null`). Null on a personal template. |
| `cameras` | list | stage cards only: the mold's named cameras (`two_shot`, `ots_a`, `ots_b`, `wide`, `close_1`, `close_2`, `entrance`). |

`uses` gains `speed` and `impact`:

- `speed`: category `drive`; camera family `chase`, `pursuit`, `hood` or `wing`; a treadmill or `drive-*` dressing; a
  subject that travels while the camera tracks, rides or slides; or any `speed-*` id.
- `impact`: a camera shake or an explosive world effect (what the old rules folded into `action`). `action` keeps it too.

`uses` rules corrected:

- `dialogue`: two subject slots, not `far`, not `product`, **not** a chase, pursuit, hood or wing family, and no impact beat.
- `reaction`: one subject, `close`, and a push, an arc, or a still frame that is not a look.

## 4. Search contract

- Both languages, word by word, through `world3d_template_vocabulary.py`. A word belongs to one group only.
- **`unknown_words`**: every reply lists the query words that hit no card at all (after stop words). They never count
  against the match. A query whose words are all unknown returns nothing and the list says why.
- **`match`**: `full` when every known word is in the card. `partial` when at least half of the known words are
  (one of two is enough). Partial cards never mix with full ones in a reply.
- **Scoring**: a trait hit (`shot`, `moves`, `uses`, `kind`, `place`, `travel`, tags, roles) outranks a stray word in
  a line. A literal id or title word of three letters or fewer counts only when the whole title matches.
- **Tie-break**, in order: higher score, more hits, a card that moves before a still one, a base template before a
  variant, the shorter id, catalogue order.
- Filters: `shot`, `use`, `move`, `subjects`, `format`, plus `kind`, `place` and `travel`. `category` keeps naming a
  UI category or a tag.
- Place words are split into groups a director would tell apart: kitchen and dining; bedroom; living room; office;
  classroom and school; bar, café and restaurant; church and temple; hospital; court and parliament; TV studio and
  press room; vehicle interiors stay with `drive`; street and city; rooftop; forest and garden; mountain, canyon and
  cave; desert; volcano; sea and shore; river and lake; space; home architecture (door, stairs, corridor, window,
  balcony); industry and tech (hangar, warehouse, factory, lab, server); institutions (prison, bank, vault, casino,
  library, museum, palace).
- New word groups: emotions reach `reaction` (sad, cry, laugh, surprise, anger, fear, love); walking reaches `travel`;
  sitting reaches `seated` stage marks; entering reaches `entrance`; crowd and group words reach `crowd` and the
  `group-*` and `cine-group-shot` cards; `pov`/`subjetivo`, `cowboy`/`americano`, `phone`/`llamada`, `flashback`/`dream`.

## 5. `world3d.templates.suggest`

Input: `{line?, speakers? (0–4), place?, mood?, beat? (dialogue|reaction|establishing|action|speed|impact|reveal|transition|title|music|product), format? (landscape|portrait), kind?}`.
It never instantiates. It returns up to three cards, each with a `reason` in plain words («two seated speakers, close
cameras ots_a/ots_b, moves on its own»), plus `unknown_words` and the filters it derived. `speakers` becomes
`subjects` and `dialogue`/`talk`; `mood` goes through the emotion words; `place` through the place words; `beat`
through `uses`. The same REST route and MCP envelope as the other template operations.

## 6. Stages

- A **mold** is a shape, not a place: `sala` (room), `sala_ventana`, `mostrador` (counter room), `filas` (rows),
  `pasillo`, `umbral` (threshold), `escalera`, `calle` (two façades), `plaza` (open ground and horizon), `orilla`
  (shore), `escenario_publico` (stage with audience), `vehiculo`, `azotea`. The fifteen named interiors already shipped
  (`cocina`, `aula`, `bar`…) stay as **recipes**: a shape with furniture blocks and a default skin.
- `kind: "exterior"` molds have no ceiling, may list fewer walls, and are lit by a directional sun (`daylight`,
  `dusk`, `night` presets). Their far wall holds the view.
- Every mold is a card `stage-<mold>` with `kind: stage`, `place: <mold>`, `cameras`, `subjects` = speaking marks,
  `roles` `subject_1`/`subject_2` (and `prop` for extra marks), `shot` and `distance` measured from the default camera
  to the first mark, `uses` `dialogue` (two or more marks), `talk`, `figure`. `world3d.templates.get`,
  `world3d.scene.instantiate`, `world3d.scene.apply_query`, the production `scene3d.template` and a Series
  `kind: "3d"` shot accept a `stage-*` id. The document is the mold staged on `two-shot` with its default skin, exactly
  what `stageRoomSet` builds in the editor; `roomCamera` picks another camera; a `sets` entry of `kind: room` brings a
  Qwen skin.
- **Ambient life**: every staged room carries low dust motes and a key light that breathes (±8 % over 6 s), so a stage
  is never `still`. A mold may set `"ambient": false`.
- A stage shot whose skin is only colours warns `stage_unskinned` in the dry run. The same template and background in
  more than four consecutive shots warns `looks_samey`.

## 7. Packs by intent

New template files, one per pack, registered like the anime pack (ids file, document builder, categories, i18n copy):

| pack | prefix | cards |
| --- | --- | --- |
| transitions | `transition-` | whip pan, iris in, flash white, wipe by a crossing prop, match on shape, eyecatch (plain colours), smash in, rise off |
| speed | `speed-` | run toward camera, foot chase (two subjects, track, shake), fly-by, rush with speed lines, side dash |
| dialogue | `dialogue-` | over-the-shoulder A and B with matched eyelines, seated at a table, triangle of three, embrace close, phone split |
| reaction | `reaction-` | push on the face, slow orbit on the face, turn to camera, look up, impact (shake and flash, plain colours) |
| group | `group-` | arc of five, line of four, performer with audience, circle |
| title | `title-` | lower third, kinetic title on a stage, chapter card, end card |

Durations: transitions 0.7–2.5 s, the rest 4–8 s. Every pack card must come out of `templateTraits` with the intended
`uses` and `kind` without hand-written traits.

## 8. Modifiers

- `light` names: `noon`, `golden`, `overcast`, `night`, `neon`, `stage`, `campfire` plus `rembrandt`, `butterfly`,
  `split`, `low_key`, `high_key`, `candle`, `backlight`, `window`, `moonlight`, `under`, `hard`, `soft`, `dusk`, `dawn`.
- `grade` names: `natural`, `teal_orange`, `bleach`, `noir`, `sepia`, `flashback`, `dream`, `giallo`, `cold`, `warm`,
  `vhs`, `film`. A grade is exposure and tone mapping on the document `look`, a light tint, and screen effects that
  already exist (`vignette`, `film_grain`, `vhs`, `crt`, `canvas`).
- `lens` names: `14mm`, `24mm`, `35mm`, `50mm`, `85mm`, `135mm`, `200mm` → the camera `fov` (and a framing's
  `fovFrom`/`fovTo` scaled by the same ratio).
- `camera_template`: a `kind: camera` card id whose camera and framing are copied onto any shot (the symmetric of
  `world`). The shot keeps its own duration, cast and place.
- The honest cards (`cine-film-grain`, `cine-bokeh`, `cine-lens-flare`, `cine-vignette`…) gain the screen effect that
  does the thing when one exists, and their lines say so.

## 9. Regeneration and CI

- Cards: `cd ui && node --import ./node_modules/tsx/dist/loader.mjs scripts/export-world3d-catalog.mjs` (`--check` in CI).
- Python shards: new test files go into `scripts/ci_test_groups.json` with recounted weights (`pytest --collect-only -q`),
  file counts within five of each other, `weight_note` updated. `tests/test_ci_shards.py` checks it.
- Routes or UI imports changed: `python3 scripts/architecture_contracts.py --write`.
- Never `npm ci` in a worktree whose `ui/node_modules` is a symlink to the live tree.
