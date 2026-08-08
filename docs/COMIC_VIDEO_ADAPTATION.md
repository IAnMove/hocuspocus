# Comic-to-video adaptation

Maestro treats a finished comic as narrative and visual source material, not as
a list of video jobs. A comic panel and a film shot are different units:
several panels can become one shot, a panel can be omitted, and a dense panel
can produce more than one shot.

## Workflow

1. **Settings** selects output aspect, LTX model, quality and defaults.
2. **Source beats** lets the user include, order and annotate comic panels
   before adaptation. These controls are hints and explicit locks, not the
   final shot list.
3. Director turns those beats into a shorter film edit. It may fuse adjacent
   panels, omit a redundant beat or split an important panel. Any source beat
   with an explicit user override remains the primary frame of at least one
   shot.
4. **PRE** freezes the exact clean plate, effective prompt, duration, seed and
   renderer before any generative video work starts.
5. The user approves that exact PRE fingerprint, renders representative test
   shots, reviews their playable results and explicitly accepts them. A
   reasoned waiver is available as an auditable exception.
6. Completed clips are assembled with hard cuts only after automatic
   validation. Lettering remains metadata and is never baked into an I2V
   conditioning frame. Spoken dialogue is preserved in full in PRE; an
   automatic LTX shot also receives a bounded excerpt as a performance/native
   soundtrack cue.

PRE is a separate comic workspace tab. It must not cover the comic canvas or
appear as a transient modal over editable artwork.

Storyboard projects are the exception to the editorial adaptation step: their
approved panels are already authored shots, so Maestro preserves them
one-to-one by default. Printed-comic projects use the shorter cinematic edit.

## Film-shot contract

New comic projects persist the editable fields on their source panels and send
their snake-case equivalents to Director:

```json
{
  "shot_id": "comic-shot-page-3-panel-2",
  "source_panel_ids": ["panel-page-3-2"],
  "included": true,
  "renderer": "ltx",
  "action": "Nara lowers her gaze and offers the blue seed to Kael.",
  "camera": "locked",
  "motion_level": 1,
  "duration_seconds": 3.2,
  "fit_mode": "contain",
  "test_selected": true,
  "seed": 1847721,
  "end_beat": "Kael's hand stops just above the seed."
}
```

Legacy `motion_mode`, `camera_move`, `page_number` and `panel_number` fields
remain accepted during migration.

### Renderers

- `hold`: deterministic fixed frame; no generative redraw.
- `parallax`: deterministic centered push of at most 1.5%. It does not infer
  depth layers and is therefore not true 2.5D parallax.
- `cinemagraph`: subtle full-frame LTX I2V. There is no region mask in this
  implementation, so PRE labels it as an AI living still rather than
  promising selective motion.
- `ltx`: a chronological subject or environment action generated with I2V.

A contextual quiet character or portrait defaults to `hold`, because the
current cinemagraph route can redraw the complete frame. AI ambient motion is
used only when it is explicitly requested; PRE can still change any individual
shot after reviewing its face, line-art and aspect risks.

A locked camera is a hard renderer decision for `hold` and `parallax`. For LTX
it remains a requested behavior and must be checked after generation.

## Video-safe clean plates

The default is `contain`, which keeps the complete panel on a matte canvas.
The former blurred-side `smart` mode is migrated to `contain`; PRE never
silently invents or blurs missing scenery.

- `reframe`: compatibility state for projects that already contain a verified
  prepared keyframe. Creating or importing a new AI reframe is not yet exposed
  in this branch. An unresolved legacy reframe is shown but disabled and
  blocks approval until the user chooses `cover` or `contain`.
- `cover`: protected editorial crop, with its retained fraction shown in PRE.
- `contain`: preserve the full panel with a dark matte.

PRE shows the original capture beside the prepared frame. Extreme aspect
mismatches remain visible warnings. The user approves the exact prepared frame
that will be sent to the selected renderer.

## LTX prompt contract

The source image already establishes appearance. The I2V prompt describes only
the changes after the first frame:

1. camera behavior;
2. one chronological visible action;
3. restrained secondary motion;
4. a stable end beat;
5. a bounded excerpt of real spoken dialogue when the shot contains speech;
6. a short list of invariants when identity or line art is fragile.

Do not repeat the complete story bible, static image prompt or long negative
instruction blocks in every clip.

LTX's empty audio-source mode generates video and soundtrack jointly from the
text prompt. That can attempt spoken performance, but it is not deterministic
TTS: exact wording, timing and voice identity are not guaranteed. PRE therefore
shows the complete editorial line and labels this limitation. `hold` and
`parallax` shots retain dialogue only for later dubbing or subtitles. During
normalization, Maestro preserves and pads LTX audio to the exact shot duration;
deterministic shots receive a silent stereo AAC track so mixed-renderer films
can be joined reliably without discarding generated ambience or speech.

## Reproducibility and recovery

- Every PRE has a fingerprint of comic content, shot list, prepared images and
  effective runtime settings.
- A changed shot or setting invalidates the old PRE.
- Every shot seed is derived from the master seed and stable shot ID.
- Regeneration reuses that seed unless the user explicitly randomizes it.
- PRE and generated children remain resumable checkpoints. Every completed
  individual clip is persisted before final assembly.

## Quality gate

The representative test set covers available high-risk categories rather than
the first two panels:

- extreme aspect mismatch;
- face close-up;
- multiple characters;
- meaningful action;
- wide environment;
- fine line art.

Before assembly, generated clips record checks for exact duration and canvas,
first-frame divergence, gross locked-camera drift and duplicate generated
outputs. These checks are deliberately conservative heuristics, not a
perceptual-quality oracle; the required human review remains part of the gate.
A failed clip stays recoverable and is not silently accepted into the final
film.
