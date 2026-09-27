# Scene SFX, speech and MCP

## Scene effects

Video 2.5D and Video 3D share **Scene SFX → Apply SFX showcase template**.
The template adds a 90-second track demonstrating 30 effects, three seconds each:
sparks, explosion, fireworks, confetti, rain, snow, embers, smoke, fog, bubbles,
stars, portal, shockwave, lightning, speed lines, scanline, aurora and laser; plus magic circle, arcane missiles, summoning gate, black hole, ice burst, meteor shower, lightning storm, anime aura, energy orb, energy beam, sword slash and manga impact.
The separate magic/anime template demonstrates the 12 additions in 36 seconds.
It preserves existing layers, actors, camera and voices, replaces the SFX track,
and extends the scene if necessary. An empty 2D scene gets the bundled stage SVG.
Save the resulting scene JSON to reuse it with other assets.

Each cue has start/end, position in screen percent, size, intensity, rotation, color, seed,
and optional sound/volume. These are canvas overlays in screen space, including
in the 3D editor; they do not simulate volumetric particles or physical collisions.

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
**Calculate gestures with Rhubarb (local)** refines the initial volume-based motion.
Use interventions to schedule different speakers; each intervention keeps its
literal dialogue, source audio, trim offset, timing and phonetic cues.
Rhubarb must be installed as described in [VIDEO3D_SPEECH.md](VIDEO3D_SPEECH.md).
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
| `scenes.speech.capabilities` | Empty input; returns installed Rhubarb and optional local vocal-isolation availability without loading a model. |
| `scenes.speech.prepare` | Native `document`, exact `slot_id`, `clip_id`, `workspace`, existing `audio_filename`, literal `text`, scene `start`/`end`, source `offset`, optional `isolate_vocals`. Rhubarb analyzes up to 90 seconds and returns a scene with the intervention attached. |

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
and Rhubarb run without an open browser. Rendering these scenes still uses the
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
