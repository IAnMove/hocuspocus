# Music video from one spec

For agents that drive HocusPocus through MCP. The agent writes one spec (the creative part);
the studio does the rest and decides by numbers what a model used to decide by watching.
One `production.run` calls `audio.analyze`, `generation.music`, `generation.image`,
`scenes.world3d.export` for `scene3d` shots, `scenes.video2d.edit`, `scenes.video2d.export`, `montages.save` and `montages.export`.
Export stays inside that run. Do not also call `montages.export`.
For a 3D singer, put the calibrated `slot.speech` and phonetic cues in the native
`scene3d.document`. Set each voice/intervention's `audible: false`; the montage
owns the song. Mouth cues use `scene time - speech.start + speech.offset`, so set
the offset to the shot's position in the analyzed vocal track. This paints the
built-in 2D mouth on the animated GLB; it does not use H3. Headless exports accept
muted speech and cue-only faces; audible speech still requires the editor's audio
export path. Leave the H3-only `sing` flag unset on these scene3d shots.

The editor, MCP and Ask the Wizard share one CPU lip-sync analysis service.
`audio.mouth_cues` accepts `engine: "auto"` (default), `"phoneme"` or `"rhubarb"`;
auto prefers installed phonemes and reports `fallbackReason` when using Rhubarb.
Wizard `scenes.speech.prepare` uses the same engine, exact `text`, `language`
and optional `isolate_vocals`, preserving face calibration and source-clock cues.
If singing vowels are wrong, use native `audio.phonemes.setup` to inspect or
explicitly install the optional CPU phoneme engine, then `audio.mouth_cues`
with the isolated voice, source window, and exact `dialogue`. It aligns acoustic
phonemes to the transcript and returns source-clock mouth cues plus confidence.
Import these into `slot.speech`, review sustained vowels and low-confidence
phones, and recalibrate the small mouth transition offset. A global advance of
the older Rhubarb track cannot fix a misclassified vowel. See
[Video 3D speech](../development/VIDEO3D_SPEECH.md) for the native contract and limits.
The editor's engine installer and Wizard `speech_analysis_engine` invoke the
same native setup handler; analysis never downloads. The older
`audio.phoneme_cues` remains an explicit-phoneme alias.
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

People use **Music productions** in the sidebar. It lists each `*.production.json` (status, title, duration, montage contact sheet). Opening one shows the rows of `<id>.shots.json`: start frame, clip, lyric, whether it is sung, every take with its r, and the scene. **Open scene** opens that shot's scene in Video 2D. **Another take** is `production.run` with that shot in `retake`; it is disabled while the shot is locked. **Use this take** swaps that take in without a GPU. **Open montage** loads the montage into the Video Editor.

Agents use the same actions as commands:

- `production.shot.use_take` `{workspace, production_id, shot, take_file}` sets that kept take as the shot clip, saves a new scene revision, re-exports only that scene and replaces its montage clip under the same `expected_revision` a repackage uses. The clip origin stays. `take_not_found` when the file is not one of that shot's takes. No GPU.
- `production.shot.update` `{workspace, production_id, shot, lyric_style?, title?, camera?}` stores those fields on `spec.shots[i].overrides` and re-exports only that scene. A `lyric_style` override replaces the global lyric look for that shot. This is the agent path; people use the panel.
- `production.song.use` `{workspace, production_id, candidate}` switches to a candidate kept in `song_candidates` (its id or its file). The switch re-analyses the song, recomputes windows and marks a clip `obsolete` when its audio window moved by more than 0.3 s. It does not delete clip files. Shots whose window stayed put keep their clip. A locked shot whose window would move is `shot_locked` and the current song stays; otherwise the later `production.run` would keep that old take on the new soundtrack.
- `production.cancel` `{workspace, production_id}` asks a live run to stop between rounds. Status becomes `cancelled` (a restart will not treat that as `running` and will not launch a GPU run by itself). The files and the spec stay. A later `production.run` with the same id resumes.

`production.run {workspace, production_id, package: true}` does the packaging for a production made before this existed (no GPU, no export; it saves the scene documents, the manifest and the montage clips' origins). Each document goes through the Video 2D scene validator: `production.status` → `editable.warnings` counts what it flags (text cut off or overlapping, low contrast when it can sample it), listed per shot in the manifest. It does not see everything: `dymo` lyrics used to punch their letters out of black tape and vanished on dark pictures; `dymo` now defaults to dark letters on cream tape (set `lyric_style.box` to choose your own).

## Quality: what the run spends

`quality` in the spec is `draft`, `standard` or `max` (a brief may say `calidad`). It fills only what the spec left out (song seeds: 1 / 3 / 4, `max_takes`: 1 / 2 / 3) and sets the bar `dry_run` measures the plan against: the share of the runtime that may be a still image (60 % / 35 % / 15 %) and the clips a minute (2 / 5 / 7); missing the bar is a `too_static` or `few_clips` warning before any GPU work. No `quality` keeps the spec as written and the `standard` bar. What made the long videos thin was the plan, not a bug: 160 s with 9 clips and `max_takes` 1 is 45 % still pictures and no quality gate. Give a long song more shots, not a slower zoom.

While it runs:

- each clip is judged and saved the moment it lands (a restart mid-round keeps what was already shot), and a better verdict beats a higher lip-sync number (an `unreliable` result never pushes out a take that measured `ok` or `retake`);
- after the start frames, `production.status` gives `frames_sheet` (one labelled picture of every frame): look at it before the clips, where a wrong frame is minutes of GPU per clip;
- a cast entry may be `{"id": "trio", "group": ["hum", "tinker", "zap"]}`: one reference image with their portraits side by side (letterboxed, nothing cropped), for shots with several characters when the image model runs out of memory with three references. `count` defaults to the group's size;
- a shot with one character gets "Only this character appears; no other characters" in its action (the planner does it; write it yourself in a hand-made spec), because a video model invents company otherwise.

## Direction: what happens, and two ways to compile it

An image prompt says how a shot looks; it does not say what happens in the video. `spec.treatment` is the short account the
model writes before any shot: `arc` (what changes from the first image to the last), `want` and `obstacle` (what the
protagonist wants and what stands in the way), `moments` (`[{at, event, id?}]`, the few memorable moments and where they land)
and `motifs` (what comes back). `at` is a section (`chorus`, `chorus2`, `bridge`, `pre-chorus`), `line:N` or, in a trailer, a
beat (`tension`, `reveal`). HocusPocus does not judge the idea; it checks the plan carries it, in `dry_run`:
`moment_without_shot` (a moment lands where no shot is), `moment_unresolved` (the section does not exist),
`chorus_repeats_identical` (a chorus comes back with the same shots: repeating an image is fine, repeating it unchanged is what makes
a clip feel like slides), `treatment_invalid`, and at `quality: "max"` `treatment_missing`. With `shots: "auto"` each moment's event is
written into the action of the shot that covers it, a returning chorus is varied (wider, closer, a consequence, bigger; another
desktop layout or zoom for the native looks) and the automatic pads rotate their camera. A `Pre-Chorus` is now planned as a build
(verse-style shots), not as a second chorus. A `brief` may carry `treatment`/`tratamiento`.

`structure` is `"clip"` (default, unchanged) or `"trailer"`. A trailer is planned on time, not on lyric lines: five beats that share
the duration (presentation 14 %, tension 28 %, escalation 30 %, reveal 16 %, close 12 %), snapped to bars. The quiet beats
hold generated shots of at least 4 s; the escalation is quick cuts that accelerate, made by re-framing clips that already exist
(`kind: "clip"`, a different camera each), so a trailer is a handful of generated shots, not thirty; the reveal is one big shot; the
close carries the end card. No singer. The sound is designed on the CPU (ffmpeg, no model): the song is muted in the bar before the
reveal, a riser climbs through it and ends on the hit, the reveal lands on an impact, and a smaller impact marks the close. The cues go
to the montage as `audioCues` and the soundtrack is the processed file (`<id>-trailer-soundtrack.wav`); anchors are the planned shots'
`t0`. A trailer may be instrumental (`song.lyrics: ""`: the music model gets `[Instrumental]`, nothing is transcribed), and then
`song.late_entry` (seconds) delays the music; a song with lyrics is never shifted because its captions are timed to it.
Use `treatment.moments[].at` with a beat name to say what the reveal or the tension is.

## What the run does

| Step | Tool it uses | Decision made by code |
|---|---|---|
| song | `generation.music` × `song.seeds` (ACE-Step 1.5 XL) | keeps the candidate with the best lyric recall whose last 2 s are not cut; every candidate stays in `song_candidates` |
| analyze | `audio.analyze` | tempo by period × phase search, vocals, word-timed lines |
| cast | `generation.image` (Flux 2 Klein) | one reference sheet per cast member, then a plain full-body portrait of that one person |
| frames | `generation.image` with that portrait as the reference (the sheet if the portrait failed) | one start frame per `h3` shot |
| clips | `generate` MiniMax H3 with the exact song slice as driving audio | `qa.lipsync` on `sing` shots. A shot that is not sung is judged on the picture instead (frozen, blinking, color drift, or a center that no longer matches the first frame) and retakes with a new seed on the same rule: until ok, the score stops rising, `max_takes`, or 4 recorded takes. For those shots `r` is that visual score, not a lip-sync correlation. A file that cannot be opened is unreliable and does not spend another take. The thresholds are provisional until they are measured on the Gremlins v2 clips. Naming the shot in `retake` may shoot it past 4. `clip_seconds` stores each shot's generation seconds (not the backoff, and not in `production.status`). A failed take is logged with its reason (`failures` in `production.status`, e.g. out of GPU memory); when a whole round fails the runner waits 60 s before the next. A resume retries clips that are still missing and still under the cap |
| scenes | `scenes.video2d.edit` + `scenes.video2d.export` | one scene per shot, lyric captions timed to the words, clip trimmed to stay in sync, instrumental gaps longer than a clip filled from `fill` on bar lines |
| montage | `montages.save` + `montages.export` | song as soundtrack, scenes in order |

A start frame that does not arrive is asked for again (a new job, and a smaller picture after an out-of-memory) twice per run; if it still fails the run stops as `failed` with `frames_incomplete` and `production.status` lists `frame_failures`. A cast entry may set `count` (how many distinct subjects that reference image shows, default 1); the frame prompt then says "Exactly N distinct subjects, no duplicated characters", because a sheet with several views makes the model draw the character several times. Each cast member also gets a second portrait, one full-body subject on a plain background (`single_prompt`, or that phrase derived from `sheet_prompt`). Start frames use the portrait instead of the sheet. A group reference is composed from those portraits, not from the sheets. The six-seed check that a one-person frame no longer duplicates the character still needs a GPU pass. After the frames and again after the clips, that declared count is compared with the people in the picture. A group of 4 that comes out as 1 is `subject_count` on `production.status` (`subject_counts`, with the shot, the stage, the expected count and the detected count). The comparison uses the same CPU weights as `qa.people` (`pose/yolox_l.onnx`). When those weights are absent no count is invented. `qa.people` itself returns retake when `max_people` is above or below `expected`. A group reference (several characters in one image) is the way to keep three references under the image model's memory limit.

Packet times of each clip, each exported scene, and the final video are compared on `production.status` as `smoothness`. A held frame, a cadence hitch, or a stretch at another speed is blamed on the clip, the retime, or the export. A file that cannot be read is left out, and the animatic preview is not measured. A steady cadence, even a slow one, is the clip's own rate.

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

`review` is `{execution, technical, artistic}`. `execution` is `ok` when the named final file opens, `fail` when that name is missing or unreadable, and `unreliable` when the run never claimed a final. `technical` is `ok`, `watch`, `fail`, or `unreliable`. Its `failures` are `[{key, question}]`. A smoothness `watch` or `fail` is on `technical` and does not by itself fill `retake_keys`. `artistic` is always `pending`: it lists the contact sheet, the animatic, and up to eight start frames, and it is never an automatic `ok`. `retake_keys` is the shot keys from the technical failures, in scene order, and is passed unchanged as `production.run` `retake`.

A shot may set `allow` to `still`, `dark`, or `secondary`. `still` is not `frozen_shot`. `dark` is not `black_bars`. `secondary` is not `duplicate_people` or `appearance_changed`.

The four code questions:

1. `black_bars` — sampled frames of the final video and of each scene. A letterbox or pillarbox (a thick black edge, not a vignette) is a failure.
2. `frozen_shot` — a shot marked held, including an H3 scene whose picture is a still because the clip was missing, or a scene whose frames barely change.
3. `title_cut_off` — a Video 2D text box outside the frame. `text_covers_face` — that box over a face from `qa.people` when `ckpts/pose/yolox_l.onnx` can run on CPU. If the detector cannot run, the face part is skipped and the box is still checked against the frame. No count and no face box are invented.
4. `duplicate_people` — `qa.people` on one frame per scene. More people than the shot's `cast` is a failure. If the detector cannot run, this check is skipped.

`appearance_changed` asks whether the protagonist changes appearance. It stays in `unknown` unless a face-embedding model is already loaded and injected. The review does not download one and must not invent yes or no. Unknown identity does not by itself retake the video.

```json
{
  "review": {
    "execution": {"verdict": "ok"},
    "technical": {
      "verdict": "fail",
      "failures": [{"key": "chorus_one", "question": "frozen_shot"}],
      "unknown": ["appearance_changed"]
    },
    "artistic": {"verdict": "pending", "evidence": {"contact_sheet": "sheet.jpg", "animatic": null, "frames": []}}
  },
  "retake_keys": ["chorus_one"]
}
```

`technical` `ok` means keep the video (`retake_keys` is empty). `fail` means call `production.run` again with those keys and the same id:

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

For a shared GPU workstation, set `HOCUS_SCENE_RENDER_DEVICE=cpu` in the
owned instance's Pinokio environment before starting it. Native Video 3D and
Video 2D exports then use Chromium SwiftShader with hardware acceleration
disabled and the existing CPU H.264 encoder. Video 3D takes a CPU render lane;
`production.run` still checks disk space but does not wait for GPU memory for
these software exports. Music, image and video generation retain their GPU
guards. The default `auto` keeps the existing hardware discovery. Resolution,
frame rate, document, mouth morph and camera stay part of the same renderer;
software export may take longer. Video 3D capabilities expose `renderDevice`.

Video 3D automatically separates its fallback ground from authored surfaces
by 2 mm and applies a depth bias, including when the projected-floor material
changes. Floor/wall image surfaces receive a stable depth priority in document
order. Preview and export share this protection; it is independent of the N64
look and requires no per-shot adjustment. For a GLB set with its own floor,
`environment.floorStyle: "none"` also removes the redundant fallback ground.
Thickness alone does not fix coplanar top faces. Intersecting or duplicated
faces inside an imported GLB still require correcting that asset's geometry.

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
`pixelWorld`, `rhythm`, `width`, `height` and `fps`. `subject` also accepts `clip` (an authored
GLB animation name, or null), `motion`, `position`, `scale`, `rotationY` and
`grounded`. Explicit `slots` use the native Video 3D slot fields. A rigid GLB can
turn, bob or slide without a skeleton. `rotationY` and `motion.turnTo` are radians (6.283 is one full turn). `sing: true` is rejected for these shots;
no H3 lip-sync is implied.

For a musical performance, set the document's `rhythm` to
`{"bpm":120,"offset":24,"cameraPulse":0.025,"lightPulse":0.3}` and add
`"rhythm":{"beats":1,"phase":0,"bounce":0.12,"sway":0.06,"yaw":0.12,"pulse":0.025}`
to each explicit model slot that should perform. `offset` adds seconds to the
local scene clock: use the shot's song start time minus the detected beat phase
to keep successive cuts on the same grid. `beats` is beats per cycle; `phase`
is a cycle offset. Bounce/sway are meters, yaw is radians and pulse is a scale
fraction. Actors can use different phases and speeds while sharing the song.
The camera makes a small dolly pulse and light brightens at each downbeat;
neither replaces the authored camera/travel. Everything is sampled from time,
so preview, export and backward seeking agree without an audio model or rig.
This is rigid performance, not skeletal dancing or lip-sync. Invalid rhythm
values fail native document import rather than entering the renderer.

Each export covers its actual cut duration, defaults to 1280×720 at 24 fps, and
uses `scenes.world3d.export` followed by `scenes.world3d.export.receipt`. Durable
intents recover an uncertain admission. A failed or lost export is retried once;
a second failure stops the production without substituting a still or H3 clip.
The receipt's `geometry` lists warnings found before the frames: characters
under the floor or floating, bodies through props, the camera inside a model,
characters out of frame. They never block the export; read them before
publishing (see `docs/development/VIDEO3D_GEOMETRY_CHECKS.md`).
The exported MP4 enters Video 2D as a video layer for captions/finishing and the
montage adds the song normally. Empty `cast` and all-3D shots request no cast
images, start frames or H3 generation. Both template and full-document shots
are supported in `fill`.

Cuts containing native 3D use the montage's 24 fps grid: round each absolute
boundary to its nearest frame, then subtract boundaries for each shot's length.
The native export, Video 2D wrapper and montage share those lengths. Rounding
every length independently would accumulate lip/audio drift over many cuts.
When authoring muted speech against source-clock cues, set `speech.offset` to
the source position at that actual frame-aligned start; account for the returned
`time_map` when `audio.shorten` has repeated or crossfaded the song.

State stores each native document in `clips[key].world3d_document`, the export
receipt identity and a config/duration fingerprint. Resume reuses unchanged
clips; a changed scene or `retake: [key]` exports that shot again. A locked clip
is not rebuilt, and an explicit retake of it is `shot_locked` before its revision
changes. A retake updates its revision so the following resume keeps the new clip.


### Shared workstation resource gate

An isolated runtime can set `HOCUS_PRODUCTION_MIN_FREE_GB=15` and
`HOCUS_PRODUCTION_EXTERNAL_VRAM_MB=2048` in its process environment. Before each
music/image/speech/SFX/H3 or native video export admission, the runner invokes `df -h` and
`nvidia-smi`. It waits in 30-second intervals while another GPU process exceeds
the limit; its own resident model is excluded. A disk shortfall stops the
resumable production with `resource_disk_low`, without deleting files. The agent
must propose a cleanup and wait for the user's approval before resuming.
These opt-in checks leave other instances untouched. They require the named
local commands when enabled; absent commands fail before admission.

Series Lab's native renderer applies the same checks to each speech and export
call in `series.episode.render_native` and the render stage of
`series.episode.produce`. The UI, MCP and wizard share that renderer. Disk is
measured on the episode workspace, including every speech retry. Status polling
and CPU speech checks do not wait for the GPU. CPU video exports check disk
without waiting for an unrelated GPU generation.


### Rig an existing model through MCP

Import accepted GLBs with `assets.upload` using `filename` and `data_base64`
(up to 8 MB), just like other workspace assets. For larger media already in
the app's uploads root, use `input: {workspace, source, copy_to_workspace: true}`
to import a copy up to 500 MB; the original remains intact. The returned
workspace URL can be used directly by Video 3D. Omitting the copy flag retains
the existing reference-only behavior; image/audio tools still reject GLB refs.

Use `model3d.rig` with `{version: 1, intent_id, input: {workspace,
source: "hero.glb", engine: "unirig", rig_profile: "humanoid",
animations: ["idle", "walk"], seed: 64}}`. Poll `model3d.rig.status` with
`{version: 1, input: {workspace, job_id}}`. These commands wrap the native
`/api/v1/rig/generate` and `/api/v1/rig/status/{job_id}` contracts; they reuse
the scheduler, short-lived workers and workspace publication. A retry with
the same intent/body replays the original admission; a changed body conflicts.
The source stays intact and the result is a new GLB with exact clip names.

Install UniRig from HocusPocus's Advanced menu using `rigging_install.js`.
`GET /api/v1/rig/capabilities` reports installation before any generation.
UniRig predicts joints and skin weights. With `rig_profile: "humanoid"`, the
`idle`, `walk` and `wobble` clips resolve recognizable upright Y-up pelvis,
torso and limb branches and rotate both arms and legs around their bind pose.
They preserve source geometry, skin weights and textures, without scale or
whole-body bounce channels. Optional `animation_bpm` (60–180, default 120)
sets the walk/dance loop tempo. Inspect an exported pilot: generated skinning
can still deform poorly and these loops do not provide foot-contact IK.
Results expose `animation_mode`, `humanoid_joints`, `articulated_clips` and
`animation_warnings`. Unrecognized topology and other clip IDs explicitly
report body-chain fallback. `engine: "procedural"` remains CPU-only and
constructs an approximate single chain rather than an anatomical rig.

For a character standing in a T or A pose, prefer `engine: "humanoid"`: it is
CPU-only (about a second), fits a Mixamo-named skeleton, bakes clips such as
`idle`, `walk`, `wave`, `talk` or `dance_side` for that body with the feet on
the floor, and refuses arms-down or legs-together meshes with `not_humanoid`
and a reason instead of rigging them badly. Add clips or a BVH/glTF animation
later with `model3d.animate`. See the [humanoid rig guide](HUMANOID_RIG.md).

### N64-inspired render look

Set `scene3d.renderLook: "n64"` (or `document.renderLook`) to use the native
whole-frame pixel pass at an effective 240-pixel height, 32 color levels per
channel and no bloom/dither. All loaded mesh materials use flat shading and
nearest texture sampling; linear fog starts at 4 m and closes at 28 m in the
background color. Camera motion, model motion and GLB geometry stay fully 3D.
The flag survives scene save/load and applies to both preview and server export.
Removing it restores authored shading, texture filters and atmosphere fog.

### Toon / cel render look

Set `scene3d.renderLook: "toon"` (or `document.renderLook`, or `renderLook` in
`world3d.scene.patch`) to draw 3D model slots as cels: flat light bands and an
ink outline, so GLB characters, vehicles and props match flat anime cutouts and
painted backgrounds. Image slots and cutouts are not changed. Optional
`toon: {"steps": 2-4, "outline": 0-8, "ink": "#rrggbb"}` sets the number of
light bands (default 3), the ink width in pixels of a 1080p frame (default 3;
0 draws no line) and the ink colour (default `#141018`). Rigged models keep
their clips: the outline follows the skeleton. Transparent and alpha-cut
materials get no ink, and a materializing model gets its ink once it has
arrived. Preview and export match. `renderLook: "none"` in a patch returns to
the authored materials and keeps the `toon` settings. An unknown look or an
out-of-range toon value is refused (`invalid_render_look`).

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

## Phase close 2026-09-30

`production.status` accepts `wait_s` up to 1200 and `until` of `change` (default), `stage`, or `done`. `done` returns immediately when the production is already `completed`, `failed`, or `cancelled`. A client poll of `wait_s` 300 is still a safe interval. The reply includes `waited_s` and `progress`: `stage`, clips `landed`/`total`/`eta_s`, and scenes `done`/`total`/`eta_s`. `eta_s` is 0 when nothing remains, a median of this run or of `<workspace>/.production-timings.json` when that file has samples, and null when it does not. It is not a guessed number.

`production.plan` dry-run `estimate_source` is `history(n)` or `defaults`. When `spec.enhance.method` is `flashvsr` or `rife` and history exists, the source is `history(n)+default_enhance`. The extra minute per clip is a labeled default, not a measurement. The no-history formula stays seeds × 2 + H3 clips × 5 + 1.

`usage` also reports `gpu_seconds` (song, frames, clips), `cpu_seconds` (scenes, montage, package), `retry_seconds` (the share of clip seconds that belongs to takes after the first), and `reused_seconds` (clip seconds kept from before this run, except keys in the latest retake). These are still not LLM tokens.

`spec.resolution.frames` may be `1280x704`, `1152x640`, `1024x576`, `1536x1024`, or `1024x1536`. `spec.resolution.clips` may be `1280x704`, `1152x640`, or `1024x576`. Unset stays `1280x704`. Scene export is 1920×1080 with fit fill. The dry-run `resolution.crop` is `none`, `horizontal`, or `vertical`. `spec.enhance` is method `flashvsr` or `rife` and scale 2 or 4. Without an injected upscaler the run logs `enhance planned, not run`. RIFE is only a recommendation (`rife_recommended`) when packet-time smoothness already failed. It does not run. SSIM and GPU minutes for enhance were not measured.

`timing.shots` adds `s_per_step`, `degraded`, and `model` only when the H3 job returned a performance object. Missing fields are null. A job without that object adds nothing.

`production.shot.review` records `pending`, `approved`, or `changes_requested` in `<id>.review.json`, not in the production file. `production.shot.lock` sets `locked`. Locked shots are omitted from `frames()` and `clips()`, including a named retake, until unlock. `scenes()` keeps them in the cut and skips re-export only when that scene file already exists, so a lock before the first export, or after a failed one, still writes the file. A retake of another shot does not drop or stretch the locked one. An explicit retake of a locked shot, or a run while a locked clip is still marked `obsolete` after `production.song.use`, is `shot_locked` before the run sets `status` to `running`, so a completed production stays completed. `production.shot.redo` on a locked shot returns `shot_locked` and changes nothing. `production.shot.undo` restores one shot. A locked shot is `shot_locked` and the cut stays. Undo does not delete files. `production.shot.request` validates a closed plan. With no plan and no configured language model it is `llm_unavailable` and does not invent a plan. `apply` true with the previewed plan validates and runs that closed object; the LLM is not asked again. The REST request route validates and returns `applied: false` when apply is not true.

`production.publish` refuses a completed production whose spec lists shot keys until each key is `approved` in the review file (`review_incomplete`). A spec with no shot list is unchanged. Artistic review stays `pending` without a human file. A human file may set `approved` or `changes_requested`. It is never the string ok.

To let someone watch the completed cut before approving it, call `production.publish` with `input.mode: "preview"` (default: `"release"`). The preview has its own immutable page, prominently labelled **Review preview · Not approved for release**, and returns `mode: "preview"`. It copies the MP4, song and contact sheet through the same native publication path and never writes or changes a human review. A preview and a release have different publication identities even for the same media. Release publication still requires every shot to be approved; previews also require a completed production. Use a unique `slug` and the configured LAN root as usual; neither mode edits `index.html`.

`face_consistent` is the human sheet question on `production.review`. No vision model means that answer stays unreliable, and the sheet must not invent yes or no. `appearance_changed` is the separate code check. It stays unknown unless an embedding backend was injected. The field `face_consistent` stays.

Scene export and the contact-sheet painter share `HOCUS_SCENE_EXPORT_CONCURRENCY`. Unset or blank is one painter per six cores, from 2 to 6 (5 on 32 cores). A value outside 1–8 is 1. Painters bind `127.0.0.1:0`. This change does not claim a measured speedup for 21 scenes.

Qwen is already unloaded before the next model by `generation_memory.py`. The live 17-frame Qwen-to-H3 seconds-per-step table was not measured. Do not add a second unloader.

Queue and memory settings (2026-10-04):

- `HOCUS_QUEUE_MAX_WAIT_SECONDS` (default 300). A generation job that has waited this long is overtaken only by a higher `priority`. `0` turns it off. `tools/list` shows `priority` on every `generation.*` tool.
- `HOCUS_GPU_WAITER_MAX_WAIT_SECONDS` (default 120). A Video 3D export, or another coordinator ticket on the local GPU, gets the next turn when it has waited longer than the generation queue head, or this long. `0` turns it off.
- `HOCUS_MALLOC_TRIM` (default on). Freed model memory goes back to the system after a model release and after each GPU job. `0` turns it off. Large releases are logged as `[Memory] Returned … GiB`.
- `app/settings/server-endpoint.json` holds the bound `url`, `mcp_url` and `pid` while the server runs. Check `pid` before you trust it.
- After a restart, `jobs.leftovers` also lists interrupted Video 2D/3D exports. Use `jobs.resume` to retry the same task and `jobs.discard` to cancel it.

How to add a style preset: add an entry to `app/shared/style_presets.json`. Do not put a person or project name in it. Set `style.preset` to that id. Add the id to `PRESET_IDS` in `app/services/production_style_presets.py` only when that preset needs a check beyond filling the style fields.

`music_production.py` is 688 lines. Shot windows live in `production_windows.py`. Cast, frames and the look preview live in `production_stage_frames.py`. Clip jobs live in `production_stage_clips.py`. Scenes, the package, the montage and the animatic live in `production_stage_scenes.py`. The run body lives in `production_stage_run.py`. `Production` still owns those methods and calls the modules. Wait stays at 1200 seconds with `until`. Resolution helpers, shot lock, planned enhance, and the 5 second save gate stay. The older 669-line cut was not reused.

Six portrait seeds and the gremlins-devday-v2 before/after were not measured.

## Project link before `production.run`

The producer registers ownership automatically before its worker. Call
`POST /api/v1/production-projects/resolve` to prepare an intention before
`production.run`, or send an explicit `project` to the producer. Send `workspace`,
`origin` (`mcp`, `wizard`, or `ui`), `intent_id`, and either `format`
(`music_video`, `trailer`, `quick_video`, `full_story`) or `project`
(`{kind: story|episode, id}`). The same `intent_id` returns the same
`production_id`. Pass that id to `production.run`. Do not read the browser's
active Story. An unknown project id fails with `invalid_project` and creates
nothing. `new_execution: true` starts another production on the same project.
The contract and the coverage matrix are in
`docs/development/UNIFIED_PRODUCTIONS.md`. LLM token counts for this link are
not available from the client.

## Read the shots

`GET /api/v1/production-projects/{production_id}/shots?workspace=` returns the
shots already stored for that production. It does not render, retake, or mark
an export stale. A missing manifest returns an empty shot list and
`no_shots`. The UI listens for `hocuspocus:production-shots-open`. Choosing a
take and publishing stay on the existing review commands.

## Update one shot from the shared view

`POST /api/v1/production-projects/{production_id}/shots/{shot_id}` with
`action` `select`, `review`, `lock`, `undo`, or `reexport`. Send
`expected_revision` from the GET for select, undo, and reexport. A locked shot
returns `shot_locked` and does not write. A stale `expected_revision` returns
`stale_revision`. `request` returns `applied: false` until `apply` is true,
and then it runs only the `plan` object you send. `regenerate` with `expected_revision` returns `applied: false` and an execution
target in `regeneration`. Execute that existing producer operation once; the
shared UI does so automatically and marks review pending only after success. This path does not
delete take files.

## List works and open the shared view

`POST /api/v1/production-projects/commands` with `version` 1 and
`input.workspace`. `production.works.list` returns `applied: false` and one
row per production id in that workspace. `production.works.open` returns the
same review event the UI listens for: `hocuspocus:production-shots-open`.
`production.works.resolve` is the existing link call. A repeated `intent_id`
sets `reused: true` and does not create another Story. An episode project
does not create a Story. Do not describe `applied: false` as a new cut.

## Link an old production

`production.works.link` needs `production_id` and `project` `{kind, id}` for a
Story or episode that already exists. It does not create a project and it does
not match a title. A second call with the same pair returns `reused: true`.
The production file and its takes stay where they are. A missing sidecar still
lists the file as unlinked. An unreadable production file is a warning, not a
new project.

## Producers link before the worker

`production.run` binds the given `production_id` after the slot is free and
before it starts the thread. The same id returns the same Story. Pass
`project: {kind, id}` only when that Story or episode already exists; an
unknown id is HTTP 422 and the thread does not start. A concurrent shot or
song edit is HTTP 409 and does not rewrite the production file. `dry_run`
does not create a project.

Director `start_pipeline` binds its canonical production id before the worker.
An existing `project` or `provenance.project_id` is validated and reused.

Series episode render binds that episode after the request is accepted and
before the episode is marked `rendering` or the queue is persisted. A refused
render does not create a project. A failed bind does not leave a queued job
without a worker. The link does not create a Story, records the id in the
episode's `productionIds`, and does not rewrite the series library on the
bind itself. Tokens for this link are not available from the client.

## Shared regeneration and registration completion

Direct music, Director and Series starts persist ownership before work starts.
Director saves its canonical production id and project in the snapshot; a
failed initial save refuses generation. Series stores the production id in its
episode before generated-video workers or native 2D batch media operations.
Native 3D Series and imported shots without a generator stay unsupported.

Shared HTTP regeneration rechecks lock, revision and exact shot at the producer
endpoint. Music refreshes only the target manifest row and marks its export
stale without replacing the montage. Failed or occupied operations are errors,
not successful takes. Keep the previous take and do not retry automatically.

`cd ui && npm run test:e2e:production` verifies this journey with real Chromium,
real registration/review HTTP and simulated media generation. It requires only
the CPU packages in `scripts/ci-production-browser-requirements.txt`, downloads
no models and uses isolated test ports. It does not assess visual quality.

## Flat rigs for full-body cel characters

`characters.rig.flat` also checks small cream-coloured eyes inside warm-toned
face regions when its large white-eye detector finds fewer than two eyes.
This fallback joins sclera fragments around the pupil and excludes goggles
above the face and bright body props. Painted-mouth selection requires a
horizontal seed wide enough for the face, so a short nose stroke is preserved.
Review every pose's mouth and blink before production; an unsupported face or
an ambiguous result still needs a regenerated pose.

## Comic film PRE after a restart

A comic PRE that was ready before the lab stopped is still ready afterwards.
Opening it restores the saved approval and does not start the film. The output
size is the canvas chosen in the comic video controls, including an H3 720p
canvas of 1280×704. A deterministic render that fails reports the end of the
ffmpeg log and keeps the full log on the pipeline. Accepting a reviewed test
clip records the person who requested that acceptance, the channel, and the
attestation note. The review checkbox is not filled in by playback.

## Native Series requires acoustic mouth cues

Native Series analyses each recorded line with `audio.mouth_cues` and
`engine: "auto"`: the shared CPU phoneme engine when it is installed, Rhubarb
otherwise. If analysis fails or returns no cues, rendering stops before
building the scene; it does not silently replace audio alignment with text
rhythm. Each line in `series.episode.render_native.status` reports its
`engine`, its `cueCount` and, when Rhubarb drew it, `fallbackReason:
phoneme_not_installed`. For sung or vowel-heavy lines install the phoneme
engine with `audio.phonemes.setup` and resume the job: recorded voices are
reused. Inspect `cueCount` before approving the visual result.

## Publishing a reviewed take with an exact resource name

A script can retain its original resource names after an audio or image retake.
Use `assets.upload` with `source`, `copy_to_workspace: true` and
`destination_filename` in the same workspace. The extension must match the
source. To replace an existing resource, supply its current
`expected_destination_sha256`; a stale or missing hash returns
`destination_conflict` without replacing it. Reuse the same `intent_id` on a
transport retry. The source remains available, bytes are copied without media
conversion, and a generation sidecar retains provenance with the destination
asset name. Only a sidecar that names the source is copied: `clip.meta.json`
written for `clip.mp4` is not the metadata of `clip.wav`. Sidecars are keyed by
the name before the extension, so a destination that would share one with
another output (`song.wav` beside `song.png`) returns `sidecar_conflict` and
nothing is written when that sidecar holds the other output's metadata or the
copy would create it; choose another name. This is a CPU
operation and downloads no models.
