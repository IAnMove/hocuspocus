# HocusPocus · Creation Lab

A local studio for turning an idea into a production: story, pictures, clips, comics, sound and 3D — with every intermediate result visible and editable.

HocusPocus is an experimental, **non-commercial** fork of [Blizaine/Maestro](https://github.com/Blizaine/Maestro) by [Blaine Brown](https://github.com/Blizaine) ([@blizaine](https://x.com/blizaine)). Maestro already did the hard part: a serious local generation stack on [Wan2GP](https://github.com/deepbeepmeep/Wan2GP). We keep that foundation and add the missing production layer — a world that can be planned, directed, recovered and revised without starting from zero.

The **HocusPocus** mark is a quill shaping a cube: imagination becoming a buildable world. The UI is English and Spanish.

Open **Help / Ayuda** next to Settings for the in-app tutorial, with screenshots of the layout, generation, studios and queue. Its ES/EN selector changes the UI language. Use Tab and Shift+Tab to navigate the dialog; Escape closes it and returns focus to Help.

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
| Image | Flux 2 Klein, Qwen Image 2.1, Qwen Image Edit |
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

**Generate all / Regenerate all** in **Series Lab → Shots** prepares editable 2D scenes and MP4 takes. Each shot also has **Regenerate this shot**. The app removes character backgrounds, uses saved voices and synchronizes mouths to each isolated recording with the offline Rhubarb engine. English recordings also use the script; other languages use phonetic recognition. New speaking-shot preparation requires all nine mouth positions; previously rendered clips and imported four-mouth scenes remain usable. The **20 mouth styles** provide complete nine-position packs, and Character Creator shows missing slots before generation. Download individual styles or all 20 as PNG packs from Character Creator. Saving a character creates a reusable resting still with the selected mouth while retaining the mouthless animation base. Configured listeners and silent shots use that resting mouth too.

Regeneration preserves saved motion and audio and appends unapproved versions; approved takes remain available. Save the character workshop, return to Shots and click **Regenerate all** to update existing scenes. Missing setup links directly to the character. Keep the tab open during the batch. Completed shots release their temporary recovery copies after the editable scene and video are saved; unsaved editor changes and failed preparations retain their backups. Install/Update prepares the pinned offline engine; **Pinokio → Advanced → Repair offline lip sync** repairs it separately. See [2D speech quality and mouth packs](docs/character-kits/SPEECH_QUALITY.md).

**Results** separates approved references from pending video takes and links to each incomplete item. **Generate AI draft takes** leaves its outputs awaiting review; 2D/3D and imported shots have their own production shortcuts.

You can also enable production methods directly in **Series Lab → Shots**. For an existing episode, select an enabled method and use **Apply to shots without a take** to assign it across unfinished shots; completed and active takes are preserved.

Location image prompts describe empty environments. Series Lab separates the physical setting and rendering style from character design and narrative occupants before generating. Use **Prepare environment prompt** in the location card to review the exact prompt first.

Character Creator identifies each Qwen3 preset by its original language/profile and timbre. The nine presets can speak several languages, but none is natively Spanish. Use **Generate voice sample** with a Spanish or English sentence to hear the selected voice before saving or preparing mouths. Changing the voice cancels only that audition and stops the previous sample.

Choose **Add your own voice: import or record** to use **Qwen3 Base** with a clean 3–30 second recording (up to 20 MB). Import an audio file or record with the microphone, name the voice, enter the exact recording transcript, and choose the language for new dialogue. Audition it, then **Save everything** on the character. Saved custom voices appear in the voice selector for other characters; new or regenerated native 2D/3D dialogue uses the stored recording and transcript. Existing takes remain available. Recording requires a browser with microphone support on HTTPS or localhost; importing also works over LAN HTTP. Audio samples are stored as persistent local uploads, and character metadata stores public references rather than machine-specific paths. No new model or recording is generated merely by selecting or saving a voice.

Each **Canon → Characters** card also shows voice, 2D lip-sync and 3D lip-sync readiness. **Configure in Character Creator** opens a dedicated view for that exact character, carries over its reference image, and links the saved configuration by ID. The Series card keeps its library selector. **Save everything and return to Series Lab** saves voice, mouth images and placement together, then returns to the source character. A failed save retains the draft and keeps the editor open; a fully saved session can yield to the next character even after switching tabs. A voice can be saved without a 3D model. Save the character before opening its 2D mouth workshop or 3D face calibration. The mouth workshop has a rectangle whose width and height can be adjusted independently, a visible mouth-pack catalog with previews, explicit AI generation buttons, and a one-click prerecorded English voice sample for previewing mouth movement without generating speech. **Apply placement to all mouths** copies the current position, scale and rotation to all nine mouth shapes. **Try with their voice** previews the full isolated recording with the same phonetic analyzer as native shots, including pauses and resting-mouth closure; the separate quick text preview is approximate. Eyes and blinking are optional: keep the original drawing unless you want to add overlays. Review the cleaned base and mouth variants, then save the speech character. Dialogue shots open Character Creator directly; the advanced voice table links to the character card. AI video with native audio continues to use its generator's voice; the reusable TTS preset is used in the speech editor.

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

### Creative and Dark Fantasy perspective templates

In **Studios → Video 3D → Shot library**, **Perspectives** adds 20 new vertical scenes with a [clip review page](ui/public/examples/perspective-lab/README.md). **Creative** now offers 50 vertical scenes ranging from neon streets and paper landscapes to orbital gardens and ceramic architecture. **Dark Fantasy** offers 60 more: ten landscape compositions, ten vertical scenes, ten PSX variants, twenty layered worlds with animated landscapes, and eight fixed-camera studies. Play and rate the new colossi, ruins, forests and oceans in the [Living Dark Fantasy gallery](ui/public/examples/dark-worlds/README.md). These editable 2.5D scenes use grounded image characters with gentle camera movement or a fixed viewpoint. The fixed-camera set includes six new characters and an eight-second wounded-knight study whose poses hold and jump while the environment flows. Play and rate it in the [Time Has Weight gallery](ui/public/examples/dark-stillness/README.md). **PSX** includes selective treatments of characters, props or backgrounds; each image layer can keep its own style. Edit depth, contact shadows, tint, camera movement, spatial effects and the floor projected from the backdrop, then render with the native compositor. See the [Creative guide](ui/public/examples/creative/README.md) and [Dark Fantasy guide](ui/public/examples/dark-fantasy/README.md) for editing and sharing.

**Video background removal** is available in **Studio → Tools → Remove background**. Choose a video to create a reusable transparent WebM with audio. The [Moving Cutouts gallery](ui/public/examples/moving-cutouts/README.md) adds six native compositions: a walking knight and an illustrated skater over independently moving backgrounds. Their editable templates are included in the shot library.

The [Skate Portal study](ui/public/examples/skate-portal/README.md) joins four editable shots into a vertical jump between the coast and a cloud road. Portal videos follow the scene clock, including backward scrubbing and export; each portal owns and releases its media independently.

The [Kingdom Road collection](ui/public/examples/kingdom-road/README.md) extends the skater and PSX dragon journeys across 35 animated backgrounds. It also includes a Spanish YuE2 song with a beat-aligned music film, editable scene archives and downloadable media. Video layers expose source intervals, forward/backward looping and sequence time offsets under **Continuity between shots**. Native exports reuse a bounded local video cache for faster seeks, preserve transparent characters, and share the GPU queue with generation.

The preview fits portrait scenes between black sidebars while keeping editor controls readable. **Expand video** shows just the picture fullscreen. Select covered characters, props or backgrounds in **Scene objects**, then move, rotate or scale them. For a cutout layer, enable **Animate this layer** and choose a video from the gallery or upload one; its depth and individual PSX treatment are retained in saved scenes and native exports.

If automatic background removal leaves color inside a ring, between ropes or along an edge, select the layer and enable **Image appearance → Clean transparency**. Choose the leftover background color, then increase **Tolerance** gradually and adjust **Soft edge**. The cleanup works on still images and animated cutouts, keeps existing transparency, and can be combined with PSX. It is saved with the scene and can be disabled without changing the source file. Colors shared by the object and its background need a more selective mask; keep tolerance low to protect pale details.

For a stationary viewpoint, select **Fixed camera**. Image cutouts can use **Held poses** with per-pose duration, relative height and ground placement. **Preserve transparency** supports images and videos that already have alpha, including transparent WebM; it does not segment an opaque video. These controls remain editable in saved scenes and portable templates.

The [Portal Ride study](ui/public/examples/skate-portal-v2/README.md) expands that experiment to three continuous world changes. Native world effects now support editable position/rotation/scale keyframes and screen-projected portal video with its own start, speed and loop controls.

The [Portal Rides gallery](ui/public/examples/portal-rides/README.md) adds a downhill skater and a dragon rider. **Cinematic stage → Endless road** keeps a separately moving road underneath world changes; edit speed, slope and timeline continuity. **Image appearance → Tilt** rotates a cutout around its foot anchor to match a slope. Both clips are saved native scenes with portable templates, rendered from interpolated transparent video layers at natural speed.

### Qwen Image 2.1 in Studio

Choose **Image → Create**, **Edit**, or **References**. Each keeps its own prompt,
canvas, image inputs, sampling settings, seed, LoRAs and output count; switching
back restores the draft. The selected model is shared between these flows.
Create submits no hidden editing image or mask. Edit needs a source; References needs references.
**Start over** clears these drafts. Panorama has its own generation button.

Gallery actions distinguish **Edit this image** (use the result as the new source),
**Load settings** (restore the complete saved recipe) and **Use as reference**.
Loading settings or applying a recipe restores source, mask, references, method,
sampling and LoRAs together. Missing inputs produce an error without replacing
the current draft; a late download cannot overwrite a newer edit. Stored inputs
keep their source workspace. Hidden model variants can still be restored by ID.
Once Generate is pressed, the submission retains its selected local source and
mask even if those inputs are replaced while the job is being prepared.
Edit Anything / Viggle opens an extracted frame in References and restores the
previous reference draft when the frame is applied, skipped or cancelled.

Qwen 2.1 and Qwen Edit Plus/Plus2 accept additional references inside **Edit**;
the source counts toward the model's input limit. Older Qwen image models expose
their supported inpainting methods and outpainting controls. Studio keeps the
public image mode at `1` and translates legacy masked edits to native mode `2`
at the server boundary. Qwen Layered offers an editing source and **Number of
layers**, separate from the number of queued results. Incompatible flows are
excluded from the chooser and blocked if already open after a model switch.

Start with **Auto / 1K**, **40 steps**, **CFG 1**. Every Qwen 2.1 preset uses
32-pixel aligned dimensions. Auto aspect follows the editing source; without a
source it is square. **2K** has roughly four times as many pixels and requires
more time and memory. Recommended 1K canvases:

| Format | Pixels | 2K option |
|---|---|---|
| Square | 1024×1024 | 2048×2048 |
| Landscape 16:9 | 1376×768 | 2752×1536 |
| Portrait 9:16 | 768×1376 | 1536×2752 |
| Landscape 4:3 | 1184×896 | 2400×1792 |
| Portrait 3:4 | 896×1184 | 1792×2400 |
| Wide 21:9 | 1536×672 | 2816×1216 |

Use **VAE tiling: Auto** for memory management, including on a 24 GB GPU.
Explicitly disabling tiling can still exhaust VRAM. The INT8 ConvRot text encoder
now restores embedding orientation when loading; this also applies when the
image transformer uses GGUF. No checkpoint re-download is required.

**Fit to model** exports PNG, keeps transparency and applies the same crop,
padding or stretch to the editing mask. Black mask padding preserves that area.
Replacing a source clears its previous mask and outpainting margins.

The **Activity** footer shows model, canvas, current stage, steps and a truncated
prompt. Hover over the prompt to read it in full, or click to copy it. **Generate**
keeps its action label; the separate active-job count includes running and queued
jobs. The activity panel also opens while loading or reconnecting. Incomplete
image writes are hidden until publication. Missing-model errors identify the
selected variant and required files. ETA becomes
available after measured sampling steps, excluding loading and reference encoding;
decoding and saving can add time. It is an estimate for the current sampling pass,
not a hardware-independent promise for the entire queue.

The version-2 image command API accepts the same explicit resolutions. Reuse an
`intent_id` only when retrying exactly the same request. Example request body:

```json
{"version":2,"operation":"generation.image","intent_id":"my-qwen-image-001","input":{"workspace":"default","params":{"model_type":"qwen_image_21","prompt":"A red toy house in a sunny meadow","resolution":"1024x1024","num_inference_steps":40,"guidance_scale":1,"seed":7}}}
```

Save it as `qwen-request.json`, then submit to your running app:

```bash
curl -H 'Content-Type: application/json' --data-binary @qwen-request.json "$HOCUS_BASE_URL/api/v1/generation/commands"
```

```javascript
const body = JSON.parse(await (await import('node:fs/promises')).readFile('qwen-request.json', 'utf8'));
const result = await fetch(`${process.env.HOCUS_BASE_URL}/api/v1/generation/commands`, {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
});
console.log(await result.json());
```

```python
import json, os, urllib.request
body = json.load(open('qwen-request.json', encoding='utf-8'))
request = urllib.request.Request(
    os.environ['HOCUS_BASE_URL'] + '/api/v1/generation/commands',
    data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request) as response:
    print(json.load(response))
```

Use the receipt to identify the admitted job; live canonical tasks are available
at `/api/v1/tasks` and `/api/v1/tasks/events`. For editing, use uploaded/catalog
references through the command reference endpoint; local browser tokens are
materialized by Studio before submission.

The abenzerps GGUF entries retain their legacy `qwen_image_21_uncensored_*`
identifiers so saved recipes keep working, but are hidden from the model selector
until they offer a verified distinction from the other Qwen 2.1 variants. Existing
downloaded weights are kept. The [publisher's current model card](https://huggingface.co/abenzerps/Qwen-Image-2.1-GGUF)
identifies the downloads as quantizations of the original base weights and says
a separate uncensored version is still in development. The former name is not
evidence of a distinct uncensoring fine-tune.

Image previews open from gallery cards and selected source/reference thumbnails.
The enlarged view shows dimensions, file details and available generation metadata,
with the full saved record under **All saved information**. Activity uses frozen
reference links from the submitted job, with cached thumbnails and the same enlarged
view. Updating the model catalog preserves the current Studio draft. A server or UI
update now offers an explicit reload instead of discarding an in-progress form.
