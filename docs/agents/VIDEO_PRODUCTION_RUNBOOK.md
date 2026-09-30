# Music video from one spec

For agents that drive HocusPocus through MCP. The agent writes one spec (the creative part);
the studio does the rest and decides by numbers what a model used to decide by watching.
One `production.run` calls `audio.analyze`, `generation.music`, `generation.image`,
`scenes.world3d.export` for `scene3d` shots, `scenes.video2d.edit`, `scenes.video2d.export`, `montages.save` and `montages.export`.
Export stays inside that run. Do not also call `montages.export`.
Call `production.plan` with the eight-field brief when you do not already have a spec. It returns the spec. Then `production.run`.

## Call order

The agent makes these calls for a finished video:

`production.plan` `{brief}` returns the spec when the agent has a brief and no spec yet. The brief fields are `tema`, `publico`, `duracion`, `musica`, `estilo`, `protagonista`, `cta` and `limites`. `lyrics` (or `letra`) is required: the plan does not write placeholder lines that a singer would perform (`invalid_brief` without it). An optional `footer` (or `aviso`) is the small print on every scene. Reading rules: an explicit look word beats a subject word ("zine riso sobre Omarchy" is `riso-zine`), `124 BPM` or `110-125 bpm` is the tempo (decades such as `2000s` are not), `1:30`, `90 s` and `2 minutos` are lengths, and accents survive in titles. What the non-sung shots are follows the look: your `stills`, the native desktop for `omarchy-desktop` (nobody sings on screen), otherwise short H3 clips of the protagonist. Then start at step 1.

1. `production.run` `{workspace, production_id, spec}` — starts in the background and returns at once (`production_id`, `running: true`). It does not return a job id.
2. `production.status` `{workspace, production_id, wait_s}` until `status` is `completed` or `failed`. `jobs.wait` is a real command and blocks on a generation `job_id` until that job is `completed`, `failed`, `cancelled` or `discarded`. This run does not return a job id, so do not call `jobs.wait` to wait for it. Poll `production.status` with `wait_s` 300 instead of many short polls. Do not save tokens at the expense of the result: opening `frames_sheet` before the clips and one real-size frame of each sung shot and of the first caption before delivering costs a few thousand tokens, and it is what catches a duplicated character, an unreadable caption or a title that covers the picture. A retake with a stricter action is cheaper than a video that is delivered wrong.
3. Read `review` and `retake_keys` from that `production.status`. The four checks are code. Do not call `production.review` to ask a model to look at the sheet.
4. If the verdict is `retake`, `production.run` again with `{workspace, production_id, retake: retake_keys}`, then repeat steps 2 and 3. The run shoots those clips again (new seeds, the better take is kept), including a shot that already has 4 takes, and re-exports only the scenes whose clip changed. Pass `retake_keys` unchanged.

Two other `production.run` forms are optional and still the same command. They are not extra tools, and they do not replace steps 2–4 once a full video exists:

- `{workspace, production_id, preview:{prompts:[p1,p2,p3], image_model:"qwen_image_21"}}` generates three look tests and no song. Poll `production.status` until `preview_completed` or `failed`. The three URLs are `preview_frames` on that status. There is no contact sheet yet, so do not call `production.review`.
- `{workspace, production_id, spec, through:"frames"}` stops after cast and frames (`status` `frames_ready`). Restart the isolated runtime if a large image model would slow H3, then resume with `production.run` `{workspace, production_id}` and continue at step 2.
- `{workspace, production_id, spec, through:"animatic"}` builds a CPU preview after those frames: the start frames play as stills with the lyrics, titles and the song (`status` `animatic_ready`). `production.status` reports the preview as `animatic` (not `video`) plus `contact_sheet` and `animatic_warnings` (a title card covering the picture, the same image used twice, a still stretch over 10 seconds, or an unreadable caption). A restart does not treat `animatic_ready` as `running`, so it does not start a GPU run by itself. Resume with `production.run` `{workspace, production_id}` and the run continues at the clips, reuses the frames, and re-exports a scene once its clip is different from the still it previewed.

Do not call `tools/list` or `models` to plan a production: everything the run needs is here.
Do not read the song, clips or scenes yourself: `production.status` reports lip-sync verdicts,
the video URL, a contact-sheet URL, and `review`. Do not judge that sheet yourself. The four
checks are code, not a model looking at the sheet. `appearance_changed` stays unknown unless a
face-embedding model is already loaded; do not invent that answer.

A later `production.run` with the same id and no `retake` resumes from the last finished step.

`production.run` with `dry_run: true` checks the spec before any GPU work. It also reports `motion` (`static_s`, `static_ratio`, `longest_shot_s`, `avg_shot_s`) and warns about a static video (`too_static`, over 35 % of the runtime on still images: the 160 s videos with 9 clips were 43–56 %), a hold over 10 s (`long_shot`), a still used three times (`still_reused`), `max_takes` 1 (`single_take`) and fewer than three song seeds (`few_song_seeds`). It lists each shot window, the H3 frame count, lyric lines with no shot, gaps with no fill, titles over 12 characters, captions over 32, and estimated minutes. `shots: "auto"` is expanded in that check. Each window includes `hold_after_clip`: how many seconds that H3 shot would sit still after its clip (the longest H3 bucket is 345 frames, 14.375 s), or 0 when the shot is not H3 or a moving fill (`h3`, `clip`, `scene3d`, `screen`) covers the tail. A hand-written `title-card` on an `h3` or `still` shot is `title_card_on_image` and still validates; the planner rewrites that template to `lower-third-date` on those kinds. The same check compiles every scene document in-process, so a style the editor would reject (`scene_invalid`, for example a text field out of range) shows up here. Before the scenes stage the run measures the busiest caption against its start frame and stops with `caption_unreadable` (the scene and the ratio) when contrast is under 3:1. An opaque caption box is measured against the box; text with no box is measured against the picture.

## Edit it by hand, shot by shot

A finished production is not a black box. At the end of every run the studio packages it (`package` in the log):

- one durable `<production_id>-<shot>-<hash>.scene.json` per shot (the clip layer, the lyric captions, the title, the finish), which opens in Video 2D;
- the montage (`production.status` → `editable.montage`, a `*.montage.json` that opens in the Video Editor) with each clip named after its shot, carrying its lyric and an origin (`scene2d`, the scene document, the production and the shot). The shot board (Video Editor → Shots) shows them and has an **Open scene** button;
- `<production_id>.shots.json` (`editable.manifest`): for every shot its time span, lyric, prompts, seed, start frame, every take with its lip-sync number, scene document and scene video;
- every take of every clip stays on disk (only the audio slices and the takes nobody recorded are cleaned up), so swapping one in is possible.

To fix a shot: open the montage in the Video Editor, press **Open scene** on the shot, change the clip layer to another take or retouch the text/camera in Video 2D, export, replace the clip in the timeline (the usual replace-clip handoff), export the montage. To redo a shot with the GPU, `production.run` with `retake: ["shot"]`; that re-exports only that scene.

## Change a take, a look, the song, or stop the run

People use **Music productions** in the sidebar. It lists each `*.production.json` (status, title, duration, montage contact sheet). Opening one shows the rows of `<id>.shots.json`: start frame, clip, lyric, whether it is sung, every take with its r, and the scene. **Open scene** opens that shot's scene in Video 2D. **Another take** is `production.run` with that shot in `retake`. **Use this take** swaps that take in without a GPU. **Open montage** loads the montage into the Video Editor.

Agents use the same actions as commands:

- `production.shot.use_take` `{workspace, production_id, shot, take_file}` sets that kept take as the shot clip, saves a new scene revision, re-exports only that scene and replaces its montage clip under the same `expected_revision` a repackage uses. The clip origin stays. `take_not_found` when the file is not one of that shot's takes. No GPU.
- `production.shot.update` `{workspace, production_id, shot, lyric_style?, title?, camera?}` stores those fields on `spec.shots[i].overrides` and re-exports only that scene. A `lyric_style` override replaces the global lyric look for that shot. This is the agent path; people use the panel.
- `production.song.use` `{workspace, production_id, candidate}` switches to a candidate kept in `song_candidates` (its id or its file). The switch re-analyses the song, recomputes windows and marks a clip `obsolete` when its audio window moved by more than 0.3 s. It does not delete clip files. Shots whose window stayed put keep their clip.
- `production.cancel` `{workspace, production_id}` asks a live run to stop between rounds. Status becomes `cancelled` (a restart will not treat that as `running` and will not launch a GPU run by itself). The files and the spec stay. A later `production.run` with the same id resumes.

`production.run {workspace, production_id, package: true}` does the packaging for a production made before this existed (no GPU, no export; it saves the scene documents, the manifest and the montage clips' origins). Each document goes through the Video 2D scene validator: `production.status` → `editable.warnings` counts what it flags (text cut off or overlapping, low contrast when it can sample it), listed per shot in the manifest. It does not see everything: `dymo` lyrics used to punch their letters out of black tape and vanished on dark pictures; `dymo` now defaults to dark letters on cream tape (set `lyric_style.box` to choose your own).

## Quality: what the run spends

`quality` in the spec is `draft`, `standard` or `max` (a brief may say `calidad`). It fills only what the spec left out (song seeds: 1 / 3 / 4, `max_takes`: 1 / 2 / 3) and sets the bar `dry_run` measures the plan against: the share of the runtime that may be a still image (60 % / 35 % / 15 %) and the clips a minute (2 / 5 / 7); missing the bar is a `too_static` or `few_clips` warning before any GPU work. No `quality` keeps the spec as written and the `standard` bar. What made the long videos thin was the plan, not a bug: 160 s with 9 clips and `max_takes` 1 is 45 % still pictures and no quality gate. Give a long song more shots, not a slower zoom.

While it runs:

- each clip is judged and saved the moment it lands (a restart mid-round keeps what was already shot), and a better verdict beats a higher lip-sync number (an `unreliable` result never pushes out a take that measured `ok` or `retake`);
- after the start frames, `production.status` gives `frames_sheet` (one labelled picture of every frame): look at it before the clips, where a wrong frame is minutes of GPU per clip;
- a cast entry may be `{"id": "trio", "group": ["hum", "tinker", "zap"]}`: one reference image with their sheets side by side (letterboxed, nothing cropped), for shots with several characters when the image model runs out of memory with three references. `count` defaults to the group's size;
- a shot with one character gets "Only this character appears; no other characters" in its action (the planner does it; write it yourself in a hand-made spec), because a video model invents company otherwise.

## What the run does

| Step | Tool it uses | Decision made by code |
|---|---|---|
| song | `generation.music` × `song.seeds` (ACE-Step 1.5 XL) | keeps the candidate with the best lyric recall whose last 2 s are not cut; every candidate stays in `song_candidates` |
| analyze | `audio.analyze` | tempo by period × phase search, vocals, word-timed lines |
| cast | `generation.image` (Flux 2 Klein) | one reference sheet per cast member |
| frames | `generation.image` with the cast sheets as references | one start frame per `h3` shot |
| clips | `generate` MiniMax H3 with the exact song slice as driving audio | `qa.lipsync` on `sing` shots; retake with a new seed until ok, the best `r` stops rising, `max_takes`, or 4 recorded takes. Naming the shot in `retake` may shoot it past 4. `clip_seconds` stores each shot's generation seconds (not the backoff, and not in `production.status`). A failed take is logged with its reason (`failures` in `production.status`, e.g. out of GPU memory); when a whole round fails the runner waits 60 s before the next. A resume retries clips that are still missing and still under the cap |
| scenes | `scenes.video2d.edit` + `scenes.video2d.export` | one scene per shot, lyric captions timed to the words, clip trimmed to stay in sync, instrumental gaps longer than a clip filled from `fill` on bar lines |
| montage | `montages.save` + `montages.export` | song as soundtrack, scenes in order |

A start frame that does not arrive is asked for again (a new job, and a smaller picture after an out-of-memory) twice per run; if it still fails the run stops as `failed` with `frames_incomplete` and `production.status` lists `frame_failures`. A cast entry may set `count` (how many distinct subjects that reference image shows, default 1); the frame prompt then says "Exactly N distinct subjects, no duplicated characters", because a sheet with several views makes the model draw the character several times. A group reference (several characters in one image) is the way to keep three references under the image model's memory limit.

Lip-sync is measured on the sung span.
When an H3 clip fails, its scene holds that shot's start frame and `production.status` lists the shot key in `held`.
A scene whose `scenes.video2d.export.receipt` is failed or cancelled, or whose job disappeared after the queue restarted, is exported again, at most twice in total. If it still fails, the run status is `failed` and the error is `scene_export_failed:` followed by the sorted scene keys separated by commas; `montages.save` is not called when no scene file exists.

State is saved in `<workspace>/<production_id>.production.json`: a restart or a new
`production.run` with the same id continues from the last finished step.
`production.run` refuses to start when the workspace volume has under 10 GiB free and the error code is `disk_low`.
When the run reaches `completed` it deletes this production's losing takes and `{id}-slice-*.wav` audio slices. Other videos in the same workspace stay. It keeps the chosen song, the best take of each shot, the scene exports and the final video; a failed run deletes nothing.
A production left `running` resumes itself for 24 hours after a server restart only when it asked for it: `production.run` with `auto_resume: true` (kept in its state file), or the server started with `HOCUS_PRODUCTION_AUTORESUME=1`; MCP must be on (a token and an app URL). Without that a stopped server stays stopped and no GPU work restarts on its own. That resume is not another agent call. A run that finishes completed clears `error`.
A second `production.run` for a production that is still running fails with `already_running` (409): wait for `production.status`, or use another `production_id`. A job the queue forgot (a restart drops the queue) is shot again up to 3 times per shot and is not counted as a take.
Lip-sync stops when the next measured `r` does not beat the best `r` already kept:
0.04, then 0.17, then 0.06 keeps 0.17 and does not shoot the next take. A shot with
4 recorded takes is not shot again unless that key is in `retake`.
`production.status` includes `timing` in seconds for song, analyze, cast, frames, clips, scenes and montage (0 when that stage did not run), and `timing.shots` lists each clip's `key`, `seconds` and take count.
`production.status` also includes `usage`: `mcp_calls`, `response_bytes` (what the run's own runner read from the studio's MCP replies) and `h3_takes`. These are not LLM tokens and are not converted to them: the client that runs the language model (for example Claude Code, which logs usage per message) is the only one that can measure those.
The montage export in the table is internal. The agent does not call `montages.export` after the run.

## production.review

The four checks are code. They are not a language model looking at the contact sheet. `production.status` runs them once the run is over (`completed` or `failed`) and remembers the answer, because they open the video files; while a run is going `review` is `unreliable` and empty. The reply stays small: no image bytes.

`review` is `{verdict, failures, unknown}`. `verdict` is `ok`, `retake`, or `unreliable`. `failures` is `[{key, question}]`. `retake_keys` is the shot keys from those failures, in scene order, and is passed unchanged as `production.run` `retake`.

The four code questions:

1. `black_bars` — sampled frames of the final video and of each scene. A letterbox or pillarbox (a thick black edge, not a vignette) is a failure.
2. `frozen_shot` — a shot marked held, including an H3 scene whose picture is a still because the clip was missing, or a scene whose frames barely change.
3. `title_cut_off` — a Video 2D text box outside the frame. `text_covers_face` — that box over a face from `qa.people` when `ckpts/pose/yolox_l.onnx` can run on CPU. If the detector cannot run, the face part is skipped and the box is still checked against the frame. No count and no face box are invented.
4. `duplicate_people` — `qa.people` on one frame per scene. More people than the shot's `cast` is a failure. If the detector cannot run, this check is skipped.

`appearance_changed` asks whether the protagonist changes appearance. It stays in `unknown` unless a face-embedding model is already loaded and injected. The review does not download one and must not invent yes or no. Unknown identity does not by itself retake the video.

```json
{
  "review": {
    "verdict": "retake",
    "failures": [{"key": "chorus_one", "question": "frozen_shot"}],
    "unknown": ["appearance_changed"]
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

`unreliable` means the frames could not be read (no finished video yet, or the files are missing). Do not guess a retake. `failures` is empty and `retake_keys` is empty. `unknown` still lists `appearance_changed` when no embedding backend ran.

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

`style` may be only a preset. That stands in for the long image, video, finish and lyric block (about 2k tokens when the prompts are written out). `production.run` expands `style.preset` before it checks the spec. The expansion fills `image`, `video`, `finish`, `lyric_template`, `theme` and `image_model`, plus the other style fields from the production that already rendered that look. A key you set next to `preset` replaces that field. Presets live in `app/shared/style_presets.json` and carry no person or project names: put a footer, a name or a lip-sync rule for one production in the spec (for example `footer`).

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

`shots` may be `"auto"`. The agent then writes lyrics and an optional action phrase per section (`section_actions`, keys `verse` and `chorus`). A verse alternates a sung H3 shot with a still or screen, a chorus is one H3 spanning two lines, the intro and outro are end cards, and fill shots cover any gap longer than two bars.

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

A 60 s video with 5 H3 shots is about 25–35 min of GPU on an RTX 4090; 17 clips of 4–8 s (one take each) took about 60 min of clips, plus 20 minutes of Qwen images and 30 of scene export (CPU, one after another). Two finished Omarchy videos on that card took 74 min (10 H3 shots, no singing) and 154 min (lip-sync retakes). `timing` on `production.status` is where those minutes show up, stage by stage. The agent's side is the spec
(~2–3k tokens, less when `style` is only a `preset`), one `production.run`, and a few `production.status` polls (~300 tokens each). The `review` is already on that status: four checks in code, not a model looking at the sheet. A retake is another `production.run` only when that
verdict says so, using `retake_keys` unchanged. Poll `production.status` with `wait_s` 300 instead of many short polls.

## Things to avoid

- Lyrics the singer cannot sing: keep lines short, one idea per line, and give the song a clear bpm.
- Close-ups for `sing` shots are fine, but extreme close-ups make `qa.lipsync` report `unreliable`
  (the face is not detected); prefer medium close-ups.
- Titles on the right edge of the frame collide with nothing, but keep them off faces: put the
  performer to one side in the `frame` prompt when a shot has a title. The code review checks
  `title_cut_off` and `text_covers_face` for this.
- Do not invent `appearance_changed`. Unknown means stop on that question, not a guessed yes or no. Do not guess a retake when `review.verdict` is `unreliable`.


## Native Video 3D shots

Use explicit `shots` with `kind: "scene3d"`. `scene3d` takes exactly one native
`template` id or a complete Video 3D `document`. A template also needs `subject`
(a workspace GLB URL) or explicit `slots`. The runner uses the existing UI template
factory and document parser; it does not build a separate renderer.

```json
{
  "title": "A moving model",
  "song": {"lyrics": "We move together", "caption": "original synth pop", "duration": 60, "bpm": 120},
  "style": {},
  "shots": [{"key": "orbit", "kind": "scene3d", "t0": 0,
    "scene3d": {"template": "product-orbit", "subject": "/api/v1/file/hero.glb?workspace=movie",
      "motion": {"to": [2, 0, 0], "turnTo": 6.283}, "grounded": true,
      "camera": {"family": "orbit", "orbitRadius": 5}, "atmos": {"timeOfDay": "dawn"}}}]
}
```

Overrides include `camera`, `atmos`, `environment`, `light`, `dressing`,
`pixelWorld`, `width`, `height` and `fps`. `subject` also accepts `clip` (an authored
GLB animation name, or null), `motion`, `position`, `scale`, `rotationY` and
`grounded`. Explicit `slots` use the native Video 3D slot fields. A rigid GLB can
turn, bob or slide without a skeleton. `rotationY` and `motion.turnTo` are radians (6.283 is one full turn). `sing: true` is rejected for these shots;
no H3 lip-sync is implied.

Each export covers its actual cut duration, defaults to 1280×720 at 24 fps, and
uses `scenes.world3d.export` followed by `scenes.world3d.export.receipt`. Durable
intents recover an uncertain admission. A failed or lost export is retried once;
a second failure stops the production without substituting a still or H3 clip.
The exported MP4 enters Video 2D as a video layer for captions/finishing and the
montage adds the song normally. Empty `cast` and all-3D shots request no cast
images, start frames or H3 generation. Both template and full-document shots
are supported in `fill`.

State stores each native document in `clips[key].world3d_document`, the export
receipt identity and a config/duration fingerprint. Resume reuses unchanged
clips; a changed scene or `retake: [key]` exports that shot again. A retake updates
its revision so the following resume keeps the new clip.


### Shared workstation resource gate

An isolated runtime can set `HOCUS_PRODUCTION_MIN_FREE_GB=15` and
`HOCUS_PRODUCTION_EXTERNAL_VRAM_MB=2048` in its process environment. Before each
music/image/H3 or native video export admission, the runner invokes `df -h` and
`nvidia-smi`. It waits in 30-second intervals while another GPU process exceeds
the limit; its own resident model is excluded. A disk shortfall stops the
resumable production with `resource_disk_low`, without deleting files. The agent
must propose a cleanup and wait for the user's approval before resuming.
These opt-in checks leave other instances untouched. They require the named
local commands when enabled; absent commands fail before admission.


### N64-inspired render look

Set `scene3d.renderLook: "n64"` (or `document.renderLook`) to use the native
whole-frame pixel pass at an effective 240-pixel height, 32 color levels per
channel and no bloom/dither. All loaded mesh materials use flat shading and
nearest texture sampling; linear fog starts at 4 m and closes at 28 m in the
background color. Camera motion, model motion and GLB geometry stay fully 3D.
The flag survives scene save/load and applies to both preview and server export.
Removing it restores authored shading, texture filters and atmosphere fog.

### Publish a completed production locally

`production.publish` copies a completed production's MP4, contact sheet and
song into its own immutable publication directory and writes a dedicated HTML
page. It never edits `index.html` or overwrites another publication. Optional
`extras` are artifact basenames in the same workspace (for example GLBs, an
asset contact sheet or the spec JSON). Paths, symlinks and unsupported file
types are rejected. Repeated calls reuse unchanged artifacts; a changed final
creates a new directory.

Configure the **isolated instance** with `HOCUS_PUBLICATION_ROOT` (a dedicated
public folder) and `HOCUS_PUBLICATION_BASE_URL` (the URL serving that folder).
For a new app-owned server also set `HOCUS_PUBLICATION_SERVE=1` and
`HOCUS_PUBLICATION_BIND=0.0.0.0`; the port comes from the base URL, for example
`http://192.168.1.87:8844`. The default bind is loopback. An occupied external
port fails without stopping its server. Leave `HOCUS_PUBLICATION_SERVE` unset
when publishing into an already configured static server's root. Only selected
published files are served; directory listing and symlink escapes are blocked.

```json
{"version":1,"input":{"workspace":"movie","production_id":"music-video",
  "slug":"my-homage","extras":["hero.glb","spec.json"]}}
```

Call the MCP tool `production.publish` with that body. Its result contains
`page`, `video`, `files` (download URLs) and `publication_id`. Publication is CPU
only: it neither re-renders the video nor starts any generation.
