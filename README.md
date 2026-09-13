# HocusPocus · Creation Lab

A local studio for turning an idea into a production: story, pictures, clips, comics, sound and 3D — with every intermediate result visible and editable.

HocusPocus is an experimental, **non-commercial** fork of [Blizaine/Maestro](https://github.com/Blizaine/Maestro) by [Blaine Brown](https://github.com/Blizaine) ([@blizaine](https://x.com/blizaine)). Maestro already did the hard part: a serious local generation stack on [Wan2GP](https://github.com/deepbeepmeep/Wan2GP). We keep that foundation and add the missing production layer — a world that can be planned, directed, recovered and revised without starting from zero.

The **HocusPocus** mark is a quill shaping a cube: imagination becoming a buildable world. The UI is English and Spanish.

<p align="center">
  <img src="docs/images/readme/gandalf-hero.jpg" alt="Gandalf and Tentri in a HocusPocus Video 3D scene" />
</p>

Gandalf and Tentri, from a real **Video 3D** production (world compositor, image lip-sync, MiniMax plates on the screens). Not a mockup.

The same clip inside the running studio (gallery, Wizard, Spanish UI):

![HocusPocus gallery playing the Gandalf Video 3D export](docs/images/readme/studio-gallery.jpg)

Install with [Pinokio](https://pinokio.computer) from [`https://github.com/IAnMove/hocuspocus`](https://github.com/IAnMove/hocuspocus). NVIDIA GPU required.

---

## What you can do

### Direct a film, videoclip or trailer

**Director** takes a brief (or a song) and turns it into reviewable shots, prompts and references. Manual mode lets you approve each step. Auto mode runs analyze → plan → images → clips → assemble, and **Productions** keeps the whole thread so you can resume or retake one shot.

**Example — music video.** Drop a track. Director reads BPM, sections and energy, writes shots on the downbeats, generates start frames with the same characters, then runs the video model. Open **Productions** if a chorus clip fails; regenerate that shot only.

**Example — short film.** Write “two couriers argue in a rainy alley, then one reveals a glowing cube.” Director writes a screenplay, named cast, continuity across cuts. Pick MiniMax H3 for picture + native stereo audio, or Wan / LTX / Hunyuan Video for picture-only pipelines.

**Example — trailer without a song.** In **Story Lab** create a *Tráiler cinematográfico*. You get a 6–12 beat theatrical arc (cold open → unresolved hook), then generate 15–180 seconds as text-to-video or from approved frames.

### Build a world once, reuse it everywhere

**Story Lab** is the production bible: premise, world rules, locations, cast, relationships, beats. Approve fields, then hand the canon to Comics, Director, trailers or videoclips. Export a `.storypack` when you want to move the project.

**Example.** Approve a desert city, three characters and a logline. Open **Productions → Comic** for a 4-page chapter that does not retell the whole plot. Open **Short Film → Story** with the same canon and the same identity images. The writing model stays the one you picked on the story, not a silent global default.

Walkthrough with screenshots: [Story → Comics → Video](docs/MAESTRO_X_STORY_COMICS_VIDEO.md).

### Draw a comic, then optionally film it

**Comics** plans pages and panels, drafts a script you can rewrite, generates art per panel, letters with restraint, and exports PDF / CBZ / PNG. Translation can rewrite balloons without touching artwork.

**Example — Comic → AI film.** Approve the comic first. The film path feeds the canon and every planned scene to the LLM, strips lettering from the panels, and uses each panel as the real first frame of that shot. You spend video time, not a second comic pass.

### Generate one asset by hand

**Studio** is the manual bench: pick image, video or audio, write the prompt, add references and LoRAs, generate. Outputs land in the gallery and are reusable as references, editor clips, 3D plates or comic identities.

| Kind | What ships in the box (among others) |
|---|---|
| Video | MiniMax H3 (picture + stereo audio), Wan 2.1 / 2.2, Hunyuan Video, LTX-2.3 |
| Image | Flux 2 Klein, Qwen Image Edit |
| Audio | ACE-Step 1.5 XL (default new songs), MiniMax Music, Kugelaudio / Qwen3 TTS, MMAudio SFX |

**Example — MiniMax H3.** Prompt a wide night sea and add `Audio: surf, wind, a low cello`. Use **FL2VA** when you have an exact first/last frame from Story. Use **Ref2VA** when you pass up to 9 images, 3 videos and 3 audio clips as identity/mood references (`<Picture 1>`, `<Video 1>`, `<Audio 1>`).

### Steal a look from a real H3 style library

**Hoja de estilos / Style sheet** imports [ostris/minimax_h3_1k](https://huggingface.co/datasets/ostris/minimax_h3_1k) by [ostris](https://huggingface.co/ostris) ([@ostrisai](https://x.com/ostrisai)): 1,000 MiniMax H3 clips with full multimodal captions (look, action, soundscape, music). Each style keeps author, repo, revision and a preview. Search, apply the prompt language to a new H3 job, or keep the clip as a visual reference.

**Example.** Download the source from the Style sheet tab. Filter “claymation”. Open a style, copy its visual lead-in into Studio H3, keep your own story beats. That library is how HocusPocus learned what a strong H3 brief looks like — credit ostris when you show the results.

### Make 3D, then shoot it like a set

**3D** runs [Hunyuan3D](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) in an isolated env: text, one image, or front/left/right/back views → GLB. **Retexture GLB** paints a new copy; the source file stays untouched.

**Character Creator:** one photo → H3 360° turntable → pick front/left/back/right → Hunyuan multi-view mesh.

**3D Video** is a real compositor (not a video model pretending to be a camera): place GLBs, images, Character Kits, lights and **world SFX** (portals, circles, beams, auras, missiles — they live in the 3D world, occlude, and export with the shot). **Animate** can rig a static GLB. **Face Rig** is the 2D cutout path: mouth overlays on a reviewed pose, not a mesh.

**Example.** Photo of a courier → Character Creator mesh. Drop it in 3D Video with a street plate. Anchor a magic circle to the character, pause mid-walk, nudge the gizmo — the offset follows the live pose. Export MP4. Operator guide: [3D Video compositor](docs/3d-video-compositor/HOWUSEIT.md), [Character Kits](docs/character-kits/HOWUSEIT.md).

**Video 3D editor** (live compositor: stage, Play, world SFX, lip-sync):

![Video 3D scene studio](docs/images/readme/video3d-editor.jpg)

Gandalf speaking in that world (image lips on the mesh, not a baked video):

![Gandalf image lip-sync in Video 3D](docs/images/readme/video3d-gandalf.jpg)

**Video 2.5D** compositor (layers, plates, SFX, export):

![Video 2.5D compositor](docs/images/readme/video2d-editor.jpg)

**Image lips / Face Rig** — click the mouth on the portrait, place overlays, then play them in the stage:

| Close-up | Placement in the 3D stage | Character Creator → Face Rig |
|---|---|---|
| ![Gandalf image lips](docs/images/readme/imagelips-closeup.jpg) | ![Mouth overlay on the 3D stage](docs/images/readme/imagelips-stage.jpg) | ![Create or open CharacterKit Face Rig](docs/images/readme/face-rig.jpg) |

### Talk to the studio

The **Wizard** is an in-app director: “open the concert scene”, “prepare a 3D showcase”, “make a 5-second clip of the cube in the rain”. **MCP** exposes the same jobs to external agents (image, video, SFX, scenes, receipts). Switching the footer workspace while a Wizard scene is still loading will **not** stomp the compositor or wipe undo.

Connect through **Settings → Integrations → Hocuspocus MCP**, using the app's address plus `/api/v1/mcp` and the MCP Bearer token. This is Hocuspocus's shared tool server, including generation, assets, collections and scenes supported by the installation. The historical `/api/v1/wangp/mcp` URL remains an alias for existing clients. See the [MCP connection guide](docs/development/SCENE_EFFECTS_AND_MCP.md#enable-and-connect-mcp).

**Example.** In 3D Video, ask the Wizard to open a saved scene by name and select a layer. If you change output folder mid-load, it aborts instead of importing into the wrong world.

Wizard interprets your intended outcome using the conversation and current project. Describe what you want in your own words: it can explain, ask for essential missing context, or plan supported actions. Questions remain visible even when it also opens a lab. Once a series request has creative direction, Wizard can propose missing titles and plot details and save a first episode draft without another interview. Its receipt includes the saved series and episode premises. Opening Series Lab alone does not generate an episode's media.

In **Series Lab → Canon**, generate reference images from each character or location's description and the series style. Use **Shots → Generate all missing references** to prepare the episode's characters and environments in a batch. Approve the images with the canon, then click **Use approved references in this episode** directly in Shots. Existing series images are reused without another generation. **Setup → Allowed production methods** lets you combine AI video, 2D animation, 3D scenes and imported clips; each shot has its own method and production controls. See [Series production and references](docs/series-lab/IMPLEMENTATION.md#reference-images-and-mixed-production).

For 2D/3D animation, prepare both environments and characters. Each shot shows its environment selector and reference previews, and opens the editor once the episode has approved images for the environment and every visible character. Preparation shortcuts lead directly to the corresponding Bible cards. An establishing shot can use just its environment.

**Generate all pending 2D shots**, available in Shots and Results, removes character backgrounds, generates dialogue with saved character voices, saves editable scenes and renders/imports every missing take. The batch preserves existing drafts and approved takes. Keep the browser tab open; stop finishes the current shot and retry skips completed takes. Character cards also offer **Remove character background**, retaining the original approved image. Dialogue requires a saved base pose, four approved mouth shapes and mouth placement in Character Creator. The batch mounts that exact pose (including mouth erasure), removes its background and animates the saved mouths using the text and recorded phrase duration. Missing configuration links directly to the character. **Update lip sync in generated takes** reuses saved scene motion and audio to append new unapproved takes after mouth/placement changes, preserving earlier and approved takes. Save the mouth workshop before refreshing the configuration in Series Lab.

**Results** separates approved references from pending video takes and links to each incomplete item. **Generate AI draft takes** leaves its outputs awaiting review; 2D/3D and imported shots have their own production shortcuts.

You can also enable production methods directly in **Series Lab → Shots**. For an existing episode, select an enabled method and use **Apply to shots without a take** to assign it across unfinished shots; completed and active takes are preserved.

Location image prompts describe empty environments. Series Lab separates the physical setting and rendering style from character design and narrative occupants before generating. Use **Prepare environment prompt** in the location card to review the exact prompt first.

Each **Canon → Characters** card also shows voice, 2D lip-sync and 3D lip-sync readiness. **Configure in Character Creator** opens a dedicated view for that exact character, carries over its reference image, and links the saved configuration by ID. The Series card keeps its library selector. **Save everything and return to Series Lab** saves voice, mouth images and placement together, then returns to the source character. A failed save retains the draft and keeps the editor open; a fully saved session can yield to the next character even after switching tabs. A voice can be saved without a 3D model. Save the character before opening its 2D mouth workshop or 3D face calibration. The mouth workshop has a rectangle whose width and height can be adjusted independently, a visible mouth-pack catalog with previews, explicit AI generation buttons, and a one-click prerecorded English voice sample for previewing mouth movement without generating speech. **Apply placement to all mouths** copies the current position, scale and rotation to the four mouth shapes. Eyes and blinking are optional: keep the original drawing unless you want to add overlays. Review the cleaned base and mouth variants, then save the speech character. Dialogue shots open Character Creator directly; the advanced voice table links to the character card. AI video with native audio continues to use its generator's voice; the reusable TTS preset is used in the speech editor.

### Finish without regenerating

**Video Editor** trims, splits and reorders clips you already like (H3 MP4s, compositor exports, series handoffs). Export is a queued FFmpeg job. Guide: [Video Editor](docs/video-editor/HOWUSEIT.md).

**Studio Tools** post-process an existing image or clip (FlashVSR/Lanczos upscale, SeedVC revoice, rembg) and always write a new file. Guide: [Studio Tools](docs/tools/HOWUSEIT.md).

**Edits** (experimental): retake a section, outpaint a frame, prompt-driven replace. **Multi-clip** is for longer prompt-by-prompt sequences with overlapping continuity.

### Housekeeping that actually matters

- **Output folders** are physical save directories (client A vs B, SFW vs NSFW).
- **Workspace collections** group projects without moving files. The gallery **Workspaces** tab is the Director thread dashboard for the *active* folder — [guide](docs/workspaces/HOWUSEIT.md).
- **CivitAI LoRA browser** with one-click install, update badges, and auto-written prompting guides from CivitAI / Hugging Face cards.
- **Local LLM** (Gemma 4 / Qwen GGUF via llama.cpp) or external OpenAI / Anthropic / compatible endpoints. Unloads after idle so VRAM goes back to generation.
- **Themes:** Golden Hour, Classic, Onyx.
- **LAN:** optional share on the local network; optional token auth (`LOREFRAME_LAN_AUTH`). Creating series drafts, characters and speech clips also works from plain HTTP network URLs. After updating, reload the browser; Wizard can continue an empty series draft with the same title after a failed creation attempt.
- **NSFW** and experimental gates are opt-in.

Operator index: [docs/HOWUSEIT.md](docs/HOWUSEIT.md).

---

## A typical production

1. Create canon in **Story Lab** (or skip it and start in **Studio**).
2. Approve a character and a location. Optional: import ostris styles so H3 speaks a consistent look.
3. Generate a few clips in **Director** or one-off shots in **Studio**.
4. For exact cameras, build a **3D Video** scene from Hunyuan GLBs / kits / world SFX.
5. Assemble in **Video Editor**. Keep sources in the same **output folder**.
6. If anything dies mid-run, open **Productions** — do not start from zero.

Every step can also start from an existing image, video, audio file or GLB.

---

## Requirements

| | Minimum | Recommended |
|---|---|---|
| **OS** | Windows 10/11 or Linux | Windows 11 or Linux |
| **GPU** | NVIDIA, 6 GB VRAM | RTX 3090 / 4090 / 5090, 24 GB+ |
| **RAM** | 16 GB | 32 GB+ |
| **Disk** | 150 GB free | 500 GB free for a full model shelf |
| **Python** | Installed by Pinokio | — |

| Card | After models are cached |
|---|---|
| 24 GB | comfortable; short clips in a few minutes |
| 12–16 GB | auto-tune offloads; slower |
| 6–8 GB | works with heavy offload; keep clips short |

AMD GPUs and macOS are **not** supported (CUDA kernels). First launch downloads weights on demand (often 50–100 GB; the full set can pass 300 GB). Hunyuan3D compiles native extensions: on Windows you want CUDA Toolkit and Visual Studio Build Tools.

## Install

1. Install [Pinokio](https://pinokio.computer).
2. Discover → paste `https://github.com/IAnMove/hocuspocus`, or download from this repo.
3. **Install**, then **Start**. The first job on each model fetches its weights.

Pinokio **Install** and **Update** share Windows/Linux recipes with separate Python environments and pinned dependencies per engine. Update also rebuilds the UI. SAM (Inpaint) and UniRig are optional menu installs; UniRig currently has a Linux recipe. See [runtime profiles and recovery](docs/development/RUNTIME_PROFILES.md).

**Start** verifies and repairs the React build before loading the backend. For a missing or incomplete interface, stop Start, use **Repair Web UI**, then Start again; models are preserved. Startup logs show the app version, commit, OS and React build ID for bug reports. See [React recovery and manual commands](docs/development/REACT_INSTALLATION.md).

**Reset** removes the managed environments, vendor checkouts and UI build, including the Hunyuan model cache in `app/ckpts/model3d`. Use Install/Update to retry a failed setup; Reset is destructive.

To inspect the selected runtime recipes, use the URL shown by Start (replace the example host and port, including when connecting over LAN):

```sh
curl -X GET http://127.0.0.1:7860/api/v1/runtime-capabilities
```

```python
import requests
report = requests.get("http://127.0.0.1:7860/api/v1/runtime-capabilities", timeout=30).json()
print(report["engines"])
```

```javascript
const report = await fetch('/api/v1/runtime-capabilities').then(response => response.json());
console.log(report.engines);
```

---

## How it is built

HocusPocus is not a single Python script with a web wrapper. It is a small studio stack:

1. **Pinokio** clones this repo, creates isolated environments, and owns Install / Start / Update / Reset. The published line is `main`; day-to-day work lands on `development`.
2. **FastAPI** (`app/`) is the studio server: jobs, gallery, provenance, Director pipelines, 3D, comics, styles, MCP. The React UI (`ui/`) is the control surface. Both languages share the same commands.
3. **Generation** still runs on the WanGP lineage Maestro already integrated — Wan, Hunyuan Video, LTX, Flux, audio models — plus an isolated **MiniMax H3** ComfyUI runtime (picture and native stereo audio) and an isolated **Hunyuan3D** env (meshes). Optional SAM and UniRig live in their own envs so their stacks cannot fight the video venv.
4. **Director** is a multi-pass LLM planner (story → shots → per-model polish, including LoRA guides). It writes artifacts you can inspect. **Productions** serializes that state so a crash is a resume, not a myth.
5. **3D Video** renders in the browser (Three.js). World SFX are objects in that scene, not 2D overlays. Export is local composition + FFmpeg, not “ask a video model to pretend it dollied”.
6. **Style sheet** stores ostris’s H3 captions with source attribution. **Wizard** and **MCP** call the same backend tools the buttons use, so an agent cannot do a secret second pipeline.
7. **Auto-tune** profiles VRAM on first launch. Jobs report through the footer. Nothing important is only in a chat bubble.

If you are automating: `POST /api/v1/generate` and `POST /api/v1/model3d/generate` are the same contracts the UI uses. MCP tools are listed by the running server (`tools/list`). Do not scrape internal Python.

Lineage in one line: **Wan2GP → Maestro → HocusPocus**, plus Hunyuan3D, MiniMax H3, ostris’s H3 style corpus, Pinokio, and the models credited below.

---

## Credits

We would not exist without the people who shipped the layers we stand on. Tag them if you show HocusPocus.

### Direct ancestors

| Who | What | Links |
|---|---|---|
| **Blaine Brown** | [Maestro](https://github.com/Blizaine/Maestro) — the local studio we forked | [@blizaine](https://x.com/blizaine) |
| **deepbeepmeep** | [Wan2GP / WanGP](https://github.com/deepbeepmeep/Wan2GP) — generation pipeline and non-commercial license we inherit | [@deepbeepmeep](https://x.com/deepbeepmeep) |
| **cocktailpeanut** | [Pinokio](https://pinokio.computer) and the original Wan2GP launcher | [@cocktailpeanut](https://x.com/cocktailpeanut) |

### Style corpus we imported

| Who | What | Links |
|---|---|---|
| **ostris** | [minimax_h3_1k](https://huggingface.co/datasets/ostris/minimax_h3_1k) — 1,000 H3 clips and multimodal captions that power **Style sheet**. Also [AI Toolkit](https://github.com/ostris/ai-toolkit). | [@ostrisai](https://x.com/ostrisai) · [HF](https://huggingface.co/ostris) |

The dataset card does not name a license. We keep author, repo and revision on every imported style and do not claim those prompts as ours.

### Models and runtimes (non-exhaustive)

| Who | What | Links |
|---|---|---|
| **MiniMax** | MiniMax H3 (FL2VA / Ref2VA, native stereo audio), MiniMax Music | [@MiniMax_AI](https://x.com/MiniMax_AI) · [HF](https://huggingface.co/MiniMaxAI/MiniMax-H3) |
| **Comfy-Org** | H3 ComfyUI runtime we isolate | [PR](https://github.com/Comfy-Org/ComfyUI/pull/15224) |
| **Tencent Hunyuan** | Hunyuan3D 2 / 2.1 (meshes, paint) and Hunyuan Video | [@TencentHunyuan](https://x.com/TencentHunyuan) |
| **Alibaba / Wan-Video** | Wan 2.1 / 2.2 | [Wan2.1](https://github.com/Wan-Video/Wan2.1) |
| **Lightricks** | LTX-Video 2 / 2.3 | [LTX-Video](https://github.com/Lightricks/LTX-Video) |
| **Black Forest Labs** | Flux | [@bfl_ai](https://x.com/bfl_ai) |
| **Qwen / Alibaba** | Qwen image + LLMs | [Qwen](https://github.com/QwenLM/Qwen) |
| **Google** | Gemma 4 (default local Director LLM) | [Gemma](https://ai.google.dev/gemma) |
| **Meta** | SAM (optional Inpaint) | [SAM](https://github.com/facebookresearch/sam2) |
| **llama.cpp** | Local GGUF inference | [llama.cpp](https://github.com/ggml-org/llama.cpp) |
| **CivitAI** | LoRA browser and community weights | [civitai.com](https://civitai.com) |
| **MMAudio** | Ambient audio | [MMAudio](https://github.com/hkchengrex/MMAudio) |
| **seed-vc** (Plachta) | Voice conversion, GPL-3.0, cloned at install from [maestro-seedvc](https://github.com/Blizaine/maestro-seedvc) | [seed-vc](https://github.com/Plachta/seed-vc) |

Other vendored pieces keep their own licenses, including BigVGAN (MIT), FlashVSR sparse-sage (Apache-2.0), IndexTTS2, Rhubarb lip-sync, BS-RoFormer / audio-separator, Three.js, UniRig (optional), and Tencent’s Hunyuan checkouts. Read those `LICENSE` files before you redistribute.

If we missed a name you shipped into this tree, open an issue — we want the list complete.

---

## License

**WanGP Non-Commercial Evaluation License 1.1**, inherited through Maestro from Wan2GP. Summary: [LICENSE](LICENSE). Full text: [app/LICENSE.txt](app/LICENSE.txt).

**TL;DR:** free to use and modify for non-commercial purposes. *Outputs you generate* are yours to use commercially (with attribution). Commercial use of the *software* (including hosted APIs) needs a separate license from the WanGP licensor. Third-party models keep their own terms.

---

## Issues

Bugs and requests: [github.com/IAnMove/hocuspocus/issues](https://github.com/IAnMove/hocuspocus/issues).
