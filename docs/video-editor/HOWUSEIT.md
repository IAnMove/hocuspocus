# HOWUSEIT — Video Editor and assembled mixes

Operator guide for Loreframe Lab’s FFmpeg cut tool and the gallery tabs that list **assembled** Director / Series joins.

This is not MiniMax H3 and not the 3D compositor. The editor **never regenerates pixels**; it probes, trims, transitions, and exports existing files. Director auto-joins and `POST /api/v1/outputs/rejoin` are a separate mix path (soft freeze + crossfade).

UI tab: **Video Editor** (`mediaFilter: videoeditor`). Code: `ui/src/features/video-editor/`. Render: `app/services/video_editor.py`. HTTP: `app/_launch_runtime.py`. Mix kinds: `app/services/output_result_kind.py`.

Related: [3D Video compositor](../3d-video-compositor/HOWUSEIT.md) §5.8, [Workspaces / Director threads](../workspaces/HOWUSEIT.md).

---

## 1. What this system is

| Tool | Tab | Job |
|---|---|---|
| Video Editor | **Video Editor** | Import Lab/local clips, trim, reorder, play/scrub, export one MP4 |
| Gallery mix tabs | **Videoclips / Tráilers / Capítulos / Multi-clip** | Filter assembled joins by `result_kind` |
| Director / Series rejoin | Productions / Series Assembly | Concatenate generated shots; write `result_kind` |

Use the editor when you need an **editable cut** (trim, split, time cards, letterbox). Use Director/Series rejoin when you want the **pipeline’s assembled movie** with the standard 0.5 s freeze + ~0.4 s crossfade. Video Editor exports are **not** tagged as mix kinds.

---

## 2. Hard limits

1. **1–100 clips** per export. Resolution 240–3840, even width/height. FPS ∈ `{24, 25, 30, 50, 60}`.
2. **Sources** must be `.mp4`, `.webm`, `.mov`, `.mkv`, `.avi`, or `.m4v` inside a permitted workspace/uploads path.
3. **Strip `?workspace=`** before probe/export. Gallery URLs look like `/api/v1/file/clip.mp4?workspace=default`. The filename-with-query does not exist on disk. UI helper: `editorSourcePath()` in `ui/src/features/video-editor/editorHandoff.ts`. Server helper: `parse_media_ref()` in `app/services/media_refs.py`.
4. **Min trim / split span is 0.05 s.** Transition duration 0.05–5 s. Time-card text size 50–160. Time-card copy is normalised to max 240 characters.
5. **Timeline edit is UI-only.** Drafts live in `localStorage` key `maestro-video-editor-draft-v1`. The server only sees probe, thumbnail, screenshot, and export.
6. **Cancel is deferred.** `POST .../export/{job_id}/cancel` waits until the current FFmpeg subprocess finishes (`cancel_mode: deferred`, `safe_boundary: after_current_ffmpeg_render`).
7. **Upload cap is 500 MB** (`POST /api/v1/upload`).
8. **Mix soft-join is skipped** when an external driving audio file is supplied to `concatenate_multi_clip_videos`. Failure falls back to a hard concat.

---

## 3. Import workflows

| Source | How |
|---|---|
| Gallery card | “Editar vídeo en Video Editor” writes `maestro-video-editor-pending-source` and switches tab |
| **From Loreframe Lab** picker | `GET /api/v1/outputs?media_type=video` (24 per page), multi-select, then Add selected |
| Local file | Drag/drop or file picker → `POST /api/v1/upload` |
| Series Lab | `maestro-video-editor-pending-sequence` with ordered shot URLs (replace or append) |
| Comic animatic | Single-clip handoff after `POST /api/v1/comics/animatic` |

Each imported clip is probed (`POST /api/v1/video-editor/probe`) and stored as an `EditorClip`: full duration, default transition `none`, default time-card text `Momentos después…`.

---

## 4. Timeline, play, and scrub (UI-only)

Selecting a clip **parks the playhead at that clip’s start**. Selecting a transition gap parks at the transition start.

**Play** starts at the current selection (transition start, else clip start, else 0). If playback is already mid-sequence and not at the end, Play continues from the playhead.

**Scrubber:** pointer drag; keyboard ±0.1 s, ±1 s with Shift, ±0.01 s with Alt, Home/End. An exact-seconds field commits on blur.

| Action | Notes |
|---|---|
| Trim | Edge drag or inspector numbers; min 0.05 s |
| Split | At playhead; refuses if within 0.05 s of a clip edge |
| Reorder | Drag-and-drop |
| Fit | `fit` (letterbox) or `fill` (crop) |
| Volume | UI 0–1; export accepts 0–2 |
| Bulk transitions | “Apply to all gaps” copies the outgoing transition |

Supported `transition` strings:

```
none, crossfade, fade-black, wipe-left, slide-left, slide-right,
circle-open, dissolve, pixelize, blur, zoom-in,
later-clock, later-tropical, later-cinematic
```

`later-*` inserts a full interstitial time card (duration clamped to 0.5–5 s). The others overlap adjacent clips (xfade / acrossfade). Crossfade duration is also capped at 45% of each adjacent clip.

---

## 5. HTTP API

Base URL: the running Lab. Pass workspace as a body field or `?workspace=` on **file URLs only**, never as part of a `source` filename.

### Probe

`POST /api/v1/video-editor/probe`

```json
{ "source": "clip.mp4", "workspace": "default" }
```

Returns `{ duration, width, height, fps, has_audio, pixel_format, has_alpha }`.

### Thumbnail / screenshot

- `GET /api/v1/video-editor/thumbnail?source=clip.mp4` — JPEG
- `POST /api/v1/video-editor/screenshot` — `{ source, time, name?, workspace? }` → `{ filename, url, time, width, height }` plus a PNG sidecar (`generation_mode: "image"`, `source: "video_editor_screenshot"`). Used by Character Creator for the four orbit stills.

### Export

`POST /api/v1/video-editor/export` → **202** job snapshot.

```json
{
  "name": "final_cut",
  "width": 1280,
  "height": 720,
  "fps": 30,
  "workspace": "default",
  "clips": [
    {
      "name": "open",
      "source": "shot_a.mp4",
      "trim_start": 0,
      "trim_end": 4.2,
      "volume": 1,
      "muted": false,
      "fit": "fit",
      "transition": "crossfade",
      "transition_duration": 0.4,
      "transition_text": "Momentos después…",
      "transition_text_size": 100
    }
  ]
}
```

Poll `GET /api/v1/video-editor/export/{job_id}`. Cancel with `POST /api/v1/video-editor/export/{job_id}/cancel`.

Job `status`: `queued`, `waiting_resource`, `running`, `cancelling`, `completed`, `failed`, `cancelled`.

Completed MP4 sidecar: `params.source = "video_editor"`, `generation_mode = "video"`. **No `result_kind`.**

Optional task IDs (`task_id`, `root_task_id`, `parent_task_id`) must match `task-[A-Za-z0-9_-]{1,180}`.

Comic animatics share this job machinery: poll the same `GET .../export/{job_id}` after `POST /api/v1/comics/animatic`.

---

## 6. Assembled mixes (not the editor)

Director auto-rejoins when ≥2 clips finish. Manual rejoin:

| Method | Path | Body |
|---|---|---|
| `POST` | `/api/v1/outputs/rejoin` | `{ "group_id": "...", "audio_file"?: "..." }` → `{ filename, clip_count }` |
| `POST` | `/api/v1/director/pipelines/{pid}/rejoin` | — → `{ filename, assembly_time_sec, total_time_sec }` |
| `GET` | `/api/v1/outputs/group/{group_id}` | clip list |

Soft join (`app/services/mix_concat.py`): last-frame hold **0.5 s** + crossfade **~0.4 s**, only when joining ≥2 clips **without** external `audio_path`. On FFmpeg failure the caller falls back to a hard concat.

`POST /api/v1/audio/mix` mixes **audio tracks** (amix). It is not video concatenation.

### `result_kind` values

Exact kinds: `music_video`, `trailer`, `series_episode`, `chapter`.

A file is an assembled mix only if the lowercase name matches `is_assembled_mix`: contains `multiclip`, or ends with `_mv.mp4` / `_movie.mp4` / `_rejoin_multiclip.mp4`, or contains `_series_assembly`.

Classification (`classify_output_result_kind`):

1. Explicit `result_kind` / `production_kind` / `story_production_kind` on sidecar **and** assembled filename (aliases `episode`, `capitulo`, `capítulo` → `chapter`).
2. Filename `_series_assembly.` → `series_episode`.
3. Non-assembled files → `null` (component clips stay off mix tabs).
4. Else heuristics on `pipeline_type` (`music_video`, `series_episode`, `short_film_story` / `short_film_audio` → `chapter`) and blob/filename text.

Live Director tagging (`result_kind_for_pipeline`): `production_kind == "trailer"` → `trailer`; `pipeline_type == "music_video"` → `music_video`; short-film pipeline types → `chapter`. Series Assembly writes `series_episode`.

### Gallery tabs

`GET /api/v1/outputs` query: `result_kind`, `multiclip_only`, `media_type`, `search`, `workspace`, `favorites_only`, `limit`, `offset`.

| Tab (`MediaFilter`) | Server query | Match rule |
|---|---|---|
| Videoclips | `result_kind=music_video` | exact |
| Tráilers | `result_kind=trailer` | exact |
| Capítulos | `result_kind=series_episode` | `series_episode` **or** `chapter` |
| Multi-clip | `multiclip_only=true` | filename `multiclip` + sliding-window seed groups |

When `result_kind`, `favorites_only`, or `multiclip_only` is set, the server returns **all** matches and **bypasses pagination**.

`workspace=__uploads__` lists the uploads folder without changing the active workspace.

UI mapping: `ui/src/lib/galleryListQuery.ts`. Completing a clip shows a toast instead of jumping the feed if the user has scrolled away from the top.

---

## 7. Pitfalls

- Probe/export with a gallery URL that still has `?workspace=` → `Video source could not be found`.
- Expecting a Video Editor export under Videoclips/Tráilers/Capítulos → it will not appear; those tabs only list assembled mixes.
- Rejoin with fewer than 2 clips → rejected.
- Director rejoin while the pipeline is active → `409` `Pipeline is still active; try again shortly.`
- Soft join + driving soundtrack → hard concat; the freeze/crossfade path is skipped on purpose so lyrics stay locked to the song.
- `result_kind` on `GET /api/v1/outputs` is **computed at list time**. Changing a sidecar without an assembled filename will not reclassify a component clip.

---

## 8. Files to read next

| Path | Why |
|---|---|
| `ui/src/features/video-editor/VideoEditorPanel.tsx` | Import, play/scrub, export |
| `ui/src/features/video-editor/editorTimeline.ts` | Sequence math |
| `ui/src/features/video-editor/editorClipNormalization.ts` | Trim / split / defaults |
| `app/services/video_editor.py` | FFmpeg probe and render |
| `app/services/mix_concat.py` | Soft join constants |
| `app/services/output_result_kind.py` | Mix classification |
| `app/services/media_refs.py` | Workspace query stripping |
