# Scene → Recipe: what cannot survive the trip — T2.3

Field-by-field audit of everything a `Scene` can hold against everything a
`SceneRecipe` can express. Six readers swept one domain each, and every claim
was then re-checked by a second reader briefed to refute it.

**Status (2026-08-31):** a Scene → Recipe serializer now exists at
`ui/src/lib/sceneToRecipe.ts`. It copies `animation.keyframes`, `strip` /
`seamOccluder`, `relationship`, `visible`, `locked`, `faceBinding`, per-layer
`effects`, and related timing. The counts below are the **T2.3 snapshot** from
before that serializer; do not treat “there is no serializer” as current.
Re-audit before using this file as a blocker list. Character Kit / cutout
dialogue transport is documented in [`character-kits/HOWUSEIT.md`](character-kits/HOWUSEIT.md).

**122 fields audited. 65 cannot be expressed at all, 28 partially, 29 fully.**
118 claims survived verification; 4 were corrected.

At audit time there was no `Scene → Recipe` serializer in `ui/src`. The sidecar written
beside every exported MP4 pairs the recipe with the compiled scene and presents
the recipe as the clip's reproduction. For 65 fields that was already untrue, and
it becomes untrue for a given clip the moment anyone edits it.

## Where the losses cluster

| Cluster | Fields lost | What actually breaks |
|---|---|---|
| `animation.keyframes` | 1 | Every template's motion. See below. |
| `strip` + `seamOccluder` | 12 | The whole infinite-scroll world tool, including the lamppost that covers the loop seam |
| `animation.orbit` | 10 | A layer circling another, with its per-frame depth swap |
| `relationship` | 7 | Parent / follow / lookAt rigs, including the depth-band inheritance |
| `animation` timing | 7 | `offset`, `speed`, `loop`, `trimStart`, `trimEnd`, `events`, `clipOffset` |
| `effects` beyond the grade | 5 | `blur`, `shadow`, `blendMode`, `mask`, `maskRadius` |
| `atmosphere` tuning | 5 | `density`, `speed`, `size`, `wind`, `color` — only the kind survives |
| Layer state | 4 | `visible`, `locked`, `thumbnail`, `missingAsset` |
| Scene records | 4 | `composition`, `copilotAudit`, `narrative`, `audioTracks[].model` |

## The single largest loss

**`SceneLayer.animation.keyframes` cannot be expressed, and a keyframe track is
what every narrative template's motion *is*.**

`buildDriftKeyframes` emits `max(4, ceil(duration/2)) + 1` frames with a sine bob,
pulse and rotation baked into each one. `hero-arrival` and the cutout hold/snap
sets are hand-authored four- and five-frame timing charts. A recipe carries only
a start point and an end point, so the round trip collapses all of it into one
linear interpolation: the breathing bob disappears, and the deliberate
hold-snap-hold comic timing becomes a slide.

This is a direct blocker for the plan's phase 4. Making `createScene()` the shot
compiler means every template-backed shot produces motion the recipe format
cannot describe — so the recipe shown in the UI, and the one saved beside the
MP4, would stop matching the screen on the very first shot.

Two more that are quietly wrong rather than merely lossy:

- **`visible`** — a hidden layer comes back rendering. Hidden alternate costumes,
  muted plates and toggled-off cameras all return. For cameras the importer masks
  this by keeping the highest-z visible camera, which means the survivor is
  whichever sorts last, not the one the author chose.
- **`effects.blur`** — both over-the-shoulder templates lose the only cue
  separating the defocused shoulder from the subject, so the reverse angle
  compiles back as two equally sharp figures.

## List A — add to the schema

Ordered by what a faithful round trip actually requires.

1. **`animation.keyframes`** — without it no template-built shot can be described,
   and phase 4 cannot proceed honestly.
2. **`strip` and `seamOccluder`** — the anchor prompt's own lamppost clause is
   unrepresentable, and `run-travel-parallax` exists to produce exactly this.
3. **`relationship`** — the copilot can create these and requires explicit user
   confirmation to do so; that confirmed structure is precisely what is lost.
4. **`visible` and `locked`** — trivial to add, and their absence is silently
   wrong rather than merely incomplete.
5. **Per-layer `effects`** beyond the scene grade — `blur` at minimum.
6. **`animation` timing**: `offset`, `speed`, `loop`, `trimStart`, `trimEnd`.
7. **`seamlessHorizontal`** — it gates the world tools, so it has to travel with them.
8. **`audioTracks[].model`** — one string, and the only record of which model
   voiced a track. Reproducibility is the sidecar's whole claim.

## List B — accept the loss, and say so in the sidecar

- **`thumbnail`** — decorative, derivable from the source, no effect on a frame.
- **`missingAsset`** — a runtime state, not authored content.
- **`copilotAudit` and `narrative`** — already preserved in the scene half of the
  sidecar. The recipe half cannot regenerate them, which is worth stating rather
  than fixing.
- **`composition`** — verified not baked into the exported frames: `paintScene`
  never reads it. What is lost is the author's working setup (grid, snap, safe
  area), not the picture.
- **`animation.orbit`** — manual-only state that the copilot can clear but never
  create. Worth revisiting if orbit becomes reachable from language.
- **`atmosphere` tuning** — the kind survives and carries sensible defaults.
  Only worth adding once someone asks for fog that behaves differently.

## What the adversarial pass changed

Four verdicts were corrected, and several sub-claims inside otherwise-confirmed
rows were refuted. The instructive one: the `Scene.narrative` row claimed two
*behavioural* consequences, that a round-tripped scene would scroll a run/travel
world the wrong way and would lose its template selection in the UI. Both were
wrong. `applyNarrativeSceneControls` has exactly one call site, inside
`createNarrativeScene`, so nothing re-applies controls to an existing scene; and
the template selector reads separate component state. The documentary loss of all
eight sub-fields stands, but the alarming half of the claim did not survive
being checked.

This is the third time in this work that a confident, well-cited claim has failed
verification. Treat single-reader findings here as unverified by default.

## The decision this needs

Splitting List A from List B is a product call, not an implementation one: it
sets how much of the format is contract and how much is convention. What is not
optional is the third path — if neither list is acted on, the sidecar should stop
describing the recipe as the clip's reproduction, because it is not one.

## Resolution — recipe contract v1 (2026-08-26)

Product decision: **List A is the v1 reproduction contract.** These fields now
exist in the closed JSON schema, parser and compiler, and `sceneToRecipe()` is
used when an edited scene is exported so the MP4 sidecar records the scene that
was actually rendered rather than the earlier LLM plan.

| Contract field | Status |
|---|---|
| `animation.keyframes`, events and layer timing | transported and compiled |
| `strip`, `seamOccluder`, `seamlessHorizontal` | transported and compiled |
| `relationship` | transported, validated for targets/cycles, and compiled |
| `visible`, `locked`, local `effects` | transported and compiled |
| skeletal clip timing | transported and compiled |
| `audioTracks[].model` | transported |

The documented List B remains intentional for v1: `thumbnail`, `missingAsset`,
working `composition`, `copilotAudit`, narrative/gallery provenance,
`animation.orbit` and detailed atmosphere tuning. These are either runtime/UI
state or not yet language-addressable. A sidecar may still contain the full
`scene` alongside its recipe, but only the contract rows above claim recipe
reproduction.
