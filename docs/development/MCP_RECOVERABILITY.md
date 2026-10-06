# MCP and Wizard recoverability

Contract and audit (2026-10-06). The owner's rule: whatever an agent makes through MCP
(`/api/v1/mcp`) or **Ask to the Wizard** must be recoverable by the user. The user must be able to
find it, open it in the editor they would have used, edit it, and see who made it and how.

The audit used the full MCP catalogue (163 tools, 85 of them mutating) and the agent production
left on the Plus Ultra instance (`app/outputs/plus-ultra/`: 6,476 files, 48 personal Video 3D
templates, 168 working scenes, 909 scene documents, 33 GLBs, 2,079 tasks). It was checked
read-only against that production and against copies of its artifacts on a development server.

## How it works now

- **Agent trail in Activity.** The MCP dispatcher (`routers/wangp_mcp.py`) calls
  `services/agent_activity.py` after every successful mutating call from an outside client.
  - A call that admits a job (a generation or an export) is attributed on that job's task:
    `tool: external_agent`, `capability` and `command_id`.
  - Any other change becomes one completed `agent` task per artifact. Later calls on the same
    artifact update that task (`operations` counts each tool).
  - Each `agent` task stores the artifacts as `targets`. A target is one of: workspace template,
    working scene, scene document, kit, series or episode, montage, collection, or file.
  - Activity has an **All / Agents** filter. *Agents* reads `GET /api/v1/tasks?origin=agent`, so a
    long session is not crowded out of the 300 most recent tasks. It lists the most recent change
    first and ignores "Clear history".
  - Each row shows an **Agent (MCP)** or **Wizard** badge and the tools used. It has one button per
    artifact, and the button opens that artifact in its editor (`openAgentTarget.ts`).
  - Replays of a stored intent are not counted twice.
  - The server's own jobs are not agent work. A native Series render that calls the same handlers
    in process (`LocalMcp`) runs as `SERVER_CALLER`. A music production's loopback calls send
    `X-Hocus-Caller`. Plain HTTP calls are not attributed either.
- **Generation provenance by caller.** `generation.*` / `model3d.*` handlers label
  `external_agent` only for MCP clients. Before this change, 668 of 1,144 generation tasks in the
  sample were the server's own Series render labelled as an external agent.
- **Personal Video 3D templates.** `world3d.templates.user.put` writes
  `<workspace>/world3d-user-templates.json`. Each entry now has `createdAt`, `updatedAt` and
  `createdBy` (`agent`, `wizard` or `user`).
  - `GET /api/v1/world3d/templates/workspace` lists them. `…/workspace/{id}` returns the stored
    document.
  - The Video 3D shot library shows them under **My templates → Saved in this workspace**, with a
    badge. Picking one and pressing "Use this shot" opens it as an editable shot.
- **Scenes built from workspace templates open safely.** Those documents keep
  `templateId: user-…` (153 of the 167 published scenes in the sample). Before this change,
  opening one did three things wrong: the shot card showed a raw translation key, the shared
  thumbnail loop stopped, and opening the shot library crashed the Video 3D view
  (`unknown_template`). `isBuiltinScene3DTemplate` now guards each of those paths.
- **Exports reopen their scene.** A Video 2D or Video 3D export already embeds the scene it
  rendered (`params.scene_recipe`, plus `params.scene` for 2D). Every such video now has an
  **Edit scene** button (`lib/exportedScene.ts`) that opens that scene in Video 2D or Video 3D.
  Export tasks keep the agent attribution when they finish, and the MP4 sidecar records
  `requested_by`.
- **Provenance on files.**
  - A rigged GLB keeps the provenance of the request. The rig task and the sidecar say
    `external_agent` / `model3d.rig` / `command_id`, where before they said `actor unknown`.
  - Compose and animate sidecars name the agent.
  - A trimmed Series speech line (`ln-*.wav`) keeps the raw take's sidecar: text, voice design,
    model and seed, plus a `trim` transformation. In the sample, 1,041 lines had lost it.

### Second pass (follow-ups)

- **Wizard changes have trail rows.** A Wizard capability with risk `edit` or `compute` reports
  what its result names (`features/agent/wizardTrail.ts`): a Character Kit, a story, a series
  episode (with its series), a collection, a working Video 3D scene, a personal template or a
  published scene file. `POST /api/v1/tasks/wizard-changes` turns that into the same row an MCP
  change gets (`AgentActivity.record_wizard`): one per artifact, `tool: wizard`, a **Wizard**
  badge and open buttons. A story opens in Story Lab. Reporting never fails the Wizard.
- **Who approved.** A Series take records `approvedBy` and `reviewedBy` (`user`, `agent`,
  `wizard`, or `server` when a render with `approve: true` or `series.episode.produce` approved
  what it made), with `approvedAt`; a language version's approval also records
  `approvedLanguage`. MCP tools that run through the app's routes send `X-Hocus-Actor`, and
  `ActorHeaderMiddleware` puts it in the caller scope, so `current_actor()` names the agent in the
  route. The Wizard's approvals declare `X-Hocus-UI-Surface: wizard`. Render & Review shows "by an
  agent", "by the Wizard" or "automatically by the render" on the decision. The staged review's
  plan and preview decisions record `planBy` / `previewBy` with the same words, a note without
  an author is the decider's, and the Validation cards show it. Music production reviews record
  `decidedBy` / `decidedAt`, and the artistic verdict's `source` is `human`, `agent` or `mixed`
  (it was always `human`).
- **Exports name the scene they rendered.** `scenes.document.save` and the Video 3D save record
  the digest of the document as the exporter normalizes it (`services/scene_links.py`,
  `.scene-digests-v1.json`). When a Video 2D or 3D export finishes, that digest finds the saved
  file: the sidecar names it (`params.scene_file`, also `output.scene_file` on the task), and a
  file with no preview or only the agent placeholder gets the export's middle frame as its
  preview. A preview saved from an editor is never replaced. The Series render (it saves each
  shot's scene, then exports it) and agents that export what they published get both.
- **Readable names.** A Video 2D export keeps the last part of a composed name, so a Series shot
  export is `…_video2d-Plus-Ultra-Mas-alla-del-Plan-La-confesion-e1s163_…mp4`; accents fold to
  ASCII (`services/readable_names.py`). `world3d.scene.publish` names the file after the template
  title and the scene id (`Anime-Face-off-w3d-0123456789ab-<uuid>.world3d.scene.json`). Scene
  titles in the Open dialogs drop the revision ids saves append. A 2D save with a `preview` keeps
  it as the scene's picture.
- **Working scenes in the Open dialog.** The working copy records what it was published as
  (`published: {file, revision}`). `GET /api/v1/world3d/templates/working-scenes` lists the ones
  not published at their current revision (older scenes count as published when a
  `w3d-<id>-….world3d.scene.json` exists), and the Video 3D Open dialog lists them after the saved
  scenes; choosing one opens its current revision.
- **Gallery details.** The details panel shows who made a file (an agent with its tool, or the
  Wizard), a song's style, a line's voice (design, preset, or the recording it was cloned from)
  and language, the tool and source files of a tool output, and the saved scene or montage behind
  an export (`lib/outputProvenance.ts`). Feed cards badge agent and Wizard outputs.
- **Montage exports.** `montages.export` and the Video Editor's own export name the montage
  (`params.video_editor.montage: {file, revision}`); an agent's export has `requested_by` (a
  request body cannot claim it). The video has **Edit montage**, and a montage trail target opens
  that montage in the Video Editor. The Wizard's export saves the draft as a montage first (the
  one it came from, or a new one) and sends the montage's overlays and cues, like the editor.
- **Tool sidecars.** `audio.shorten` (source, kept ranges, time map) and every `characters.rig.flat`
  image (kit, role such as `mouth.wide.source` or `anchors.base.mouthSources.open`, style, hints,
  the pose images as parents) write the same sidecar as `studio.key` and the media tools
  (`production_media_common.publish_sidecar`, `services/tool_sidecars.py`). An agent's rig, which
  reaches the route through a loopback, is named `external_agent` with `requested_by`.
- **Productions.** `GET /api/v1/series/produce/jobs?workspace&series_id&episode_id` lists the
  episode productions, newest first. Render & Review shows each one with its render and cut
  steps per language, errors, the chapter files (plain and subtitled) and Stop or Resume.

### Third pass (the last open items)

- **Machine translations are marked.** `series.episode.translate` (and **Translate with AI** in Series Lab) marks
  every line, card and title it wrote in the version:
  `languageVersions.<language>.machineTranslated = {dialogue: [beat ids], cards: [shot ids], title, translatedAt,
  requestedBy}` (`services/series_language_versions.py`).
  - Series Lab's **Language versions** shows a **Machine translation** badge on each marked line and card and on the
    title, and a count that says who asked for the translation. The version's title and cards are now shown and
    editable beside the original's.
  - A person's edit clears the mark of what it wrote. **Checked** (one text) and **Mark all as checked** save the text
    as it is, so a person can accept a translation without changing it. The route decides who wrote: only a write
    with `current_actor() == "user"` clears marks. An agent's (`language_version.set`), the Wizard's or a script
    rewrite's write keeps them, because the text is still not checked by a person.
  - The library keeps marks only for texts the version still has, so a removed line or card loses its mark.
- **The scripts of `series.episode.from_script` are kept.** Every script written into an episode is stored as it was
  sent, revisioned per episode, in `<workspace>/.series-scripts-v1/<series>/<episode>.json`
  (`services/series_script_history.py`). A revision has `revision`, `submittedAt`, `by` (`user`, `agent`, `wizard`,
  `server`), `created`, `shots`, `languages`, `digest`, `applied` and `restoredFrom`.
  - The same script sent again counts on its revision (`applied`) instead of adding one. The 50 newest revisions are
    kept. A `check: true` call writes nothing and keeps nothing. The reply of a write has `scriptRevision`.
  - `GET /api/v1/series/{series}/episodes/{episode}/scripts` lists the revisions, newest first.
    `…/scripts/{revision | latest}` returns one with its script, and `download=true` saves the script as JSON.
    `POST …/scripts/{revision}/rewrite` writes the episode again from it (`check: true` only checks it).
  - MCP `series.episode.script.get` (read-only, in the series profile) returns the revisions and one script in full.
    An agent re-runs it with `series.episode.from_script` and `episode_id`.
  - Series Lab's **Episode** tab has **Scripts this episode was written from**: who sent each revision and when, its
    shots and languages, **View**, **Download** and **Rewrite from this script**. A rewrite asks first, saves pending
    edits, checks the script against the series as it is now (its problems are listed and nothing is written), then
    rewrites. Shots whose content changes lose their takes and go back to pending review; the others keep theirs.
- **Published pages are linked.** `production.publish` records each publication beside the production
  (`<id>.publications.json`: page, video, mode, `published_at`, `published_by`). `GET /api/v1/music-productions` (and
  the detail) returns the newest as `publication`. The music production card and its detail view link that page (a
  new tab), say when it is a review preview, who published it and how many publications it has.
- **Origin in the gallery listing.** Each row of `GET /api/v1/outputs` carries `origin: {actor: agent | wizard,
  capability}` (or `null`), read from the sidecar in the same scan as the other listing fields
  (`services/output_origin.py`, the same rules as `outputMaker`). `origin=agent` keeps MCP and Wizard work, `mcp` or
  `wizard` one of them, before paging.
  - The gallery has **Media → Made by agents**. It pages like the full list.
  - Feed cards badge from the listing before the sidecar loads, and grid and mosaic tiles badge agent and Wizard work.

## Matrix: mutating MCP tools

Legend: ✅ the user can find it, open it in its editor and see who made it · ⚠️ partly · ❌ gap.
"Trail" means the Activity *Agents* view.

| Tool | Artifact and storage | Where the user finds it | Open / edit in the matching editor | Provenance shown | Status |
|---|---|---|---|---|---|
| `generation.image` (v1/v2, `output_name`) | Workspace root file + `.meta.json` (prompt, model, seed, refs, `origin.tool`) | Gallery (also **Made by agents**), Assets, Activity task | Edit, use as reference, Load settings / Re-generate (`restoreStudioImageSettings`) | Prompt and model in details; the listing's `origin` badges cards and tiles | ✅ |
| `generation.speech` / `music` / `sfx` | Root `.wav` + sidecar (`prompt`, `alt_prompt`, voice reference) | Gallery (audio), Activity | Load settings restores the Studio audio form | Text, music style, voice (design, preset or cloned recording) and language in the details; agent badge | ✅ fixed here |
| `generation.video`, legacy `generate` / `recast` | Root video + sidecar | Gallery, Activity | Retake, Extend, Video Editor, Load settings | Yes. `lineage.parents` stays empty for refs and start frames | ⚠️ lineage |
| `tools.upscale`, `upscale`, `wizard.image_upscale` | Root file + tool sidecar with parents | Gallery (Edits) | Re-generate does not reopen the Tools form | Source only | ⚠️ |
| `audio.shorten` | Root WAV + sidecar (source as parent, kept ranges, time map) | Gallery; trail | As media; redo with the same source and ranges | `requested_by` on the file; source and tool in the details | ✅ fixed here (was ⚠️) |
| `studio.key` | Root PNG/WebM + sidecar (source as parent, mode, adaptive, despill, residual haze share) | Gallery; trail | As media; redo with the same source and mode | `requested_by` and `command_id` on the file | ✅ |
| `media.frame`, `media.compose`, `audio.trim` | Root PNG/JPG/WAV + sidecar (sources as parents, the tool's parameters) | Gallery; trail | As media; the sidecar names every source and setting | `requested_by` and `command_id` on the file | ✅ |
| `assets.import_from_workspace` | Copy at the root + the source's sidecar rewritten (`copied_from`, lineage parent) | Gallery; trail | As media (a GLB in the 3D viewer) | `copied_from` and `requested_by` on the file | ✅ |
| `series.shot.update` | The shot's changed fields in the series library (takes kept) | Series Lab; trail (the episode) | Series Lab › Validation shot inspector (each part) | Trail | ✅ |
| `series.shot.voice` | The line's recording `ln-<episode>-<beat>-<key>.wav` + sidecar (text, voice, model, seed); job in `.series-jobs-v1/voice` | Series Lab › Validation › the shot's Dialogue (plays, newer than the take); trail (the episode) | Record again from the same place; the next render of the shot reuses it | Sidecar and trail | ✅ |
| `assets.upload` | Root file (named copies keep the source sidecar) | Gallery, Assets; trail | As media | Trail | ✅ |
| `world3d.templates.user.put` | `world3d-user-templates.json` row | **My templates → Saved in this workspace**; trail | Opens as an editable shot | `createdBy` badge, dates | ✅ fixed here (was ❌) |
| `world3d.scene.instantiate` / `apply_query` / `patch` / `talk` | `world3d-edits/w3d-*.json` (working scene) | Trail (one row per scene) | Trail button opens the current revision in Video 3D | Template, tools and counts | ✅ fixed here. Unpublished ones are also in the Video 3D Open dialog |
| `world3d.scene.publish`, `scenes.document.save` (3D) | `<template title>-<scene id>-<uuid>.world3d.scene.json` (publish) | Gallery (scene), Open scene dialog, trail | Video 3D | Trail; the working copy records the published revision | ✅ fixed here. The preview stays the placeholder until the scene is exported (then its middle frame) |
| `scenes.world3d.export` | Timestamped MP4 + sidecar with the embedded document | Gallery, Activity task | **Edit scene** reopens the document in Video 3D | Agent badge on the task; `requested_by` in the sidecar | ✅ fixed here. The sidecar names the saved scene file (`params.scene_file`) |
| `scenes.document.save` (2D) | `<name>-<hex>.scene.json` (+ `.scene.preview.png`) | Gallery, Video 2D library, trail | Video 2D | Trail | ✅ The preview is the one sent with the save, or the export's middle frame |
| `scenes.video2d.export` | MP4 + sidecar with the scene | Gallery, Activity task | **Edit scene** opens Video 2D | Agent badge | ✅ fixed here. Names keep the shot id; the sidecar names the saved scene |
| `scenes.video2d.edit`, `lyrics.import`, `template.compile`, `effects.apply` | Nothing until a save (read-only operations) | — | Only once saved | — | ⚠️ by design: lost if the agent never saves |
| `model3d.generate` | `{stamp}_{model}_{job}.glb` + meta + `.preview.png` | Gallery (3D), Activity | Viewer, Rig, Retexture | Recipe; agent label on the task | ✅ |
| `model3d.rig` | `…_rigged_….glb` + meta + `.humanoid.json` | Gallery with clip selector, Activity | View; no "re-rig with these settings" | Engine, profile and clips; now the agent and command | ✅ fixed here (was `actor unknown`) |
| `model3d.compose` / `model3d.animate` | `compose-*.glb` / `humanoid-*.glb` + recipe sidecar | Gallery, trail | View or rig only (no compose UI). Animate is shown as static | Recipe; agent tool | ⚠️ |
| `characters.save` | `.character-kit-library-v1.json` | Character Kit library, trail (the Wizard's changes too) | Character Kit editor | Trail (`kit.provenance` is not shown) | ✅ via the trail |
| `characters.rig.flat` | `kit-*-mouth/blink/rig-*.png` (no sidecar) + kit record; warp mouths also `kit-*-<pose>-mouth-*.png` in `anchors.<pose>.mouthSources` | Kit face rig, trail | Anchors editable (face rig panel); a warp pose's mouth line in the Face Rig's Mouth line editor | Every PNG has a sidecar (kit, role, style, hints, pose sources as parents); kit record and trail | ✅ (the PNGs still show in the gallery) |
| `lips.*` | `.lips-creator-library-v1.json` | Lips Creator, trail | Yes | Trail | ✅ |
| `series.create` / `update` / `create_from_template` / `canon.approve` / `episode.*` / `language_version.set` / `translate` | `.series-library-v1.json` | Series Lab, trail (the Wizard's changes too) | Series Lab | Trail. Machine translations are marked per line, card and title until a person checks them. No creator on the series or episode record | ✅ |
| `series.episode.from_script` | The episode + `.series-scripts-v1/<series>/<episode>.json` (every script written, revisioned, with who sent it) | Series Lab **Episode** tab (scripts), `series.episode.script.get`, trail | View, download, **Rewrite from this script** | `by` on each revision | ✅ fixed here |
| `series.episode.review.set` / `series.shot.review.set` | `episode.review` in `.series-library-v1.json` | Series Lab **Validation**, trail | Series Lab | `planBy`, `previewBy` and each note's `by` (`user`, `agent`, `wizard`, `server`), shown on the cards | ✅ |
| `series.asset.import` (`as_take`), `series.take.approve` | `assets/<series>/asset_*` copy + take | Series Lab only, trail | Series Lab (see the per-shot review work) | The take's `approvedBy` (`user`, `agent`, `wizard` or `server` for a render's own approval), shown in Render & Review | ✅ fixed here |
| `series.episode.render_native` / `produce` | Jobs in `.series-jobs-v1/`, per-shot scene documents, takes and lines | Series Lab, gallery (scenes and videos), trail | Scenes open in their editors; videos have **Edit scene** | Trail for the call. The render's own steps are not agent work | ✅ fixed here (lines keep their sidecar). Productions are listed in Render & Review with steps, chapters, stop and resume |
| `series.location.plate3d` | Plate video + `layout2d.plate3d` | Series Lab location | An inline source document is not saved as a scene | Intent only | ⚠️ |
| `series.assembly.start` | Chapter video + subtitles | Series Lab chapters, gallery, Activity | Plays | Task | ✅ |
| `montages.save` / `derive` / `shot.*` | `<slug>.montage.json` | Video Editor Open list, trail | Video Editor (the trail button opens that montage) | Trail. `derivedFrom` is dropped on a UI save | ✅ via the trail |
| `montages.export` | MP4 + sidecar (`params.video_editor.montage: {file, revision}`) | Gallery | **Edit montage** reopens the montage in the Video Editor | `requested_by` on the file; agent badge | ✅ fixed here (was ❌) |
| `templates.save` / `import` / `community.install` / `apply` / `export` / `delete` | Template library folder + `origin.json` | 2D and 3D template panels, trail | Yes | An agent's save says `source: user`; delete is permanent | ⚠️ |
| `production.run` / `shot.*` / `song.use` / `publish` | `<id>.production.json`; publication outside the workspace, recorded in `<id>.publications.json` | Music productions overlay (the card links the published page), trail | Its montage in the Video Editor; the spec itself is not editable | `origin` stored, not shown. Each review decision records `decidedBy`; the verdict says `human`, `agent` or `mixed`; a publication records `published_by` | ⚠️ (`publish` ✅ fixed here) |
| `collections.create` / `update`, `organize` | `_hocuspocus/workspaces-v1.json` | Collections, trail | Yes | Trail | ✅ |
| `jobs.resume` / `discard`, `*.cancel`, `audio.analyze`, `audio.phonemes.setup`, `wizard.workflow_answer` | Job state only | Activity tasks | — | — | not an artifact (left out of the trail) |

## Wizard actions

The Wizard mostly drives the open editors, so its results are on screen while it works.
Generations it submits are tasks with `actor: wizard`, and Activity now badges them **Wizard**.
Its Video 3D template commands now declare `X-Hocus-UI-Surface: wizard`, so templates it saves read
`createdBy: wizard`.

The Wizard's other server changes (kits, series, stories, collections, Video 3D templates and
scenes) get an Activity row in the Agents view, badged **Wizard**, with buttons that open each
result. Its take approvals record `approvedBy: wizard`. Its Video Editor export saves the draft as
a montage first. The following results still live only in the browser until the user saves:

- the Video 3D layer scene (`create_3d_scene` … before `save_3d_scene`)
- `create_comic`, before a manual save
- the Video Editor draft between edits (it becomes a montage when the Wizard exports it)
- rhythm analyses

## Remaining work, by priority

Done in the second pass: Wizard rows, agent origin and audio style/voice in the gallery details,
readable published names, export previews and the Open dialog's working scenes, Video 2D export
names and the saved scene in the sidecar, montage links (and the Wizard saving its draft), the
`audio.shorten` and flat-rig sidecars, take, staged-review and production-review deciders, and the
list of productions. Done in the third pass: machine translations marked, the scripts of
`from_script` kept (viewer, download, rewrite, MCP read tool), publication links on the music
production cards, and `origin` in the gallery listing with **Made by agents**. Still open:

1. **Previews of scenes that were never exported.** An agent's scene gets a real preview from its
   first export. Before that it keeps the placeholder: a still from the headless renderer would
   take the export lane on every save.
2. **Files without a sidecar.** Scene documents (`.scene.json`, `.world3d.scene.json`) and comics
   have no `.meta.json`, so the listing gives them no `origin` and **Made by agents** does not list
   them. The Activity *Agents* view does.
3. **Who made the series records.** The series and episode records still have no creator field (the
   trail and the kept scripts say who wrote them). The other-language lines a script brings are
   the agent's text and are not marked as machine translations.

## Tests

- `tests/test_agent_activity.py`: targets, one row per artifact, replay, server and plain-HTTP
  callers, job attribution, the `origin=agent` filter, LocalMcp scope, the MCP endpoint.
- `tests/test_recoverable_artifacts.py`: workspace templates (`createdBy`, list, get), export
  attribution kept when the export finishes, rig origin, trimmed lines keeping their sidecar.
- `ui/tests/agentActivityTrail.test.tsx` and `ui/tests/world3dWorkspaceTemplates.test.tsx`: origin
  badge, Agents view, open buttons, workspace templates in My templates, scenes with `user-…`
  template ids, Edit scene.
- `tests/test_recoverability_followups.py`: Wizard rows and their route, montage targets, the
  actor header and loopback, take and review deciders, export names, montage links, the
  `audio.shorten` and flat-rig sidecars, the saved scene and preview of a 2D export (end to end)
  and of a 3D save, published names, working scenes and their route, the productions list.
- `ui/tests/recoverabilityFollowups.test.tsx` and `ui/tests/scene3dLibraryControls.test.tsx`:
  Wizard trail targets and reporting, Wizard badges, gallery provenance and the details panel,
  scene titles, working scenes in the Open dialog, the productions list with resume, and the
  Wizard saving its draft as a montage before exporting.
- `tests/test_recoverability_last.py`: translation marks (what they cover, the library, who clears them through
  the route), kept scripts (revisions, the same script again, the cap, odd ids, the routes end to end with
  download and rewrite, the MCP tool), publications on the card, and `origin` in the listing with its filter
  before paging.
- `ui/tests/recoverabilityLast.test.tsx`: the marks and **Checked** / **Mark all as checked** in Language
  versions, the Episode tab's scripts (view, download, rewrite, a script that no longer fits), the published
  page link on the music production cards, and **Made by agents** (query, listing origin, tile badge).
