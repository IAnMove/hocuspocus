# Template selection baseline — T0.5

Run: 28 golden prompts, provider `minimax` (remote), temperature 0.2, structured
output requested via `json_schema`. Reproduce with:

```bash
npx tsx --tsconfig tsconfig.app.json scripts/eval-selection.mjs --out /tmp/eval-baseline.json
```

| Metric | Value |
|---|---|
| Selection top-1 | 27 / 28 (96.4%) |
| Selection top-1, dialogue + character only | 17 / 18 (94.4%) |
| Contract compliance (valid JSON) | 26 / 28 (92.9%) |
| Shot-count within expected range | 24 / 26 (92.3%) |
| Shots requesting under 10 s | 9 / 31 (29.0%) |
| Portrait prompts that selected a template | 5 / 5 (100%) |

## The three kill signals

### 1. Is top-1 accuracy below 50% on the near-duplicate dialogue and character templates?

**No — it is 94.4%.** This was the plan's primary hypothesis and the baseline
refutes it. The prediction was that asking a model to prefer
`american-action-frame` over `dialogue-medium-single` from prose amounts to
asking it to guess a constant, since sixteen of the twenty-eight templates share
one structure with framing numbers differing by a few percent. On this evidence
that is wrong: the `visualIntent` text carries enough signal to separate them.

**Consequence for the plan: phase 3 is no longer a prerequisite.** The refactor
to grammars × parameters was scheduled before connecting templates to the recipe
precisely because selection was assumed broken. It is not, so the ordering
changes — connect first, refactor when catalog growth actually demands it.

The refactor keeps its other justification. At 462 characters per template the
current catalog is 12,939 characters (~3,200 tokens); a ~117-template library
lands near 54,000 (~13,500 tokens), which forces faceted retrieval regardless of
how accurate selection is today. That is a scaling argument, not a correctness
one, and it belongs with the catalog expansion rather than ahead of it.

### 2. What share of shots requested under ten seconds?

**29%, and every one of them was a request the user made explicitly.** The
durations returned were 3, 4, 4, 4, 5, 5, 5, 6 and 6 seconds, and they line up
with the prompts that asked for a short beat. The model honours an explicit
duration correctly.

**Consequence: the `durationOf` floor is confirmed as a product-level blocker.**
`Math.max(10, …)` in `sceneNarrative.ts` would silently overwrite a correct
answer in roughly three of every ten shots. T2.1 is not a detail to clean up
later; it is the difference between the compositor honouring rhythm and
discarding it.

### 3. Did any portrait prompt select a template?

**All five did.** Nothing in the catalog declines a vertical request, and every
template coordinate is a percentage tuned for 16:9 — `mediumClose(60, 75, 1.72)`
crops entirely differently at 720×1280.

**Consequence: aspect-conditional variants are a prerequisite, as predicted.**
The model cannot avoid this on its own; the catalog gives it no way to know. This
needs either per-aspect variants or an explicit `aspects` field on each template
so an unsupported request fails loudly instead of framing wrong.

## Findings the signals did not anticipate

**Structured output is not enforced.** Two of 28 responses (three in the first
run) returned JSON with an extra closing brace, leaving the shots array
unterminated, despite `json_schema` being supplied. The remote provider treats
the schema as guidance. Everything downstream must assume the repair pass in
`sceneRecipe.ts` is load-bearing rather than defensive.

**The one selection miss is a catalog gap, not a selection error.** `vertical-line`
("el personaje mira a cámara y suelta la frase") chose `inner-thought`, which is
built for voice-over contemplation. There is no direct-address template in the
library, so the model picked the least-wrong option for a request the catalog
cannot serve. That is an argument for the catalog expansion, and it means true
selection accuracy on requests the library can actually serve is 27/27.

**Two shot-count "violations" are probably fixture errors.** `paper-snap` ("he
pauses, then snaps into a shocked pose") and `behind-pillar` ("start hidden, then
reveal her") each returned two shots against an expected maximum of one. Both
read as two beats to a human too. The fixture should be corrected, not the model.

**Run-to-run variance is material.** Two runs at temperature 0.2 differed in
malformed-JSON count (3 vs 2) and in several template choices that all remained
inside the accepted set. A single run is not a stable measurement; treat these
figures as approximate and re-run before reading a small change as a regression.

## What this baseline is not

The expectations in `goldenPrompts.json` were drafted by the same author as the
plan and the catalog they evaluate. A 96% score against one's own answer key is
weak evidence, and the caveat is recorded in full in
`ui/tests/fixtures/goldenPrompts.README.md`. **This baseline should be treated as
provisional until someone else reviews the fixture.** The three structural
findings above — the duration floor, the aspect gap, and unenforced structured
output — do not depend on the answer key being right, and stand on their own.
