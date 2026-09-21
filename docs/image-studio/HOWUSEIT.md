# HOWUSEIT — Studio Image intents

Operator guide for **Direct generation → Image**. The sidebar now starts with
an intent chooser; you only see the controls that flow needs. This is not
Studio → Edit (that tab is video) and not Tools rembg.

UI: `ui/src/components/Sidebar/ImageStudioPanel.tsx`,
`ImageIntentChooser.tsx`, `ImageEditSection.tsx`.
Intents: `ui/src/features/studio/imageStudioIntent.ts`.
Local files: `ui/src/lib/localEditImages.ts`.
Canvas labels: `ui/src/lib/imageResolution.ts`.
Admission: [IMAGE_COMMANDS](../development/IMAGE_COMMANDS.md).

Related: [Wizard / MCP](../development/WIZARD_MCP_USAGE.md),
[Tools rembg](../tools/HOWUSEIT.md).

---

## 1. What this system is

Four operator intents plus a chooser. They share one `generation.image`
command. Switching intent does not invent a second scheduler.

| Intent | UI id | What you see | Typical model path |
|---|---|---|---|
| New image | `new` | Prompt, canvas, count | Text-to-image. No source photo. |
| Edit image | `edit` | Source, optional mask, outpaint, 2.1 tools | Unified Qwen Image 2.1 (`qwen_image_21*`) |
| Character | `character` | Identity / style references | Subject stills (`KI` / `I`) |
| Looping backdrop | `loop` | Panorama loop panel | Seamless backdrop, not a video loop |

`chooser` is the landing grid. **Start over** returns there and clears the
image-studio draft (`resetImageStudio`). It does not cancel a queued job.

---

## 2. Hard limits

1. **Edit is stills, not video.** Studio → Edit remains the video retake /
   outpaint / recast family. Do not send an `edit` intent to those workers.
2. **No separate Edit-2.1 checkpoint.** Qwen Image 2.1 is one architecture
   (`qwen_image_21`, plus `_bf16`, `_gguf_*`, and `_uncensored_gguf_*`).
   Identity/style still uses `subject` / `style` refs (up to `max_image_refs`,
   10 on 2.1).
3. **Local files stay in the tab.** A computer photo becomes a
   `local-edit:<n>` token (`rememberLocalImage`). It is **not** in the gallery
   until Generate uploads it. Closing the tab or calling `forgetLocalImage`
   drops the blob. Reload cannot recover it — pick the file again.
4. **Upload before admission.** `materializeLocalEditFields` walks
   `image_refs`, `image_start`, `image_end`, `image_guide`, `image_mask` and
   replaces `local-edit:` / `blob:` tokens with `/api/v1/uploads/…`. The
   command reference API never sees a browser token.
5. **Auto is a real canvas.** Image commands reject `auto` / `auto_720p`.
   `concreteImageResolution` maps labels before POST:

   | Label | Qwen 2.1 | Other image models |
   |---|---|---|
   | `auto` | `2048x2048` | `1024x1024` |
   | `auto_720p` | `1024x1024` | `1280x720` |
   | `auto_1080p` | `2048x2048` | `1920x1088` |
   | explicit `WxH` | snapped to multiples of 8, 64–4096 | same |

6. **Uncensored GGUFs have no Mature Mode gate.**
   `qwen_image_21_uncensored_gguf_q4_k_m` / `_q5_k_m` / `_q6_k` are local
   image weights, not the Wizard LLM. Q8_0 from that pack is **not** shipped
   (upstream shape mismatch). License still follows Qwen Research License.
7. **Fit-to-model is optional.** Edit → **Fit size to the model** crops,
   letterboxes, or stretches the source to a size the selected model admits.
   It writes another local-edit token; it does not generate.

---

## 3. Operator workflow

1. Open **Direct generation → Image**.
2. Pick an intent. The pills at the top switch later without leaving Image.
3. **New:** write the finished picture, pick model and canvas, Generate.
4. **Edit:** attach a source (gallery, library **Choose**, or a computer
   file). Optional white=change mask. Optional outpaint margins
   `"top bottom left right"` percents — they need a source. Describe the
   **finished** picture, not a delta (“remove the cup”).
5. **Character:** attach identity/style stills, then the prompt.
6. **Loop:** use the panorama panel; do not expect Image Edit tools there.
7. Watch Activity. A receipt means admission, not a finished PNG.

Wizard: `prepare_image` then `attach_studio_references` with
`reference_role=edit_source` (and optional `edit_mask`) **before**
`start_generation`. MCP v2 uses `image_guide` / `image_mask` / `image_refs`
and `video_prompt_type` containing `VAG` (plus `I`/`KI` when identity refs
are also attached).

---

## 4. Prompt-type letters

`mergeVideoPromptLetters` keeps identity letters when a mask is added or
cleared:

| Action | Letters |
|---|---|
| Identity refs only | `KI` or `I` |
| Source canvas | add `V` |
| Source + white=change mask | add `VAG` |
| Clear mask, keep source | drop `AG`, keep `V` |

Do not hand-edit `video_prompt_type` to invent selectors the model did not
declare.

---

## 5. Pitfalls

- Using Studio → Edit for a still. That tab is video.
- Expecting a `local-edit:` token to survive reload or another browser tab.
- Sending `resolution: "auto"` on `generation.image` without going through
  the Studio mapper — the command rejects the label.
- Treating uncensored GGUF visibility as Mature Mode. The gate is for the
  Wizard LLM, not these image weights.
- Putting `instruction` on rembg and expecting Qwen 2.1 to read it. Tools
  rembg stores the note and ignores it; Image Edit uses the prompt + mask.
- Attaching `edit_mask` before `edit_source`. Wizard rejects that order.

---

## 6. Files to read next

| Path | Why |
|---|---|
| `ui/src/features/studio/imageStudioIntent.ts` | Intent ids |
| `ui/src/lib/localEditImages.ts` | Tab-local tokens and upload |
| `ui/src/lib/imageResolution.ts` | Auto → pixel canvas |
| `ui/src/lib/studioImageEdit.ts` | 2.1 capability flags |
| `ui/src/i18n/locales/en/studio.json` (`imageIntent`, `imageEdit`) | Operator copy |
| `ui/tests/studioImageEdit.test.ts` | Intent list and Auto mapping |
| `app/defaults/qwen_image_21*.json` | Installed 2.1 variants |
