# Maestro X / Experimental: Story → Comics → Video

Maestro can carry one approved story canon through three editable production
spaces: Story Lab, Comic Studio, and Video Editor. The important idea is that
each hand-off remains reviewable. The story is not flattened into a single
prompt, comic pages remain editable, and video generation begins only after a
shot-level PRE review.

This guide uses the **Maestro X / Experimental** name for launch posts and
work-in-progress demonstrations. The product shown in the screenshots is the
local Maestro v1.5.5 interface.

## Before you begin

- Install and start Maestro from Pinokio.
- In **Settings → Services**, choose a writing provider. Maestro's local model
  works without an external writing API.
- Install or configure the image model that will create comic panels.
- Install the video engine you intend to use for the AI-film pass. The selected
  engine and exact output size are frozen into PRE before generation.
- Start with a four-page comic and a small representative video test. Expand
  the production only after its characters, lettering, and motion treatment
  work at that scale.

## The workflow at a glance

1. Build and approve a reusable canon in **Story Lab**.
2. Send a chapter to **Comic Director**, then review the script, characters,
   pages, and quality checks in **Comics**.
3. Open **Video**, adapt comic beats into cinematic shots, and approve the
   exact prepared frames and prompts in **PRE**.
4. Generate the film or a fast FFmpeg animatic.
5. Open the result in **Video Editor**, arrange the final cut, and export MP4.

## 1. Create the source story

Open **Story Lab** from the top navigation and click **New**. Choose **Guided ·
approve stages** when you want explicit review gates, or Automatic mode for a
faster first draft.

![Story Lab with the editable story bible](images/maestro-x-story-comics-video/01-story-lab.png)

In the **Story** section, define the title, language, genre, tone, audience,
premise, and visual direction. Then work through:

- **World** for rules, locations, and a reusable visual language.
- **Characters** for psychology, arcs, dialogue voice, wardrobe, visual
  invariants, exclusions, and identity references.
- **Relationships** for the dynamics that should survive adaptation.
- **Structure** for the dramatic beats and ending.
- **Music** only when the production needs themes or a soundtrack plan.

Generated text is a draft, not a lock: edit any field before clicking
**Approve**. In Guided mode, the production hand-off stays locked until the
required canon and identity sections are approved.

When the story is ready, open **Productions**. Set the comic direction, page
count, and panels per page. Use **Open in Comic Director** for the review-first
path. **Generate complete comic chapter** runs the same staged hand-off and
continues automatically; it may start image-generation work and use provider
credits.

## 2. Direct and edit the comic

Comic Director receives the complete canon, structured cast, locations, and
available labelled references from Story Lab. Review the production format and
chapter direction before generating the script and artwork.

![Comic Studio with its editable page canvas and production tabs](images/maestro-x-story-comics-video/02-comics.png)

Use the right-side production tabs as checkpoints:

- **Director**: revise the chapter brief, writing provider, page structure, and
  per-panel plans.
- **Script**: edit captions, dialogue, and sound effects; approve the script
  version before committing image-generation time.
- **Characters**: confirm the identity references and visual constraints used
  by the panel generator.
- **Quality**: resolve missing references, unknown characters, dense text,
  duplicated lines, and continuity warnings.
- **Assets / Inspector**: regenerate individual panel art, adjust lettering,
  or replace an asset without rebuilding the whole chapter.

Save the editable comic JSON as well as the desired reader export (PNG, PDF, or
CBZ). The JSON is the reusable production source; a flattened export is not.

## 3. Turn comic beats into film shots

Open the comic's **Video** tab. Printed-comic panels are source beats, not an
automatic one-panel/one-shot timeline. Director may combine adjacent beats,
omit a redundant image, or split a dense beat into multiple shots. Storyboard
projects remain one-to-one by default.

![Comic-to-film configuration with the selected video engine](images/maestro-x-story-comics-video/03-comic-to-video.png)

In **Configuration**:

1. Select the actual video engine for this movie.
2. Choose landscape, portrait, or square output and its listed resolution.
3. Choose the default panel fit and motion treatment.
4. Keep lettering out of video conditioning frames; Maestro captures clean
   panel artwork while retaining dialogue as editorial metadata.

In **Source beats**, include, exclude, reorder, or annotate panels. Per-beat
overrides are explicit locks. Use them sparingly for a required action, camera
request, duration, seed, fit, or renderer.

Click **Prepare PRE for enabled film shots**. PRE opens as its own full comic
workspace and shows the authoritative film plan: source image, prepared clean
plate, effective prompt, duration, seed, renderer, fit, and model settings for
every shot.

Before the full render:

1. Resolve missing media and aspect warnings.
2. Approve the exact PRE fingerprint.
3. Render the suggested representative test shots.
4. Play and explicitly accept those tests, or record a reasoned waiver.
5. Generate the complete AI film.

For a quick editorial preview, expand **FFmpeg animatic · no generative video**
and click **Render animatic**. This is much faster and does not spend video
generation time, but it is not the AI-motion result.

## 4. Finish in Video Editor

Completed animatics and AI-film outputs are added to Maestro's gallery and are
available from **Video Editor**. Open the editor directly or use **Open in Video
Editor** from the comic result.

![Video Editor ready to assemble and export the generated clips](images/maestro-x-story-comics-video/04-video-editor.png)

Use **From Maestro** to select generated clips, then reorder the timeline,
preview cuts, split where needed, and choose the final output resolution and
frame rate. Click **Export MP4** only after the timeline preview matches the
intended cut.

## Recovery and reproducibility

- Story Lab autosaves a multi-story library per workspace and can export a
  `.storypack` containing editable canon plus available visual assets.
- Story-to-comic and story-to-film Productions keep a source snapshot so the
  exact adaptation can be reopened without mutating the master story.
- Comic and Video Editor drafts autosave locally.
- PRE is fingerprinted. Changing comic content, shot order, prepared media, or
  effective runtime settings invalidates the old approval.
- Each completed generation child is checkpointed before final assembly, so a
  long run can retain finished work after interruption.

## Copy-ready X thread

The following copy is intentionally compact and can be posted with the three
screenshots above.

**Post 1**

> Maestro X / Experimental: one story, three editable production spaces. Build
> the canon in Story Lab, direct the comic, then turn its visual beats into a
> reviewed AI-film cut — locally.

**Post 2**

> Story Lab is the source of truth: world rules, characters, relationships,
> dramatic structure, visual references, and production snapshots. Approve the
> canon once; adapt it without flattening it into one giant prompt.

**Post 3**

> Comic Studio keeps the chapter editable: script, layouts, lettering,
> identity references, per-panel regeneration, quality checks, and PNG/PDF/CBZ
> exports. The project JSON remains the production master.

**Post 4**

> Comic → AI film is an editorial adaptation, not a panel slideshow. Director
> can merge, omit, or split source beats. PRE exposes every clean plate, prompt,
> seed, duration, fit, renderer, and model setting before the expensive render.

**Post 5**

> Test representative shots, approve the PRE fingerprint, generate, then finish
> the cut in Video Editor. Or make a fast FFmpeg animatic first. Story → Comics
> → Video, with review gates and recoverable checkpoints throughout.

## Related technical reference

For the exact shot contract, clean-plate rules, renderer behavior, prompt
contract, fingerprints, and quality gate, see
[Comic-to-video adaptation](COMIC_VIDEO_ADAPTATION.md).
