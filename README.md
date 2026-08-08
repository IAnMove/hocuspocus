# Loreframe Lab

> Loreframe Lab is an experimental, non-commercial fork of [Blizaine/Maestro](https://github.com/Blizaine/Maestro). Features and workflows may change while we explore persistent story worlds, comic-to-video production, episodic continuity and optimized local generation.

A one-click AI **video, image, and audio studio** for creators. Loreframe Lab builds on Maestro's modern React UI and generation backend, adding a **Director mode** that uses an LLM to plan music videos and short films from a single prompt. Optimized for the latest LTX-2.3 models & LoRAs, with support for virtually all open weight models.

![Loreframe Lab UI](Maestro_UI_02.jpg)

## What it does

### 🎬 Director Mode — automatic music videos and short films
The flagship feature. Drop in an audio track or write a story; a local LLM plans every shot, writes screenplays/lyrics, generates start frames & keyframes with character consistency, polishes prompts per model & LoRA-specific prompting guides, and runs the full multi-clip generation. Two skills:

- **Music Video** — beat-aware shot planning aligned to your audio. The LLM analyzes BPM, sections (verse/chorus/bridge), and energy, then writes shots that hit the downbeats. Speaker transcription & diarization lets you name and target different voices or singers.
- **Short Film** — screenplay-driven scenes with named characters, dialogue, and continuity across cuts. Pacing-bias slider controls cut frequency.

- **Auto Mode** runs the entire pipeline end-to-end (analyze → plan → generate images → generate clips → combine). Manual mode lets you review and edit at every step.
- **Director v2 architecture** with structured shot planning, mode-specific prompt renderers, and a 3-pass refinement (screenplay → shot breakdown → per-model polish). Director v2 optimizes what the LLM is being asked to do across several passes, with each pass optimizing the LLM request for creativity (when writing the screenplay), structured outputs (when outputting JSON), and prompt refinement, which injects LoRA prompting guides into the context.

### ⚡ Performance Auto-Tune — zero-config setup
Detects your GPU, VRAM, and RAM on first launch and picks the right profile, quantization, VAE tiling, and VRAM safety coefficient. No more "Profile 1 vs 2 vs 4.5" guesswork. Power users still have full manual control under "Show advanced settings."

- **OOM recovery banner** auto-suggests lowering the VRAM headroom when a generation runs out, with one-click apply.
- **Live download status** during model setup ("Downloading transcription model (first use downloads ~300MB)..." instead of a vague spinner).

### 🎨 Studio Mode — full manual control
Direct access to every model and every knob:
- **Video** — LTX-2.3, Wan1/2, Hunyuan, and many more.
- **Image** — Flux 2 Klein 9B (default), Qwen Image Edit, and many more
- **Audio** — TTS: Kugelaudio, Qwen3 TTS. Music: ACE-Step. SFX: MMAudio
- **Multi-clip generation** with per-clip prompts, seamless overlapping (sliding window) transitions, and shared LoRAs
- **Blend video Mode** Remember Sora 1 blend mode, where you could overlap two videos, and use AI to blend them together?
- **Frames Injection (KFI)** for character continuity in long videos
- **Sliding window** for arbitrarily long generations
- **Spatial upsampling, film grain, codec selection** as post-processing options

### 🎥 MiniMax H3 — native video and stereo audio

Studio Video includes the open **MiniMax H3 Base** model through an isolated, quantized ComfyUI runtime designed for 24 GB NVIDIA cards. One model card exposes all three official workflows:

- **T2VA**: prompt only; describe shots, dialogue, music, ambience and sound effects together.
- **FL2VA**: add a first frame, a last frame, or both.
- **Ref2VA**: up to 9 images, 3 videos and 3 audio clips (12 files total). Video soundtracks are paired automatically. Audio-only references are not valid; include at least one image or video.

H3 outputs 24 fps video with native 32 kHz stereo audio. The open Base release supports a canvas up to 768×1344 and 4–15 second clips. Maestro aligns duration to H3's `17k+5` frame grid. The RTX 4090 defaults are **960×544, 124 frames and 20 steps**; choose a larger canvas when quality matters more than turnaround. `H3-Regenerate-2K` is not part of the open checkpoint and therefore is not presented as a local option.

The Advanced/Model Options panel exposes inference steps, seed, video sigma shift (default 12), audio sigma shift (default 3), an editable **Audio Direction**, resolution, reference-image sizing and two explicit conditioning contracts: **Exact frame · FL2VA** and **References · Ref2VA**. FL2VA is the default when Story has an approved shot frame; Ref2VA must be selected explicitly and composes a new opening from its references rather than promising an exact first frame. **Quality 4090** uses INT8 + INT8 by default. **Low VRAM fallback** uses INT4 + INT4 and is retried automatically only after an INT8 out-of-memory error; the old `balanced` setting remains a backwards-compatible INT8 alias. Maestro appends the audio direction as an `Audio:` clause when a Studio prompt does not already contain one. Reference prompts use `<Picture 1>`, `<Video 1>` and `<Audio 1>` tags.

Director → Short Film → Story defaults to FL2VA, sending only each approved shot/continuity frame to the video model; character and location artwork still guides creation of that composite frame without competing with it during video generation. Ref2VA is an explicit alternative: the main artwork and character references are passed as identity references, while each shot receives only its single exactly matched labelled location. The UI previews that per-shot reference manifest, and Productions stores the authoritative manifest with warnings for unmatched locations. Story targets 124-frame segments and divides long action prose into non-repeating temporal windows, so consecutive clips continue the sequence instead of replaying the full prompt. Structured ambience, effects, vocal style and dialogue are assigned to their relevant segment. Before releasing the writing model from memory, Director makes one additional structured H3 validation pass over the exact post-split prompts. It may improve motion and camera phrasing, but protected story beats, style contracts, quoted dialogue and the complete audio direction are validated and preserved; malformed or drifting output falls back automatically to the deterministic prompts. Productions shows both the validation result and the exact H3 segment prompts that were used.

#### MiniMax H3 API

All normal Maestro job/status/cancel endpoints apply. A complete text-to-video request with curl:

```bash
curl -X POST "$MAESTRO_URL/api/v1/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "model_type": "minimax_h3",
    "prompt": "A wide shot of waves at night. Audio: surf, wind and a low cello motif.",
    "resolution": "960x544",
    "video_length": 124,
    "num_inference_steps": 20,
    "h3_model_profile": "quality",
    "h3_reference_mode": "first_frame",
    "seed": -1,
    "flow_shift": 12,
    "h3_audio_shift": 3
  }'
```

Python:

```python
import requests

job = requests.post(f"{MAESTRO_URL}/api/v1/generate", json={
    "model_type": "minimax_h3",
    "prompt": "<Picture 1> walks through a rainstorm. Audio: footsteps and distant thunder.",
    "resolution": "768x1344",
    "video_length": 243,
    "num_inference_steps": 20,
    "seed": 42,
    "image_refs": ["/absolute/path/from-the-upload-endpoint.png"],
    "h3_reference_mode": "references",
    "h3_ref_image_size": "max",
}).json()
print(job["job_id"])
```

JavaScript:

```javascript
const response = await fetch(`${MAESTRO_URL}/api/v1/generate`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    model_type: 'minimax_h3',
    prompt: '<Video 1> in a new location. Preserve <Audio 1> as a sonic reference.',
    resolution: '1344x768',
    video_length: 362,
    num_inference_steps: 20,
    seed: 1234,
    h3_reference_mode: 'references',
    h3_ref_videos: ['/absolute/path/from-the-upload-endpoint.mp4'],
  }),
})
const { job_id } = await response.json()
```

Use `POST /api/v1/upload` first for local reference assets, then pass the returned `path`. Poll `GET /api/v1/status/{job_id}` or cancel with `POST /api/v1/cancel/{job_id}`.

### 📚 Story Lab — reusable stories, worlds and characters
Story Lab is a production bible that sits before Comic Studio and Director. Write a premise once, then generate or manually edit the logline, synopsis, world rules, locations, character psychology and appearance, relationships, dramatic beats, and ending. Every generated field stays editable.

For a screenshot-led, end-to-end walkthrough, see **[Maestro X / Experimental: Story → Comics → Video](docs/MAESTRO_X_STORY_COMICS_VIDEO.md)**. It also includes copy-ready captions for an X launch thread.

- **Guided mode** creates reviewable field-level drafts and locks production until the relevant story, world, cast identities, relationships, and structure are approved. **Automatic mode** runs the same checkpointed pipeline, then offers first-look world, location, and character concepts.
- Choose Maestro internal, DeepSeek V4 Pro/Flash, MiniMax M3/M2.7/M2.7 Highspeed, OpenAI, or a custom compatible writing agent inside the story itself. Concept-art generation has its own independent Maestro/MiniMax selector.
- Character cards combine role, desire, need, flaw, arc, dialogue voice, wardrobe, visual invariants, negative prompts, multiple references, and a selected primary identity image.
- Export/import a `.storypack` with the editable JSON and available visual assets. Each workspace has a multi-story autosaved library; generated plans and local concept jobs can resume from durable checkpoints after interruption.
- **Productions** offers a review-first hand-off and a complete one-click generation for both media. Comic opens **Director → Comic** and creates a self-contained chapter rather than retelling the master plot; four pages remain the quick-test default, while page count and panels per page are configurable up to the Director limits. Short Film opens **Director → Short Film → Story** with an editable target duration and independently selectable image and video models, and inherits the Story project's selected writing provider instead of silently falling back to the global LLM. Its shot frames can use a local Maestro image model or the external MiniMax Image-01 API; the latter does not consume local VRAM and is distinct from the local MiniMax H3 video runtime. Both productions receive the full editable canon, structured cast, locations and labelled visual references. Character images remain attached through planning and MiniMax `image-01` uses the visually prioritised character as its single supported identity reference per request. Adaptation history preserves the selected models when reopening the staged target, or can restore its exact source as a new editable copy.

### 💬 Comic Studio — script, characters, pages, translation and animatics
Build a comic as an editable production rather than a single flattened generation. Comic Director creates a causal page structure and a full script that can be revised and approved before image credits are spent. The editor includes varied layouts, restrained automatic lettering, per-panel image regeneration, page navigation, zoom, a full-screen read-only Fit preview, PDF/CBZ/PNG export, and text-only rewriting or translation without changing artwork.

- **Characters** stores personality, motivation, dialogue voice, wardrobe, visual invariants, exclusions, and multiple generated or uploaded identity references.
- **Quality** checks text density, duplicated lines, missing continuity notes, unknown characters, unapproved scripts, and missing references. Translation glossaries lock names and terminology across languages.
- **Writing LLM override** keeps Maestro's internal model as the default, with separate DeepSeek, MiniMax, OpenAI, and custom-compatible profiles. DeepSeek offers V4 Pro or V4 Flash and automatically uses Flash for translation. MiniMax offers M3, M2.7, and M2.7 Highspeed, sharing its saved API key with image generation while keeping the writing and image model selectors independent. Provider keys remain in Settings and are never embedded in comic JSON.
- **Video** keeps the fast FFmpeg animatic path and adds a generative **Comic → AI film** path. The latter gives the LLM the master canon and every planned scene, captures clean artwork without lettering, and reuses each panel as that shot's actual I2V first frame; it spends video generation time/credits but does not regenerate comic artwork. Per-panel duration and camera movement remain editable.
- Comic and Video Editor drafts autosave locally; saved comics remain backward-compatible with older version-2 project JSON.

### 🤖 Local LLM — built-in, no setup
Maestro auto-downloads `llama-server` (~600 MB one-time) and your chosen GGUF model on first use. Defaults to **Gemma 4 4B (Recommended)** — fast, capable, and runs comfortably on smaller GPUs. Auto-detects CUDA and binds the LLM to GPU when available.

- Pre-curated registry: Gemma 4 (2B / 4B / 26B MoE / 31B) and Qwen3.6 27B — uncensored/abliterated instruct variants tuned for creative prompting
- **External providers** also supported: OpenAI, Anthropic, custom OpenAI-compatible endpoints (currently experimental)
- **Vision support** so LLMs can enhance prompting based on reference images
- Auto-unloads after 60s idle to free VRAM for video gen

### 🛒 Built-in CivitAI LoRA browser
- Search, filter, and one-click install any LoRA from CivitAI without leaving Maestro
- **LoRA update detection** — Check button refreshes from CivitAI, shows update badges on outdated LoRAs
- **My LoRAs view** with filters for Updates and direct uninstall
- **AI-generated LoRA prompting guides** Helps remove the guesswork from LoRAs. AI generates LoRA guides when LoRA is downloaded based on CIVITAI and HuggingFace repos. The guides explain what each LoRA does and how to use it, provide prompt examples, and recommend weight settings that are automatically applied when LoRA is selected.
- **Recommended weight ranges** (sourced from CivitAI sidecars, HuggingFace, or fallback heuristics) shown directly on the weight sliders
- **Multi-LoRA pack auto-extraction** for archives that bundle several LoRAs

### 🎭 Themes
Three themes, switchable in Settings → System:
- **Golden Hour** (default) — warm cinematic palette with sunset-gradient CTAs and spotlight bezels
- **Classic** — the original cool charcoal palette with blue accents
- **Onyx** — minimalist monochrome, pure black with neutral grey surfaces

### 🛠️ Edit Mode *(experimental)*
- **Retake** — re-roll a section of an existing video with a new prompt
- **Outpaint** — extend a video's frame in any direction
- **Edit Anything** — allows users to modify, add, or remove elements from existing videos using text prompts and In-Context LoRA (IC-LoRA) models

### 🧊 Native Hunyuan3D Studio
Maestro includes an integrated **3D** section for text-to-3D, image-to-3D, and multi-image reconstruction. Hunyuan runs in an isolated environment inside Maestro, so its older Diffusers stack cannot conflict with the audio/video models. Each worker exits after export and releases its CUDA context and VRAM.

Included geometry variants:

- **Hunyuan3D 2 Mini**: Turbo, Fast, and full-step 0.6B variants
- **Hunyuan3D 2**: Turbo, Fast, and full-step 1.1B variants
- **Hunyuan3D 2 Multi-view**: Turbo, Fast, and full-step models using front/left/right/back references
- **Hunyuan3D 2.1**: high-fidelity 3.3B geometry with optional PBR materials

The advanced panel exposes inference steps, guidance, octree resolution, processing chunks, seed, texture model/resolution, CPU offload, FlashVDM, Torch compilation, DMC/Marching Cubes, mesh simplification, face target, and GLB/OBJ/PLY/STL export. Four presets provide sensible Low VRAM, Balanced, Quality/PBR, and Multi-view configurations.

**Retexture GLB** applies Hunyuan Paint 2.0/Turbo or Hunyuan Paint 2.1 PBR to an existing static GLB using either a reference image or a text-described material. Maestro always saves a new GLB copy and leaves the source untouched. Rigged or animated inputs are rejected because Hunyuan rebuilds the UV layout; retexture the static base first, then rig the resulting copy.

Hunyuan3D is part of Maestro's normal lifecycle: **Install** prepares its isolated runtime, **Update** keeps it current, and **Reset** removes it with the rest of Maestro. There is no separate 3D installer. Model weights are downloaded lazily from Tencent's official Hugging Face repositories the first time a variant is used.

The cloned source code and downloaded weights remain subject to Tencent's Hunyuan license terms. Review the `LICENSE` files in the official checkouts before redistribution or commercial use.

#### Hunyuan3D API

Start a job with curl:

```bash
curl -X POST "$MAESTRO_URL/api/v1/model3d/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "balanced",
    "model_id": "hunyuan3d-2-turbo",
    "prompt": "a stylized bronze robot figurine",
    "texture_mode": "v2-turbo",
    "output_format": "glb"
  }'
```

Multi-image requests use uploaded Maestro paths:

```bash
curl -X POST "$MAESTRO_URL/api/v1/model3d/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "multiview",
    "model_id": "hunyuan3d-2mv-turbo",
    "images": {
      "front": "front.png",
      "left": "left.png",
      "right": "right.png",
      "back": "back.png"
    }
  }'
```

Retexture an existing gallery or uploaded GLB as a new copy:

```bash
curl -X POST "$MAESTRO_URL/api/v1/model3d/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "retexture",
    "source_model": "my-static-model.glb",
    "model_id": "hunyuan3d-2-turbo",
    "prompt": "weathered red steel with scratched edges",
    "texture_mode": "v2-turbo",
    "output_format": "glb"
  }'
```

The response contains a `job_id`. Poll `GET /api/v1/model3d/status/{job_id}` or cancel with `POST /api/v1/model3d/jobs/{job_id}/cancel`. Discover models and defaults from `GET /api/v1/model3d/capabilities`.

```javascript
const base = 'http://127.0.0.1:7860';
const job = await fetch(`${base}/api/v1/model3d/generate`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ preset: 'eco', prompt: 'a carved wooden owl', output_format: 'glb' }),
}).then(r => r.json());

const status = await fetch(`${base}/api/v1/model3d/status/${job.job_id}`).then(r => r.json());
```

```python
import requests

base = "http://127.0.0.1:7860"
job = requests.post(f"{base}/api/v1/model3d/generate", json={
    "model_id": "hunyuan3d-2.1",
    "image_path": "reference.png",
    "texture_mode": "pbr",
    "cpu_offload": True,
}).json()
status = requests.get(f"{base}/api/v1/model3d/status/{job['job_id']}").json()
```

### 📂 Workspaces
Multiple isolated output directories with a quick switcher in the sidebar. Useful for separating client projects, NSFW vs SFW, or experiments. Pinned and favorited outputs are tracked per workspace.

### 🔒 Mature mode + experimental gate
- **NSFW mode** is opt-in with a disclaimer step. Disabled by default. Gates uncensored model variants, NSFW LoRAs in the CivitAI browser, and the Settings → Services NSFW toggle.
- **Experimental features gate** hides power-user toggles (external API keys, Voice Reference, Inpaint, Restyle, Wan2GP Enhancer) by default for a focused first-launch experience.

### 📊 Productions + global activity footer
The persistent footer shows what Maestro is doing from every screen, including live sampling steps and a direct link to **Productions**. Productions keeps all past Director runs with their full state — clip plans, generated images, generated clips, and polish diffs — so interrupted work and individual clips can be recovered without re-running the whole pipeline.

## Updates

The version you are running is shown next to the Maestro title in the UI. To update, use the launcher's Update button in Pinokio.

### v1.6.5 (2026-08-08)

**MiniMax H3 performance and lower-VRAM support**
- H3 Turbo now works with the recommended Pruned 20B models as well as the optional Full 33B models.
- Turbo now starts at six steps and LoRA strength 0.50, while keeping the LoRA visible and adjustable in Advanced settings.
- Reworked H3 model residency, activation chunking, and VRAM budgeting to reduce step-zero out-of-memory failures and excessive CPU offloading.
- Added resolution- and GPU-aware First / Last window recommendations, with clear warnings and a manual override for experimental combinations.
- Added an optional experimental First Block Cache for faster H3 generations, with selectable quality/speed thresholds.

**H3 resolutions and long-video planning**
- Added a faster model-aligned 720p tier using 1280x704 landscape output and matching portrait, square, and 4:3 canvases.
- Restored 1080p H3 generation with an experimental note and hardware-aware shorter-window recommendations.
- Hid the less efficient 768p preset from the main selector while retaining compatibility with existing saved settings and API requests.
- Added automatic H3 sliding-window storyboarding: one idea is expanded into a complete, editable prompt for every continuation window.
- Actions, dialogue, camera coverage, sound effects, ambience, and music are distributed across the timeline instead of being completed and repeated in the first window.
- Each exact window prompt is visible during generation in its own full-height editor, with the active window highlighted and no nested scrollbars.

**Director H3 workflow improvements**
- Director now uses the same H3 resolution, VRAM, and native-frame rules as Studio when planning shot lengths and execution profiles.
- Long scenes are divided before generation to fit the selected model, resolution, GPU, and Turbo configuration instead of being silently shortened at runtime.
- Added H3 Turbo controls and adjustable per-LoRA strengths directly to Director mode.
- Improved independent-shot context so recurring characters, wardrobe, locations, blocking, dialogue, and sound remain self-contained across prompt-only H3 shots.

**MiniMax LoRA discovery and compatibility**
- Added a MiniMax H3 filter to the CivitAI browser and routed downloaded H3 LoRAs into the correct shared H3 folder.
- Pasted Hugging Face MiniMax H3 LoRA URLs now use the same correct destination instead of defaulting to LTX.
- Added automatic H3 LoRA architecture conversion where required so compatible adapters can run on both Pruned and Full checkpoints.
- Added early validation, pinned support assets, and clearer recommendations for combinations that may exceed available VRAM.

### v1.6.1 (2026-08-06)

**MiniMax H3 Turbo mode**
- Added the H3 Turbo LoRA to the Full H3 model lists as a managed, first-use download.
- Added an experimental one-click Turbo mode for Full First & Last and Full Omni models.
- Turbo mode uses six inference steps and starts at LoRA strength 0.70.
- The active Turbo LoRA is shown in Advanced settings so its strength can be tuned per generation.
- User-adjusted Turbo strengths are preserved while duplicate Turbo adapters and incompatible Pruned-model combinations remain blocked.

### v1.6.0 (2026-08-06)

**MiniMax H3 Omni Reference**
- Added MiniMax H3 Omni for generating new video and synchronized audio from ordered image, video, voice, motion, and sound references.
- References can be reordered, labeled with their intended role, and used for identity, appearance, scene, motion, voice, performance, ambience, or music conditioning.
- Added both recommended Pruned 20B and optional Full 33B Omni models.
- Added Match Output reference preparation for consumer GPUs and an optional Maximum Detail mode for higher-memory systems.
- Improved reference-video memory use with output-aware sizing, chunked projections, dedicated attention workspace, and safer model re-profiling.

**Expanded H3 models and performance options**
- Simplified the model choices to First & Last and Omni, with clear Pruned 20B and Full 33B variants and concise explanations in the selector.
- Added Full 33B support for both workflows, including ConvRot checkpoint loading, fused projection handling, and memory-efficient streaming.
- Added selectable NVFP4-AWQ, GGUF Q2/Q4, Quanto INT8, and BF16 Qwen3-VL text encoders with hardware-aware recommendations.
- Added support for the MiniMax H3 Turbo LoRA on compatible Full 33B models with true 4, 6, and 8-evaluation schedules.
- Incompatible Turbo LoRA and Pruned-model combinations are rejected before loading instead of failing after a long generation.

**H3 Studio workflow and prompting**
- Omni generations are limited to the native 345-frame maximum: 14.375 seconds at 24 FPS, displayed as 14.4 seconds, with sliding-window controls automatically hidden.
- First & Last uses the same native 14.4-second maximum per window and can now generate longer videos by continuing each window from the preceding final frame.
- Long First & Last runs preserve the requested duration, remove continuation overlap, keep synchronized audio aligned, and apply an optional end image only to the final window.
- Fixed portrait and other selected aspect ratios being forced or decoded as 16:9.
- Improved H3 Prompt Enhance for exact dialogue retention, stable speaker IDs, voice-reference intent, opening ambience, silent intervals, and reduced gibberish or invented speech.

**MiniMax H3 in Director**
- Added model-aware Director workflows for both First & Last and Omni models.
- First & Last can create prompt-only shots or use optional generated start/end frames, while Omni can condition shots on character, location, voice, video, soundtrack, and other project references.
- Director no longer spends time writing or generating unused start images for H3 prompt-only workflows.
- H3 shot prompts now carry the project world, location, wardrobe, character blocking, screen position, dialogue, soundscape, and continuity needed by independently generated clips.
- Added stable project-wide speaker mapping, locked screenplay dialogue, duration-aware pacing, and multi-speaker exchanges with camera changes inside a single H3 clip.
- Incomplete or altered local-LLM shot plans are repaired deterministically without silently truncating, moving, duplicating, or rewriting approved dialogue.
- Dashboard repair and regeneration recreate the same H3 references and timing, including exact per-shot audio conditioning and one clean final soundtrack.

**Compatibility and reliability**
- Director model lists now show only image and video models that support the selected automated workflow.
- Native audio generation is distinguished from audio-reference input so incompatible models are no longer offered for audio-driven jobs.
- Reduced console noise by hiding successful system-stat polling while retaining failures and meaningful API requests.
- Interrupted saved Director jobs are now reported as interrupted instead of disappearing as missing projects.
- Expanded automated coverage for H3 checkpoints, quantization, Omni reference packing, Turbo LoRA, Studio continuation, Director compatibility, dialogue planning, memory behavior, and UI contracts.

## Requirements

| | Minimum | Recommended |
|---|---|---|
| **OS** | Windows 10/11 or Linux | Windows 11 |
| **GPU** | NVIDIA, 6 GB VRAM | NVIDIA RTX 3090 / 4090 / 5090, 24 GB+ VRAM |
| **System RAM** | 16 GB | 32 GB+ |
| **Disk space** | **150 GB free** | **500 GB free** (for full model collection) |
| **Python** | Auto-installed by Pinokio | — |

**What to expect by GPU** (rough ballpark — varies with model, resolution, and length):

| Your card | First run | A short clip after models are cached |
|---|---|---|
| **24 GB** (3090 / 4090 / 5090) | smooth — everything runs | ~1–3 min |
| **12–16 GB** (3060 12GB / 4070 / 4080) | good — auto-tune picks an offload profile | ~4–10 min |
| **6–8 GB** | works, but expect heavy offloading | slow; stick to short/low-res clips |

The first video is always the slow one: install is ~10–20 min, then the first generation on each model downloads its weights (the default video model is ~18 GB). After that, weights are cached and only generation time applies. Maestro's auto-tune sizes the settings to your card on first launch so you don't have to.

> ⚠ **AMD GPUs and macOS are not currently supported.** The pipeline depends on CUDA and several NVIDIA-only kernels. MacOS support is in development.

> ⚠ **Model downloads are large.** A typical install pulls **50–100 GB** of model weights on first launch. The full collection can exceed **300 GB**. Make sure you have headroom on the drive where Pinokio is installed. However, only models requested during generation will be downloaded.

## Install

1. Install [Pinokio](https://pinokio.computer).
2. In Pinokio, open the **Discover** tab and search for *Maestro* — or click the **Download** button on the [Maestro repo page](https://github.com/Blizaine/Maestro) and paste the URL.
3. Click **Install**. The launcher will:
   - Create a Python virtual environment in `app/env/`
   - Install all Python dependencies (torch, xformers, transformers, fastapi, …)
   - Build the React UI in `ui/`
4. When install finishes, click **Start**. The first generation in each model triggers a one-time weight download.

The install (without model downloads) typically takes **10–20 minutes** depending on internet speed. SAM 3.1 (used only for the experimental Inpaint feature) is **not installed by default** — install it on demand via Pinokio menu → "Install Inpaint Support (SAM 3.1)" if you want to use Inpaint.

### Updating

Click **Update** in the launcher menu. This pulls the latest launcher scripts and app code, reinstalls any new Python dependencies, and rebuilds the React UI.

### Resetting

Click **Reset** to wipe the install and start over. Removes `app/env/`, `ui/node_modules/`, `ui/dist/`, and the SAM venv if installed. Model checkpoints in `app/ckpts/` are NOT removed by default — delete them manually if you want a true fresh start.

## Usage

After clicking **Start**, the launcher shows an **Open Web UI** button once the server is up.

- **Sidebar** — mode toggle (Studio / Director), model picker, prompt, LoRAs, advanced settings
- **Main feed** — generated outputs and Director pipeline status
- **Activity footer** — persistent live job progress and access to current or past **Productions**
- **Settings drawer** (gear icon) — model visibility, performance auto-tune, services (LLM, API keys, NSFW, theme)
- **Pinokio menu** — Update, Reset, Install Inpaint Support, LoRA folder shortcuts

## Sharing on the local network

Maestro respects Pinokio's `PINOKIO_SHARE_LOCAL` environment variable. Set it to `false` (in the per-app or global ENVIRONMENT file) to bind the server to loopback only; set to `true` for LAN access. Pinokio's own daemon proxy is a separate concern that may also need to honor the variable depending on your setup.

## Credits

Maestro is built on top of, and indebted to, the following projects:

- [**Wan2GP / WanGP**](https://github.com/deepbeepmeep/Wan2GP) by [@deepbeepmeep](https://github.com/deepbeepmeep) — the entire generation pipeline. Maestro inherits WanGP's non-commercial license.
- [**LTX-Video**](https://github.com/Lightricks/LTX-Video) by Lightricks — LTX-2 and LTX-2.3 distilled models.
- [**Wan 2.1 / 2.2**](https://github.com/Wan-Video/Wan2.1) by Alibaba — text-to-video and image-to-video.
- [**MiniMax H3**](https://huggingface.co/MiniMaxAI/MiniMax-H3) by MiniMax and its [ComfyUI implementation](https://github.com/Comfy-Org/ComfyUI/pull/15224) — omni-modal video generation with native stereo audio.
- [**Flux**](https://github.com/black-forest-labs/flux) by Black Forest Labs — image generation.
- [**Qwen**](https://github.com/QwenLM/Qwen) by Alibaba — image generation and LLMs.
- [**Gemma**](https://ai.google.dev/gemma) by Google — Gemma 4 LLM (default for Director mode).
- [**SAM**](https://github.com/facebookresearch/sam2) by Meta — segmentation backbone for Inpaint.
- [**MMAudio**](https://github.com/hkchengrex/MMAudio) — automatic ambient audio generation.
- [**CivitAI**](https://civitai.com) — LoRA browser and weight recommendations.
- [**llama.cpp**](https://github.com/ggml-org/llama.cpp) — local LLM inference engine.
- [**Pinokio**](https://pinokio.computer) by [@cocktailpeanut](https://github.com/cocktailpeanut) — the launcher framework.
- The original Pinokio Wan2GP launcher by [@cocktailpeanut](https://github.com/cocktailpeanut), which Maestro forks and extends.

## License

Maestro is released under the **WanGP Non-Commercial Evaluation License 1.1**, inherited from the upstream Wan2GP project. See [LICENSE](LICENSE) for the summary and [app/LICENSE.txt](app/LICENSE.txt) for the full text.

**TL;DR**: free to use and modify for non-commercial purposes; the *outputs* you generate are yours to use commercially (with attribution); commercial use of the *software itself* (including hosted services and APIs) requires a separate commercial license from the WanGP licensor.

Third-party models, weights, and components keep their own licenses — review them before redistributing. Notably, the [seed-vc](https://github.com/Plachta/seed-vc) voice-conversion component is **GPL-3.0**, so it is distributed from its own repository ([Blizaine/maestro-seedvc](https://github.com/Blizaine/maestro-seedvc)) and cloned into `app/postprocessing/seedvc/` at install time rather than shipped in this tree. Other vendored components include BigVGAN (MIT), FlashVSR sparse-sage (Apache-2.0), and IndexTTS2 (bilibili model license).

## Issues

Bug reports and feature requests: [github.com/Blizaine/Maestro/issues](https://github.com/Blizaine/Maestro/issues).
