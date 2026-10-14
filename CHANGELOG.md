# HocusPocus Changelog

Product version comes from the repo-root `VERSION` file. Historical Maestro
releases below 0.9.0 are the upstream lineage. WanGP pipeline history lives
in [app/docs/CHANGELOG.md](app/docs/CHANGELOG.md).

## [Unreleased]

**Fixed: the LAN, video-command and operator documentation now matches the code.** The README said LAN token protection was optional; on the full server it is on by default whenever the app is shared, and the new LAN authentication page says so, with the token, cookie and MCP exceptions. It also says plainly that the core server has no LAN gate and prints no token, so it should not be shared on an untrusted network. A new page documents the `generation.video` command (Wan 2.1 version 2, H3 and LTX-2.3 version 3, validate-only checks) and who calls it; the Wizard and MCP guide no longer says the command is unpublished. The guides also describe VoxCPM2 as the default voice engine, Qwen 2.1 Turbo, and the ground styles of Video 3D.

**Recast and its preview left the launch module.** POST /api/v1/recast and POST /api/v1/recast/preview still answer the same way. A preview still returns the same picture of the people it found. A recast job still starts in the background, still tracks the person with the same mask, and still hands the same work to the generation worker. A Viggle recast and MCP still call that same recast function.

**Storage duplicate tools, the managed LoRA download, model-file helpers, generation option helpers and the request guards left the main server file.** The duplicate scan, reclaim and linked-install removal still answer the same way. A generation still downloads a managed LoRA that is missing, and still reads the same registry. The model list still reports the same weight groups and the same missing image-model files. Prompt types, SCAIL-2 steps and guidance, the output seed and the MiniMax H3 options are still normalised the same way. A policy refusal is still a 409, a browser mutation from another origin is still refused, and a traced mutation is still recorded. LAN authentication is still the first check. The main server file is about 700 lines shorter.

**Canonical tasks left the main server file (no behaviour change).** The helpers that read a job's id, status, time and progress, the functions that publish a generation, a Series plan or render, an assembly, a Director pipeline and the older job kinds, and the functions that list those tasks, retry or cancel one, and reopen one for resume, moved unchanged. The server hands each module its own objects once, and the old names on the server are those same functions. A Series, Story or comic service still reaches them through a forwarder that looks the name up when it is called.

**Fixed: a generation started by a command (picture, speech, music, sound effect or video, from the Studio, the Wizard or MCP) works again on the full server.** Since the generation job core moved into the kernel, such a job was cancelled and marked interrupted ("dispatch_failed") before its worker started. The job now joins the GPU queue and starts as before.

**Generation job status, cancel and the job list left the main server file.** GET /api/v1/status/{job_id}, POST /api/v1/cancel/{job_id} and GET /api/v1/jobs still answer the same way. The core server keeps its own copies of these routes.

**Generation queue recovery left the main server file.** GET /api/v1/jobs/recovery, POST /api/v1/jobs/recovery/resume and POST /api/v1/jobs/recovery/discard still answer the same way. A recovered job still starts again from the beginning. Leftover files are still prepared, started or discarded the same way, and intermediate files are still released when the server starts.

**Generation preparation and the simulated run left the main server file.** A job still prepares the same way before the worker runs. A simulated job still walks the same steps. The local GPU owner is still prepared the same way. The worker still receives those same functions.

**The H3 idle-release timer and the hardware probe left the main server file.** A native H3 model still stays loaded while another H3 job is waiting and still releases after the same idle wait. The legacy H3 release and the Wan interrupt are the same functions. The hardware probe still runs once and still reports no VRAM when the probe fails. The coefficient pass and the director pipeline still call that same probe.

**Recast shot planning, the shot manifest and shot generation left the launch module.** Finding the camera shots, recovering a person the first pass missed, building each shot's prompt and reference, and joining the generated clips still work the same way. The assembler still calls the same generation worker. A cancel while the clips are joined still drops the unfinished file.

**Blend left the launch module.** Joining two clips with a generated transition still answers the same way. The blend worker still asks the generation worker to render the transition, then finishes the job itself.

**Outpaint left the launch module.** Extending a picture or a clip, including the official LTX-2 path and a clip with several camera shots, still answers the same way. The generation worker still does the outpaint audio and pixel pass itself.

**Repaint planning left the launch module.** Checking region mappings, the edited frame's aspect, the prepared frame, the preview image, and the shot prompt, conditioning and manifest still works the same way. The Repaint routes call those same functions.

**Repaint shot assembly left the launch module.** Writing the shot sidecar and assembling the shot videos still work the same way. The Repaint route calls that same assembly.

**The Repaint routes left the launch module.** Previewing changed regions and starting a Repaint still answer the same way, including a request the server refuses before any model work.

**Recast masks, mattes, and reference pictures left the launch module.** A character mask, a mask-locked video, a cut-out reference, and the prepared reference a replacement uses are still built the same way. The background-removal model still loads once, on CPU, and its cache stays one object. The relighting LoRA is still the same file with the same hash, and a job still waits for that download.

**The generation worker left the main server file, split into small steps (no behaviour change).** One function used to run every picture, video, speech and sound job on the full server, in a single block of about 1,800 lines. It is now a short frame that keeps what must always happen (take the GPU, report an error, clean up, even after a cancel) and hands the job from one step to the next: start, legacy H3 route, preflight, task manifest, queue, tasks, collecting the files, the post-processing passes, and finishing. The steps are the old code moved without edits into `app/services/generation_worker/`, so a job does the same things in the same order and ends the same way on a cancel or an error, and every route that starts a job still calls the same `_run_generation`. The main server file is about 1,800 lines shorter. The server hands the new package its own objects once, at start-up.

**Sound-effect generation left the launch module.** A sound-effect job still prepares MMAudio, writes the clip, and publishes the same sidecar.

**FlashVSR chunked upscaling left the launch module.** A long clip is still upscaled in memory-bounded chunks, and the tools upscale still uses that same function.

**Film grain and spatial upsampling left the launch module.** A finished video is still grained in place, and a spatial upscale still replaces the file and keeps its audio.

**The per-job VRAM coefficient left the launch module.** A job still tightens the safety coefficient for its own weights and puts the saved base value back when the job finishes.

**Hugging Face LoRA import left the launch module.** An empty import, a URL the server does not recognize, and a target directory that leaves the folder still answer the same way. The download registry that import writes is the same object the CivitAI downloads use.

**CivitAI browsing, CivitAI downloads, and checkpoint import left the launch module.** The filter list, the architecture picker, a cached search, a cached model, a refused download, and an empty download list still answer the same way. Installed checkpoints, an update check on an empty folder, and a guide for an unknown checkpoint still answer the same way. The download registry and the CivitAI response cache stay one object each.

**SAM status and segment preview left the launch module.** GET /api/v1/sam/status and POST /api/v1/segment/preview still answer the same way.

**Edit-anything and inpaint left the launch module.** POST /api/v1/edit-anything and POST /api/v1/inpaint still answer the same way.

**Retake and frame extraction left the launch module.** POST /api/v1/retake and POST /api/v1/extract-frames still answer the same way.

**Submitting a generation left the launch module.** POST /api/v1/generate still answers the same way. A Viggle recast, a series shot and MCP still call that same function.

**LoRA guide generation left the launch module.** Asking for a guide, starting a scan, and reading a scan that does not exist still answer the same way. Generating a guide still needs a loaded language model. The scan registry stays one object.

**The LoRA library left the launch module.** The directory list, the installed LoRAs, a model's LoRA list and details, deleting a file, and the NSFW override still answer the same way. The update manifest still answers the same way.

**Model visibility, selections, the production profile, the model catalog and model options left the launch module.** Showing or hiding a model, remembering the model chosen for each mode, and saving the production profile still answer the same way, including a list or a mode the server refuses. The catalog, a model's debug view, its defaults, its options, the resolution list, and the download status still answer the same way. Deleting a model that is not installed, or one that is in use, and downloading a model that does not exist, still answer the same way. The visibility write lock and the download map stay one object each. The core server keeps its own copies of these routes.

**Director v2 plan jobs left the main server file.** Planning a v2 production, listing its saved jobs, reading one job, resuming it, and reading plan progress are the same routes with the same answers. A plan still checkpoints the same batches and still shows up in Activity. The set of public model providers is still the main server's set. The core server does not plan a v2 production.

**Director planner and short-film pipeline routes left the main server file.** Classifying sections, planning prompts and images, planning dialogue scenes, planning a short film's prompts, and planning a short film's script are the same routes with the same answers. Starting, continuing, previewing, updating a preview, stopping, and resuming a pipeline are the same routes with the same answers. Editing a clip's prompt, tag, or chosen video, repairing a pipeline, cancelling that repair, rerunning an image, a video, or a segment, rejoining the clips, and deleting a pipeline are the same routes with the same answers. The pipeline is still prepared once, the first time a route needs it, and music generation, a quick-video batch, and the Activity cancel and resume actions call that same function and those same stop and resume routes. The core server does not start, continue, or rerun a pipeline.

**Alternative songs left the launch module.** Listing the songs on a videoclip, attaching one, deleting one, and refusing a mount that has no song still answer the same way. A remount still uses the video editor's job registry. A real FFmpeg remount was not run here.

**Gallery thumbnails, metadata, extra info, rejoining clips, and moving or deleting an output left the launch module.** A still still gets a preview. A missing file is still not found. Metadata still comes from the sidecar, or from the file, or is empty. Extra info still reads the saved prompt and refuses a language it does not know. A group that is not on disk still has no clips. Rejoin still asks for a group and for two clips before it concatenates. Moving a file still stays inside the workspace, and deleting one still removes the file the gallery was listing.

**Director comic planning left the main server file.** Planning a comic, rewriting or translating one page, and revising the story are the same routes with the same answers. Starting a plan, reading it, resuming it, and recovering the newest completed plan are the same routes with the same answers. The job list, the set of plans that are running, and their lock live in one place, and the main server still uses those same objects. A plan still writes the same checkpoints and still shows up in Activity. The core server does not plan a comic.

**Comic page checks and the comic animatic left the main server file.** A panel's characters, captions and dialogue are normalised the same way. A page is still rejected for the same shape problems, and lettering is still trimmed to the same budget. English that shows up in another language is still detected and repaired. The animatic still finds the same panel images, writes the same sidecar, and renders through the same video-editor job. The comics route that starts an animatic is unchanged. The Story Lab storyboard check now imports the comic page check directly instead of waiting for the main server to hand it over, so it also works outside the main server. The core server does not render an animatic.

**Favorites and scene save left the launch module.** Marking a clip as a favorite, saving a scene, and uploading a scene recording still answer the same way on the main server. The core server uses the same scene and recording routes, so it checks input the way the main server does. Saving a scene on core needs a JSON object sent with the JSON content type: a body that is not an object, a broken body, or JSON sent as plain text or with no content type is now rejected as invalid input (it used to be saved, or to fail with a server error). A core recording sent without a file is rejected as invalid input too, and one whose metadata field is far too large now gets a plain 400 instead of a server error. The web app always sends the right content type and a file, so it is not affected; a script that posts to core by hand must set `Content-Type: application/json`.

**Audio upload, trim, mix, and analysis left the launch module.** Uploading a clip, adopting one the machine already has, trimming it, mixing tracks, and reading an analysis still answer the same way. An unknown analysis job is still not found. Asking for clips or a structure without an analysis is still refused. The analysis jobs stay in the same job registry as every other job.

**Story Lab planning left the main server file.** Checking a story stage, normalising its ids, and the problem checks now live with the Story Lab schema. Analysing uploaded images, generating one stage, translating lyrics, and starting, reading, resuming and cancelling a Story Lab job are the same routes with the same answers. The job list, the set of jobs that are running, and their lock live in one place, and the main server still uses those same objects. A plan still writes the same checkpoints and still shows up in Activity. The comic page check it relies on lives with the comic helpers. The core server does not plan a Story.

**Director music and character-reference description left the launch module.** Asking for a song, or for a description of character reference images, still answers the same way. An empty description still asks for the images. An empty music request still stops before any track is generated.

**Presets, system settings, and service settings left the launch module.** Saving a preset, changing a memory profile, and reading or updating service settings still answer the same way. An empty update is still refused. The core server keeps its own copies of the settings routes it already served.

**Upscale and revoice left the launch module.** Asking the full server to upscale a clip or replace its voice still answers the same way, including a request it refuses before any model work. The core server still blocks those two routes when the local tool is not available.

**System status, hardware detection, and model release left the launch module.** The full server still answers the same system stats, hardware detection and apply, preflight, runtime capabilities, resource lanes, WanGP processor list, debug user-action, and release-model requests. The core server keeps its own torch-free copies of the routes it already served.

**The core server lists the gallery the same way as the full server, and shares the 3D model and rig routes.** On core, the gallery can be searched, ordered oldest first, and filtered by where a clip came from and what kind of result it is. An image row includes its width and height. Saving the core configuration, which holds API keys, now replaces the file atomically and leaves it readable only by its owner. Core can delete a workspace, and creating one creates the folder. A missing output answers "File not found", the same text as the full server. Generating a 3D model or a rig uses the same routes on both servers. A rig keeps the provenance of the submission, accepts a model that was uploaded, and publishes an Activity task. A finished remote model job writes an asset manifest and an Activity task. A Hi3D prompt with no photo draws a still through MiniMax when that image provider is configured, and a request the execution mode refuses answers 409. The full server's answers for these routes do not change. Choosing which files a model download needs now lives in one helper; the full server still downloads the same files.

**The core server uses the full server's Series library.** Deleting a series or an episode answers 409 while one of its jobs is still active, and the series stays. The episode list includes an episode that no season lists. Approving canon checks the world summary, the cast and the locations as three separate answers, and a stale canon revision names the current revision. An imported asset has to be a real file under the uploads folder, given by the full path the upload route returns; a bare file name no longer works. An unknown kind is stored as other, a missing character, location, prop, episode or shot answers 404, a metadata key is kept to 100 characters, and metadata cannot replace the reference role or the import time. The core server also answers canon commit, reference routing, shot duration preview, and attempt approve, bulk approve and reject. Those are the routes the Series UI already calls.

**Series render jobs left the main server file.** Starting a Series render, reading it, cancelling it, resuming it, discarding it, and listing renders that can be recovered are the same routes with the same answers. The job list, the set of renders that are running, and their lock live in one place, and the main server still uses those same objects. A render still takes the GPU slot the same way, writes status in the same order, and recovers the same checkpoints. The render still shows up in Activity. The core server does not render a Series.

**The core server plans a Series with the same jobs as the full server.** A stage that breaks a production rule is sent back to the model, up to two extra tries, and a broken JSON answer is repaired before that. Resuming a plan re-checks stages that already finished. A later episode is planned with a summary of the earlier ones. Cancelling a running plan stays cancelled, and a second worker cannot pick up a job that already has one. An edited proposal cannot change internal ids. Applying a plan keeps the canon snapshot and writes the reference manifest for each shot. Starting a plan checks the series again under the library lock, so a delete that wins answers 404. The job shows up in Activity. The core server answers the recovery list and can discard a plan job. Preparing canon answers 400 when the title, the premise or the visual style is missing, where it used to start a job that failed. Plan apply uses the same library lock as a series edit, so one cannot drop the other.

**Generation, the job queue, and Director pipeline reconnect left the main Studio store.** Starting a picture, a video, speech, music, a sound effect, or an avatar edit still uses the same Generate button, including a prompt split across several lines. Stopping a job, dismissing one, and picking the queue back up after a reload still work the same way. A Director pipeline still checks its own progress and reconnects on its own. Director post-processing, the storage manager, the LoRA list sort, the streaming text from the language model, and the Viggle restore message now sit with the code that uses them. The screen still reads and writes all of it through the same `useStore` hook. The main store file only wires the slices together.

**Loading a finished clip's settings, and the Studio form, left the main Studio store.** Opening an output still fills in the same mode, model, prompt, and edit settings. Switching mode, changing a setting, picking a model, and resetting Image Studio still work the same way. The screen still reads and writes them through the same `useStore` hook.

**The full server's shared state now lives in a kernel package (no behaviour change).** The workspace helpers, the generation job registry with its GPU queue, abort states and durable queue, the atomic save of the server configuration, the path and upload rules and the canonical task accessor moved out of `app/_launch_runtime.py` into `app/services/kernel/`. The full server builds one runtime context right after it binds WanGP and keeps its old names as aliases to the same objects, so every route and worker still shares one job dictionary, one GPU lock and one durable queue. `tests/test_import_layers.py` now enforces the import rules: a service does not import a router, nothing but the two servers imports a server file, and the kernel imports only its allowed neighbours. The Director pipeline no longer imports the server file: it is handed the server's cached hardware probe, and when that probe failed it measures the hardware again itself, as it did before.

**Music-video Director actions, and five Studio edit submissions, left the main Studio store.** Blend, outpaint, restyle, recast, and retake, inpaint, or edit-anything still start from the same Generate button. Adopting or uploading a track, writing a song, planning a music video, generating start images, and generating the video still work the same way. The screen still reads and writes them through the same `useStore` hook.

**The core server shares five more paths with the full server.** Saving a production profile still uses each server's own checker and default model. The shared model loader reloads the client when a DeepSeek URL changes, and the Director sends the DeepSeek key and reloads when the local device changes. Core keeps its local-LLM gate and its MiniMax-M3 default. A scene recording on core now transcodes off the request thread, two jobs at a time, refuses an oversized upload before reading it, and drops that folder from the output scan cache. Returned scene URLs on the full server still have no workspace query. A Series asset path that points at a missing file fails closed on both servers. Director plan prompts, angle prompts, and the pipeline list, active, get, and status routes are one router. On core, a stale running checkpoint is listed as crashed and the status carries the same summary and preview fields as the full server; starting, continuing, or rerunning a pipeline stays blocked. Story music jobs use one store and one router. Core still answers 409 when local music is unavailable. It now reserves a music attempt, replays a repeated idempotency key without a second worker, reloads an interrupted job from its checkpoint, and publishes the job and its candidates to Activity. Candidates are generated one at a time.

**The Director dashboard, short-film planning, the Director pipeline, and Studio video editing left the main Studio store.** Opening the pipeline dashboard, planning a short film, and starting or continuing a Director pipeline still work the same way. Studio edit, continue, blend, and outpaint, including sending a frame to Image mode and applying it back as an anchor, still work the same way. The screen still reads and writes them through the same `useStore` hook.

**The model catalog, which models are shown, and the selected model's options left the main Studio store.** Loading the catalog, showing or hiding a model, and filling in that model's settings still work the same way. The screen still reads and writes them through the same `useStore` hook.

**The core server edits video, keeps Wizard work, and reports the same machine identity as the full server.** On a Mac, or any machine without a local AI recipe, the core server now mounts the same video editor as the full server. A timeline can use Video 2D layers, an export stays inside the workspace, a clip with an invalid trim is rejected, and an export can be cancelled. The core MCP endpoint uses the same router as the full server. A non-ASCII authorization header is refused instead of failing the request, a call is attributed to the external agent, tool answers can include structured content, and status reports a real remote job. Wizard conversations and workflows are saved by the same router on both servers. A workspace name that is not allowed still answers 400. Saving a conversation as a JSON array, which the core server used to reject as 400, now answers 422, the same as the full server. System stats on core include the runtime identity, so an open tab can tell that the server restarted, and they include the GPU compute percent. Memory figures use the same two-decimal rounding as the full server, and a machine with an NVIDIA GPU reports that GPU instead of a blank reading. Starting the core server binds its port before it prints the address, moves to the next free port when that port is taken, writes `settings/server-endpoint.json`, and prints the same address banner as the full server. A task update on core can complete a task the ordinary status rules would refuse, and it keeps that task's reserved title and workflow. A finished 3D model job records the same lineage references, and a provider default, as a Studio job.

**Tools, recipes, services, and LoRAs left the main Studio store.** Those controls still show up in the same places, and the screen still reads and writes them through the same `useStore` hook. Saving a mode's settings, including the chosen model and the LoRAs that were on, works the same way as before.

**The Studio store is starting to split.** System settings, generation presets, foreground activity, and the CivitAI browser now live in their own slices. The screen still reads and writes them through the same `useStore` hook.

**Security fix: the macOS "core" server no longer serves uploaded pages and
scripts as pages of the app.** On the core server, `POST /api/v1/upload` kept
any extension, so an uploaded `x.html`, `x.svg` or `x.js` was stored under that
name and `GET /api/v1/uploads/...` sent it to the browser as a page on the
app's own address (stored cross-site scripting). Both servers now use one
uploads router, `app/routers/uploads.py`: only the known media, model, text and
archive extensions are kept, every other name is stored as `.bin`, and every
file it serves back carries `X-Content-Type-Options: nosniff`. The full server already did
this, so its answers do not change. The core server also gets what the full
server had: files are streamed to disk instead of held in memory (500 MB cap),
a name that is not an upload falls back to the workspace outputs, MP3, M4A and
AAC files become WAV (with the ffmpeg program when the install has no
ffmpeg-python package, as the core install does), and a video upload reports its `fps`, `frame_count`,
`duration_seconds` and `has_audio`. The core server's old raw-body upload
(`?filename=`) and a multipart upload without a `file` part now answer `422`,
as on the full server, and `GET /api/v1/uploads/` no longer accepts a name with
slashes in it. Core also had four wrong or hidden routes, now fixed: `POST
/api/v1/llm/load` ignored the stored provider key and the LLM routing and loaded
with an empty key; `GET /api/v1/series/{id}` and `POST /api/v1/llm/plan-h3-windows`
were each defined twice, so one copy never ran; and `GET /api/v1/jobs/recovery`
offered the jobs that were running as leftovers of a crash, which the recovery
dialog would have offered to resume. It now answers an empty list.

**The Wizard says which defaults it chose, and no longer invents a "cinematic" style.** When the Wizard creates a Story or a Series from a short request, it still does not stop to ask about style, model, duration or format, but it now says so: if the style or the tone was left unset, its reply ends with one line ("Choices I made: style not set (the model decides), tone not set. Tell me if you want something else.") and lists only what really stayed empty. Before, it filled the style with a generic sentence ("Coherent cinematic direction..."), the tone with "Cinematic" and a Series camera with a television camera language. Story Lab then turned that sentence into a "VISUAL STYLE LOCK" prefix on every image and video prompt, so every Wizard story looked like the same "cinematic TV". Now a Story or Series made by the Wizard with no style has an empty style (no lock), an empty tone and an empty camera language; new projects made by hand also start with an empty tone, and a style or tone you write is kept exactly. The Story Lab writer and the Comic planner leave the "Tone:" line out of their prompt when there is no tone. Projects already saved keep what they have. Risk: a Wizard story with no style gets no style lock from Story Lab, so its look can drift between shots until you write one; the reply line tells you. The same holds when such a story is staged for the Director: with no style of its own it is staged with no style (before, the Director's own sentence "Match the approved Story reference artwork exactly... keep it illustrated..." took its place and became a lock that forced an illustrated look), so the Director adds no style lock. A story that has a style it does not enforce keeps that sentence.

**A safety net for the coming split of the two largest files (no behaviour
change).** Tests can now import the full server with a fake WanGP engine, with
no GPU. `tests/characterization` records what read-only routes answer
(workspaces, Series, jobs and tasks, the model catalog, the gallery, the video
editor probes and settings) and which routes the server serves, so each PR that
moves code out of `_launch_runtime.py` or `useStore.ts` can prove it changed
nothing. CI runs these tests in their own step. The static route table now
follows routers that include other routers and requires literal route paths;
the four Series shot routes written as f-strings are now literals with the same
paths. `scripts/size_ceilings.json` caps the line count of `_launch_runtime.py`,
`core_runtime.py` and `useStore.ts`, and the caps can only go down.
`scripts/boot_smoke.sh` boots a worktree on a free port with its own folders and
no model, checks its routes and stops it by its process id; it puts the
worktree back even when it is interrupted, also by Ctrl+C in the middle of a
rename or of the cleanup. It refuses a worktree whose full or core server
already runs, and `--cpu` without `--core` (the full server needs a GPU).
Neither the boot smoke nor the test harness touches the live install's temp
folder (the server sweeps old `hocuspocus-*` folders out of it at start) or its
Numba cache. A test checks the fake engine's names and parameters against the
real WanGP source, also for a function WanGP imports from another module, so
the fake cannot drift unnoticed.

**New stories, series, songs, and comics follow the interface language.** A new project uses the language selected in the UI, which is English on a fresh install. The server uses English when a request does not name a language. A project that already has a language keeps it. A saved project without a language label takes it from its saved language intent, then English; the UI language is never used for saved work. Wizard replies, progress text, errors, and the remaining Spanish labels in Studio, Story Lab, Series Lab, Comics, the video editor, Video 3D templates, and Settings now come from the English and Spanish catalogs. The game asset list also accepts English option words (`player`, `enemy`, `boss`, `effect`, `layers 3`, `variants 3`, `loop 60 s`, `size 64`, `method strip`, `anim spin`), so the English example list in the paste dialog parses.

**Director's hidden house rules are now visible.** With no reference image,
Director still draws one shared picture from shot 1 and draws every shot from
it, but the Dashboard now shows that picture, its prompt and the run's options
above the shots, and can replace it with another image of the run or stop
using it for repairs and reruns. Settings › Services › *Director shared
reference* chooses Always (default), Only when there are no character
references, or Off (each shot from its own prompt); a run can override it with
`reference_anchor`, and the step-by-step Director chat follows it too. The
shared picture's prompt no longer says "cinematic".
"Use lighting and color temp from reference image" is gone from the guide used
when no reference exists, and elsewhere it follows *Light from the reference*
(default: only with your own reference image, so a story with character
portraits alone no longer copies the anchor's light). *Keep clothes from
references* (on by default) can be turned off to describe clothes per shot;
the clothing words then also survive the optional third-pass polish.
*Raw prompts* now also skips the planner's cleanup of image prompts, as its
description promised; otherwise Extra info says how many clothing words,
motion sentences and filler phrases that cleanup removed. The music-video
treatment shows its coverage cycle and what choruses do (return to the first
set by default, rotate through the sets, or the planner chooses), and the
Dashboard shows each shot's planned set and coverage. When the planner returns
no shots and Director builds a simple plan itself, the Dashboard says so and
that plan no longer says "cinematic" either.

**The code-health check now recognizes moved code and no longer misses new
folders.** It checks every pull request against its base, and the coming
refactor moves functions out of `_launch_runtime.py` and `useStore.ts`. Before,
moving a complex function word for word into a new file failed as a "new
complexity hotspot", and nothing could waive that. Now the check records a
fingerprint of each complex function. A Python function that moves with the
same name and the same code is reported as `moved: X from A to B` and passes.
Comments, docstrings and the route decorator may differ. A UI function passes
when it keeps its name and its complexity does not rise. A changed body, a
rise in complexity or a copy left behind still counts as new code. The limit of
five new complex functions per pull request no longer counts pieces split out
of an existing function, as long as that function gets simpler by at least as
much and the pull request adds no logic overall. The development → main
release check gives the same split credit at each merge. A new file over 1,200
lines still fails, moved or not. The check also fails when Python code is added
under `app/` in a folder it does not measure (for example a new
`app/features/`). Vendored engine folders and the eleven files that are already
outside the measured folders are exempt, but those eleven files can no longer
grow by more than 75 lines (in a pull request, or over a development → main
release) or gain a complex function, and new vendored files are listed for
reviewers. A waiver now covers only its own rule and exactly its file, and its
expiry must be a real date. No limit changed.

**Music videos show their defaults, and the agent can change them.** Auto-planned
music videos no longer turn the brief's call to action into every chorus's sung
action, or its theme into every verse's: the theme is now only where the shots take
place (`section_actions.scene`) and the call to action stays on the end cards. Content
shots no longer share one "Wide cinematic shot… slow camera" text: they rotate four
framings, each with its own camera move in words (H3 makes the move), and a trailer
beat opens on a framing of its own scale. `dry_run` shows what the planner filled in
(`auto_plan`), which windows are sung, and each trailer beat's action.
`spec.video` picks the H3 model and steps (Fused Turbo at 4 steps stays the
default; base, full and legacy H3 can be chosen; steps must be in the model's range,
4-8 for Fused Turbo); `dry_run` and `production.status` show it as `video_model`, and
a change shoots the kept clips of unlocked shots again instead of mixing models, while
going back to the earlier model keeps the clips it shot. Painted sets keep the
empty-floor recipe by default and can ask for a `backdrop` or no staging
(`sets.<name>.staging`); `dry_run` shows each set's prompt and the look sentences it
leaves out, and a look that names its medium or material ("figurine look",
"doll-like", "cast iron") keeps it. Productions that already ran resume unchanged:
the same spec, seeds and jobs, and no set or clip is made again. A new set, or a model
drawn from a prompt, whose look names a figurine or doll medium now keeps that
sentence, and a sentence about a crowd is now left out. A scene2d shot that draws its
own background from such a look draws it again on its next run (lock the shot to
keep it).

**Music never uses paid MiniMax by default.** Every music default is now the local,
free ACE-Step 1.5 XL model, the one Studio and `production.*` already use. The paid
MiniMax API models (`music-3.0`, `music-2.6` and covers) run only when you pick one
in Story Lab, where they are labelled "MiniMax API (paid)", and confirm the cost
before each request. The Wizard, MCP tools, `production.*` specs and the core
profile no longer offer them and refuse an explicit request with the local model
IDs to use instead. Stories saved with `music-3.0` as their old default now read as
the local model and Story Lab tells you so; the file on disk is not rewritten.
`media.options` lists the installed local music models.

**Honest defaults.** Regenerate makes something new: a Director image, clip or
H3 segment rerun draws a fresh seed and records it, so the seed shown is the one
that made the result (comic films keep the seed their approved PRE pinned). Every
new `production.*` run draws its own seed base, kept in its record, so two
productions no longer start from the same noise and a resume asks for the same
jobs; Hunyuan3D and the external 3D engines draw a seed when none is set (-1),
and a game asset's Regenerate gets its own. Auto-planned music videos give each
sung shot its own framing and seed, and a style with no named look keeps the
brief's own words instead of falling back to anime. Published pages no longer
carry another production's tagline or Nintendo disclaimer.

**Prompts reach the model as written.** Director prompt polish is off by
default (opt-in in Settings › Services); the 1,450-character cut is gone (only
MiniMax Image-01 needs one, and its own `prepare_prompt` keeps it); a prompt the
user types for a rerun, changes at the review pause or approves in the
direct-video review screen keeps the lettering it asks for. *Raw prompts* in
Settings › Services sends every Director prompt exactly as planned: no
art-style prefix, locks, motion-word removal or polish, in planning (the plan
endpoint, the orchestrator and the legacy planner), after the review pause, in
the H3 validation pass and on every rerun; the planner's own words are not
compressed either. Continuity anchors of bounded shots, the spoken-language
line and H3's own contracts still apply. When a model handler rewrites a
prompt (H3 window timing, outpainting), Extra info shows *What the model
received* for each window. Until a production profile is saved, a dismissible
notice says which providers text and pictures use; a saved profile that cannot
be read is reported instead of silently replaced.

**Narrower Director layers.** The no-visible-text lock now goes only on music
videos, where planners used to put the song's lyrics on screen, and only on the
prompts the LLM wrote. Stories, audio short films and comic movies send their
prompts without it. A direct-video H3 segment the user types keeps its
lettering too, and so does a regenerated H3 segment of a shot the user typed at
the review pause. The project's *allow text* switch still turns the lock off. The
"Maintain the same … art style." prefix, and the vision call that names the
reference's style for it, are used only with Flux.2 Klein models, the only ones
it was tested with, and the call is skipped with *Raw prompts*. Other image
models get the prompt as planned.

The Video Editor routes now come from one place. The main server mounts the
extracted Video Editor router and the second copy inside the launch runtime is
gone, with the same paths, answers and job list as before. Saved montages and
the agent that asked still reach the export's metadata. A new CI test fails when
a router is not mounted and not listed with a reason, when a server defines the
same method and path twice, or when a route of the core server or the route table
is missing from the main server. A new UI check (`npm run unreachable:check`, in
CI) fails when a file in `ui/src` cannot be reached from an entry point and is not
listed with a reason; 11 files that nothing used are deleted.

**A hard rule about minors is now in every LLM system prompt, with NSFW mode on or
off.** It forbids sexual or sexualized content with minors or with characters who
look like or are described as minors, whatever the fiction, claimed age or art
style, and asks for clearly adult characters in any sexual content. The LLM service
adds it to every request to every provider, so Director, Story, Series, Wizard,
comics, songs, production commands and the prompts the UI sends all carry it; the
WanGP prompt enhancer adds it too. The PG-13 rules that NSFW-off mode used to add
are gone (`nsfw_off_safety_rules.md`, the inline PG-13 enhance text,
`get_safe_content_guidance` and the unused `PUBLIC_PROVIDERS`). The NSFW toggle
itself does not change: it still filters models and LoRAs and still adds the
mature-content guides. The Director shot-length examples about sex scenes and
the undressing examples in the Qwen image-edit guide now appear only with NSFW on.

**A quality-gate refusal now says what to fix, and there is an explicit way past
it.** When `production.run` refuses a plan before any GPU work (`quality_gate`),
the message no longer just says "the plan would look thin". It names the shots,
the picture, model or camera involved and the limit, and says how to fix each
problem. The three checks that only make a video look static still refuse by
default: one still picture in three or more shots, too much of the song on still
pictures, and a full-frame title over a moving shot. Send `allow_thin: true` to
run such a plan anyway; those problems come back as warnings, and
`production.status` lists them as `allow_thin` while that spec runs. A clip a
model will not have, or a camera that does not exist, is always refused. The dry
run takes the same flag and reports the same warnings, each problem once. The MCP
schema now declares `allow_thin`, and it accepts `allow: ["title_card"]`, which
the gate already honoured. A dry run names a shot with no key by its place
(`shots[2]`).

**Series video resolution can be chosen, 480p by default.** The H3 clips that a
Series script asks for were always 480p. Series setup now has a *Script video clip
resolution* (480p, 540p, 720p or 768p), and each video shot can pick its own size in
its editor, with `series.shot.update`, or in the script (`resolution`). The
backend's own default for the Series Lab render is now 480p too, as the setup screen
already showed (a series that follows the global production profile still takes the
profile's size), and H3 now keeps a 540p or 768p choice instead of rendering it at
720p. Shots and takes made before this change keep their digests, so nothing already
made is generated again. A series on H3 (not H3 Legacy) saved at 540p or 768p now
renders its new takes at that size; its earlier takes stay 1280x704, and the cut
scales every clip to the episode frame. Choose 720p to keep the old size.

**Series camera, finish and episode format are now visible choices.** A 2D Series
shot could only hold still or push in, every 2D shot got the same paper finish, and
agents were told one fixed episode shape. The camera can now also pull out, pan left,
pan right or drift (in the shot's *Framing and timing*, `series.shot.update` and the
script's `camera`); a pan or drift frames the plate a little closer so its edge never
shows. The finish is chosen for the series in Setup (`look.finish`: paper, none, any
Video 2D finish such as film or noir, without its letterbox bars, or an agent's own
amounts) and for one shot.
Setup also has an *Episode format*: the episode planner and agents follow it, and
when it is empty agents keep the default sitcom format, which Setup now shows.
Nothing changes for a series that chooses nothing: paper stays the default, only a
camera's own name (`pan-left`) moves it, so words such as "slow pan" stored in old
shots still render static, and every stored shot keeps its digests, takes and
approvals.

**VoxCPM2 is the default voice engine.** Once its weights are installed, Studio
speech, the Wizard, scene recipes, lip previews and game voices use *VoxCPM2 Voice
Design*, and the Character Creator voice designer and new reference voices start on
VoxCPM2. Installs without it keep KugelAudio in Studio; Qwen3 stays available
everywhere, and saved character voices keep their engine.

**VoxCPM2** joins the local speech engines next to Qwen3 TTS: OpenBMB's 2B model
speaks 30 languages at 48 kHz. *VoxCPM2 Voice Design* makes a voice from a written
description and *VoxCPM2 Voice Clone* clones a recording (with its transcript for
the closest match), with two-voice dialogue and an optional speaking style. The
Character Creator voice designer and reference voices can pick it as their engine,
and series lines, auditions, Studio, Wizard and MCP `generation.speech` use it like
Qwen3. Weights (~5 GB) download on first use. See [VoxCPM2](docs/development/VOXCPM2.md).

Story Lab and Series Lab add optional **Help me write** panels with essential
questions, examples, missing-answer suggestions, section development and editorial
review. Answers share existing story fields; editable proposals persist until
reviewed, apply by field and support guarded undo. Episode advice respects frozen
canon. See the [writing guide](docs/story-lab/WRITING_GUIDE.md).

Every Video 3D shot card now tells an agent what the built shot does, read from
the document itself: `shot` (close, medium, wide, far, plate) with the camera
distance, `moves` (push, pull, slide, rise, descend, arc, orbit, zoom, roll,
ride, track, shake), `moving` (what the template animates on its own), `still`,
`subjects`, `props`, `screens`, `authoredFor`, `floor`, `uses` (dialogue, talk,
reaction, figure, establishing, action, reveal, product, music, drive,
transition, title, look, plate) and the authored requirement notes of the
action, campaign and anime shots. `world3d.templates.list`, `catalog` and
`apply_query` understand intent words in Spanish or English («diálogo», «plano
general», «persecución», «girar alrededor») through one shared vocabulary, ignore
the words that name the search itself, rank a literal word over its synonyms,
match plurals, take the filters `shot`, `use`, `move`, `subjects` and `format`,
accept a tag as `category`, and return the best cards marked `partial` when no
card has every word (never applied, never planned). Lines are no longer cut at
180 characters, three pairs of shots no longer share a title, the editor's
gallery search finds shots by the same traits, and a production dry run warns
`template_still` when a shot uses a template that animates nothing without a
clip, a motion, a camera or a world. See
[Video 3D templates for agents](docs/development/WORLD3D_TEMPLATES_AGENTS.md).

The Video 3D library is chosen on axes instead of a flat list. Every card now
carries `kind` (scene, stage, camera, look, transition, title), `place` (a
dressing, world or mold id), `travel` (a subject crosses the set), a `reference`
film still of the real technique and, on stages, `cameras`; `uses` gains `speed`
and `impact`, and `dialogue` and `reaction` follow stricter rules. The search
reads both languages through one vocabulary whose place words are split the way
a director tells places apart (kitchen, bedroom, office, classroom, bar, church,
hospital, court, TV studio, street, rooftop, forest, sea, space...), plus
emotions, walking, sitting, entering and crowds; every reply lists
`unknown_words`, which never count against the match, and returns the best cards
with at least half of the known words as `partial` when none has them all. New
filters `kind`, `place` and `travel` on `world3d.templates.list`, `catalog` and
`apply_query`, and a read-only `world3d.templates.suggest` that takes a shot as a
writer phrases it (`line`, `speakers`, `place`, `mood`, `beat`, `format`, `kind`)
and returns up to three cards with a `reason` in plain words, reachable from
MCP, the Series profile and the Wizard.

Room molds become shots. Thirteen shape molds (`sala`, `sala_ventana`,
`mostrador`, `filas`, `pasillo`, `umbral`, `escalera`, `escenario_publico`,
`vehiculo` and the exteriors `calle`, `plaza`, `orilla`, `azotea`, with no
ceiling and a sun preset) join the fifteen named interiors, and every mold is a
`stage-<mold>` card (`kind: stage`) with its cameras, speaking marks and a
measured shot, accepted by `world3d.templates.get`, `world3d.scene.instantiate`,
`apply_query`, a production `scene3d.template` and a Series `kind: "3d"` shot
(`roomCamera` picks the camera; the location's set brings the skin). Every
staged room carries dust motes and a key light that breathes, so no stage is
still.

Six packs of short cards by intent, 32 in all: `transition-*` (whip pan, iris
in, flash white, wipe by a prop, match on shape, eyecatch, smash in, rise off;
0.6–2.5 s), `speed-*` (run toward camera, foot chase, fly-by, rush lines, side
dash), `dialogue-*` (over-the-shoulder A and B with matched eyelines, table,
triangle, embrace, phone split), `reaction-*` (push, orbit, turn to camera, look
up, impact), `group-*` (arc of five, line of four, performer with audience,
circle) and `title-*` (lower third, kinetic title, chapter card, end card). Their
traits are read from the built documents like every other card's; the catalog
holds 801 cards plus the 28 stages.

Named modifiers on any Video 3D shot, shared by the production compiler and
`world3d.scene.patch` through `app/shared/world3d_modifiers.json`: `light` (21
names from `noon` to `dawn`, or a directional light object), `grade` (`natural`,
`teal_orange`, `bleach`, `noir`, `sepia`, `flashback`, `dream`, `giallo`, `cold`,
`warm`, `vhs`, `film`: exposure and tone mapping, a gel over the lamp and
existing screen effects), `lens` (`14mm` to `200mm`: the camera fov, with a
framing's fov move scaled) and `camera_template` (a `kind: camera` card whose
camera and framing any shot takes while keeping its duration, cast and place).
The honest effect cards (`cine-film-grain`, `cine-vignette`, `cine-lens-flare`)
now carry the screen effect that does the thing.

Production dry runs warn `stage_unskinned` when a stage or room shows only its
mold colours and `looks_samey` when the same template and background run for
more than four shots in a row, next to `template_still` and `template_reused`.
The contract behind all of it is
[TEMPLATE_LIBRARY_MODEL.md](docs/development/TEMPLATE_LIBRARY_MODEL.md).

Every shipped and stage card's `preview` is now the URL of our own picture of
the shot, `GET /api/v1/world3d/templates/{id}/thumbnail`: the built template at
mid-shot, 640×360 (portrait 360×640) WebP, painted by the same headless renderer
as the 3D export with empty slots drawn as the editor's placeholders, and cached
in the outputs' `.world3d-thumbs` once per template version (the compiled
document and `RENDER_RECIPE`). One picture renders at a time; when it cannot be
painted now the route answers 503 `thumbnail_unavailable` with `retryable: true`,
never a broken image. `world3d.templates.get` returns `previewUrl`; `reference`
stays a film still for inspiration. `scripts/render_template_thumbnails.py`
pre-warms the cache of a running instance and reports times and failures.
A card that shows optional example media this installation has not downloaded
(122 of 829 cards use the creative, dark-fantasy and other collections) answers
409 `examples_not_installed` with the `collections` to download, at once and
without a render; the pre-warm reports it as skipped. Before, each one held the
render lane for minutes. The shipped scene `stage-crane` compiles again: only an
existing mold makes a `stage-<mold>` id.

A picture bound where a model stood through `world3d.scene.patch` (Series and
MCP) now turns toward the camera as a production cast does: at most 60° from
facing it along the shot, unless the binding gives `rotationY`. The editor's
«All» shelf ends with the stages that match the search, and the Stages shelf
reads every page of stages instead of the first 50. The humanoid auto-rig no
longer takes a dress's waist for the neck when long hair half hides the neck: a
neck that would leave more than a third of the figure above it gives way to a
notch higher up. The pilot doll's Head bone moves from 66 % to 87 % of its
height and its shoulders become level. `RIG_VERSION` 5, so a production rigs
its GLB humanoids again on the next run.

Video 3D adds eight complete procedural motion sets: beat landings, a contact
music machine, sunset flight, a seasonal carriage, data assembly, a lighthouse
journey, volumetric poster lettering and particle morph typography. Editor, MCP
and Wizard share their controls; visible music contacts and local notes share
one deterministic timeline. MCP previews rasterize the native geometry. See
[native motion templates](docs/development/WORLD3D_MOTION_LAB.md).

Series approvals keep pending note drafts and ignore saves and render polls
from another episode. Changed dialogue pauses and saved 3D scenes invalidate
their takes; reviewed imported/generated videos promote correctly and prepare
their foley. Media tools serialize retries and publication, and Wizard and
Production use the shared command paths in full and Core runtimes. Failed
named asset publication restores the previous files. New named scene export
receipts verify their exact video bytes, including on download; an overwritten
version is reported unavailable. GPU profile checks respect visible-device
identity and report uncertain CUDA ordering explicitly. See the
[audit corrections and regression tests](docs/development/DEVELOPMENT_AUDIT_FIXES_2026-10-07.md).
Release code-health verification fingerprints the analyzer dependency graph
and installation hooks, allowing unrelated type-package cleanup while keeping
the existing budgets and historical checks. Eye detection, frozen canon snapshots
and frame encoding move to focused helpers; smaller rig and score functions clear
the release gates without changing their limits.

Series 2D shots keep look room: HocusPocus now knows which way each pose looks
(left, right or front), read on the pose's face with DWPose on the CPU or set on
the kit pose as `facing`; the flat rig stores it on each pose and the series
bible lists it. `series.episode.from_script` stands a character facing left
right of centre and one facing right left of it, swaps two people who look away
from each other, and reports every move (`lookRoom`) and who still looks out
(`lookRoomKept`: three or more people, a pose held on its cut side by edge snap).
`lookRoom: false` on a cast entry or a shot keeps its `x`; `series.shot.update`
never moves anyone and only warns.

Series Lab's **5 · Validation** tab is now a grid of every shot of the episode,
grouped by scene: each tile shows the shot's latest take (or its plan sketched
from the location and the cast's poses when nothing is rendered), its number,
length, method and review state, a quick approve and a clear **Open**. An opened
shot (the shot inspector) plays its take on top, with the other takes to switch
to, its review and notes, and one call to action, **Re-render this shot**, that
says what it regenerates (the voice of the lines that changed, the 2D or 3D
scene, its foley). Below it every part of the shot has its own section with
**Edit**: characters on screen (pose, position, entrance; Open goes to the
character's face rig on that pose and comes back to the shot), dialogue (speaker,
text in every language, emotion, delivery, pause, room; each line plays and can
be recorded again on its own), location and set (variant, the location's
background chosen or generated, set layers), props, screen effects, sound effects
(in/length, on a line or an entrance; they play), music, foley and the voices'
room (with the episode score and the location ambience it plays under), framing
and timing, title cards, the 3D scene (its objects, clips and hand holds; **Edit
in Video 3D** opens the shot's own scene and saving there writes it back to the
shot), a generated or imported clip (its prompt, start frame and seed, how its
own sound plays at the cut, another clip as its take) and the takes (use one,
open its Video 2D or 3D scene). Each part saves through the shot edit, so it is
checked like a script shot and resets the shot's approvals; an unsaved edit is
kept across a trip to an editor and shown on the tile. Arrows go to the previous
and next shot, Escape closes, and it fits a phone. Agents record one line with
`series.shot.voice` (+ `.status`; `series.shot.voices` lists each line's
recording) and the Wizard with `regenerate_series_line_voice`.

What agents and the Wizard make is easier to find, open and trace back. The
Wizard's own changes (a Character Kit, a story, a series episode, a Video 3D
template or scene) get a row in Activity's Agents view, badged Wizard, with
buttons that open each one. The gallery details say who made a file (an agent
and its tool, or the Wizard), a song's style, a line's voice and language, what
a tool output was made from, and the saved scene or montage behind an export;
feed cards badge agent work. A Video 2D or 3D export names the saved scene file
it rendered, and an agent's scene without a picture takes the export's middle
frame as its preview. Series shot exports keep the shot id in their name
(`…_video2d-Plus-Ultra-Mas-alla-del-Plan-La-confesion-e1s163_…`), published
Video 3D scenes are named after their template, and the Video 3D Open dialog
lists the working scenes an agent never published. A montage export has **Edit
montage**, and the Wizard saves its Video Editor draft as a montage before
exporting it. `audio.shorten` and the flat-rig images have provenance sidecars
like `studio.key`. Takes record who approved them (`approvedBy`: a person, an
agent, the Wizard or the render itself) and Render & Review shows it; the
staged review's plan and preview decisions record who made them
(`planBy`, `previewBy`) and the Validation cards show it; music production
reviews say whether people or agents decided. Render & Review also
lists the episode's productions with their steps, chapter files, Stop and
Resume.

The last open items of that work are done. What the language model translates
in a series language version is marked **Machine translation** per line, card
and title (with who asked for it) until a person edits it or marks it
**Checked**; Language versions now also shows and edits the version's title and
cards. Every script `series.episode.from_script` writes is kept per episode as
it was sent, with who sent it: the Episode tab lists the revisions, shows and
downloads each one, and rewrites the episode from it (checked against the
series first), and agents read them with `series.episode.script.get`. A music
production card links the page `production.publish` made, says when it is a
review preview and who published it. The gallery listing carries each file's
`origin`, so **Media → Made by agents** lists what agents and the Wizard asked
for and grid tiles badge it.

Series Lab can make an episode in three production modes, and the user
validates every shot from inside HocusPocus, also from a phone over the LAN.
`direct` renders everything, as before, and is what every existing episode
is. `plan` asks for each shot's plan (cast and poses, lines and speakers,
framing, camera, set, effects) to be approved before it renders. `preview`
adds a preview render that the user approves or sends back with notes before
the final: a 2D shot's preview is its normal render and is promoted to the
final take without rendering again, a 3D shot's preview is exported at draft
quality and its final at the shot's own. The new **5 · Validation** tab shows
every shot in order, grouped by scene, as a card with its latest take (played
in place), number, method, duration, location, framing, camera, cast with
poses, lines with speakers and a summary of its effects, sounds, set layers or
3D template, with Approve / Request change, a notes box that saves itself,
filters, a progress counter and the next step of the episode. A card edits
its shot in place, opens exactly its take's scene in the Video 2D or Video 3D
editor and takes the export back as the shot's take, renders it again, and
opens each character's Face Rig on the pose the shot uses. The review is the
server's (`episode.review`): a change to a shot's content puts its approvals
back to pending and keeps the notes, `series.episode.render_native` and
`series.episode.produce` render only what the review lets through (the rest
is listed as waiting, not failed; a production stops as `waiting` before the
cut and resumes after the approvals), and the assembly of a staged episode is
refused until it is approved unless forced. Agents read the user's requests
and answer them with `series.episode.review.get`, `series.episode.review.set`
and `series.shot.review.set`.

Painted characters that talk with their own drawing are now a repeatable path.
Character Creator has a **Graphic novel (painted)** style (`graphic-novel`,
also in MCP `characters.styles`): bold ink, flat black shadows, both eyes with
clean white sclera out of the shadow and the rest mouth painted as one short
line, on a plain screen, so the rig finds the eyes and the mouth. Its rig look
is `{"mouthStyle": "warp"}`: saving a character rigs it with warp mouths, and
the rig review names the poses whose mouth line was guessed or unsure, to place
by hand in Prepare 2D speech › **Mouth line**. A kit also keeps its look: every
`style` key a `characters.rig.flat` call leaves out is the kit's (its last
rig's, else the rig of the preset it was made in), so adding a pose or an
agent's re-rig no longer turns warp mouths back into paper ones; only
`style.mouthStyle` changes them, and the result's `style` is the look used.
The agent guide (`series.guide`) and the Wizard describe the path, what to
check and that a bust pose reads better in dialogue than a full figure.

Warp mouths read on small faces too. On a full figure the head is under 160 px
and the mouth 20–45 px, and the face landmarks, made on the whole figure, put a
small mouth's lips on the philtrum and its corners past the painted ones. Such
a face is now read again on the head alone, its mouth line is snapped and its
nine states are warped on the face enlarged to a bust's size, and each state
is fitted back to the pose's own pixels: `closed` is still the drawing
unchanged, the openings have smooth edges, and every opening is a few pixels
deep at least, so an "a" still reads when the figure is drawn small in a wide
shot. Busts warp exactly as before, except one whose landmarks were unsure:
read on its head alone, its mouth is found where a manual hint had to put it.
Per pose `faceSize` (in the rig result, the review sheet and the Face Rig's
Mouth line editor) says how big the face was and whether it was enlarged.
Rig a kit again to get the new mouths.

Flat-rigged characters can talk with their own drawing. On painted busts
(graphic-novel art with ink lines and flat black shadows) the ink mouths still
looked like Flash animation, not like the painting. `characters.rig.flat` with
`style: {"mouthStyle": "warp"}` keeps the upper lip and moves the lower lip,
chin and beard down, the drawing's own pixels, and fills the gap between the
lips with a flat mouth in the character's ink: muted teeth only in `wide` and
`bite`. The mouths are per pose, square patches of that pose's lower face saved
as `anchors.<pose>.mouthSources` and used by Video 2D, Series shots, native lip
sync, Video 3D talking cutouts and the review sheet; `closed` is the drawing
unchanged, so the rest pose shows no seam. The mouth line is snapped onto the
painted stroke between the lips, not a nose fold or a moustache's edge, and
the Face Rig has a **Mouth line** editor: drag a point onto the line and two
handles to the corners, on a phone too, and the warped rest, i, e, a, o, u
follow live (`characters.rig.flat.preview`) before saving the line as the
pose's hint. Rig every pose with `mouthStyle: "warp"` to switch a kit.

Series Lab voice rooms, looping ambience beds and looping score cues work on
ffmpeg 6 (the one Ubuntu 24.04 ships). There every room failed with `Option not
found`, because the convolution asked `afir` for `irnorm`, an option only
ffmpeg 7 and later have, and a bed or cue that loops a file shorter than itself
came out silent, because ffmpeg 6's `acrossfade` ends without the crossfade when
both of its inputs are cut from one file. Both are now built from filters that
every ffmpeg from 6.0 on runs alike, and they sound as before: a looped bed is
the same sample for sample, a room the same to within a thousandth of a dB.

Everything an agent did outside HocusPocus to finish a series episode is now
done in the app, so its files can be found, redone and edited. One shot is
edited by its number or id with `series.shot.update` ("edit the fifth shot and
put a hat on him": `changes` and `append` in the script vocabulary, or an
`instruction` the server's LLM turns into the edit against the real shot, cast,
poses and files); only the changed fields are written, the takes stay and a
take that no longer fits loses its approval. The Wizard does the same with
`edit_series_shot`, renders one shot again with `rerender_series_shot`, and runs
the new media tools with `media_tool`. `studio.key` reads the screen from the
image border and keys relative to it, so a weak generated screen no longer
leaves a semi-transparent haze over the whole background; it takes the screen
colour off the edges and reports the residual semi-transparent share, which the
Character Creator shows. Generated and imported takes get their shot's `sfx`,
`music` and `foley` at the cut (keeping or dropping the clip's own sound), and
every clip in another size, frame rate or pixel aspect is conformed to the
episode's instead of failing the join. A sound cue can play part of its file
(`in`, `length`). New MCP tools save a frame of a clip (`media.frame`), compose a
still from cutouts (`media.compose`; `scenes.video2d.preview` with `still`
keeps a full-size frame of a scene), cut a sound exactly (`audio.trim`) and copy
a file from another workspace with its provenance
(`assets.import_from_workspace`); Video 3D and Video 2D exports take an
`output_name` for a stable file a set layer can name.

The light screen effects read in dark, painted frames. In a tenebrist episode
a `shockwave` in gold, used as a prayer spreading over a city, came out as a
thin flat yellow-green ellipse, and a gold `shield` around a praying woman at
`intensity` 0.4 was barely visible. In 2D overlays both filmed their 3D world
sprite: a ground ring seen from the sprite camera, whose overdriven colour
clipped channel by channel, so gold (red already at its peak) kept gaining
green. They are now painted on the frame with additive light. The
`shockwave` is a white-hot flash with a thin flare, then a front that eases
out and dims, made of a long soft trail of lit air, a band of light, a glowing
line and a thin hot core, uneven along the ring, with brighter patches, two
softer echoes behind it and sparks it throws off. The `shield` is a
see-through dome brighter toward its rim (never more than 25 % light), with an
uneven bright line, a glow stronger above, slow shimmer and ripples, a
highlight and drifting motes; it swells in, breathes and fades out, and
`intensity` sets its light on a square-root curve so 0.4 still reads. Every
layer keeps the hue of `color`: on the episode's background the brightly lit
pixels of the old shockwave added light with equal red and green (86 % of
them yellow-green), the new ones add it in the proportions of the gold. The
parameters are the same. `embers` are glowing sparks that rise on curved paths
and cool from near white to a darker glow of their colour; `stars` and
`bubbles` no longer line up on diagonals; `smoke` is a lumpy column lit from
above; the flames of `anime_aura` no longer end on a straight cut at the
bottom of their card.

A `laser` or `lightning` cue can start at `from` and run to its `x`/`y`. In a
Series shot, `"from": {"cast": 0, "point": [95, 46]}` in `layout2d.fx` is a
point in % of that cast member's pose image (`cast` is an index in the shot's
cast or a character id), so a rifle's beam leaves its muzzle wherever the
cutout stands, however big it is drawn and while the camera pushes in;
`{"point": [70, 40]}` is a point of the frame. A Video 2D cue stores
`from: {x, y}` (frame %) or `{layerId, x, y}` (% of that layer's picture), and
the 2D painter, the export and the editor preview place it at every frame.
`scenes.effects.apply` and the `screenFx` of `world3d.scene.patch` take it too
(a 3D shot keeps a frame point only); the catalog marks the two beams with
`"aim": true`.

Series 2D shots no longer show the straight cut of a cutout cut by its image
border, stand grounded props on the floor, and can give a video layer its own
clock. The render reads each pose's alpha (`series_cutouts`): a cut is a run of
opaque pixels along the left or right border at least 8 % of the image height
long, or along the bottom at least 15 % of its width, so a stray pixel, a
strand of hair or feet resting on the border are not cuts. The Series compiler
then slides a cutout whose side cut would show until that cut is just past the
frame edge, at the same size; a bottom cut goes past the frame bottom (slid
down in a wide shot, enlarged with the eyes on the eye line in the other
framings); cut on both sides, it is enlarged proportionally until both cuts are
out of the frame, at most 2.5×. A cut that is already out of the frame moves
nothing, and `"edgeSnap": false` on a cast entry keeps the old placement. A
prop with `"ground": true` (or `"grounded": true`) stands its lowest opaque row
on the floor the cast stands on in that framing, or on its anchor, and ignores
`y`. A video layer with any of `start`, `speed` (0.1–4) and `loop` (`"loop"`,
`"hold"`, `"pingpong"`) plays on its own clock in the editor preview and in the
headless export (`layer.playback` in the Video 2D document); without them it
loops from its first frame as before. Take digests do not change, so no shot is
rendered again by itself; a shot rendered again after this change gets the new
placement when its pose is cut.

Series Lab voice rooms are subtle now, and only the people in a shot are in
its room. The first presets made a cathedral so wet that the dialogue was hard
to follow: a 3.5 s tail 5 dB under the voice, nearly all of it diffuse. Every
place is re-tuned to be felt, never to cost a word: the room sits 14–22 dB
under the voice and is mostly early reflections, its tail is short (the
cathedral 2.2 s) and starts after a predelay (50 ms in the cathedral), and the
room's own sound is band-limited (low cut 200–350 Hz, high cut 4–6 kHz), so it
masks neither the words nor the consonants. Measured on the rendered response,
the cathedral went from STI 0.53 to 0.92 and from C50 (500 Hz–2 kHz) −0.9 dB to
+12.2 dB, the hall from 0.65 to 0.96, and on real lines STOI against the dry
voice went from 0.73 to 0.96 in the cathedral. The preset names stay; the
processing version is now 2, so the copies are made again and every shot that
hears a room renders again once. A place (every preset but `none` and `radio`)
now reaches only the speakers in the shot (its `layout2d.cast`, else
`visibleCharacterIds`; a 3D shot's `scene3d.cast`), so a narrator over a church
plate stays dry. `radio` is a transmission, not a place, and reaches every
line of its shot. A line can carry its own `voiceRoom` (on a dialogue beat, or
on a line of `series.episode.from_script`), which wins over the shot and the
location for that line, also off screen. The take digest holds the room of
each line, so only the shots whose lines change room render again, and a shot
whose lines are all dry keeps the digest it had without rooms.

A character can walk into a 2D shot in time with its footsteps. A cast entry
with `enterFrom` used to slide in from 0.2 s to 1.4 s while its sound effects
were placed by hand, so a monk entered silently and his steps sounded after
he had arrived. `enterAt` and `enterDuration` time the entrance (a slow 3 s
walk-in), and `"enterGait": "walk"` replaces the quick hop with a walk: the
body is down on every footfall and up mid-step, leaning `enterSway` degrees to
alternating sides, at `enterStep` seconds a step (default 0.5), stretched a
little so the walk is a whole number of steps. A sound or screen effect with
`{"anchor": "enter", "cast": 1}` (an index into the shot's cast or a character
id, plus `offset`) starts with that entrance, and an sfx with `"repeat":
"steps"` plays on every footfall of the walk (or of the hops), so one footstep
sample walks with the character. Shots without the new fields keep their
digests. `series.episode.from_script` checks an unknown gait and an entrance
cue that names nobody, or someone who does not enter.

A timed screen effect (`layout2d.fx`) of a Series shot now keeps the length
its author gave it. A `duration` above the 30 s maximum was dropped and read
as the 1 s default, so a vignette, film grain or candle light written with 99
to cover the whole shot vanished after one second (673 cues on one real
episode). A `duration` outside 0.1–30 s is now clamped to the nearest limit
and only a missing or non-numeric one takes the 1 s default. `"duration":
"shot"` is the explicit way to say "until the end of the shot": it is stored
as written and `fx_cues` ends the cue just before the end of the shot, however
long the shot is. It is documented in `series.guide` and in the
`series.episode.from_script` description. The script path needed no change: it
passes the cues to the same normaliser. A shot whose effect durations were
valid, missing or non-numeric keeps the same take digest and is not rendered
again; only a shot whose stored duration changes because of the clamp (such as
99 turning into 30 instead of 1) gets a new digest. Other cues keep their
earlier handling: a sound effect's `volume`, `offset` and `at`, a line's
`pauseBefore` and the `timing` values outside their range are still dropped to
their defaults.

The flat rig (`characters.rig.flat`) now handles faces drawn with realistic
proportions, such as graphic-novel or tenebrist art with flat black shadows,
eye bags drawn as strokes, round spectacles and moustaches. It was tuned on
cartoons, where the mouth sits just under the eyes, so it took the first dark
mark under the eyes: an eye bag or the lower rim of the spectacles. It wiped
that mark into a smudge under an eye and anchored the mouth there, 15–45 px
above the real one. The rig now measures each face first. A face is realistic
when the taller eye opening, measured on the eyes' whole whites, is at most
0.1 of the head's width at the eye rows and at most 0.3 of the eye pair's
width. On the poses at hand, realistic faces measure 0.058–0.079 and cartoon
or anime faces 0.123 or more. On a realistic face the mouth is the thin,
roughly level pen stroke 0.45–1.35 eye-pair widths under the eye line, nearest
0.9. A stroke is thin when its dark run down each column is short and it is a
few pixels long across, so flat shadows, moustaches, nostrils and beard
strands are never taken. The search and the fallback placement use the eyes'
whole whites, because the eye search cuts a long almond white in two. Bolívar's
mouth anchor moves from −35.4 to −31.9 % (on the line between his lips) and
Anselmo's from −31.7 to −32.5 % (the slit under his moustache, not the top of
his chin tuft). Cartoon faces keep the earlier search. On every keyed pose in
the Plus Ultra, Uncanny Valley and Moncloa Park workspaces, rigged with and
without `screen`, and on the kit sources rigged with their recorded styles,
only those four realistic poses change. Every other run keeps the same boxes,
anchors, warnings and rigged image.

`style.mouthStyle: "ink"` is the mouth for this art; the default stays
`paper`. The painted mouth is not wiped and is the rest shape, so `closed`
and `pressed` draw nothing. The other shapes are hard-edged openings in the
painted mouth's own ink, sampled from it. They hang from the painted line and
are sized from its width. Only `wide` shows a hint of teeth and tongue. The
blink and eye anchors do not change. Placement hints fix what the search still
gets wrong: `hints: {"<pose id>": {"mouth": [x, y], "eyes": [x, y]}}`, in %
of that pose's keyed image before cropping. With a mouth hint, the rig takes
the mark nearest the point, or places the mouth there and wipes nothing.
With an eyes hint, it takes the pair of light eyes at the point anywhere in
the figure. The kit provenance keeps the hints and later rigs reuse them;
`null` clears a pose's hints. The result reports per pose `face` (`realistic`
or `cartoon`) and `mouthFound`. `unwipedPoses` still lists the poses whose
painted mouth was not found.

Series Lab 2D shots can now have a set in layers, so a slow push reads as depth.
Before, a shot had one background and the camera push scaled the whole frame,
which looked flat. A location's `layout2d.layers` holds up to 8 images with
alpha or looping mp4/webm videos (`assetId` or `file`). Each one has a `depth`
from 0 (the background's far plane) to 1 (nearest), plus `front`, `opacity`,
`x`/`y` and `scale`. Layers with `front: true` (a pillar, a candle, a bed frame,
fog in the foreground) are drawn in front of the cast. The others go behind it,
above the background, farthest first. `x`/`y` place a layer on the background,
so it keeps its spot when a tighter framing zooms and pans the background. With
layers, the push moves every plane by its depth. The far wall grows less than
the cast and a near pillar grows more, linearly in depth. The cast stands at
`castDepth` (default 0.6). `drift` (frame pixels per second) slides a layer on
its own, which suits fog. A shot's own `layout2d.layers` replace its location's,
and `[]` turns them off. The same keys work on a `from_script` shot. A bad layer
is refused when it is saved or checked. The renderer has a new layer flag,
`parallaxZoom`, which lets a layer take only its parallax share of the camera
zoom; layers without it render as before. A shot without layers compiles to a
byte-identical document and keeps its take digest. When a location's layers
change, only its 2D shots that draw them are marked out of date.

A new collection of screen effects, `cinematic` («Luz de cine y película»),
grades the whole frame for candle-lit, tenebrist scenes. `candlelight` («Luz de
vela») is a warm key light from a flame at `x`/`y`: the picture is lit by colour
dodge inside a pool of light (`size`, the radius in % of the frame height, 45 by
default), a glow is screened near the flame and the frame darkens slightly away
from it; a flicker of three layers of smooth noise near 1.6, 3.7 and 7.9 Hz
(at most ±16 %, no strobe) makes the flame breathe and sway. `vignette`
(«Viñeta») darkens the edges in `color` (black), `size` how far in it reaches.
`film_grain` («Grano de película») is monochrome grain, new on every frame and
drawn with `overlay` around mid grey, so the picture keeps its mean; `size` is
the grain size in % of the standard. `light_rays` («Rayos de luz») are soft
god rays from `x`/`y` pointing at `rotation` (from high on the left by default),
`size` long, that sway and shimmer slowly. `glitch` corrupts the frame in
bursts: tears that move bands of the real picture sideways with red and blue
split apart, displaced and noisy blocks, and green phosphor lines and flashes.
`canvas` («Lienzo pintado») multiplies a woven-cloth and brush-stroke texture
with a warm tint over the frame. `intensity` sets the strength of each. They
work in Video 2D, in Series `fx`, in Video 3D `sfx` and in `screenBackdrop`;
the previews copy the stage for the ones that blend with it, so they look as in
the export. The frames are a pure function of seed and time and repeat over the
cue, so a plate as long as the cue loops with no seam. A catalog entry can now
carry its own default `x`, `y` and `rotation` as well as `size` (light rays use
it); the editor, `scenes.effects.apply` and both showcases honour them, and the
"all" showcase grows to 55 effects and 165 seconds. A showcase label in a very
dark colour (the black vignette) is drawn in white.

Series Lab voices now sound like the place they are in. Lines are recorded
dry, so a monk in a stone cathedral and a captain on an open deck sounded the
same. `soundDesign.roomByLocation` maps a location id to a room (`none`,
`small_room`, `room`, `hall`, `cathedral`, `cockpit`, `outdoor` or `radio`),
and a shot's `layout2d.voiceRoom` (or `voiceRoom` in a script shot) overrides
it. When the server render builds a shot in a room, it plays a processed copy
of each line instead of the dry recording: a short generated impulse response
(decaying noise, darker as it dies, with early reflections) convolved with
ffmpeg and mixed under the voice, plus a tone filter. The cathedral rings
for 3.5 s, 5 dB under the voice, through a dark tail; the cockpit is small and
metallic, with dense reflections inside 10 ms and a presence peak; the outdoor
room has no reverb, only a gentle low cut and one very slight slap; the radio
is band-passed from 420 Hz to 3.3 kHz and lightly distorted, for telepathy and
transmissions. The copy is made once, next to the recording and named by
recording, room and processing version, and the dry recording is never
touched. Timing and lip-sync stay the dry line's, and every copy is levelled to
the dry line's loudness, so a room never makes a voice louder or quieter. The
only thing a room adds is a tail that may ring past the end of a line, for at
most 0.8 s, faded out. A shot that cannot get its room fails with that error
instead of rendering dry. A series without `roomByLocation` renders and
digests exactly as before, and with rooms set only the shots with lines whose
room changed are out of date. An unknown room in `roomByLocation`,
`layout2d.voiceRoom` or a script is rejected.

A Series Lab episode can have a score: background music that the assembly
lays across runs of shots, so dialogue scenes are no longer bare voices. Set
`episode.score` with `series.episode.update` to a list of cues, each
`{"fromShotId", "toShotId", "file", "volume": 0.18, "fadeIn": 1.5,
"fadeOut": 2.0, "duck": true}` or `{"sceneId", "file", ...}` for the shots of
one scene. A cue plays from the cut before its first shot to the cut after its
last on the clips actually joined, loops its file with a crossfade if it is
shorter, fades in and out inside the cue, and is balanced against the dialogue
like a shot's music. It dips 9 dB under every recorded line (0.25 s down
before the line, 0.6 s back up after; lines less than 1.5 s apart share one
dip), timed from the same lines the subtitles come from, as a deterministic
volume envelope rather than a sidechain on the mix. A shot with its own
`layout2d.music` keeps it, and the score is silent under that shot. The score
is mixed after the ambience and before the -16 LUFS pass, in every clip kind
and language version, and the cut's metadata records each cue. No take
depends on it, so changing the score needs only a new cut. Cues that overlap
or end before they start are rejected, and so is a new cue that names a shot
the episode does not have; a cue left behind when a rewrite removed its shots
is kept and skipped by the assembly, which says why. Episode-mode ambience can
dip under the lines the same way with `soundDesign.ambienceDuckDb` (0-24 dB,
default 0: off).

A Series shot can get foley made from its own picture. Add
`foley: {"prompt": "wooden airship creaking, wind, cannon shots", "volume": 0.5}`
to a shot (2D or 3D; the same key works in `series.episode.from_script`), and
the server render, after the shot's export, asks `generation.sfx` (MMAudio
v2) for sound guided by that exported video, then mixes it under the take's
own lines, music and effects before importing it. `volume` (above 0, up to 2,
default 0.5) is relative to the dialogue and balanced by the generated
sound's loudness, like a shot's music and effects; the picture is
stream-copied. The render has a new `foley` stage, so a resume continues
there, and the generated sound and the mixed take are kept by export digest,
prompt and volume, so a resume or a render of the same picture reuses them and
a new volume only mixes again. Foley never fails a shot: when MMAudio is not
installed, fails, or is not done within 30 minutes, the take is imported
without it and the render item shows a warning. Changing a shot's foley marks
its take out of date; shots without foley keep the take digest they had.

Series Lab can lay a location's ambience once under the whole episode instead
of in every shot. With `soundDesign.ambienceMode: "episode"` (the default stays
`"shot"`), shots no longer mix `ambienceByLocation`, so the bed does not
restart at every cut, and their takes no longer depend on it: a new file or
level for a location needs only a new cut, not new takes. The episode
assembly lays one continuous bed per run of consecutive shots in the same
location, placed on the clips actually joined (probed, with the freeze-tail
dissolve or the hard-cut fallback accounted for). A file shorter than its run
loops with a 1 s crossfade at each seam; a bed fades in and out over 0.8 s
inside its run and crossfades with the next location's bed, centred on the
cut. Its `volume` (default 0.22) is balanced against the dialogue like a
shot's, and the beds are mixed before the -16 LUFS pass. Shots in a location
without an entry get none, and every clip kind and language version gets the
same beds. A series in shot mode renders and digests exactly as before;
switching the mode renders every shot once. The cut's metadata records the
beds, and `ambienceMode` other than `"shot"` or `"episode"` is rejected.

The flat cutout rig (`characters.rig.flat`) now finds and wipes the painted
mouth on a face drawn as a texture, such as a face made of falling code
glyphs. On such a face the gaps between the glyphs are as dark against them as
a pen line is against skin, so every mark under the eyes merged into one
face-sized mark (or, with `screen`, the glyphs were the only light marks): the
pose was reported in `unwipedPoses`, the painted mouth stayed, and the
animated mouth was drawn under it, so the video showed two mouths. When the
usual search finds nothing and the skin under the eyes is a texture, the
mouth is now the wide, flat mark near the middle that is darker than the
texture's own dark ink and thicker than its glyphs, and it is wiped with a
copy of the face just above or below it, chosen so the texture runs on across
the edge, instead of an inpainted smudge. The animated mouth then sits where
the painted one was. The texture is measured with the eye pair scaled to a
fixed width, so the wrinkles and beard strands of a small face are not taken
for one. Plain faces are found and inpainted exactly as before: the other 104
keyed poses of three rigged casts give the same result, with and without
`screen`.

Short lines in a cloned voice are spoken again when the reference recording
has long pauses. Qwen3 Base continues its reference recording, and a reference
that waits 0.5 to 1 s between sentences taught it to wait: lines of two to
four words came back as 0.05 s of a click or only silence, in every take and
with every seed, while the same recording with its pauses shortened spoke them
all. Before the model reads a Qwen3 Base reference
(`audio_guide`, and `audio_guide2` for the second speaker), the generation
worker now shortens every pause longer than 0.3 s to 0.25 s, half kept on each
side, and the silence at the start and end to 0.25 s. No speech is cut, so the
reference transcript stays valid. Silence is anything under -35 dBFS and at
least 30 dB under the recording's peak, so a quiet recording keeps its quiet
words. The shortened copy is a WAV in `cache/voice-references/`, keyed by the
recording's bytes, and every later line reuses it; the user's file, the job
parameters and the generation metadata keep the original. A reference without
long pauses is used as it is, and when ffmpeg is missing or fails the original
is used. This covers every path that clones a voice: Series native renders,
`generation.speech`, Character Kit auditions and a designed voice used as a
reference.

Video 3D clouds, fog and smoke (`worldSfx` `fog`, `smoke`, `dust` and every
other effect drawn with the shared effect noise) no longer show hard square
blocks on NVIDIA GPUs, with or without the toon look. The noise hashed each
lattice corner with `fract(sin(dot(p, k)) * 43758.5453)`; the GPU compiler may
compute the same corner as `dot(i, k) + k.x` in one cell and `dot(i + 1, k)` in
the next, and the sine turns that last-bit difference into an unrelated value,
so the noise jumped at every cell border. The hash now mixes the integer cell
coordinates, so two cells always agree on the corner they share. The software
renderer was not affected. Rain, snow and spark points now also grow with the
`scale` of their effect, as its sheets do: a `rain` cue scaled up to fill a set
drew drops of the unscaled size, under a pixel wide a few metres away, so it
looked empty.

A Series native render no longer keeps a voice take that came out empty. Some
cloned voices sometimes stop before speaking a short line: the take is only
silence, or a click of a few hundredths of a second. Trimming the silence left
an empty file, and the shot failed with `could not convert string to float:
'N/A'`; a click was kept as the line and then failed lip-sync. A take shorter
than 0.1 s per word (0.25 s at least) is now spoken again with the next seed,
before the transcription check. When all three takes are empty, the shot fails
with `speech_empty` and names the line. An empty recording left by an older
render is recorded again instead of reused.

A new screen effect, `code_rain` («Lluvia de código»), paints digital code
rain over the whole frame: columns of half-width katakana, digits and Latin
capitals fall at their own speed, with a near-white head and a trail that fades
to the effect colour (`#39ff6a` by default) and then out, and the glyphs change
as they fall. `size` is the glyph height in % of the frame height (3 by
default: the catalog entry now carries that default size), `intensity` the
density and brightness; `x`, `y` and `rotation` are not used. It works in Video
2D, in Series `fx`, in Video 3D `sfx` and in `screenBackdrop`. The frames are a
pure function of seed and time and repeat over the cue: every column makes a
whole number of trips and every glyph a whole number of changes between `start`
and `end`, so a cue as long as a Series location plate loops with no seam. When
the browser has no font with katakana it draws digits, Latin capitals and
symbols. The Video 3D shot `anime-code-rain` (6 s, 1920×1080) uses it as a black
backdrop behind an optional `subject` cutout with a slow push-in. An export now
draws nothing for an image cutout that has no picture, so a shot whose figure
was left empty renders as a clean plate; the editor still shows the placeholder.

Publishing a reviewed take under an exact name with `assets.upload` no longer
overwrites or deletes the metadata of another output. Generation sidecars are
keyed by the name before the extension, so `song.wav` and a cover `song.png`
share `song.meta.json`: copying a take to `song.wav` replaced the cover's
metadata with the take's, or deleted it when the take had none, and a source
like `clip.wav` took `clip.meta.json` even when it described `clip.mp4`, so the
copy claimed the video's prompt and seed. A sidecar is now copied only when it
names its source file. A copy is refused with `sidecar_conflict`, before
anything is written, when the destination's sidecar belongs to another file
that still exists, or when it would create a sidecar that such a file would
read as its own. A sidecar left by a deleted file is still replaced.

A production or a Series render that waits for the GPU no longer waits
forever. With `HOCUS_PRODUCTION_EXTERNAL_VRAM_MB` set, each music, image,
speech, SFX, H3 or video export admission waited in 30-second steps for as long
as another process held the GPU, and a cancel had no effect until that process
finished. The wait now lasts at most `HOCUS_PRODUCTION_GPU_WAIT_SECONDS`
(default one hour; `0` keeps waiting). After that the run stops with
`resource_gpu_busy`, naming the processes that still hold the GPU, and can be
resumed. Cancelling a music-video production or a Series render job ends the
wait at once. A Series render job now stops at the shot that ran out of GPU or
disk instead of waiting again for each following shot, and a cancel during its
last shot ends the job `cancelled` instead of `failed`.

The flat cutout rig finds small painted mouths again. Since the rig started
skipping narrow nose strokes, a mouth narrower than a talking mouth (a small
open «o», or a short line on a small face) was skipped too: the pose kept its
painted mouth under the talking mouths and was reported as `mouth_not_found`. A
mouth wide enough for the face is still preferred, so a nose above it stays.
When there is none, the largest small mark in the middle of the face, below the
nose's place right under the eyes and not upright, is taken as the mouth, and
nothing beside it is wiped with it. A nose stroke, a nose right under the eyes
and marks off to the side (a jaw line, stubble) are never taken, so an already
rigged pose still gets no wipe. Rig the character again to wipe such a mouth.

The humanoid rig accepts characters in capes and long robes. A cape over the
shoulders and upper arms joined the arms to the torso in the front silhouette,
so the shoulders were put at the cape's edge (or the model was refused with
`not_humanoid: hands_stuck`), and a robe or skirt down to the ankles hid the
gap between the legs (`legs_too_short`, or a crotch at the hem with the shoes
taken for whole legs). Rays along the depth axis now tell cloth from body:
cloth with air inside (a cape over the arms, the hollow of an open robe) or
hanging behind the body (a hero's cape, coat tails) is set aside, and the arms
and legs are found on the body under it (warnings `covered_arms`,
`covered_legs`). Legs hidden in a robe are placed from the feet that show under
its hem (`legs_hidden`); a robe down to the floor with no feet showing is still
refused (`single_leg`). The skin weights follow: a robe, skirt or cape over the
legs hangs from the hips and blends into both thighs across the middle without
the knees, so a stride sways it instead of tearing it down the middle and a
bent knee does not fold it, and a cape over the shoulders has its weights
blurred so a raised arm stretches it smoothly. Landmarks of models without such
cloth are unchanged.

The flat cutout rig closes anime eyes. Its blink covered only the white of each
eye, so on an anime eye (a big dark iris against a thick upper lid, with the
white a thin crescent beside it) the iris, the pupil and a dark corner of the
lid showed through the closed eye, and the cover took its colour from the iris
and lashes around it, so it came out darker than the face. Each eye is now
covered whole: the white grows into what is drawn in and beside it (iris, pupil,
highlights, lid and lash lines) up to the skin, then into the dark lid line
resting on it, no thicker than that line is across the middle of the eye, so
brows and bangs above stay. The cover takes its colour from the face pixels
around it only. The pupils that showed on large round cartoon eyes are covered
too, and the faint ring around each closed eye is gone. Rig the character again
to get the new blinks.

A Series 3D shot can have a narrator or a voice on the radio. A line by a character
with no object in `scene3d.cast` stopped the render with `unbound_speaker`; it is
now heard over the shot and ducks the music like a talking cutout.
`world3d.scene.patch` takes `voiceOver` [{audio, start, gain}].

A Video 3D model that follows its path (`motion.faceTravel`) can say where its nose
is: `motion.headingOffset` (radians) is added to the travel heading. Generated
ships and airships often point their nose along -X, so they flew sideways;
`headingOffset: 1.5708` makes them fly nose first, also on waypoint curves.
Series `scene3d.objects` keep it.

The Video 3D toon look renders in the headless exporter. Hunyuan3D GLBs have no
normals; three flat-shades PBR materials then, but not toon materials, so their
light was NaN: a draft export came out entirely black (the bloom spread the NaN
over the frame) and a final export drew every model as a black silhouette.
Those meshes now borrow smooth normals for the toon draw. Toon models also get
the scene's environment light back as flat fill, so scenes lit mostly by the
room environment keep their colours, and the ink no longer shows as black
specks through holes in scanned meshes.

Video 3D has eight anime shots (tag `anime`, 1920×1080 at 24 fps) for the
classic 1980s TV-anime tricks: `anime-speedline-charge`, `anime-impact-frame`,
`anime-snap-zoom`, `anime-sword-clash`, `anime-face-off`, `anime-airship-flyby`,
`anime-fleet-approach` and `anime-eyecatch`. Characters are empty flat cutouts
and vehicles empty GLBs, bound by object id like any other shot; a GLB, static
or with a clip, can take a cutout's place (with `renderLook: "toon"` it is drawn
in cel bands to match). The objects, timings and bindings are
in [docs/development/WORLD3D_TEMPLATES_AGENTS.md](docs/development/WORLD3D_TEMPLATES_AGENTS.md).
They need four small engine additions, all available to every shot:
`camera.shake` (seeded windows in scene seconds, the same in the editor, the
MP4 export and the software preview; `world3d.scene.patch` validates it),
`camera.framing.moveStart`/`moveEnd`/`ease: "snap"` for a crash zoom inside part
of the shot, `screenBackdrop` (a colour and screen effects painted behind the
world, so speed lines sit behind the characters), and the screen effects
`impact_flash` and `impact_invert`, full-frame impact frames that Video 2D and
Series shots can use too. The magic/anime effect showcase is now 14 effects and
42 seconds. `speedlines` now reads `intensity` (the number and weight of the
lines; 1 draws the original 65), and a production subject that is a GLB turns a
cutout object into a model, and a picture turns a model object into a cutout.
`world3d.scene.patch` with `retime` also stretches the shake windows and the
backdrop's effects.

Series 3D shots play their sound effects and screen effects. A 3D shot got the
location's ambience, the stinger and its music but dropped `sfx` and `fx`, so an
explosion or a laser in a 3D shot was silent and anime speed lines or a manga
impact could only go on 2D shots. They are now timed on a line or at a second
as in a 2D shot; `world3d.scene.patch` takes `screenFx` (ids `shot-*`), which
replace the shot's earlier effects and keep the template's own.

The humanoid rig accepts characters with long hair and a skirt. Hair down to the
shoulders hides the neck in the front silhouette and a skirt makes the waist the
narrowest row, so the waist was taken for the neck, the arms for part of the head
and a clean T pose was refused with `not_humanoid: hands_stuck`. The neck is now
looked for above the T-pose arm line.

A Series 3D shot can ask for the toon look: `scene3d.renderLook: "toon"` (and
optional `scene3d.toon`) draws its 3D models as cel anime with ink, so a rigged
character or a vehicle sits with the episode's flat cutouts and painted sets.

Video 3D has a toon / cel render look («Anime (cel)» in Spanish). With
`renderLook: "toon"` the 3D model slots are drawn with flat bands of light and
an ink outline, so rigged or static GLB characters, vehicles and props sit next
to flat anime cutouts and painted backgrounds instead of looking like glossy
plastic. Images and cutouts keep their look. The outline is an inverted hull
that follows skinned animation and morphs, keeps the same width at any model
scale and frame size, and skips glass and alpha-cut cards. Optional
`toon: {steps, outline, ink}` sets 2 to 4 light bands, the ink width in pixels
of a 1080p frame and the ink colour. The editor offers it under Render look
(where N64 can now be chosen too), agents set it with `world3d.scene.patch` or a
production shot's `scene3d.renderLook`, and preview and export match.

Series 3D shots mix 2D and 3D. `scene3d.objects` places what does not speak in
a Video 3D shot: a model from `model3d.generate`/`model3d.animate` with its
clip by name (looked up in the GLB), speed, position, scale and a path across
the shot, or an image cutout, on a template object or added to the scene; the
talking cast stays a Character Kit cutout. The template's effects, texts,
appearances and clip cues are stretched to the shot's length, so an impact
authored at 4 s of an 8 s template lands at 2.5 s of a 5 s shot instead of
after the cut. `world3d.scene.patch` gains `add` (a new prop object),
`clipPlayback` and `retime`.

`series.update` (and `PUT /api/v1/series/{id}`) keeps every top-level field it
is not sent. It replaced the whole project, so an agent that sent only
`allowedProductionMethods` emptied the episodes, characters, locations and
assets of a finished series; send an empty list to clear a field.

A restart keeps its port. The socket bound before the start-up banner had no
`SO_REUSEADDR`, so the previous server's connections in TIME_WAIT blocked the
port for a minute and the app moved to the next one (42004 instead of 42003).
It is set on POSIX, which still refuses a port another process listens on;
Windows binds exclusively.

Typed H3 and LTX video (`generation.video` version 3) can be queued. Its
commands carry content-fingerprint version 3, which the task admission store
refused, so every real request failed with «Unsupported command fingerprint
version» and only `validate: true` worked.

Flat-rigged characters close their eyes properly in every pose. Video 2D fits
each layer into a 16:9 box, so a blink sprite wider than that (a pair of round
eyes is about 2.5:1) was drawn at about 70% of its anchor and the white of the
eye showed around the lids; the rig now grows the blink crop vertically to at
most 16:9. The rig also drew a blink for each pose but the kit kept only the
base one and scaled it onto the others by eye height, so wherever a pose had
its eyes wider apart or larger the white of the eye showed around the lids.
Each pose now stores its own closed eyes (`anchors.<pose>.blinkSource`), used
by Video 2D, Video 3D talk and the rig review sheet; kits rigged before keep
the old behaviour until they are rigged again. Series shot effects keep
`rotation`, so a laser can leave the muzzle of a gun aimed left instead of
always firing right.

Native Series renders again on an install without the optional phoneme
model. Since #821 every line with dialogue failed there; the render now asks
`audio.mouth_cues` for `engine: "auto"` (phonemes when installed, Rhubarb
otherwise) and each line reports the engine that drew it and, for Rhubarb,
`fallbackReason: phoneme_not_installed`. A line without any mouth cue still
stops the shot.

A local app without a login keeps its keys and files to itself. The server
answers only to its own host names (IP literals, `localhost`, the machine
name, a Cloudflare quick tunnel, `HOCUS_PUBLIC_URL`, `HOCUS_TRUSTED_HOSTS`),
so a web page cannot reach it through a rebound domain; `/api/v1/llm/models`
and `/api/v1/llm/load` never send the OpenAI or Grok key to a URL the caller
supplies; served files are never content-sniffed and uploaded HTML or SVG
download instead of running as the app; uploads keep only known media and
document extensions (anything else is stored as `.bin`); the MCP OAuth
endpoints cap request bodies at 64 KiB, throttle registrations per peer and
never evict a connected client. Sharing on the LAN turns the access token on
by default (`LOREFRAME_LAN_AUTH=0` opts out), the session cookie lasts 30 days
and a key with non-ASCII bytes is simply wrong instead of a server error. The
settings file (`wgp_config.json`, API keys and workspaces) is written
atomically with owner-only permissions, and a truncated copy is set aside with
a clear message instead of stopping the app from starting.

Long jobs no longer wait for a state that cannot come. A server render or a
production whose job file says «running» after a restart is marked
`interrupted` the first time anyone looks at it, and «Resume» continues it
(the recording of each line is reused, only what is missing is spoken again);
a new render of the same episode is no longer refused as «already running».
A shot whose export was interrupted, discarded or forgotten by the server is
asked for again under a new intent, up to three times, instead of waiting
forever. The headless renderer is watched by its frames, not by the clock:
every frame it writes now moves the task's progress bar, and when no new
frame arrives for ten minutes (`HOCUS_RENDER_STALL_SECONDS`) the browser and
its process group are killed and the export fails with that reason; its
output goes to `browser.log` in the staging folder instead of a pipe nobody
drained. A production whose cut failed recuts once per run, so «Resume» also
recovers a failed assembly, and a render the server forgot is started again.
`series.episode.from_script` with an `episode_id` now replaces the episode:
shots the script no longer has are removed (`removedShots`) and a shot whose
lines, cast, location or layout changed starts without takes instead of
keeping a video of other content (`replaceShots` on `series.episode.update`).

What comes out sounds and reads as intended. Video 2D and Video 3D exports
share one mixer (`services/audio_mix.py`) that ends in the same limiter, and
the browser hands the server a 32-bit float mix, so overlapping voices or a
loud effect no longer clip in a 3D take. A `volume` of 0 silences a music or
effect track instead of restoring the default. Music and effects may live in
a workspace subfolder (`music/theme.wav`) and are found there by the mixer,
the loudness balance and `from_script`. A 3D shot now plays the scene's
ambience, stinger and music, balanced like a 2D shot and ducked under the
dialogue by the page (`soundtrack` on `world3d.scene.patch`). A dubbed
scene keeps its language in its name even when the name is cut to length.
A language version is refused before anything is spoken when a speaker's kit
has no voice designed for that language, both in `from_script check` and in
the server render. H3 and imported takes with dialogue get subtitles in a
mixed episode: their shot's lines are spread over the clip. The Director's
content scanner, which aborted innocent scripts («comic strip», «son
riding»), is gone.

The LLM and H3 paths agree with each other. DeepSeek is a remote provider
like Grok (it used to be loaded as a local GGUF and tried to download one).
A reply the model cut at `max_tokens` is reported: a warning in the log, and
an error (`LLMTruncatedResponse`) when JSON was asked for, instead of a half
JSON that planners filled with fallbacks. Remote calls (OpenAI-compatible and
Anthropic) try again after a 429 or a 5xx or a dropped connection, waiting 1,
2 and 4 seconds (or `Retry-After`), so a transient rate limit no longer kills
a pipeline of dozens of calls. One H3 frame lattice
(`services/h3_frame_lattice.py`: 17n+5 frames, 124 to 345 per pass, rounded
up) is read by the sidecar, the Series renderer, the dialogue duration
contract and the Director's segmenter (whose continuation segments keep their
107-frame floor, so saved pipelines regroup as before); the sidecar's own
362-frame cap with nearest rounding is gone, so a shot that fits in one path
fits in all. One speech
rate (2.16 words/s, derived from the syllable estimate) replaces the
Director's 2.1, the shot validator's 2.5 and the sidecar's separate figure.

Intermediate files are released when their job is done. A Video 2D/3D export
drops its frames and audio mix when the MP4 is published, a completed
production drops the copies it put in uploads, the series render drops each raw
voice take once trimmed, and the speech analysis no longer leaves a copy of
the audio in the system temp folder. At startup the app releases what a restart
or an older version left behind (export staging of finished exports, old raw
takes, stale temp folders) and keeps only the last ten revisions of the kit
library history. One installation held 28 GB of frames from published exports,
another 122 GB. Results are never touched; `HOCUS_KEEP_EXPORT_STAGING=1` keeps
export staging for debugging. See `docs/development/STORAGE_CLEANUP.md`.

## [0.10.0] - 2026-10-04

Animated series end to end. Series Lab makes a whole episode locally:
characters in one click (style presets, a flat rig with nine paper mouths and a
blink, a designed voice per language checked with speech QA), an episode
written as one compact bilingual script (`series.episode.from_script`, checked
against the series before anything is written) and made with one call
(`series.episode.produce`): every shot rendered on the server with its voices,
phonetic lip-sync and an editable Video 2D or Video 3D scene, takes approved,
and each language cut at -16 LUFS with SRT/VTT and burned-in subtitles. A
language version lives inside the episode with its own lines, cards, music,
takes and cut. Shots declare their rhythm (pauses, intro, tail), timed sound
and screen effects, props on background anchors, characters seated on their
prop, and 3D dialogue shots; locations can use a looping Video 3D plate. Audio
is balanced: lines are levelled, music and effects follow their own loudness,
and both dip under the dialogue in 2D and 3D. Series templates start a new
show with its cast, places and pilot.

Agents and chat assistants: the `/api/v1/mcp/series` profile serves only the
series tools, `series.guide` returns the working guide and the live series
bible, and a single-user OAuth 2.1 sign-in lets connectors such as ChatGPT
connect with their own revocable token. Video 2D is fully authorable over MCP
(published schema and catalogs, small edit operations, templates, lyrics,
contact-sheet previews), and MCP gains asset upload, `media.options`, Video 3D
shot search, Model3D generation and UniRig rigging jobs.

Productions and music videos: a music video from one spec over MCP, with
resume, retakes, review split into execution, technical and artistic checks,
cheap animatic previews and dry runs, quality profiles, shot-by-shot editing
of a finished video and publishing to local pages; comic to film and trailer
structure; many fixes that keep finished cuts, locked takes and project
identity intact across resumes.

Video 3D: new atmosphere sets (waterfall, lunar, desert oasis, sunset beach,
crystal cave, Mars, snow, silicon and more), an N64 look and PS1 backplates,
beat-synced performances, environment lighting, a humanoid rig for real meshes
(walk paths without sliding, IK sit/reach/look, foot contacts, held props),
clip sequences with fades, and cartoon lips with Lips Creator.

Export quality: draft, final and master levels with supersampling, MSAA and
deterministic motion blur, 4K, an optional ProRes master with a single final
encode, geometry and audio warnings before a render, ffmpeg probes and a
review panel on the receipt, and per-platform loudness when publishing. Assets
gain a CC0 library contract with a safe downloader and GLB import; Qwen Image
2.1 is the default image model when installed.

Install on any computer: AMD, Intel and CPU-only PCs, Linux ARM and NVIDIA
drivers below the CUDA minimum now install the core studio (projects, editors,
3D worlds, comics and remote providers) without Torch instead of stopping at
preflight. Each machine installs exactly one main runtime; NVIDIA x64 keeps
WanGP and never installs core. Start boots the core runtime on those installs,
the studio reports `coreRemote` and hides local engines, and the launcher hides
LoRAs, compiled start and CUDA-only installers. Also fixes the macOS core
install (`KeyError: 'cuda'` in the package helper) and reports the bundled
Rhubarb as available. The first Update re-runs NVIDIA engine setup because a
shared install helper changed.

Hunyuan3D is optional: Install no longer compiles it or requires Visual Studio
on Windows; install it from Advanced > Install 3D Generation (Hunyuan3D), and
Update refreshes it only where present. Procedural rigging runs with the main
app Python on every computer, including the core studio. Install ends with a
plain summary of what this computer installs, what it cannot run and why.
The optional Hugging Face login now prints its code and link in the terminal,
opens the browser, reports whether it worked, and can be retried from the
Advanced menu. Core installs no longer replace the FFmpeg that Pinokio pins.

## [0.9.0] - 2026-08-24

First HocusPocus preview. Product versioning is independent of the Maestro
lineage. The UI reads this number from `VERSION` via `/api/v1/system-config`.

## [1.6.5] - 2026-08-08

MiniMax H3 performance and memory: rebalanced transformer residency and
activation workspace, added bounded QKV/MLP processing, and made Studio and
Director choose native H3 window lengths from the selected resolution, model,
and detected GPU memory. The main resolution menu now uses an aligned
1280x704 consumer 720p tier, exposes 1080p as an experimental option with
shorter hardware-aware windows, and keeps the former 768p tier available for
saved settings and API compatibility without presenting it as the default.
Users can lock a manual window override, and an optional experimental First
Block Cache offers selectable speed/quality thresholds.

H3 Turbo and LoRAs: Turbo now runs on both Pruned 20B and Full 33B checkpoints
through automatic AdaLN adapter conversion. The managed preset uses six steps
and a default strength of 0.50 while remaining editable in Advanced and
Director settings. Full-model jobs that are unnecessarily expensive receive a
Pruned recommendation instead of a hard failure. The CivitAI browser now has
an H3 filter, and both CivitAI downloads and pasted Hugging Face H3 LoRA URLs
route to the shared MiniMax H3 LoRA folder. Required conversion support assets
are revision-pinned, verified, and atomically published before generation.

H3 long-form prompting: Studio can turn one long-video idea into a structured,
window-local storyboard. Each continuation receives its own complete
Context-IR prompt with stable subject and setting continuity but distinct
actions, dialogue, camera coverage, ambience, effects, and music. This keeps a
multi-window story from finishing and repeating in its first pass. Exact
generated prompts are saved with the job, remain editable before submission,
show the currently generating window, and expand to their full content without
nested scrollbars.

Director H3 execution: Director now uses the same model-specific resolution,
frame-grid, VRAM, and Turbo rules as Studio. It divides long scenes into valid
native shots before queueing, rejects unsafe runtime shrinkage, preserves one
native pass for Turbo shots, and supports per-LoRA strength controls. Prompt-
only independent shots receive self-contained world, cast, wardrobe, blocking,
dialogue, sound, and continuity anchors rather than rolling-window commands.

## [1.6.1] - 2026-08-06

MiniMax H3 Turbo: added the pinned Turbo adapter to the Full FL2VA and Ref2VA
LoRA catalogs as a managed first-use download. Full H3 models now expose an
experimental one-click Turbo mode that selects the adapter, sets six inference
steps, and starts at strength 0.70. The adapter remains visible in Advanced so
its strength can be tuned per generation, and the backend preserves that
user-selected value while preventing duplicate Turbo adapters. Turbo remains
hidden and rejected for incompatible Pruned H3 checkpoints.

## [1.6.0] - 2026-08-06

MiniMax H3 in Director: added model-aware bounded-shot workflows for both H3
families. FL2VA now powers story-generated short films with native 5-15 second
shot planning and start/end continuity when a scene is divided into multiple
parts. Ref2VA now supports music videos, uploaded-dialogue films, and
story-generated films using per-shot composition, character, location,
soundtrack, and voice-reference manifests. Dashboard repair and regeneration
rebuild the same inputs, while audio-driven projects condition each shot on its
exact source segment and retain one clean continuous soundtrack for the final
join.

MiniMax H3 Omni Reference: added the separate H3 Base Ref2VA checkpoint and an
ordered Studio reference workflow for images, videos, embedded video audio,
and standalone audio. References receive exact Picture/Video/Audio labels,
can be reordered by drag and drop, and retain optional role notes for Prompt
Enhance. The runtime follows the official reference packing, VAE conditioning,
shared audio/video timing, and target-only denoising path while sharing the
existing H3 conditioner and VAEs. Output-matched reference detail is the
consumer-GPU default, with the official maximum-detail preparation available.

H3 Omni prompting: added a dedicated six-section Prompt Enhance guide that
maps ordered reference labels to subjects, motion, voices, retained details,
dialogue, soundscape, and music without changing the working FL2VA Context-IR
workflow. Standalone audio can be explicitly used as a voice reference,
performance-driving/reused audio, or a sound and music style reference. Raw
prompts now receive automatic media relationships, voice references no longer
copy source speech by default, scene ambience and effects begin at the first
frame, and malformed local-LLM enhancements retry or fall back safely instead
of being truncated into an unusable prompt. Standard H3 and Omni Prompt
Enhance now validate that every user-written line survives verbatim inside an
H3 dialogue block and that vague discussion requests receive actual scripted
dialogue. Raw Omni prompts are compiled into full six-field Context-IR and
identity pictures are prevented from introducing their source background,
framing, pose, or an opening still. Both H3 enhancers now allocate short
dialogue inside duration-aware speech intervals, fill the opening and remainder
with active nonverbal action, and explicitly suppress voices, grunts, breathing,
and speech-like filler outside dialogue tags. Dialogue is no longer duplicated
as ordinary quoted text, and visual terms such as cinematic or epic no longer
cause an unrequested musical score.

MiniMax H3 model and memory options: the existing FL2VA and Ref2VA entries are
now clearly labeled as the recommended Pruned 20B variants, with optional Full
33B entries for both workflows. Advanced settings can select the recommended
NVFP4-AWQ Qwen3-VL encoder or lower-RAM GGUF Q2/Q4, Quanto INT8, and BF16
alternatives. H3 now probes full versus pruned checkpoints at load time,
restores ConvRot layouts where needed, splits fused Q/K/V projections for
streaming, and profiles the Qwen language and vision towers independently.

MiniMax H3 Turbo LoRA: added the optional LarryVRH low-step adapter for Full
33B FL2VA/Ref2VA models with true 4/6/8-evaluation sampling and independent
video/audio schedules. Fixed active LoRAs bypassing the Full model's ConvRot
activation math and corrected fused-QKV adapter splitting, which previously
produced colorful tiled noise even though the same Full model worked without
the adapter. Incompatible Pruned 20B selections are rejected before loading.

H3 Omni video-reference memory: fixed Match Output references being silently
expanded to a 768-pixel short edge even for 480p/544p output. Reference video
area is now bounded to the requested canvas, long packed projections are
chunked, and video-reference jobs reserve dedicated attention workspace and
reload an already-resident profile when it was loaded with too much transformer
weight on the GPU. This substantially reduces first-denoise VRAM peaks while
keeping Maximum Detail available as an explicit high-memory option.

H3 Studio timing and continuation: Ref2VA/Omni is now limited to its native
single-shot maximum of 345 frames (14.375 seconds at 24 FPS), with incompatible
sliding-window controls hidden and rejected by the backend. FL2VA/First & Last
uses the same 345-frame native window but can continue longer Studio timelines
by feeding each completed window's final frame into the next. One-frame overlap
is removed during assembly, the optional end image is reserved for the final
window, and joined video and audio are trimmed to the exact requested duration.
Portrait, landscape, square, and automatic aspect-ratio selections now remain
native throughout the H3 pipeline.

Director planning and dialogue reliability: model selection is now filtered by
the capabilities required by each Director workflow, preventing image-only,
control-only, fixed-length, or native-audio-output models from being routed into
incompatible jobs. H3 story planning can omit unnecessary image generation,
retains project/world, wardrobe, blocking, and location context in every
independent shot, and compiles locked screenplay dialogue into stable speaker
IDs and native H3 dialogue blocks. Duration-aware shot coalescing permits
multi-speaker exchanges and internal camera changes while preserving complete
lines, and deterministic repair paths recover incomplete local-LLM plans without
silently changing, moving, duplicating, or truncating scripted dialogue.

Interface and diagnostics: simplified H3 model names distinguish First & Last
from Omni while explaining recommended Pruned 20B versus optional Full 33B
weights. Native audio-output badges are no longer presented as audio-input
support, Turbo LoRA compatibility is identified before generation, and
successful high-frequency system-stat polling is filtered from the console
without hiding errors or meaningful API activity. Saved Director jobs whose
process disappeared are now reported as interrupted instead of missing.

## [1.5.5] - 2026-08-04

MiniMax H3: added native local H3 Base FL2VA generation for text, first-frame,
and first/last-frame video with synchronized 32 kHz stereo audio. The initial
integration supports approximately 5-15 second output at 24 FPS across native,
portrait, square, and lower-VRAM resolutions, with revision-pinned automatic
provisioning of the compact scaled-FP8 transformer, NVFP4 Qwen3-VL conditioner,
video/audio VAEs, tokenizer, and processor assets. Ref2VA reference-video/audio
conditioning and hosted 2K regeneration remain outside this initial release.

H3 prompting: added a model-specific local Context-IR Prompt Enhance workflow
with the required multimodal-description, soundscape, music, stable speaker-ID,
and dialogue-tag syntax. Vague discussion requests can be converted into short,
duration-aware scripts; supplied dialogue remains verbatim; and unused time is
assigned to silent visible action to reduce invented speech. H3 enhancement now
bypasses the generic cinematic enhancer and remains one native timeline rather
than receiving sliding-window paragraph instructions.

H3 runtime reliability: corrected compact Qwen3-VL prompt conditioning,
row-scaled INT8 embedding loading, NVFP4 scale application, and causal attention.
Fixed mixed-dtype MMGP profiling and start-frame CPU/CUDA mismatches. Added
bounded activation chunking, explicit transformer working-memory reservation,
and dtype locks so the large packed audio/video sequence can stream on consumer
GPUs without exhausting memory before denoising. Expanded model-free and runtime
regressions for prompt conditioning, quantization, keyframes, scheduling, native
audio, activation memory, and Context-IR formatting.

SCAIL-2 Recast: improved continuous multi-character shots by detecting cast
transitions and supplying late-arriving identities through hidden pre-roll
conditioning instead of publishing artificial visible cuts. Recast assembly
now verifies every generation segment and preserves the exact source timeline.

## [1.5.0] - 2026-08-02

SCAIL-2 editing: rebuilt Recast around native replacement conditioning with
automatic reference isolation, face-detail conditioning, optional official
relighting, bystander preservation, and VRAM-aware 480p/512p/704p profiles.
Added stable color-mapped replacement for up to five people and shot-aware
SAM3 tracking so identities are reacquired and correctly routed across camera
cuts, close-ups, wide shots, and group shots. Added Repaint as a first-class,
shot-aware Edit mode that preserves the source timeline and audio while
changing characters, objects, or scene styling.

LTX-2.3 editing: rebuilt Outpaint around the official In/Outpainting IC-LoRA
and mask-preserving source conditioning, including bounded seam blending,
marker-spill cleanup, accurate canvas geometry, and model-correct sampling.
Multi-scene sources are now split at camera cuts, processed independently,
and reassembled at the exact original length with source audio. Retake now
supports distilled and two-stage LTX-2.3 pipelines. This resolves #28 and #37.

Krea 2: added RAW and Turbo Identity Edit v1.2 models with Qwen3-VL vision
conditioning, instruction editing, inpainting/outpainting, background removal,
and multi-reference support. Added current Diffusers/Kohya LoRA and GGUF
compatibility, a dedicated CivitAI/My LoRAs Krea 2 filter, accurate companion-
weight readiness checks, and default visibility for all four Krea 2 models.
This resolves #35 and #43.

Studio and reliability: model visibility now persists server-side across
Pinokio ports and restarts; newly installed CivitAI checkpoints appear without
a restart; control-video motion is independent of generated, uploaded, or
source audio; Temporal Depth assets are provisioned and verified on demand;
and Voice Reference is enabled independently of experimental features.
Director no longer duplicates single-clip outputs, SCAIL-2 LoRA phases are
normalized correctly, and installed apps survive early GPU-detection failures.
This resolves #19, #36, and #40.

## [1.4.0] - 2026-07-20

Storage and library management: added the Storage Manager with usage
analytics, safe workspace/pipeline/LoRA deletion, duplicate detection and
reclamation across linked installs, and opt-in linked-copy removal through the
Windows Recycle Bin. LoRA views now show sizes, download/release dates, age
chips, and newest-first sorting; CivitAI browsing is cached to reduce repeated
requests and rate-limit pressure.

Director workflow: reference-free runs now create and persist a shared visual
anchor before generating shot images. The Dashboard gained a server-owned,
cancelable repair workflow that skips valid work, survives browser reloads,
resumes interrupted batches, and rejoins completed clips. Fixed missing
thumbnails and clip mappings, generated start images not reaching video jobs,
repairs stopping after one item, and unsafe rejoin of missing or stale media.

Music-video timing: Dashboard reruns now use the same model FPS, frame lattice,
carried frame schedule, and audio window as the original Director run. Rejoin
also preserves the planned source-audio origin while retaining one continuous
soundtrack, fixing shortened replacement clips, cumulative lip-sync drift, and
leading-silence offsets without reintroducing audible clip-boundary artifacts.

Reliability and safety: job cancellation is terminal and race-safe, pipeline
state writes and output ownership are deterministic, and failed media joins
clean up partial files. Model/LoRA downloads now validate complete payloads and
archives before atomic publication, prevent concurrent destination writes, and
offer clearer progress and retry states. Restored expanded Director minor-
content scanning, fixed conditional React hook crashes, tightened NVIDIA-only
launcher gating, and enabled Python regression tests on both public branches.

## [1.3.3] - 2026-07-17

Recast tracking resilience (cocktailpeanut's second report). When the
replace target left the scene mid-clip, or was absent from frame 0,
SAM3's propagation crashed the whole job with "No points are provided".
The mask driver now anchors on a frame where the keyword actually
detects, propagates both directions, and re-anchors past a mid-video
tracking collapse, keeping all masks produced so far; absent-target
frames get empty masks (original footage passes through). Also clamps
the batched grounding chunk window to the video length (latent upstream
IndexError exposed by re-anchored propagation). Both root bugs are
inherited from upstream WanGP's SAM3 tree.

## [1.3.2] - 2026-07-17

Community-report round. Fixed: the first Recast on a fresh install
crashed with "SAM3.1 checkpoint not found" (the masking pre-step runs
before the model download that carries the detector; it now fetches it
on first use); downloaded badges lied for weight-aliased models
(SCAIL-2 Fast, Z-Image ControlNets) because the checker iterated the
alias string character by character - resolution is now recursive and
also counts weight modules and bundled LoRAs; deleting a finetune
leaves shared base weights in place for its siblings; SCAIL-2's
image-reference mask falls back to broader keywords when the configured
phrase matches nothing. New: the download icon in Settings -> System ->
Enabled Models is a real button that pre-downloads everything a model
needs (GPU-free, progress in the banner) via the new
/api/v1/models/{type}/download endpoint.

## [1.3.1] - 2026-07-17

Fix #20: a stale local Hugging Face token made HF reject public files
with 401 ("OAuth token signature verification failed"), surfacing as
"Repository Not Found" for the SCAIL-2 checkpoint. All model-download
paths now retry anonymously when the token is rejected; valid tokens
are still tried first so gated repos keep working. Also hides Recast's
inert resolution/window controls (the endpoint pins SCAIL-2's native
operating point).

## [1.3.0] - 2026-07-17

SCAIL-2 character animation, ported from upstream WanGP v12.3 onto
Maestro's engine with the SAM3 "Magic Mask" stack. Added: SCAIL-2 14B
and SCAIL-2 14B Fast (bundled lightx2v distill, 6 steps, ~13x faster)
as default-enabled Video models; the Recast sub-mode in the Edit tab
(replace a person in a video with a reference character, automatic
keyword-driven masking, preview, scene and audio preserved); a Control
Video input tile for guide-driven models; and a "use current frame as
reference" button on gallery videos. Hardened through field testing:
model-default hydration plus server-side operating guards (sliding
windows, source-fps follow capped at 30, audio remux, true duration
math), a SCAIL-2-aware VRAM budget (in-context tokens), GPU-serialized
Recast detection, and mode-scoped model selection and validation. See
the [README Updates section](README.md#updates).

## [1.2.8] - 2026-07-16

Fix #16: the My LoRAs library view only walked Maestro's own loras
folder while the guide scan and Studio selectors already enumerated
Linked Model Folders. The installed-LoRAs endpoint now uses the scan's
enumeration (primary + linked roots, deduped, mirror-joined sidecars/
guides) and entries carry a Linked badge in the browser.

## [1.2.7] - 2026-07-16

Fix #17, the second domino behind #15 on Linked Model Folder installs:
the internal gemma folder v1.2.6 creates for the text-encoder weight
shadowed the linked install's complete folder for locate_folder, so
the tokenizer load crashed (sentencepiece 'not a string'). The
downloader now completes a partial target folder even when a linked
root holds the full set (self-healing, ~40MB once), and locate_folder
gained required_files so the gemma tokenizer lookups skip folders
without an actual tokenizer inside.

## [1.2.6] - 2026-07-16

Fix #15: on Linked Model Folder installs, text encoders (Gemma 13GB,
Qwen 8B) re-downloaded on EVERY generation and then crashed the load.
download_file moved the weight toward a folder that was never created
(the linked install had satisfied the tokenizer download read-only),
and shutil.move to a nonexistent directory renames the file to the
folder's own name - invisible to the locator forever after. The folder
is now created before the move, the misnamed leftover is cleaned up
automatically (existing victims self-heal), and a missing text encoder
raises a clear error instead of 'Loading Text Encoder None' plus a
TypeError two layers deeper.

## [1.2.5] - 2026-07-16

UI delivery hardening after a community black-screen report: MIME
types for the module bundle are forced server-side (Python reads them
from the Windows registry, which some machines have hijacked to
text/plain - browsers silently refuse module scripts served that way);
a boot watchdog replaces any silent load failure with a diagnostic
page after 10 seconds; and the /classic link works with or without
the trailing slash (the printed banner URL was a 404).

## [1.2.4] - 2026-07-15

Director art-style lock: a vision pass names the reference's medium
once per run and the validated lead sentence ("Maintain the same ...
art style.") is prepended to every image prompt deterministically at
generation time - trailing "preserve the art style" anchors provably
did nothing. Photographic references skip the prefix. Also: motion-
blur/speed-line language is stripped from start-frame prompts in code
(planner energy language leaked into stills), and the performer is
anchored to the reference image so the image model stops inventing a
new design for the star. See the
[README Updates section](README.md#updates).

## [1.2.3] - 2026-07-15

Community-driven round. Added: an Uploads view in the workspace
switcher (browse + reuse uploaded media), a manual model-unload button
in the System panel, and collapsible model families with whole-family
toggles (#14). Fixed: Director Stop aborts the in-flight clip instead
of letting it finish (#12); the Director composer auto-grows upward
(#11); stylized reference images keep their art style; instruction-
example content no longer bleeds into prompts (the dragon) and
user-specified locations are binding; speaker identification actually
runs now (checkpoints auto-download ungated) with music-tuned
clustering; the music Load Settings pencil restores caption, song
description, and the correct audio sub-tab. Changed: a page refresh
starts clean instead of restoring every edit (reverses v1.2.0
save-as-you-type restore; in-session mode-switch persistence stays).
See the [README Updates section](README.md#updates).

## [1.2.2] - 2026-07-14

Director "Analyzing" hang fix for smaller GPUs: the generation model's
VRAM is released before audio analysis loads the vocal separator and
Whisper (Windows' CUDA sysmem fallback made the overflow look like a
silent hang rather than an OOM). Also ships an int8 quanto variant of
the ACE-Step XL SFT transformer (5.5 GB vs 10 GB) so int8-quantized
installs download and load half the model.

## [1.2.1] - 2026-07-14

Fix for existing installs updating to v1.2.0: the enabled-models
whitelist stored in the browser never re-read the shipped defaults, so
the new ACE-Step XL SFT entries stayed hidden and the music default
stayed on Turbo. The curated defaults list is now versioned - new
entries merge into existing installs exactly once - and installs still
on the old music default follow it to XL SFT LM_4B with the model's
recommended settings applied.

## [1.2.0] - 2026-07-14

Two features: light themes (Ivory / Daylight / Pearl as daylight
variants of the three theme families) behind a Dark / Light / Auto
appearance mode that follows the OS, with a large legibility pass so
every status color works on paper; and ACE-Step v1.5 XL SFT, the
premium CFG music model, first shipped anywhere - consolidated weights
hosted at Blizaine/Maestro-Models, a new APG classifier-free guidance
sampling path, and set as the default music model.

Fixes: the vllm LM engine was silently disabled on Windows by a faulty
triton probe (song planning now dramatically faster); LM sampling
defaults now hydrate into the UI (temperature was stuck at 1.0);
Director planning crash on same-sized reference images + false OOM
popup; truncated song durations in the gallery (atomic audio writes);
edits persist as you type and the lyrics prompt survives refresh; new
ACE-Step models classify under Music. See the
[README Updates section](README.md#updates).

## [1.1.3] - 2026-07-12

Fixes: Director-mode start-image thumbnails no longer broken (uploads
endpoint falls back to output-workspace resolution, repairing existing
sidecars too); two-phase "a;b" LoRA multipliers accepted for
user-selected LoRAs on LTX-2 two-stage models (validation now uses the
model's phase capability instead of the request's guidance_phases);
Director LoRA selector uses theme-stable indicator colors so CivitAI
recommendations read green instead of amber on Golden Hour.

## [1.1.2] - 2026-07-12

Director dashboard repair arc: Re-join uses the real concat API with the
source song overlaid; clip reruns generate as a single window at full
planned length (a legacy 129-frame sliding-window default fragmented them
and kept only the first ~5s, breaking rejoin alignment and lip sync);
reruns record the final cumulative save; gallery refreshes after
dashboard actions. Verified end to end on a real 10-clip music video
(rejoined output sample-exact at 150.00s against the 150.00s song).

## [1.1.1] - 2026-07-12

Fixes: Director clip reruns keep the music video's soundtrack (sliced to
the clip's window); dashboard missing-count and Re-join repaired for
multi-clip runs (existing pipeline files backfilled on load); ACE-Step LM
runaway progress display corrected (generation was fine, the counter was
not); Auto-Tune now assigns audio its own memory profile so 12 GB+ cards
get the fast LM decoder instead of the legacy fallback. See the
[README Updates section](README.md#updates).

## [1.1.0] - 2026-07-10

See the [Updates section of the README](README.md#updates) for the
user-facing summary. Highlights: Linked Model Folders (reuse checkpoints
and LoRAs from other installs, read-only), Krea 2 models (Raw + Turbo),
10Eros v1.4 + Reference Pipeline toggle, the LTX-2 Dev quality fix
(leaked euler_ancestral sampler), working STG slider, Load Settings
pencil fix, theme contrast fix (#7), sticky NSFW toggles, and the UI
version badge backed by the repo-root VERSION file.

## [1.0.0] - 2026-07-08 - first public release

Initial public release of Maestro: a local AI video, image, and music studio
built on the [Wan2GP](https://github.com/deepbeepmeep/Wan2GP) pipeline.

### Highlights

- **Studio mode** — manual generation across Video (Frames / Multi-Shot /
  Extend / Blend sub-modes, each with its own isolated working set), Image,
  and Audio. Unified media-driven Inputs panel: drop images/audio/video onto
  tiles and the pipeline (start/end frame, injected keyframes, soundtrack,
  control video, references) is selected automatically.
- **Director mode** — describe a music video or short film and a local LLM
  plans it end-to-end: writes the song (ACE-Step 1.5), analyzes the audio,
  plans per-clip prompts, and renders the full video. Multi-pass planning
  with JSON-grammar-constrained output for reliability on small local LLMs.
- **Music mode** — ACE-Step v1.5 XL music generation with an LLM song-writer
  (describe → Style + Lyrics, editable guide).
- **Edit modes** — Retake (regenerate a time region), Inpaint (SAM 3.1
  text-driven segmentation), Restyle, and Edit Anything (IC-LoRA).
- **Tools** — FlashVSR DiT video upscaling (2x/3x/4x, chunked for long
  videos) and SeedVC revoice with background preservation, usable on any
  gallery or uploaded clip.
- **Voice** — TTS voice cloning, per-speaker voice references, ID-LoRA voice
  identity preservation (experimental), cross-clip voice consistency.
- **Hardware auto-tune** — detects GPU/VRAM/RAM on first launch and picks a
  performance profile; OOM recovery banner with one-click fix.
- **LoRA management** — CivitAI browser with per-LoRA auto-generated prompt
  guides, weight recommendations, and per-checkpoint enhance guides.
- **100% local** — no telemetry, no accounts, no cloud dependency. Optional
  external LLM APIs are opt-in and off by default.

### Requirements

NVIDIA GPU (6GB+ VRAM; 24GB recommended for the full experience), Windows or
Linux, installed via [Pinokio](https://pinokio.computer). Models download on
first use per model (the default set is ~30GB; the full collection exceeds
300GB).
