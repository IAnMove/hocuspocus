# Music video from one spec

For agents that drive HocusPocus through MCP. The agent writes one spec (the creative part);
the studio does the rest and decides by numbers what a model used to decide by watching.
One `production.run` calls `audio.analyze`, `generation.music`, `generation.image`,
`scenes.video2d.edit`, `scenes.video2d.export`, `montages.save` and `montages.export`.
Export stays inside that run. Do not also call `montages.export`.
Do not add a planning call before `production.run`: the spec is the plan.

## Call order

The agent makes these calls for a finished video:

1. `production.run` `{workspace, production_id, spec}` — starts in the background and returns at once (`production_id`, `running: true`). It does not return a job id.
2. `production.status` `{workspace, production_id, wait_s}` until `status` is `completed` or `failed`. `jobs.wait` is a real command and blocks on a generation `job_id` until that job is `completed`, `failed`, `cancelled` or `discarded`. This run does not return a job id, so do not call `jobs.wait` to wait for it. Poll `production.status` with `wait_s` 300 instead of many short polls.
3. Read `review` and `retake_keys` from that `production.status`. The four checks are code. Do not call `production.review` to ask a model to look at the sheet.
4. If the verdict is `retake`, `production.run` again with `{workspace, production_id, retake: retake_keys}`, then repeat steps 2 and 3. The run shoots those clips again (new seeds, the better take is kept), including a shot that already has 4 takes, and re-exports only the scenes whose clip changed. Pass `retake_keys` unchanged.

Two other `production.run` forms are optional and still the same command. They are not extra tools, and they do not replace steps 2–4 once a full video exists:

- `{workspace, production_id, preview:{prompts:[p1,p2,p3], image_model:"qwen_image_21"}}` generates three look tests and no song. Poll `production.status` until `preview_completed` or `failed`. The three URLs are `preview_frames` on that status. There is no contact sheet yet, so do not call `production.review`.
- `{workspace, production_id, spec, through:"frames"}` stops after cast and frames (`status` `frames_ready`). Restart the isolated runtime if a large image model would slow H3, then resume with `production.run` `{workspace, production_id}` and continue at step 2.

Do not call `tools/list` or `models` to plan a production: everything the run needs is here.
Do not read the song, clips or scenes yourself: `production.status` reports lip-sync verdicts,
the video URL, a contact-sheet URL, and `review`. Do not judge that sheet yourself. The four
checks are code, not a model looking at the sheet. `face_consistent` stays unknown unless a
face-embedding model is already loaded; do not invent that answer.

A later `production.run` with the same id and no `retake` resumes from the last finished step.

## What the run does

| Step | Tool it uses | Decision made by code |
|---|---|---|
| song | `generation.music` × `song.seeds` (ACE-Step 1.5 XL) | keeps the candidate with the best lyric recall whose last 2 s are not cut |
| analyze | `audio.analyze` | tempo by period × phase search, vocals, word-timed lines |
| cast | `generation.image` (Flux 2 Klein) | one reference sheet per cast member |
| frames | `generation.image` with the cast sheets as references | one start frame per `h3` shot |
| clips | `generate` MiniMax H3 with the exact song slice as driving audio | `qa.lipsync` on `sing` shots; retake with a new seed until ok, the best `r` stops rising, `max_takes`, or 4 recorded takes. Naming the shot in `retake` may shoot it past 4. `clip_seconds` stores each shot's generation seconds (not the backoff, and not in `production.status`). A failed take is logged with its reason (`failures` in `production.status`, e.g. out of GPU memory); when a whole round fails the runner waits 60 s before the next. A resume retries clips that are still missing and still under the cap |
| scenes | `scenes.video2d.edit` + `scenes.video2d.export` | one scene per shot, lyric captions timed to the words, clip trimmed to stay in sync, instrumental gaps longer than a clip filled from `fill` on bar lines |
| montage | `montages.save` + `montages.export` | song as soundtrack, scenes in order |

Lip-sync is measured on the sung span.
When an H3 clip fails, its scene holds that shot's start frame and `production.status` lists the shot key in `held`.
A scene whose `scenes.video2d.export.receipt` is failed or cancelled, or whose job disappeared after the queue restarted, is exported again, at most twice in total. If it still fails, the run status is `failed` and the error is `scene_export_failed:` followed by the sorted scene keys separated by commas; `montages.save` is not called when no scene file exists.

State is saved in `<workspace>/<production_id>.production.json`: a restart or a new
`production.run` with the same id continues from the last finished step.
`production.run` refuses to start when the workspace volume has under 10 GiB free and the error code is `disk_low`.
When the run reaches `completed` it deletes losing takes and audio slices matching `*-slice-*.wav`, and it keeps the chosen song, the best take of each shot, the scene exports and the final video; a failed run deletes nothing.
A production left `running` resumes itself for 24 hours after a server restart when MCP is on
(a token and an app URL). That resume is not another agent call. A run that finishes completed clears `error`.
Lip-sync stops when the next measured `r` does not beat the best `r` already kept:
0.04, then 0.17, then 0.06 keeps 0.17 and does not shoot the next take. A shot with
4 recorded takes is not shot again unless that key is in `retake`.
The montage export in the table is internal. The agent does not call `montages.export` after the run.

## production.review

The four checks are code. They are not a language model looking at the contact sheet. `production.status` runs them when the workspace files are on disk. The reply stays small: no image bytes.

`review` is `{verdict, failures, unknown}`. `verdict` is `ok`, `retake`, or `unreliable`. `failures` is `[{key, question}]`. `retake_keys` is the shot keys from those failures, in scene order, and is passed unchanged as `production.run` `retake`.

The four code questions:

1. `black_bars` — sampled frames of the final video and of each scene. A letterbox or pillarbox (a thick black edge, not a vignette) is a failure.
2. `frozen_shot` — a shot marked held, including an H3 scene whose picture is a still because the clip was missing, or a scene whose frames barely change.
3. `title_cut_off` — a Video 2D text box outside the frame. `text_covers_face` — that box over a face from `qa.people` when `ckpts/pose/yolox_l.onnx` can run on CPU. If the detector cannot run, the face part is skipped and the box is still checked against the frame. No count and no face box are invented.
4. `duplicate_people` — `qa.people` on one frame per scene. More people than the shot's `cast` is a failure. If the detector cannot run, this check is skipped.

`face_consistent` asks whether the protagonist changes appearance. It stays in `unknown` unless a face-embedding model is already loaded and injected. The review does not download one and must not invent yes or no. Unknown identity does not by itself retake the video.

```json
{
  "review": {
    "verdict": "retake",
    "failures": [{"key": "chorus_one", "question": "frozen_shot"}],
    "unknown": ["face_consistent"]
  },
  "retake_keys": ["chorus_one"]
}
```

`ok` means keep the video (`retake_keys` is empty). `retake` means call `production.run` again with those keys and the same id:

```json
{
  "workspace": "musical",
  "production_id": "hocuspocus-musical",
  "retake": ["chorus_one"]
}
```

`unreliable` means the frames could not be read (no finished video yet, or the files are missing). Do not guess a retake. `failures` is empty and `retake_keys` is empty. `unknown` still lists `face_consistent` when no embedding backend ran.

## Spec

```json
{
  "title": "HocusPocus - the musical",
  "song": {
    "lyrics": "[Verse]\nI had a story stuck inside my head\n...\n[Chorus]\nHocus pocus, make it move\n...",
    "caption": "Upbeat cinematic synth-pop, 112 BPM, bright female pop vocal, big catchy chorus",
    "duration": 62, "bpm": 112, "key": "A minor", "seeds": [11, 22, 33]
  },
  "style": {
    "image": "Cinematic anime key frame, rich painterly lighting, clean lineart, 16:9.",
    "video": "Cinematic anime animation with rich painterly lighting and clean lineart.",
    "lyric_template": "social-caption",
    "finish": {"finish": {"grade": {"contrast": 0.12, "saturation": 0.1, "temperature": 0.2}, "vignette": {"amount": 0.3, "softness": 0.6}}}
  },
  "cast": [{"id": "sorceress", "seed": 5, "sheet_prompt": "Character design turnaround sheet ... full body front, three-quarter and back views, two head close-ups"}],
  "stills": {"story": "/api/v1/uploads/<screenshot>.png", "keyart": "/api/v1/uploads/<keyart>.png"},
  "max_takes": 3,
  "shots": [
    {"key": "intro", "kind": "still", "t0": 0, "still": "keyart", "zoom": [1.0, 1.08],
     "title": {"template": "end-card", "fields": {"title": "HocusPocus", "cta": "the musical"}}},
    {"key": "l0", "kind": "h3", "line": 0, "cast": ["sorceress"], "sing": true,
     "frame": "Medium close-up of the young sorceress from the reference sheet ... facing the camera, lips parted",
     "action": "(S1) The sorceress sings to the camera in her candlelit study, swaying gently. Slow push in."},
    {"key": "l1", "kind": "still", "line": 1, "still": "story", "focus": {"x": 60, "y": 45}, "zoom": [1.5, 1.65],
     "title": {"fields": {"date": "STORY LAB", "caption": "characters, places, rules"}}},
    {"key": "ch1", "kind": "h3", "line": 4, "span": 2, "cast": ["sorceress"], "sing": true, "frame": "...", "action": "..."},
    {"key": "outro", "kind": "still", "after": 11, "still": "keyart",
     "title": {"template": "end-card", "fields": {"title": "HocusPocus", "cta": "free on Pinokio"}}}
  ],
  "fill": [{"kind": "clip", "clip": "l3", "camera": "camera-pan-right"}, {"kind": "still", "still": "story", "zoom": [1.2, 1.35]}]
}
```

`style` may be only a preset. That stands in for the long image, video, finish and lyric block (about 2k tokens when the prompts are written out). `production.run` expands `style.preset` before it checks the spec. The expansion fills `image`, `video`, `finish`, `lyric_template`, `theme` and `image_model`, plus the other style fields from the production that already rendered that look. A key you set next to `preset` replaces that field.

| preset | look it copies |
|---|---|
| `anime` | cinematic anime key frame from the promo musical |
| `riso-zine` | Love the Machine risograph zine (`love-the-machine.production.json`) |
| `omarchy-desktop` | native Omarchy Tokyo Night desktop (`keyboard-first`) |
| `neo-noir-realista` | photoreal rain-soaked neo-noir (`city-of-windows`) |

```json
{"style": {"preset": "riso-zine"}}
```

An unknown id fails with code `unknown_style_preset`. The full style block in the example above still works when a video needs a one-off look.

Style fields beyond the example:

- `image_model` (default `flux2_klein_9b`) and `image_params`: model for cast sheets and frames. Flux 2 Klein does not
  recognise public figures; `qwen_image_21` does (it takes ~40 steps from `app/defaults`; do not run it next to H3 on one GPU:
  generate all images first). `finish` takes any `set_finish` body, e.g. `{"preset": "risoPress"}`.
- `lyric_template`: any text template; the lyric goes in its `caption`/`line` field (`ransom`, `dymo`, `social-caption`, ...).
- `theme`: an Omarchy colour theme (`tokyo-night`, `catppuccin`, `gruvbox`, `nord`, `rose-pine`, `kanagawa`): lyrics become
  a square mono plate in the theme colours and `screen` shots use it. `lyric_style` is an `update_text` patch applied to
  every lyric cue (`color`, `font`, `weight`, `size`, `box`, `enter`) and wins over the theme.

Shot fields:

- `kind`: `h3` (generated clip), `still` (image from `stills` or a URL), `clip` (reuse an `h3` shot's clip, for `fill`),
  `screen` (a tiling-window-manager desktop painted natively, no GPU: `desktop` = `{layout: single|split|triple|quad|master,
  apps: dev|system|mixed, focus, workspace, switch: none|left|right}`; windows open one after another and `switch` slides
  the desktop in like a workspace change).
- Timing: `line` (index of a lyric line; the shot starts 0.25 s before it and spans `span` lines), `t0` (seconds) or `after` (starts 0.3 s after that line ends). Shots are cut at the next shot's start.
- `h3`: `frame` (start-frame prompt), `action` (what moves; use `(S1)` for the singer), `sing: true` for lip-sync, `cast` ids used as image references.
- `still`: `focus` {x, y} (percent of the image kept centred while zooming), `zoom` [start, end], `camera` preset.
- `title`: a text template (`lower-third-date`, `end-card`, `title-card`, …) with its fields. Lyric captions are added automatically.
- `title.style` overrides `style.title_style` for that shot; `title.cues` maps a template cue id (for example `title`, `sub`, `date`, `caption`) to an additional patch. Set the title-card cue's `box.color` to the video's own palette instead of accepting the template's black plate.
- H3 and reused clip layers default to a locked camera so a second zoom does not fight the generated camera motion. Set `camera` explicitly on a shot when a deliberate Video 2D camera move is wanted.
- `graphic`: a drawing from `app/shared/scene_graphics.json` attached to the first title cue, for example `{"id":"shatter","params":{"pieces":12}}`.

Style fields for native Video 2D finishing:

- `image_model` chooses the Studio image model for cast and frames (default `flux2_klein_9b`; `qwen_image_21` is useful for a recognizable public-person caricature). `image_steps` sets its step count; individual cast members or H3 shots may override either field.
- `finish` accepts the same `set_finish` values as Video 2D, including `{"preset":"risoPress"}`. Riso automatically traps text on the black plate.
- `lyric_template` may be `ransom` or `dymo` as well as `social-caption`. `title_style` and `lyric_style` are Video 2D text patches, for example `{"font":"mono","color":"#A9B1D6"}`.
- `footer` adds a persistent small-print line to every scene. `footer_style` can set its color, font and background through the Video 2D text patch fields.

## Cost

A 60 s video with 5 H3 shots is about 25–35 min of GPU on an RTX 4090. The agent's side is the spec
(~2–3k tokens, less when `style` is only a `preset`), one `production.run`, and a few `production.status` polls (~300 tokens each). The `review` is already on that status: four checks in code, not a model looking at the sheet. A retake is another `production.run` only when that
verdict says so, using `retake_keys` unchanged. Poll `production.status` with `wait_s` 300 instead of many short polls.

## Things to avoid

- Lyrics the singer cannot sing: keep lines short, one idea per line, and give the song a clear bpm.
- Close-ups for `sing` shots are fine, but extreme close-ups make `qa.lipsync` report `unreliable`
  (the face is not detected); prefer medium close-ups.
- Titles on the right edge of the frame collide with nothing, but keep them off faces: put the
  performer to one side in the `frame` prompt when a shot has a title. The code review checks
  `title_cut_off` and `text_covers_face` for this.
- Do not invent `face_consistent`. Unknown means stop on that question, not a guessed yes or no. Do not guess a retake when `review.verdict` is `unreliable`.
