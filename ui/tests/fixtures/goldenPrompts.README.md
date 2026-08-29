# Golden prompts — needs human review before the baseline counts

`goldenPrompts.json` is the fixed prompt set for the template-selection
evaluation (task T0.4). Each entry pairs a request phrased the way a user would
actually type it with the templates a competent answer could choose.

## The methodological caveat, stated plainly

**These expectations were drafted by the same author as the plan and the
catalog they evaluate.** That is a real weakness: an evaluation whose answer key
comes from the party being evaluated measures agreement, not correctness. Treat
the first baseline as provisional until someone else has reviewed this file.

Three things were done to limit the damage, and they are not a substitute for
that review:

1. **Prompts are written from the request side, not the template side.** They
   describe what someone wants to see, and avoid restating template names or
   internal vocabulary. `dialogue-medium-single` is elicited by "waist up, calm,
   nothing fancy", never by "medium single".
2. **`templateAnyOf` accepts every defensible answer, not one preferred answer.**
   Where two templates would both serve the request, both are listed. A
   selection is scored correct if it lands anywhere in the set.
3. **Expectations follow the library's own `visualIntent` text**, not the
   author's taste. If a template says it exists to "let surrounding space make a
   character feel small", the prompt asking for exactly that lists it.

## What a reviewer should look for

- Entries where `templateAnyOf` is too generous, so that almost any answer
  passes and the metric flatters itself.
- Entries where it is too narrow, punishing a defensible alternative reading.
- Prompts that leak template vocabulary and therefore test string matching
  rather than judgement.
- Requests a real user would make that this set never asks for at all.

Disagreements should be resolved by editing this file **before** rerunning the
eval, never by editing the eval to accommodate a result.

## Coverage the set is required to hold

| Requirement | Count |
|---|---|
| Total entries | 28 |
| Spanish / English | 14 / 14 |
| Explicit short beat (3–7 s) | 6 |
| Portrait / vertical | 5 |
| Dialogue or character | 12 |
| Multi-shot requests | 2 |
| The snowy-station anchor prompt, verbatim | 1 |

The short-beat and portrait entries are not filler. They exist to trip two known
defects on purpose: templates clamp every scene to a 10-second floor
(`sceneNarrative.ts`, `durationOf`), and every template coordinate is a
percentage tuned for 16:9. If the model happily selects templates for those
requests, the baseline has caught both.

`durationHint` extends the schema sketched in the plan. T0.4 needs to report the
share of shots asking for under 10 seconds, and separating "the user asked for
4 s" from "the model chose 4 s" is what makes that number mean anything.
