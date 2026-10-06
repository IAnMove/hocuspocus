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

## Matrix: mutating MCP tools

Legend: ✅ the user can find it, open it in its editor and see who made it · ⚠️ partly · ❌ gap.
"Trail" means the Activity *Agents* view.

| Tool | Artifact and storage | Where the user finds it | Open / edit in the matching editor | Provenance shown | Status |
|---|---|---|---|---|---|
| `generation.image` (v1/v2, `output_name`) | Workspace root file + `.meta.json` (prompt, model, seed, refs, `origin.tool`) | Gallery, Assets, Activity task | Edit, use as reference, Load settings / Re-generate (`restoreStudioImageSettings`) | Prompt and model in details; Activity badge | ✅ (the gallery details do not badge the agent yet) |
| `generation.speech` / `music` / `sfx` | Root `.wav` + sidecar (`prompt`, `alt_prompt`, voice reference) | Gallery (audio), Activity | Load settings restores the Studio audio form | Text and prompt shown. Voice design and music style only in "All info" | ⚠️ details hide the style and voice |
| `generation.video`, legacy `generate` / `recast` | Root video + sidecar | Gallery, Activity | Retake, Extend, Video Editor, Load settings | Yes. `lineage.parents` stays empty for refs and start frames | ⚠️ lineage |
| `tools.upscale`, `upscale`, `wizard.image_upscale` | Root file + tool sidecar with parents | Gallery (Edits) | Re-generate does not reopen the Tools form | Source only | ⚠️ |
| `audio.shorten`, `studio.key` | Root file, **no sidecar** (source and mode only in `.mcp-intents`) | Gallery; trail | As media only; cannot be redone | None on the file | ⚠️ trail only |
| `assets.upload` | Root file (named copies keep the source sidecar) | Gallery, Assets; trail | As media | Trail | ✅ |
| `world3d.templates.user.put` | `world3d-user-templates.json` row | **My templates → Saved in this workspace**; trail | Opens as an editable shot | `createdBy` badge, dates | ✅ fixed here (was ❌) |
| `world3d.scene.instantiate` / `apply_query` / `patch` / `talk` | `world3d-edits/w3d-*.json` (working scene) | Trail (one row per scene) | Trail button opens the current revision in Video 3D | Template, tools and counts | ✅ fixed here. Unpublished scenes are still not in the gallery or the editor's Open dialog |
| `world3d.scene.publish`, `scenes.document.save` (3D) | `<name>-<uuid>.world3d.scene.json` | Gallery (scene), Open scene dialog, trail | Video 3D | Trail; file names are opaque, previews are placeholders | ⚠️ names and previews |
| `scenes.world3d.export` | Timestamped MP4 + sidecar with the embedded document | Gallery, Activity task | **Edit scene** reopens the document in Video 3D | Agent badge on the task; `requested_by` in the sidecar | ✅ fixed here. The sidecar does not name the saved scene file |
| `scenes.document.save` (2D) | `<name>-<hex>.scene.json` | Gallery, Video 2D library, trail | Video 2D | Trail | ✅ (no preview image) |
| `scenes.video2d.export` | MP4 + sidecar with the scene | Gallery, Activity task | **Edit scene** opens Video 2D | Agent badge | ✅ fixed here. Names are cut to 40 characters and drop the shot id |
| `scenes.video2d.edit`, `lyrics.import`, `template.compile`, `effects.apply` | Nothing until a save (read-only operations) | — | Only once saved | — | ⚠️ by design: lost if the agent never saves |
| `model3d.generate` | `{stamp}_{model}_{job}.glb` + meta + `.preview.png` | Gallery (3D), Activity | Viewer, Rig, Retexture | Recipe; agent label on the task | ✅ |
| `model3d.rig` | `…_rigged_….glb` + meta + `.humanoid.json` | Gallery with clip selector, Activity | View; no "re-rig with these settings" | Engine, profile and clips; now the agent and command | ✅ fixed here (was `actor unknown`) |
| `model3d.compose` / `model3d.animate` | `compose-*.glb` / `humanoid-*.glb` + recipe sidecar | Gallery, trail | View or rig only (no compose UI). Animate is shown as static | Recipe; agent tool | ⚠️ |
| `characters.save` | `.character-kit-library-v1.json` | Character Kit library, trail | Character Kit editor | Trail (`kit.provenance` is not shown) | ✅ via the trail |
| `characters.rig.flat` | `kit-*-mouth/blink/rig-*.png` (no sidecar) + kit record | Kit face rig, trail | Anchors editable (face rig panel) | Kit record and trail | ⚠️ PNG clutter in the gallery |
| `lips.*` | `.lips-creator-library-v1.json` | Lips Creator, trail | Yes | Trail | ✅ |
| `series.create` / `update` / `create_from_template` / `canon.approve` / `episode.*` / `language_version.set` / `translate` | `.series-library-v1.json` | Series Lab, trail | Series Lab | Trail. No creator on the record; translations are not marked as machine-made | ✅ via the trail |
| `series.asset.import` (`as_take`), `series.take.approve` | `assets/<series>/asset_*` copy + take | Series Lab only, trail | Series Lab (see the per-shot review work) | Auto-approvals look like a person's | ⚠️ |
| `series.episode.render_native` / `produce` | Jobs in `.series-jobs-v1/`, per-shot scene documents, takes and lines | Series Lab, gallery (scenes and videos), trail | Scenes open in their editors; videos have **Edit scene** | Trail for the call. The render's own steps are not agent work | ✅ fixed here (lines keep their sidecar). `produce` jobs have no list view |
| `series.location.plate3d` | Plate video + `layout2d.plate3d` | Series Lab location | An inline source document is not saved as a scene | Intent only | ⚠️ |
| `series.assembly.start` | Chapter video + subtitles | Series Lab chapters, gallery, Activity | Plays | Task | ✅ |
| `montages.save` / `derive` / `shot.*` | `<slug>.montage.json` | Video Editor Open list, trail | Video Editor | Trail. `derivedFrom` is dropped on a UI save | ✅ via the trail |
| `montages.export` | MP4 + sidecar | Gallery | No link back to the montage | Looks like a UI export | ❌ |
| `templates.save` / `import` / `community.install` / `apply` / `export` / `delete` | Template library folder + `origin.json` | 2D and 3D template panels, trail | Yes | An agent's save says `source: user`; delete is permanent | ⚠️ |
| `production.run` / `shot.*` / `song.use` / `publish` | `<id>.production.json`; publication outside the workspace | Music productions overlay, trail | Its montage in the Video Editor; the spec itself is not editable | `origin` stored, not shown. Agent reviews are recorded as `human` | ⚠️ (`publish` ❌) |
| `collections.create` / `update`, `organize` | `_hocuspocus/workspaces-v1.json` | Collections, trail | Yes | Trail | ✅ |
| `jobs.resume` / `discard`, `*.cancel`, `audio.analyze`, `audio.phonemes.setup`, `wizard.workflow_answer` | Job state only | Activity tasks | — | — | not an artifact (left out of the trail) |

## Wizard actions

The Wizard mostly drives the open editors, so its results are on screen while it works.
Generations it submits are tasks with `actor: wizard`, and Activity now badges them **Wizard**.
Its Video 3D template commands now declare `X-Hocus-UI-Surface: wizard`, so templates it saves read
`createdBy: wizard`.

The Wizard's other server changes (kits, series, stories, collections) are recoverable in their
own studios, but they have no Activity row yet. The following results live only in the browser
until the user saves:

- the Video 3D layer scene (`create_3d_scene` … before `save_3d_scene`)
- `create_comic`, before a manual save
- the whole Video Editor draft, which stays in browser storage
- rhythm analyses

## Remaining work, by priority

1. **Wizard rows in Activity.** After an `edit` or `compute` capability, `capabilityRunner.ts`
   should upsert a client task with its target, and `/api/v1/tasks/upsert` should keep
   `result_refs` and `metadata.tool: wizard`.
2. **Agent origin in the gallery.** Carry `origin.tool`, `capability` and `requested_by` into the
   gallery listing. Show "Made by an agent (MCP)" in the details, and show the style and voice of
   audio outputs.
3. **Drafts and documents.**
   - Name published Video 3D scenes after their template title.
   - Render a real preview for agent scene saves, and a preview image for 2D documents.
   - List unpublished `w3d-*` working scenes in the editor's Open dialog.
4. **Video 2D export names.** Keep the shot id when shortening, and record the saved scene file
   in the sidecar.
5. **Montage exports.** Record `montage: {file, revision}` in the sidecar, add "Edit in Video
   Editor" from the video, and have the Wizard save a montage before exporting.
6. **Sidecars for `studio.key`, `audio.shorten` and flat-rig PNGs.** Record the source, mode and
   parents with `publish_generation_sidecar`.
7. **Who approved.**
   - Record the actor on Series take approvals and production reviews.
   - Mark machine translations.
   - Keep the original script of `from_script`.
8. **Produce jobs and publications.** Add a list view for `series.episode.produce` jobs. Link the
   published page from the production card.

## Tests

- `tests/test_agent_activity.py`: targets, one row per artifact, replay, server and plain-HTTP
  callers, job attribution, the `origin=agent` filter, LocalMcp scope, the MCP endpoint.
- `tests/test_recoverable_artifacts.py`: workspace templates (`createdBy`, list, get), export
  attribution kept when the export finishes, rig origin, trimmed lines keeping their sidecar.
- `ui/tests/agentActivityTrail.test.tsx` and `ui/tests/world3dWorkspaceTemplates.test.tsx`: origin
  badge, Agents view, open buttons, workspace templates in My templates, scenes with `user-…`
  template ids, Edit scene.
