# Music video in three MCP calls

For agents that drive HocusPocus through MCP. The agent writes one spec (the creative part);
the studio does the rest and decides by numbers what a model used to decide by watching.

```text
production.run      {workspace, production_id, spec}   → starts in the background, returns at once
production.status   {workspace, production_id}         → short summary; poll until completed or failed
(look at contact_sheet once; fix the spec and call production.run again with the same id to resume)
production.run       {workspace, production_id, retake:["key"]} → shoot those clips again (new seeds, better take kept);
                                                     only the scenes whose clip changed are re-exported
production.run       {workspace, production_id, preview:{prompts:[p1,p2,p3], image_model:"qwen_image_21"}}
                    → generate three look tests without making a song; URLs appear in production.status.preview_frames
production.run       {workspace, production_id, spec, through:"frames"}
                    → stop after cast and frames; restart the isolated runtime if a large image model would slow H3,
                      then resume with production.run {workspace, production_id}
```

Do not call `tools/list` or `models` to plan a production: everything the run needs is here.
Do not read the song, clips or scenes yourself: `production.status` reports lip-sync verdicts,
the video URL and a contact-sheet URL. Open the contact sheet as an image once at the end.

## What the run does

| Step | Tool it uses | Decision made by code |
|---|---|---|
| song | `generation.music` × `song.seeds` (ACE-Step 1.5 XL) | keeps the candidate with the best lyric recall whose last 2 s are not cut |
| analyze | `audio.analyze` | tempo by period × phase search, vocals, word-timed lines |
| cast | `generation.image` (Flux 2 Klein) | one reference sheet per cast member |
| frames | `generation.image` with the cast sheets as references | one start frame per `h3` shot |
| clips | `generate` MiniMax H3 with the exact song slice as driving audio | `qa.lipsync` on `sing` shots; retake with a new seed until ok or `max_takes`. A failed take is logged with its reason (`failures` in `production.status`, e.g. out of GPU memory); when a whole round fails the runner waits 60 s before the next. A resume retries clips that are still missing |
| scenes | `scenes.video2d.edit` + `scenes.video2d.export` | one scene per shot, lyric captions timed to the words, clip trimmed to stay in sync, instrumental gaps longer than a clip filled from `fill` on bar lines |
| montage | `montages.save` + `montages.export` | song as soundtrack, scenes in order |

State is saved in `<workspace>/<production_id>.production.json`: a restart or a new
`production.run` with the same id continues from the last finished step.

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

Shot fields:

- `kind`: `h3` (generated clip), `still` (image from `stills` or a URL), `clip` (reuse an `h3` shot's clip, for `fill`).
- Timing: `line` (index of a lyric line; the shot starts 0.25 s before it and spans `span` lines), `t0` (seconds) or `after` (starts 0.3 s after that line ends). Shots are cut at the next shot's start.
- `h3`: `frame` (start-frame prompt), `action` (what moves; use `(S1)` for the singer), `sing: true` for lip-sync, `cast` ids used as image references.
- `still`: `focus` {x, y} (percent of the image kept centred while zooming), `zoom` [start, end], `camera` preset.
- `title`: a text template (`lower-third-date`, `end-card`, `title-card`, …) with its fields. Lyric captions are added automatically.
- `graphic`: a drawing from `app/shared/scene_graphics.json` attached to the first title cue, for example `{"id":"shatter","params":{"pieces":12}}`.

Style fields for native Video 2D finishing:

- `image_model` chooses the Studio image model for cast and frames (default `flux2_klein_9b`; `qwen_image_21` is useful for a recognizable public-person caricature). `image_steps` sets its step count; individual cast members or H3 shots may override either field.
- `finish` accepts the same `set_finish` values as Video 2D, including `{"preset":"risoPress"}`. Riso automatically traps text on the black plate.
- `lyric_template` may be `ransom` or `dymo` as well as `social-caption`. `title_style` and `lyric_style` are Video 2D text patches, for example `{"font":"mono","color":"#A9B1D6"}`.
- `footer` adds a persistent small-print line to every scene. `footer_style` can set its color, font and background through the Video 2D text patch fields.

## Cost

A 60 s video with 5 H3 shots is about 25–35 min of GPU on an RTX 4090. The agent's side is the spec
(~2–3k tokens), one `production.run`, a few `production.status` polls (~300 tokens each) and one
contact-sheet image. Poll with a pause of 60 s or more; nothing is lost by polling slowly.

## Things to avoid

- Lyrics the singer cannot sing: keep lines short, one idea per line, and give the song a clear bpm.
- Close-ups for `sing` shots are fine, but extreme close-ups make `qa.lipsync` report `unreliable`
  (the face is not detected); prefer medium close-ups.
- Titles on the right edge of the frame collide with nothing, but keep them off faces: put the
  performer to one side in the `frame` prompt when a shot has a title.
