# Compose a low-poly model on CPU

`model3d.compose` creates a self-contained GLB inside an explicit workspace.
It does not load Torch, a model runtime or a GPU. Use the same command body
for MCP or `POST /api/v1/model3d/compose`.

```json
{
  "version": 1,
  "intent_id": "tree-1",
  "input": {
    "workspace": "my-video",
    "name": "Little Pine",
    "pieces": [
      {"type": "cylinder", "scale": [0.2, 1, 0.2], "color": "#75452D"},
      {"type": "cone", "position": [0, 0.8, 0], "scale": [1.4, 1.6, 1.4], "color": "#24904C"}
    ]
  }
}
```

A model can be described in a few hundred tokens. There are 1..128 pieces;
each needs only `type` (`box`, `sphere`, `cylinder`, `cone`, `capsule`,
`frustum`). Optional fields are `position`, `scale`, `rotation` (three numbers
each), `color` (`#RRGGBB`, default white), `segments`, `smooth` and, on a
frustum, `taper`. No unknown piece fields are accepted.

Primitives fit the unit cube centred at the origin; sphere/cylinder/cone
radius is 0.5 and their height/diameter is 1. Coordinates are metres, Y-up.
Rotations are Euler radians applied X, Y, Z. Transforms are baked in. Scales
must be positive, and every component must be finite and within ±1000.
Round primitives have eight radial segments; the sphere has six rings. An optional
integer `segments` from 6 to 48 replaces that. A sphere then has `segments // 2`
rings (24 segments is 12 rings and 528 triangles; 48 segments is 24 rings and
2208). A cylinder or cone has four triangles per segment. Leaving `segments`
out is byte for byte the eight-segment mesh, including the six-ring sphere:
passing `8` is not the same, because a sphere would then have four rings.
`MAX_PIECES` stays 128. There is no separate triangle cap. 128 spheres at 48
segments are about 30 MB, under the 64 MB inspector limit.

`smooth: true` on a piece, or `smooth: true` on the input, replaces flat normals
with radial ones on spheres, cylinders, cones, capsules and frustums. A flat cap
keeps an axial normal, so the lid does not bleed onto the side. A box stays flat.
Omit `smooth` (or pass false) and a model of the old four types is byte for byte
the flat mesh, including the gold hash of `fixtures/blob2_pieces.json`. The rig
keeps those normals: it bakes an identity mesh in place and does not recompute them.

A capsule's `scale` is diameter × length × diameter. The length includes the
hemispherical caps. When the length is longer than the diameter the middle is a
cylinder and the caps are hemispheres; a shorter one is an ellipsoid. A frustum
is a cut cone: `scale` is the bottom diameter × height × bottom diameter, and
`taper` (0.2 to 1) is the top diameter divided by the bottom. `taper` on any
other type is refused.

The GLB uses split triangle vertices, flat normals unless `smooth` is set, linear vertex colors
converted from the input sRGB hex values, and a matte white material. It
has no textures, external buffers, skeleton or animation. Animate rigid
models through Video 3D slot motion and the scene camera.

Pieces that share a face plane (a screen laid flush on a cabinet, a cushion on a seat)
would flicker against each other as the camera moves. When two differently coloured
surfaces lie in the same plane, face the same way and overlap, the one with less area
is lifted 4 mm along its normal, and a third one 8 mm. Faces that only touch back to
back are left alone. Nothing else changes, so a model with no shared planes is byte
for byte what it was. Models composed before this fix keep their old geometry; compose
them again from the piece recipe in their manifest to get the separated faces.

The reply is `{version:1, operation:"model3d.compose", status:"completed",
result:{file,name,workspace,url,sha256,pieces,bytes}}`. The URL includes the
workspace and works as a Video 3D slot `sourceUrl`. A canonical asset manifest
stores the piece recipe and command identity beside the GLB. The same intent
and body replay the original result; changed parameters conflict. Failed
or uncertain publication never silently creates another admission.

For AI-generated meshes use the [native Model3D MCP contract](MODEL3D_MCP.md).
For loading and inspecting either kind use the
[procedural 3D scene guide](../development/PROCEDURAL_3D_SCENE_SPEC.md).
