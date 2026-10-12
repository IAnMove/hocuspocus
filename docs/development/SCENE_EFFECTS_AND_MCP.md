# Scene SFX, speech and MCP

## Scene effects

Video 2.5D and Video 3D share **Scene SFX → Apply SFX showcase template**.
The template adds a 90-second track demonstrating 30 effects, three seconds each:
sparks, explosion, fireworks, confetti, rain, snow, embers, smoke, fog, bubbles,
stars, portal, shockwave, lightning, speed lines, scanline, aurora, laser and code rain; plus magic circle, arcane missiles, summoning gate, black hole, ice burst, meteor shower, lightning storm, anime aura, energy orb, energy beam, sword slash, manga impact, impact flash and inverted impact frame; plus candlelight, vignette, film grain, light rays, glitch and painted canvas.
The separate magic/anime template demonstrates the 14 additions in 42 seconds.
It preserves existing layers, actors, camera and voices, replaces the SFX track,
and extends the scene if necessary. An empty 2D scene gets the bundled stage SVG.
Save the resulting scene JSON to reuse it with other assets.

Each cue has start/end, position in screen percent, size, intensity, rotation, color, seed,
and optional sound/volume. These are canvas overlays in screen space, including
in the 3D editor; they do not simulate volumetric particles or physical collisions.

`impact_flash` and `impact_invert` are anime impact frames. They cover the whole
picture whatever their size: `x`/`y` place the vanishing point of the focus lines,
`size` the clear circle around it, `intensity` the number of lines. A flash is a
frame in `color` (white by default), then that frame crossed by ink lines, then a
release; the inverted frame is the negative of the picture, then the negative with
lines in `color`. Give them 2–4 frames (`end - start` = frames / fps, 0.083–0.167 s
at 24 fps). The negative needs the picture under it: exports paint over the frame,
and the Video 3D and Video 2D previews copy the stage while it is live.
`speedlines` uses `intensity` for the number and weight of its lines; 1 keeps the
original 65 hairlines.

`code_rain` is digital code rain over the whole frame: columns of half-width
katakana, digits and some Latin capitals fall, each at its own speed, with a
near-white head and a trail that fades to `color` (`#39ff6a`) and then out; the
glyphs change as they fall. `size` is the glyph height in % of the frame height.
Its catalog entry has `"size": 3`, so a cue without `size` gets 3, not the 65 of the
other effects (the showcase uses it too). `intensity` sets the density and the
brightness; `x`, `y` and `rotation` are not used. The frames repeat over the cue:
every column makes a whole number of trips and every glyph a whole number of
changes between `start` and `end`, so the frame at `end` is the frame at `start`.
A plate of N seconds (`series.location.plate3d`) loops with no seam when the cue
lasts N seconds. The glyphs are drawn with a monospace CJK face (Noto Sans Mono CJK
JP on Linux, MS Gothic on Windows, Osaka or Hiragino on macOS); when the browser
draws no katakana, the rain uses digits, Latin capitals and symbols.

### Cinematic light and film

The `cinematic` collection («Luz de cine y película») has six grades for candle-lit,
tenebrist scenes. Each covers the whole frame (it is painted outside the cue's
x/y/size transform), so put it on the cue track for the whole shot. A catalog entry can
carry its own `size`, `x`, `y` and `rotation`; a cue without the field gets that
default (in the editor, in `scenes.effects.apply` and in both showcases), and switching
a cue's kind in the editor resets those fields.

| Effect | Colour | What it does | Fields |
| --- | --- | --- | --- |
| `candlelight` | `#ffb35c` | Warm key light from a flame. The picture is lit by colour dodge (multiplied by up to 1 / (1 − light)), so what is there takes the light; a glow is screened in the air near the flame; the frame darkens slightly away from it. The flicker is three layers of smooth noise near 1.6, 3.7 and 7.9 Hz (at most ±16 %), and the flame sways a little. | `x`/`y` the flame, `size` the radius of the pool of light in % of the frame height (45), `intensity` the light, the glow and the darkening together. |
| `vignette` | `#000000` | Dark edges, an ellipse that fits the frame. Static. | `x`/`y` the clear centre, `size` how far in it reaches (60; at 100 it starts at the centre), `intensity` how dark the corners get (0.73 at 1). |
| `film_grain` | — | Monochrome grain, new on every frame (60 grain frames per second, a quarter step out of phase, so 24, 25, 30, 50 and 60 fps exports never repeat one). Drawn with `overlay` around mid grey, so the picture keeps its mean; like film it shows most in the midtones. | `size` the grain in % of the standard (100: about 2 px on 1080 lines), `intensity` the amount. `x`, `y`, `rotation` and `color` are not used. |
| `light_rays` | `#ffd27a` | God rays: a fan of soft shafts (about 34° wide) and lit air, screened over the frame, with a glow at the source. Each shaft sways over several seconds and brightens and fades over a few. | `x`/`y` where the light comes from (28, 0), `rotation` where it points (62; 0 right, 90 down), `size` the length in % of the frame height (120), `intensity` how many shafts and how bright. |
| `glitch` | `#39ff6a` | Digital corruption in bursts (about one every 1.8 s at intensity 1, 0.16–0.5 s long): horizontal tears that move bands of the real picture sideways with red and blue split apart, a slight RGB split of the whole frame, displaced and noisy blocks, phosphor lines and flashes in `color`. The corruption changes 18 times a second; between bursts the frame is left alone. | `size` the height of the bands and blocks in % of the frame height (6), `intensity` how often and how strong. `x`, `y` and `rotation` are not used. |
| `canvas` | `#efdcb8` | Painted canvas: woven threads of uneven thickness under brush strokes, multiplied over the frame and tinted by `color`. Static. | `size` the texture scale in % of the standard (100: threads about 4.6 px apart on 1080 lines), `intensity` the depth and the tint. |

The frames are a pure function of seed and time and repeat over the cue: whatever moves
(flicker, sway, shimmer, grain, bursts) makes a whole number of cycles between `start`
and `end`, so the frame at `end` is the frame at `start` and a plate as long as the cue
loops with no seam. A suggested order on the track: `candlelight`, `light_rays`,
`vignette`, `canvas`, `film_grain` (grain last). `candlelight`, `light_rays`,
`film_grain`, `canvas` and `glitch` need the picture under them: exports paint over the
frame, and the Video 2D and Video 3D previews copy the stage while one of them is live,
as for the retro looks. `vignette` only darkens and paints the same over anything. In
`screenBackdrop.sfx`, `candlelight` and `light_rays` light the environment plate behind
the characters without touching them. Where no off-screen canvas exists, grain and
canvas draw nothing. A world-space `glitch` (a hologram-like world SFX) is a different
effect that keeps its own look.

### Light for dark, painted frames

`shockwave`, `shield` and `embers` are drawn straight on the frame with additive light
(`lighter`), in Video 2D, Series fx, Video 3D sfx and `screenBackdrop`. In 2D overlays
`shockwave` and `shield` no longer film their 3D world sprite: that showed a ground ring
seen from the sprite camera (a flat ellipse) and clipped its overdriven colour channel by
channel, so a gold turned lemon-green. Every layer keeps the hue of `color`: the soft
glows are the colour at alphas that stay below saturation, their thin edges a deeper
shade of it (a faint gold over a blue night stays gold, not grey), and only the cores
whiten. The world kinds of the same names in `worldSfx` keep their 3D look.

| Effect | What it does | Fields |
| --- | --- | --- |
| `shockwave` | A ring of light from `x`/`y`. A white-hot flash with a thin horizontal flare at the start (gone in about half a second); a front that eases out (fast, then slowing) and dims to nothing at `end`, made of a long soft trail of lit air, a band of light, a glowing line and a thin hot core, uneven along the ring (three layers of smooth noise slide along it, so it is never a drawn circle) with brighter patches and strands; two fainter, softer echoes 7 % and 15 % of the cue behind it; sparks it throws off that drift on more slowly and dim, a few as four-point glints. | `size` its reach (the front ends half the size from the centre), `intensity` the light. |
| `shield` | A dome of light around someone (a force field, a holy aura), a little taller than wide: a see-through body brighter toward the rim (never more than 25 % light), a soft rim with an uneven bright line drifting round it, a glow around it that is stronger above, slow shimmer and light ripples rising inside, a highlight high on one side, and motes drifting up through it. It swells in over the first second, breathes about every 3.5 s and fades out in the last half second. | `x`/`y` its centre, `size` its height, `intensity` the light on a square-root curve (0.4 still reads). |
| `embers` | Sparks rising from the bottom of the cue box and drifting on curved paths as they cool: near white, then `color`, then a darker glow of it; each flickers and leaves a streak about one frame long. | `x`/`y`/`size` the box, `intensity` how many. |

`stars` and `bubbles` take their place across the box from their own random number:
one shared with their phase lined them up on diagonals. `smoke` is a column of puffs
broken into lumps lit from above (darker undersides) that swell, turn and drift on a slow
wind, and the flames of `anime_aura` fade in from the bottom of their card instead of
ending on a straight cut.

### Beams from a point: `from`

A `laser` or `lightning` cue (catalog entries with `"aim": true`) can start at `from` and
run to its `x`/`y`, where it lands; `rotation` is then not used. `from: {x, y}` is a point
in % of the frame. `from: {layerId, x, y}` is a point in % of that layer's picture: the
Video 2D painter places it where the layer is drawn at that frame (its motion, the camera
push, the contained, filled or covered fit of the picture and its rotation), so a beam
leaves a rifle's muzzle on a cutout wherever it stands. Video 2D has no mirrored layers: a
cutout facing the other way is its own pose image, with its own point. Where no layer can
be placed (a Video 3D frame, or a layer that is not in the scene) the cue is drawn across
`x`/`y` as one without `from`. Both values may lie up to half a picture outside it
(-50–150). A Series shot writes `"from": {"cast": 0, "point": [95, 46]}` in `layout2d.fx`
(`cast`: an index in the shot's cast or a character id) and the shot compiler turns it
into the cast member's pose layer; `{"point": [70, 40]}` is a point of the frame, the only
form a Video 3D shot keeps. `scenes.effects.apply` and `screenFx` of `world3d.scene.patch`
take `from` too; any other kind refuses it.

Video 3D can also paint cues behind the world: `screenBackdrop`
(`{"color": "#1c2f86", "sfx": [<cue>, ...]}`) is a flat colour plus the same cues,
drawn as the frame background, so radial `speedlines` there are focus lines behind
the characters. An image slot with `surface: "environment"` is drawn first and the
cues over it. Every object in the world, flat cutouts included, stays in front.

Video 3D also stores a separate `worldSfx` track in meters. Portal, magic circle,
summoning gate, lightning, energy beam, laser, orb, aura, missiles and shockwave
occupy the scene graph: the camera changes their perspective and opaque meshes can
occlude them. Beams use `anchor`/`target` slot ids. Screen overlays remain available.
Do not convert legacy percent coordinates to meters. `scenes.effects.apply` accepts
`worldCues` only on a world3d document.
Absolute scene time and a fixed seed make scrubbing and exports repeatable.
The sounds are local procedural synthesis, not a neural sound library or MMAudio.
MMAudio remains available separately in the existing audio tools.

Visual scenes allow up to 64 cues and 600 seconds. Exports that mix sound/voices
are limited to 180 seconds of output. Preview respects browser audio activation.
The same visual renderer paints both previews and MP4 frames.

## Speaking characters

Use the existing **Video 3D → Voice and lip-sync** controls. Choose a GLB, place
its lips with **Add lips** or **Place with a click on the face**. Attach audio,
record with a microphone, or use the bundled English example. For new audio,
**Analyze lip-sync (local)** refines the initial volume-based motion with the
shared editor/MCP/Wizard service. Automatic prefers installed acoustic phonemes;
Rhubarb fallback is explicit. Choose the engine, exact fragment text and language.
Use interventions to schedule different speakers; each intervention keeps its
literal dialogue, source audio, trim offset, timing and phonetic cues.
Install the optional phoneme engine with the visible button or Wizard
`speech_analysis_engine` (`install:true` only when requested). See
[VIDEO3D_SPEECH.md](VIDEO3D_SPEECH.md) for engine installation and limits.
A static mesh can speak using the face overlay; a GLB does not need blendshapes.
Face placement is per model and must be reviewed visually.

MP4 publication preserves the embedded mix. If the browser cannot encode AAC
(for example Linux Chrome), it sends bounded mono PCM alongside the rendered
frames. The server uses FFmpeg to produce the audible MP4 in Videos. A failed
finalization is an error, not a successful silent speech export. The 3D local
MP4 download also retrieves the finalized file in this case.

## Shared operations

`GET /api/v1/scenes/commands` lists executable operations and JSON schemas.
`POST /api/v1/scenes/commands` accepts exactly `version`, `operation` and `input`:

```json
{"version":1,"operation":"scenes.effects.showcase","input":{"dimension":"2d","sound":true}}
```

| Operation | Inputs and result |
| --- | --- |
| `scenes.effects.catalog` | Empty input; returns the 30 presets, screen/world coordinates, and world kinds. |
| `scenes.effects.showcase` | `dimension` 2d/3d, `sound`, `collection` all/anime, optional native `document`. Returns the built-in template. Do not supply prompts or an effect list. |
| `scenes.effects.apply` | Native `document`, `cues` and/or `worldCues`, optional `replace`. Cue IDs upsert; world cues require Video3D. |
| `scenes.speech.capabilities` | Empty input; returns the same phoneme/Rhubarb/vocal-isolation availability and default engine as the editor, without loading a model. |
| `scenes.speech.prepare` | Native `document`, exact `slot_id`, `clip_id`, `workspace`, existing `audio_filename`, literal `text`, scene `start`/`end`, source `offset`, optional `engine` auto/phoneme/rhubarb, `language`, `isolate_vocals`. The shared analyzer processes up to 90 seconds and attaches source-clock cues with the actual engine and fallback. |

These operations return a detached document, SHA-256, `state: prepared`,
`saved: false`, and `exported: false`. They do not save over a project, generate
a voice, admit a GPU job, or render a video. Reusing an intervention ID replaces
that intervention; other voices are preserved. Overlapping turns on one speaker
are rejected. The caller supplies the actual document and existing workspace
filenames; remote/host audio paths are not accepted.

Ask to the Wizard exposes these operations through `prepare_programmatic_video`
with `scene_command`. Try: “Prepare the 2D SFX showcase with all 30 effects and
sounds, and open the resulting scene.” The Wizard calls the same service,
validates the result, and opens it in the corresponding editor. It keeps the
returned document and a backup of the previous scene in session storage before
presentation; save/export remains explicit. A presentation failure reports an
error and retains the prepared document instead of claiming a video was made.
To attach speech through Wizard, supply the exact scene document and audio name.

MCP exposes the five operation names directly; its `tools/call` arguments use
`{"version":1,"input":{...}}` (the tool name selects the operation). Preparation
and analysis run without an open browser. Rendering these scenes still uses the
native editor; this slice does not implement a headless server renderer.

## Enable and connect MCP

Open **Settings → Integrations → MCP**. The info icon explains access and use on
hover, keyboard focus, or touch. The toggle enables/disables access immediately.
Copy the newly issued key; status reads and logs never return it. Rotation
revokes the previous key. Keys are stored in `app/settings/mcp-access.json`
with mode 0600 where supported. A configured `HOCUS_MCP_TOKEN` takes precedence;
Settings can disable access, but environment-managed keys rotate outside the UI.

This is the **Hocuspocus MCP server**: it exposes the installation's published
generation, asset, collection, scene and workflow tools. The historical
`/api/v1/wangp/mcp` URL remains a compatibility alias to the same server, with
the same token, tool catalog and request journal.

The endpoint is the app's existing address plus `/api/v1/mcp`. There is no
second listener or daemon. The HocusPocus process must be running. A client on
another machine uses the reachable LAN address shown when accessing the app
from that machine, rather than `localhost` on the client.

Use an HTTP-capable MCP client with an Authorization header. For clients that
support this configuration shape:

```json
{"mcpServers":{"hocuspocus":{"url":"http://APP_HOST:PORT/api/v1/mcp","headers":{"Authorization":"Bearer <YOUR_TOKEN>"}}}}
```

Client configuration keys vary. Transport: Streamable HTTP JSON-RPC POST,
protocol `2025-03-26`; GET is not an event stream. Initialize, send the initialized
notification, then list/call tools. Calls require the MCP bearer key even if LAN
auth is off; MCP uses its own token when shared-LAN protection is on. This does
not unlock other API routes. Disabled MCP returns 503; missing/wrong keys 401.

Enable/rotate requests are restricted to the application's own trusted origin
and retain normal LAN authentication. Keys grant the tools advertised by this
app; keep them in the client configuration and out of screenshots or prompts.

## Acceptance run (10 September 2026)

PR #299, based on development `729f784c`, includes three actual native-editor
exports: 2D and 3D 54-second effect showcases, plus a 13.5-second Nova/Byte dialogue.
All are 1280×720, 30 fps, H.264 with AAC, decoded completely by FFmpeg.
The two original robot models were authored procedurally for the demo.

The dialogue uses real local KugelAudio generations (`b618ac8a`, `ee70ef12`),
submitted through MCP `generation.speech`. Replaying the first intent returned
the same job ID. Rhubarb produced 33/32 cues: the first voice was uploaded and
analyzed through the native UI; the second through `scenes.speech.prepare`.
Native seek checks verified A speaking/B resting, both resting, B speaking/A
resting, and recovery after seeking backwards. The exported voice duration and
content were checked with the app's installed Whisper transcription.

The real MiniMax Wizard request initially invented unsupported showcase fields
and correctly failed. The capability guidance was corrected; repeating the same
request opened the returned 2D scene and reported prepared, not exported.
MCP initialize, tools/list, showcase/apply and speech preparation were called
from an external HTTP client. Settings enable/rotation, disable (503), reenable
(200), desktop hover help and mobile tap help were exercised in the real UI.

Known limits: this proves two demo models and local audio, not every GLB/voice.
The Wizard's natural-language speech preparation was not separately tested;
its shared operation and visible handoff were exercised independently. The
settings test uses the built app origin; a Vite proxy with another Origin is
rejected by the settings origin guard. Demo files and captures are local outputs,
not Git content. Independent agent review is still a separate evidence state.


## Optional vocal isolation

In a character's lip controls, **Isolate vocals before calculating lips** enables
CPU BS-RoFormer before Rhubarb. The source track, trim and scene clocks remain
unchanged. Cues store `driver: rhubarb-vocals`; save/reopen preserves provenance.
Only the already installed `audio-separator` package and
`app/ckpts/roformer/model_bs_roformer_ep_317_sdr_12.9755.ckpt` with its matching
`.yaml` are accepted. There is no automatic install, discovery or download.
The worker blocks networking, uses two CPU threads and a single process at a time,
with a 15-minute timeout and a 90-second input limit. Closing the UI discards its
pending result; an admitted CPU analysis finishes or times out on the server.
Missing dependencies and failed analysis are explicit errors; existing cues stay
intact. HTTP uses `GET /api/v1/character-kits/speech/capabilities` and
`POST /api/v1/character-kits/speech/analyze?isolate_vocals=true` (mono16k PCM WAV).
Wizard `scenes.speech.prepare` and direct MCP use the same service/flag.
Isolation reduces instrumental interference; phonetic cues still need review.

## Native Video3D gallery

**Save scene to gallery** writes a new immutable scene revision and PNG preview
in the explicit current workspace. **Open scene** uses the shared full-screen
resource picker and offers only native Video3D documents. Choose commits; Cancel,
workspace changes and stale loads preserve the current scene. JSON import/export
remains available. New `*.world3d.scene.json` outputs open in the 3D editor from
the media gallery as well. Saving references uploads/workspace resources; it is
not a portable asset package. The server rejects transient blob/file references.
The native save endpoint is `POST /api/v1/scenes/world3d` with `document`, `name`,
`workspace` and PNG data-URL `preview`. Existing 2D scene persistence is unchanged.

## Cinematic spatial effects

Video3D's existing ten spatial kinds now use noisy energy surfaces, soft particles,
branching lightning and a shared bloom pipeline. `smoke` and `sparks` also accept
world coordinates. Existing IDs, anchors, timing and sound settings are preserved;
screen overlays remain a separate track. Beam endpoints still use slot-local
anchors, including normalized/scaled GLBs. All motion derives from scene time and
seed, including backward seeks. Three pooled lights illuminate nearby geometry.

The Cinema template browser includes **Reflective stage** and **Character
materialization**. Both use the bundled animated TV robot; replace its GLB and
choose an animation from that model. The second template adds two image screens,
a lightning strike and a centered platform. Hold a living pose samples the chosen
clip at its start offset with subtle yaw motion; it never retargets another rig.
Set the character's Y position to `.235` meters for the supplied platform.

**Cinematic environment** controls mirror floor, platform and bloom. A background
image slot with `surface: environment` covers the frame with centered aspect-fill;
it is an illustrated backdrop, not modeled architecture. The reflective brushed
metal floor blends into the background at a distance. Reflections are bounded to
1280×720. Other slots retain ordinary image/wall/floor behavior.

Per-slot `appearance: {start, duration, color}` reveals the posed mesh upward with
an energized edge. It composes with native speech shaders and supports lit and
unlit GLTF materials. It does not create a voice or calculate phonetic cues.
Preview, gizmo/media redraws and exported frames share the postprocessing path.
Save/reopen preserves these native document fields; no external cinema extension
is required for these templates or effects.
