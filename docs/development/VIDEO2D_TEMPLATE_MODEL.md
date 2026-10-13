# Video 2D template model (2026-10-12)

This is the contract for the Video 2D scene templates after the 2026-10-11 review
(`/mnt/outputs/REVISION_PLANTILLAS_2D_2026-10-11.md`). The owner delegated the open decisions on 2026-10-12 with
one goal: better clips of every kind, and templates an LLM picks correctly. P1–P3 of the review are merged already
(honest production cameras, search by words in `scenes.catalog`, ES/EN names for text, motion, finish and lyric looks).

## Decisions

1. **41 scene templates** (48 with the walking and reaction cards, below). 9 cards merge into another card and 2 retire (table below). A merged id stays an
   **alias**: compiling it gives the surviving card with the alias's control preset, so old MCP calls, productions
   and saved recipes keep working. The catalog lists only the 41.
2. **One slot vocabulary**: `subject_1`, `subject_2`, `background`, `prop_1`, `prop_2`, `foreground`.
   Old names are accepted at every entry (TS compile, Python compile, MCP, the composer) and translated once:
   `hero` → `subject_1`, `plate` → `background`, `foreground` → `foreground`, `prop` → `subject_2` where the card's
   prop is a person (`cinema-two-shot`, `music-duet`), else `prop` → `prop_1`. Compiled layer ids use the new names.
   A binding that gives both an old and a new name for the same slot fails with `slot_alias_conflict`.
3. **Controls.** Numeric controls stay `{min, max, default}`. New control kinds:
   `{options: [...], default}` (a choice) and `{text: true, maxLength, default}` (a field). Every compiler
   (TS and Python) validates them the same way. A card's `exposed: true` flag is what the composer reads (no
   hand-written id lists).
4. **Review status**: `candidate` or `approved`. The loader accepts both; anything else throws. The 24 «coral v1»
   approved references stay in the repo as a historical record.
5. **Cinema intents have one shelf: the narrative grid** (`ui/src/lib/sceneNarrative.ts`, 28). The composer
   («crear con mis assets») lists the music cards, the choreographies, the space cards and the two documentary/city
   cards, not `cinema-*`. The `cinema-*` cards keep compiling by id and their catalog row names their narrative
   `twins`.
6. **Production and the Wizard reach the music family only** (P10): a `scene2d` shot plays a `music-*` card
   (the music originals and the choreographies). `cinema-*` and `space-*` stay out of production: the 3D library
   and the narrative shelf cover them. Titles and lyrics already reach production.
7. **Cards are ES/EN** like the 3D cards: `titleEs`, `titleEn`, `lineEs`, `lineEn` per card in
   `app/shared/video2d_lines.json` under `templates`.
8. **Retired**: `trailer-teaser` (a sequence of titles: use the text templates `title-card`/`trailer-slam` in a scene)
   and `lyric-vertical` (lyrics come from `scenes.lyrics.import` and the lyric looks). Compiling a retired id fails
   with `template_retired` and `use_instead`.
9. **Every shot moves** (owner rule): no frozen plates. Each music card and choreography gets a camera layer with a
   slow drift by default (control `drift`, 0–1); a `background` may be a **video** (a seamless loop). The cutout
   choreographies warn `cutout_without_alpha` when a subject picture has no transparent pixels.
10. **Derived traits** (P4): `ui/scripts/export-video2d-traits.mjs` compiles every card at its defaults and writes
    `app/shared/video2d_template_traits.json` (`--check` fails on drift; CI runs it). Traits are derived, never
    hand-written.
11. **2D finishes named like the 3D grades** (P9): `natural`, `teal_orange`, `bleach`, `noir`, `sepia`,
    `flashback`, `dream`, `giallo`, `cold`, `warm`, `vhs`, `film`, next to the 5 existing ones.
12. **Approval by render with real assets** (P8): `npm run scene:review -- --render --assets <file.json>` renders the
    cards with real pictures. The integrator reviews the renders and sets `reviewStatus: approved` on the cards that
    pass; the owner can override in the app's review page.

## Merges (alias → card + preset)

| alias (old id) | card | preset |
| --- | --- | --- |
| `cinema-isolation` | `cinema-establishing` | `{"mood": "lonely"}` (high angle, crane up, rain) |
| `music-parallax` | `cinema-tracking` | `{"atmosphere": "streaks"}` |
| `music-stage` | `music-pulse` | `{"camera": "sweep"}` |
| `music-finale` | `music-pulse` | `{"camera": "open", "atmosphere": "confetti"}` |
| `music-chorus` | `music-pulse` | `{"camera": "beat", "atmosphere": "confetti"}` |
| `music-satellite-swarm` | `music-orbit` | `{"bounce": "off"}` (the figure holds, the copies orbit) |
| `music-ricochet-pass` | `music-pinball` | `{"bouncer": "prop"}` |
| `space-shield` | `space-broadside` | `{"outcome": "shield"}` |
| `space-explosion` | `space-broadside` | `{"outcome": "explode"}` |

Control names and option lists above are the contract. Defaults reproduce the surviving card's current look.
`music-orbit` takes `subject_1`, `prop_1` (the orbiting object) and `background`; `music-pinball` takes an optional
`prop_1` used when `bouncer` is `prop`.

## Cards that need work (T)

- `cinema-two-shot`: `prop` → `subject_2`; a real camera move (slow arc or push with parallax), a small idle sway.
- `cinema-hero`: the figure enters (from a side or rising into frame) while the camera rises.
- `music-duet`: `subject_2`; the two figures alternate on the beat.
- `documentary-history`: the plate moves (slow push with parallax against subject and foreground); the caption and
  the years are text controls; 6 s by default; image-only slots.
- `city-postcard`: the plate drifts sideways; the banner is a text control; birds if a particle preset exists, else
  say so; 6 s; image-only slots.
- `music-staircase-pop`: a bounce on each step and a camera that follows (held share under 50 %).
- `music-spotlight-relay`: the relay repeats through the shot, with camera (held share under 50 %).
- Motion keeps its speed on long shots: a 12 s shot travels further or repeats, it is not three times slower.
- `space-*` ships accept a picture or a GLB (`image|model3d`).

## Traits file

`app/shared/video2d_template_traits.json`: `{"version": 1, "templates": {"<id>": {...}}}` with, per card:
`moves` (push, pull, slide, rise, descend, orbit, roll, shake, drift, bounce, spin), `moving` (camera, subject,
subjects, props, background, particles, text), `still` (true when nothing but particles moves for more than half the
shot), `holdShare` (0–1, share of the shot in which nothing but particles moves), `subjects`, `props`, `travel`
(none, cross, rise, fall, orbit, in, out), `format` (landscape), `uses` (music, dance, performance, product, transition,
entrance, exit, walk, establishing, dialogue, documentary, space), `background` (still, drift, strip, video), `duration`.

## `scene2d` production shot (P10)

```json
{"kind": "scene2d", "duration": 4,
 "scene2d": {"template": "music-pulse", "cast": {"subject_1": "<picture>"},
             "background": "<picture or video>", "controls": {"camera": "sweep", "bpm": 120}}}
```

Sources follow the `scene3d` rules (URLs, workspace file names, `stills` names; a cast name resolves the cast
member's cutout). Without `background` the shot's generated still is the background. The shot's title, lyric and
finish ops are added as for any 2D scene. Only `music-*` cards (not aliases of other families) are allowed;
another family fails with `scene2d_family_not_allowed`.

## MCP

- `scenes.catalog` keeps its kinds; template rows add the traits, `titleEn/lineEn`, `aliases`, `twins` and
  `reviewStatus`, and accept the filters `use`, `move`, `subjects`, `format`.
- New `scenes.templates.suggest`: `{line, speakers, mood, beat, format, limit}` → up to `limit` (default 3, max 8)
  music cards with a plain-words `reason`, `unknown_words` and the derived filters; read-only. The Wizard calls it.

## Walking and reaction cards (2026-10-13)

Seven `cinema` cards in their own `walk` group, at the end of the catalog (the 17 originals stay first), with no narrative
twin (so they are on the composer shelf) and `reviewStatus: candidate` until their real-asset renders are reviewed. The catalog lists 48 cards. They exist because a
cut-out figure that slides in with a bob shows legs that never move: each card hides the legs or moves them.

| card | what it does | slots |
| --- | --- | --- |
| `walk-follow-back` | from behind, waist up; the figure holds its size, the room comes to it with parallax | `subject_1` (back view), `background` (the room seen from the door), `foreground` optional |
| `walk-toward-camera` | reverse tracking from the front, waist up; the camera backs away, the room recedes | `subject_1` (front), `background`, `foreground` optional |
| `walk-behind-foreground` | a whole figure in profile crosses behind a foreground that covers its legs, walking the way it looks (`facing`) | `subject_1` (profile), `background`, `foreground` (required, alpha) |
| `walk-shadow-first` | a huge shadow (the figure in black) crosses the wall, then the figure stands on its mark | `subject_1`, `background`, `foreground` optional |
| `walk-two-pose` | two pictures of a figure in profile take turns (the stride on every footfall, the legs together mid-step) over a contact shadow that beats; the walk is paced by `step`, so the boots do not skate, and the figure stops legs together | `subject_1` (stride), `subject_2` (legs together), `background`, `foreground` optional |
| `walk-cycle-sheet` | a sprite sheet of the gait (four poses by default: contact, passing, contact, passing) plays at `step`, and the figure crosses at the speed its feet need | `subject_1` (sheet with alpha, profile, boots at 96 % of the cell), `background`, `foreground` optional |
| `character-reaction` | a figure stays on its mark and plays a sheet of a gesture (wave, nod, point) or an anime expression (angry, surprised, sad…): it pops in, plays once and holds its last pose (`loop: once`) or keeps playing (`loop`, `pingpong`), and breathes. `framing: bust` stands a bust on the frame's bottom edge; `full` stands a whole figure on the floor with a contact shadow | `subject_1` (sheet with alpha), `background`, `foreground` optional |

- **The world moves, not the figure.** A figure held on screen takes `parallax: 0` and `parallaxZoom: true`; the plate
  takes `parallax: .5` with `parallaxZoom`, so a push or a pull moves the room (the camera zoom reaches a layer by
  `1 + (zoom - 1) * parallax`).
- **A walk takes a whole number of steps** (`step`, seconds, default .55): a footfall lands on its first and last
  frame, the figure dips on every footfall, rises mid-step and leans onto the planted foot (`sway`, degrees). A longer
  shot takes more steps instead of slower ones.
- **Profile figures walk the way they look** (`facing`: `right` or `left`, default `right`): a figure looking right comes in
  from the left. A layer cannot be mirrored (a layer's `flip` exists only for strip copies), so the card never turns a
  figure around: it asks for the figure already facing the right way. The Character Kit says the same of a pose
  (`facing: left | right | front`).
- **Paced walks** (`walk-two-pose`, `walk-cycle-sheet`): one step covers `.42` of the figure's height, so the figure's
  speed is `.42 * height / step` and a longer shot has more empty room, not slower feet. In `walk-two-pose` the stride
  shows on every footfall and the legs together from a quarter to three quarters of each step; both pictures share their
  beats and the one that shows changes inside one frame (1/60 s), so there is no cross-fade. A sheet plays `frames / (2 * step)`
  frames a second (a cycle is two steps).
- **Making the sheets in HocusPocus**: Characters › Animaciones (`docs/character-kits/HOWUSEIT.md` §4.7; MCP `characters.animations`,
  `characters.animation.sheet`) makes the sheet of a saved character, with the controls each card needs. By hand: one Qwen picture per pose from the figure (`generation.image` with the figure as
  an image ref and the pose in the prompt), keyed with `image.remove_background` (`crop: true`, so a pose is fitted to its
  outline and stands on its boots), and for a sheet joined with `media.compose` (equal cells, `anchor: bottom`, same height).
  The game-assets `animation` kind (`game_actions.json`, `strip` method) makes the same kind of sheet for a game character.
- **Framing** (`framing`: `waist` or `chest`): the figure's picture is a cut-out cropped to its outline, head near the
  top of the frame and the boots far below it.
- **Traits `walk` and `reaction`** are in `uses` for every card whose id has the word `walk` or `reaction`; the dance rule does not apply to them.
  `walk-behind-foreground`, `walk-shadow-first`, `walk-two-pose` and `walk-cycle-sheet` also measure `entrance`.
- **Not covered:** `scene2d` production shots still play `music-*` cards only (decision 6), so a Series entrance does
  not use these cards yet. `walk-cycle-sheet` plays a sheet it is given; it does not draw the cycle.

