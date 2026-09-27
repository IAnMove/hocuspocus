# Editable montages and server-side Video 2D export

A finished videoclip should stay editable block by block inside HocusPocus. This
guide covers the three pieces that make that possible:

1. **Montages** (`<name>.montage.json`): a Video Editor timeline saved in the
   workspace, with timed **overlays** (captions/titles as images) and **audio
   cues** (voice-over, stingers) kept as separate, editable layers.
2. **Scene documents**: Video 2D (`*.scene.json`) and Video 3D
   (`*.world3d.scene.json`) scenes saved as immutable revisions, so every shot
   opens in its own editor.
3. **`scenes.video2d.export`**: renders a Video 2D scene to MP4 on the server
   with the Scene Animator's own evaluator and painter (headless Chromium, CPU
   lane), like `scenes.world3d.export` does for Video 3D.

Typical agent flow: compose scenes → `scenes.document.save` →
`scenes.video2d.export` / `scenes.world3d.export` (or generate clips) →
`montages.save` with the clips, song, caption images and narration →
`montages.export`. A person can open the same montage in **Video Editor →
Montages**, move a caption, retime a voice line or swap a clip, save a new
revision and export again.

Code: `app/services/montage_documents.py`, `app/services/montage_commands.py`,
`app/services/video_editor_layers.py`, `app/services/scene_documents.py`,
`app/services/scene2d_export.py`, `ui/src/lib/scene2d/`,
`ui/src/features/scene2d/ownedRenderer.ts`, `ui/scene2d-render.html`,
`ui/src/features/video-editor/MontageControls.tsx`.

---

## 1. Montage document (version 1)

```json
{
  "version": 1, "name": "The Bird Is Freed", "width": 1920, "height": 1080, "fps": 24,
  "clips": [
    {"id": "c1", "source": "shot01.mp4", "trimStart": 0, "trimEnd": 4.2,
     "transition": "crossfade", "transitionDuration": 0.4,
     "origin": {"kind": "scene2d", "scene": "Intro-3f2a.scene.json"}}
  ],
  "soundtrack": {"source": "song.wav", "volume": 1, "loop": false},
  "overlays": [
    {"id": "title", "source": "cap/t_open.png", "start": 0.6, "end": 6.5,
     "x": 50, "y": 50, "width": 100, "opacity": 1, "fadeIn": 1.2, "fadeOut": 1.2}
  ],
  "audioCues": [{"id": "vo1", "source": "vo01.wav", "start": 0.8, "volume": 1.6}],
  "duck": 0.5
}
```

| Field | Rules |
|---|---|
| `clips` | 1–100. `source` is a workspace/upload reference (`name.mp4` or `/api/v1/file/...`). `trimEnd: 0` means full clip. `origin` is provenance only (`scene2d`, `scene3d`, `generation`, `upload`, `render`). |
| `overlays` | ≤200 PNG/JPEG/WebP images. `x`/`y` = centre in % of the frame, `width` = % of frame width, alpha fades in/out. Burned after assembly; clipped to the video. |
| `audioCues` | ≤64 audio files placed at `start` s with `volume` 0–2 and optional `trimStart`/`trimEnd`. |
| `duck` | 0–1. While a cue plays, clip audio + soundtrack are sidechain-compressed (`ratio = 1 + 9·duck`). |

Blob, file, `data:` and `javascript:` URLs are rejected: montages only reference
durable workspace media. The store adds `revision` and `updatedAt`.

**Revisions.** `montages.save` creates `<slug>.montage.json`; saving the same
name again fails with `409 exists`. To update pass `file` and
`expected_revision` (compare-and-swap, `409 revision_conflict` when stale).

## 2. Video Editor

Toolbar **Montages** lists the workspace montages and opens one (clips and the
soundtrack are probed again, so missing media is reported immediately).
**Save montage** writes the current timeline, soundtrack and timed layers
(first save creates the file, later saves are new revisions). The collapsible
**Timed layers** bar lists captions and audio cues with editable start/end/volume
and a duck slider. Exports include them; the export sidecar records `layers`.

`POST /api/v1/video-editor/export` accepts the same layers directly:
`overlays[]` (`fade_in`/`fade_out`), `audio_cues[]` (`trim_start`/`trim_end`)
and `duck`.

## 3. HTTP and MCP

| Operation (MCP) | HTTP |
|---|---|
| `montages.list` | `GET /api/v1/montages?workspace=` |
| `montages.get` | `GET /api/v1/montages/{file}?workspace=` |
| `montages.save` | `POST /api/v1/montages` `{workspace, montage, file?, expected_revision?}` |
| `montages.export` | `POST /api/v1/montages/{file}/export?workspace=` → Video Editor job |
| `montages.export.status` | `GET /api/v1/video-editor/export/{job_id}` |
| `montages.shots.get`, `montages.shot.regenerate`, `montages.shot.select` | see §5 |
| `scenes.document.save` / `.get` | — (MCP; the UI keeps its existing save routes) |
| `scenes.video2d.export` (+ `.receipt`, `.cancel`) | `POST /api/v1/scenes/video2d/export`, `GET .../receipt`, `POST .../cancel`, `GET .../capabilities` |

MCP input envelopes follow the other versioned commands:
`{"version": 1, "input": {...}}`; `scenes.video2d.export` also requires
`intent_id` (reuse it only to recover the receipt).

## 4. Video 2D export limits

* Layer types: `image`, `video`, `overlay`, `effect` (atmosphere), `camera`.
  `model3d` layers are rejected (render those shots in Video 3D).
* Media must be `/api/v1/file/...`, `/api/v1/uploads/...`, `/examples/...` or
  inline `data:image/...`; remote URLs are never fetched.
* `fps` ∈ {24, 30, 60}; duration ≤ 600 s; output ≤ 1920×1080 (or 1080×1920).
* `audioTracks` (real workspace audio files with `startTime`/`volume`) are mixed
  into the MP4. Screen-FX `sound: true` cues are synthesized in the headless
  page with `OfflineAudioContext` (`mixFxAudio` + `sceneAudioWav`) and mixed
  from `staging/fx.wav` before the audio tracks. `sound: true` with `volume: 0`
  stays silent and does not write a WAV.
* Image layers may also reference `sequence.sources` or `sequence.source`.
  Those URLs follow the same durable-media rules. `blob:` and remote URLs are
  refused when the scene is saved or exported.
* `scene.rhythm` is the live beat grid stored on the document. Baking keyframes
  with `applySceneRhythmToLayer` is the older path: it rewrites the layer and
  does not keep a beat envelope. Live `beatPulse` reads the stored grid at
  paint time, so a headless export does not need a new server-side analysis.
* Requires the built UI (`ui/dist/scene2d-render.html`) and Playwright
  Chromium; `capabilities.realRender` reports `pending` otherwise.
* Rendering takes the `local_cpu:scene2d-render` lane, never the GPU lane.

The Scene Animator, its browser export and the headless renderer share
`ui/src/lib/scene2d/{normalize,evaluate,layerStyle,paint}.ts`, so a scene looks
the same in the editor and in the server export.

## 5. Shot board (plano a plano)

With a montage open, **Video Editor → Shot board** lists every clip with its
slot on the timeline and where it came from. For generated clips the board
reads the generation sidecar (`<clip>.meta.json`, or the file a slowed copy was
derived from): model, prompt, seed and start image. Nothing needs migrating.

* **Regenerate shot** queues a new take with the same parameters (optionally a
  new prompt or seed) on the normal generation queue and stores it as a
  `pending` take. The clip keeps its media meanwhile.
* When the generation finishes the take resolves from the workspace (by job id
  in the sidecar, so it survives a server restart). **Use** swaps the clip media,
  keeps the previous media as a take and slows a shorter take to cover the slot.
  Export again to get the new video.
* Clips from Video 2D/3D scenes show their scene; re-render them from their editor.

| Operation (MCP) | HTTP |
|---|---|
| `montages.shots.get` | `GET /api/v1/montages/{file}/shots?workspace=` |
| `montages.shot.regenerate` `{clip_id, intent_id, expected_revision, prompt?, seed?}` | `POST /api/v1/montages/{file}/shots/{clip_id}/regenerate` |
| `montages.shot.select` `{clip_id, take_id, expected_revision, retime?}` | `POST /api/v1/montages/{file}/shots/{clip_id}/select` |

Clips may also carry `takes[]` (≤20: `{id, source, origin?}` or `{id, pending:{jobId}}`)
and a `lyric`; `origin` accepts `meta`, `derivedFrom` and `production`
(`productionId`, `shotId`, `takeId`). Editor saves keep them.

## 6. Planned next steps

* Rest of the shot board (Story Lab and Director links, out-of-date export
  warning): [MONTAGE_SHOT_BOARD_PLAN](../development/MONTAGE_SHOT_BOARD_PLAN.md).
* Video 2D text, lyrics, finishing and templates:
  [GROK_VIDEO2D_BOOST_PLAN_2026-09-27](../development/GROK_VIDEO2D_BOOST_PLAN_2026-09-27.md).
