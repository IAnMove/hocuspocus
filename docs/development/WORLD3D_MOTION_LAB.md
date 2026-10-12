# Native motion templates

Eight complete Video 3D sets use app-owned procedural meshes and points. They
need no generated images, GLBs, providers or model installation. The editor,
MCP and Ask the Wizard discover the same cards and compile the same documents.
The templates are creative adaptations of public motion briefs, with original
geometry, lettering, choreography and musical phrases; external footage and
source code are not imported.

| Template id | Default seconds | Behaviour | Brief inspiration |
| --- | --- | --- | --- |
| `motion-bouncing-ball` | 16 | Ball contacts tuned platforms on a shared visual/audio beat calendar. | [Bouncing ball](https://www.prompt-motion.com/gorden-sun-041f56) |
| `motion-music-machine` | 20 | Balls and a mechanical percussion assembly strike instruments, producing local notes. | [Music machine](https://www.prompt-motion.com/kamstudiolabs-447565) |
| `motion-sunset-flight` | 24 | Original aircraft bank over a volumetric sea with islands and moving clouds. | [Aerial motion](https://www.prompt-motion.com/nft-chen-5f8bb0) |
| `motion-seasonal-carriage` | 32 | Train interior, table and cup; a moving 3D landscape changes seasons. | [Seasonal train](https://www.prompt-motion.com/itsolelehmann-e47532) |
| `motion-data-assembly` | 32 | Computing and cooling parts assemble with animated data flows. | [Data centre](https://www.prompt-motion.com/sayan-shanky-f850d8) |
| `motion-lighthouse-story` | 32 | A geometric keeper climbs a coastal lighthouse and its beacon turns. | [Lighthouse](https://www.prompt-motion.com/kamstudiolabs-0b0824) |
| `motion-poster-breakout` | 10 | Solid block letters, rings and an orb pass through a physical frame. | [Poster escape](https://www.prompt-motion.com/pankajkumar-dev-0bee87) |
| `motion-particle-morph` | 24 | A 3D point cloud transforms between sphere, torus, heart and lettering. | [Motion typography](https://www.prompt-motion.com/blue-clarity-ef56d0) |

## Shared controls

Apply any id with `world3d.scene.apply`, then patch its `motionLab` field through
`world3d.scene.patch` using the returned `base_revision`. Partial patches preserve
other controls. The editor exposes the same settings in **Native motion scenes**.

```json
{"motionLab":{"bpm":112,"speed":1,"color":"#54ddff","secondaryColor":"#ffb86b",
              "title":"HELLO 64","sound":true,"volume":0.35}}
```

| Field | Default | Bounds / purpose |
| --- | --- | --- |
| `bpm` | 120 | 40–240; contact tempo for the two musical mechanisms |
| `speed` | 1 | 0.1–3; choreography speed (music tempo also scales) |
| `amplitude` | 1 | 0.1–3; set-specific excursion/size |
| `seed` | 7 | Integer 0–2147483647; reproducible variation |
| `color`, `secondaryColor` | `#54ddff`, `#ffb86b` | Six-digit hex colours |
| `title` | HOCUS | Trimmed, up to 24 characters; block titles and particle text |
| `density` | 900 | Integer 200–3000; particle count |
| `sound`, `volume` | true, 0.35 | Local notes for the two musical sets; volume 0–1 |

Letter geometry uses an original block alphabet (A–Z, digits, space, !, ? and -).
Accents normalize to their base letters; other symbols use a question glyph.
The camera, lighting, render quality, duration, soundtrack and additional GLB
slots remain standard Video 3D document fields. Complete presets have no empty
asset slots. Their built-in geometry is controlled as a set; adding a GLB does
not replace a built-in aircraft or keeper automatically.

## Time and sound

Each set assigns poses from absolute scene seconds. Seeking backwards,
out-of-order export subframes and reopening a document produce the same result.
The music mechanisms are authored contact choreography, not a rigid-body physics
simulation. Their note scheduler and visible impacts use one deterministic
calendar; changing BPM or speed changes both. No notes are triggered by browser
frame callbacks. Sound is synthesized locally, mixed with existing voices,
soundtracks and effects by both browser and owned exports, and kept by the
backend mux gate. The six other presets do not create incidental audio.

`playbackSpeed` retains its existing meaning: it retimes the entire output,
including sound. Native BPM does not auto-detect or align an imported song.
Changing duration extends/truncates choreography; `retime: true` stretches
existing explicit cues but does not change the native BPM or set speed. Set
`motionLab.speed` explicitly when a different choreography pace is wanted.

## Preview and resource ownership

Library thumbnails and exports use the same native builders. MCP's diagnostic
160-pixel preview rasterizes the actual set meshes and points with a depth buffer.
It omits shadows, transparency blending and WebGL postprocessing (nearly
transparent glass and soft beams are omitted); ordinary GLB
slots retain the existing software preview markers. Use a draft export to judge
final framing and materials.

Geometries have physical thickness and animated parts do not reuse coplanar
surfaces. Disposing a set releases shared meshes and point buffers once. No GPU
generation is needed to build the sets. Software WebGL captures can still consume
CPU, so run them serially at low priority during another production.
