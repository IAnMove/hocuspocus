# Animated 3D shots and review numbers

Video 3D keeps the exact GLB animation index/name pair. The selector now labels
animations, displays their durations, and offers speed, source start time and
loop/hold controls per object. Unknown-duration clips cannot be selected.
Controls affect preview and MP4 capture identically. A single play reaches the
exact last pose, including STEP tracks; seeking back reactivates a clamped action.
“Fit animation to shot” plays the remaining source animation once over the current
shot duration by setting speed and disabling looping. It preserves the source
start time and supports 0.1–4×, including decimal values at either boundary.
Apply it again after changing shot duration or source start. This is particularly
useful for forward root motion: a non-cyclic animation can jump back when looped.

Shot JSON can be saved and reopened from the editor. Import validates render
settings, camera fields, light and unique object identities before mounting.
Saved upload/file URLs remain the source authority; JSON files do not embed GLBs
or make their source files portable. Filesystem/blob URLs retain the existing
transient-source handling. Imported dimensions determine preview and export.
Export preserves sizes up to 1920×1080 (1080×1920 for portrait shots), fits larger
documents inside that bound, and rounds dimensions to even pixels. Smaller shots
are not upscaled. The encoder, export canvas and publication metadata share this
size calculation. Full HD at 60 fps requests H.264 level 4.2; the existing browser
support check still reports unsupported configurations instead of reducing them
silently. MP4 bytes remain in browser memory, so longer exports still require
enough local memory; this change does not add streaming or export recovery.

`clipNumber` is optional, positive and integral. It is shown in preview and baked
into the encoded frame at the upper right. It is also included in the published
filename and recipe. It survives template changes with the rest of the shot.
This number is an editorial reference; it does not replace asset or attempt IDs.
For clean exports, omit `document.clipNumber`. The shot render/assembly clients
still identify files using `shot.number`, then `document.clipNumber`, then the
one-based position in the plan. They reject duplicate or invalid identities
before publication. Rendering confirms the imported editor document through a
saved JSON roundtrip before checking assets, so consecutive unnumbered shots
with the same sources still apply their own animations, cameras and lights.

`clipPlayback` stores `speed`, `start` (source animation seconds), and `loop`.
`clips` (optional) sequences several clips on one model slot with crossfades. When
it is present it drives the model and `clip`/`clipPlayback` are ignored; see
[sequence clips on a slot](../agents/HUMANOID_RIG.md#sequence-clips-on-a-slot).
`motion` stores a world-space destination, optional quadratic control point
(`via`), target yaw or tangent-facing (`faceTravel`), and linear/smooth timing.
The selected-model movement panel edits these fields; the transform panel sets
the starting pose. Travel spans the shot duration. Camera follow targets use the
current pose and optional world-space `eyeOffset`/`targetOffset` vectors.
The distance/speed label reports straight-line displacement, not curved arc length.

Three reusable templates use a procedural server citadel with no bundled user
media: `siege-ring`, `spell-duel`, and `victory-circle`. Content bindings and
animation names remain separate from these framing/layout templates.

Two additional reusable sets are `coder-room` (walls, shelves, physical desk,
keyboard and animated monitor) and `clone-chase` (a fixed road and lamps with
moving characters). Image slots can be unlit backdrops or lit wall/floor
surfaces, with editable texture repetition. Floor yaw stays horizontal.
The templates contain no private GLBs or generated images.

Optional `performance: "typing"` is a procedural arm gesture for rigs named
Left/Right Arm, ForeArm and Hand. Its keyboard target is 0.62 m ahead of the
slot origin and 0.91 m above it, matching the programmer set. It restores the
previous animation pose before resampling, including repeated/paused frames.
`grounded` aligns the animated mesh bounds with the slot's ground height before
the gesture. This is a coarse contact aid, not foot IK, retargeting, seating,
terrain collision or physics. Contact shadows are simple moving soft blobs.

## Subject framing and the twenty additional presets

The library includes eight face shots (`face-closeup`, `face-extreme`,
`face-profile`, `face-reaction-arc`, `face-low-angle`, `face-high-angle`,
`face-revelation`, `face-to-face`), four action shots (`boots-to-face`,
`dutch-charge`, `overhead-formation`, `camera-pass`) and eight vehicle shots
(`vehicle-showcase`, `vehicle-front-low`, `vehicle-rear-chase`,
`vehicle-side-track`, `vehicle-wheel-detail`, `vehicle-roof-orbit`,
`vehicle-convoy`, `vehicle-drift-arc`). The vehicle presets bind the user's GLB;
there is no bundled car, private model, texture or animation binding.

Open Studios → Video 3D → Shot library, select a preset and assign the GLBs.
Subject framing edits the tracked object, head/center/base anchor, start/end
camera and look offsets, orbit turns and camera tilt. Offsets are in meters
multiplied by the object's scene scale. They rotate with the subject heading
unless that option is disabled. Camera tilt is in degrees. A bone whose name
ends in `Head` is tracked after animation and grounding; unrigged models use
86% of the current mesh height. Center/base use animated mesh bounds. GLB rigs,
front axes and proportions vary: check the first and last frame and adjust
these controls for each asset. A car has no standard wheel-bone contract, so
the wheel-detail preset is an editable offset, not automatic wheel detection.

`camera.framing` is optional and preserved in shot JSON. Old camera families
retain their behavior when it is absent. Selecting another camera family
clears the subject framing so the selected family takes effect. Editor and
Wizard mount requests share the template registry; an explicit Wizard
`cameraFamily` override also clears framing. This does not add a separate
Wizard action for editing arbitrary framing fields.

Travel presets translate the model through the fixed street. The supplied
Quattro test asset contains a single mesh/material, no clips and no separate
wheel objects. Its travel moves the whole car; tire spin, steering, body-panel
recoloring and suspension are not claimed as rigged animations.

## Animated lettering in 2D and 3D

Both editors expose the same `texts` cues and canvas painter: impact, upward
entry, terminal typing and letter wave. Cues store literal text, local start/end
seconds, position percentages, size as height percentage, color and tilt.
They survive scene/shot JSON, 2D recipe round trips and template changes, and
are baked into MP4s. Preview uses a bounded canvas; final output uses the export
resolution. Text draws over the image, below the optional clip number.

The optional `font` field selects `sans` or `mono`. Monospace lettering provides
terminal-style typography for either editor; the same font is used for measuring
and painting. The default retains existing sans-serif output. Typeface choice
survives shot files, 2D recipes and template changes; imports accept only the two
known values rather than arbitrary CSS font strings.

At most 12 cues and 240 characters per cue are accepted. Blank or invalid lists
do not add new fields to legacy 2D scene files. Cue timing is local to a shot;
3D global playback speed affects text and scene together. A recipe's scene text
defaults apply to each compiled shot. This does not provide lyric alignment,
karaoke word timings, occlusion by 3D objects or extruded 3D type.

## Monitors, billboards and image/video surfaces

In Video 3D, **Add screen** creates a physical monitor, billboard or frameless
panel. Choose an image or video from the device or library, adjust its dimensions
and use the regular object transforms and travel controls. **Fit entire image**
letterboxes the original; **Fill and crop** fills the face without stretching.
Screen faces are unlit so the app's content remains readable under scene lights.

For an existing GLB, enable **Put a face / screen on this character**. Prepared
monitor meshes use **Paint an existing mesh**; a known bone such as `headfront`
defaults to **Anchor a plane**. Mesh selection lists paintable meshes; plane
attachment lists named bones/nodes. A plane follows its animated parent, keeps
the original body material and uses upright media by default. Its width, height,
offset and three-axis rotation are local to the GLB anchor and survive
saving/reopening a shot. Offset is limited to -2…2 and angles to -180…180 degrees
in both editor and loader. Meshy's `headfront` preset aligns its +Y-facing bone
to an upright front-facing screen; other rigs can adjust pitch, yaw and roll.

In mesh mode, select the prepared display mesh.
`SCREEN_CONTENT` is the initial name for prepared monitor models. The name must
identify exactly one mesh; missing/duplicate names fail visibly and prevent an
incomplete export. The mesh needs usable UVs. Its existing geometry and UVs
determine placement; width/height set the content aspect, not the GLB's dimensions.
Use **Flip vertically** for assets whose UV orientation needs it. Other materials
remain on the object. This is one media surface per slot, not a general material
or submesh editor.

Videos are muted and follow scene time, including start offset, playback speed,
loop/hold and backwards seeks. Export awaits the decoded frame before encoding
it. Async loads and callbacks are scoped to their current slot/configuration;
replacement and unmount dispose the old material, texture and decoder. Source
URL and source identity survive shot JSON. Keep the uploaded files with the
project: JSON references them and does not embed their bytes.

Eight reusable product templates contain no private media: `monitor-reveal`,
`desk-presenter`, `monitor-detail`, `screen-gallery`, `billboard-plaza`,
`screen-corridor`, `control-room`, and `product-finale`. Their sets are `retro-lab`,
`observatory`, and `broadcast-plaza`. The desk preset expects a user GLB with a
display mesh. Switching templates retains screen content while adopting the new
layout. The registry is shared with Wizard mounting; arbitrary screen-source
bindings still use the editor or shot JSON. This feature requires the WebGL path.

Local LogSentinel production preserves four supplied screenshots, the PC GLB,
Tentri's nine named animations and the complete supplied song. The screens include
a real rendered mascot video. Real-browser checks exercise forward/backward
video seeks and paused repaint; contract checks cover stale loads, disposal,
export locking and async frame capture. Screenshots remain user evidence: their
paused-analysis/error counters are not replaced with invented healthy telemetry.

## Validation and production observations

Unit tests cover exact STEP endings and backwards seeks, deterministic travel,
import rejection, source/clip roundtrip and optional number overlays. Real local
production exercised three separately uploaded animated GLBs, 66 browser-rendered
shots and full-song assembly. Private assets, music and generated videos remain
outside version control. Model animation names describe exported labels; they
are not a guarantee that the motion matches an editorial intention.

The local experiment found two independent Video Editor assembly concerns:

- Its returned file URL needs the explicit output workspace when downloaded by
  an automation client. A bare URL can resolve against the global default.
- Joining the 33 silent 30 fps shots through Video Editor produced 5,207/5,206
  frames versus 5,214 source frames. The first assembled video had a null-muxer
  DTS warning. This is a follow-up in Video Editor normalization/concatenation;
  this change does not claim to fix that backend. Deliverables were finalized
  from the original frame-complete shots through Scene Recordings, with their
  soundtrack supplied separately and an explicit frame count.

Original song lyrics and transcription stay separate. In this experiment the
beat detector provided useful timing, but automatic sections collapsed nearly
the whole song into “verse” and transcription omitted/rephrased parts. Storyboard
planning used those timestamps as clues, without replacing the supplied lyrics.

Next useful work: a persistent multi-shot 3D timeline with scoped audio, batch
export in the UI, named character instances, contact/foot IK, adjustable keyboard
targets, and framing that warns when an orbit crosses the set. The second local
iteration exercises all 33 original clip numbers with actual travel, clone
chases, a programmer room and generated environment materials. Image prompts,
provider/model identity, asset IDs and observed hashes are kept with the private
delivery so a generated texture is not mistaken for an authored source asset.
