# Phase 1 fidelity check

One live generation against the anchor prompt, run after T1.1–T1.4, using the
updated system prompt and schema:

> Pon a este personaje caminando hacia la derecha por una estación nevada;
> cámara lateral, fondo en parallax, una farola tapa el loop y música melancólica.

| Clause | Before phase 1 | After |
|---|---|---|
| música melancólica → grade | no field existed | `mood: dreamy`, `palette: cool`, `intensity: 2` |
| música melancólica → sound | no field existed | `audio: [{ kind: music, prompt: "Slow, melancholic piano and ambient strings, wistful winter mood", volume: 0.8 }]` |
| fondo en parallax | silent 0.2 / 1, two planes | four distinct planes: 0.3, 0.7, 1, 0.9 — set explicitly by the model |
| cámara lateral | no route to the render | `transform.rotationY: 90` on the model3d layer |
| farola tapa la costura | impossible | still impossible — `SceneRecipeLayer` has no `strip` field |
| personaje caminando | clip without translation possible | unchanged — needs the capability negotiation in phase 4 |

Four of the six clauses that died in the T0 baseline now survive the trip from
prompt to compiled scene. Both remaining failures are the ones phase 1 never
claimed to address.

The parallax result is worth separating from the rest. The compiler's automatic
banding was the fix that got written; what actually happened is that the model
set four distinct values itself once the prompt told it the lever existed and
what the numbers mean. The banding is the floor, not the outcome — which
supports the wider claim in the plan that these were vocabulary gaps rather than
reasoning failures.

## What this is not

A single generation at temperature 0.2, on one prompt, scored by reading the
JSON. It shows the fields are reachable and that the model reaches for them
unprompted. It says nothing about whether the resulting *frames* look better —
that needs the rendered-frame comparison in phase 6, and the grading formula's
actual visual payoff remains unproven.
