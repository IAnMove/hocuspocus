# A round-headed body

`model3d.blob.make` builds one person from traits or a preset, composes the
mesh on CPU and rigs it in the same call. There is no job and no
`model3d.rig.status`. The same body is the Wizard action `blob_make`, the
Studio 3D panel (next to the existing 3D models) and `POST /api/v1/model3d/blob`.
`model3d.blob.presets` (`POST /api/v1/model3d/blob/presets`) lists the limits
and the six presets. No GPU.

```json
{
  "version": 1,
  "intent_id": "sailor-1",
  "input": {
    "workspace": "my-video",
    "name": "Sailor",
    "preset": "sailor",
    "traits": {"height": 1.72}
  }
}
```

`preset` is `sailor`, `cashier`, `boss`, `kid`, `big` or `lanky`. `traits`
override the same fields. Omitting both uses the defaults (1.8 m, average,
a large round head). Unknown fields are refused.

Traits: `height` (metres, 1.2–2.2), `build` (`slim`, `average`, `round`,
`pear`), `head` (`width`, `height`, `depth` as fractions of the body height,
`shape` `sphere` or `egg`), `arms` and `legs` (`length`, `thickness`,
fractions of height), `hands` (`ball` or `mitten`), `feet` (`shoe` or `ball`),
`colors`, `accessories`. Colors are nested under `colors` because `head` is
already the shape: `head`, `top`, `sleeves`, `bottom`, `shoes`, `hands`, each
`#RRGGBB`. An egg is at least 1.12 times as tall as it is wide, and no deeper
than 0.92 of that width. Arm thickness is drawn no wider than 45% of the torso
so the rig can peel the arms; the returned traits keep the requested number.
The torso is a fraction of the head, so the head stays wider and the rig sees
a neck. Pieces overlap, the arms are a T, and the feet sit on y = 0.

Accessories, each at most once, up to six: `cap`, `sailor_cap`, `top_hat`,
`beanie`, `bucket_hat`, `apron`, `tie`, `collar`, `belt`, `backpack`, `scarf`.
A moustache, glasses, brows and freckles are the face, not accessories.

`clips` defaults to `idle`, `walk`, `talk`, `nod`, `wave`, `shrug`, `point`
and `run` when those names are in the humanoid catalog. An unknown clip name
is an error. The head uses 32 segments. The torso and belly use 16. Limbs,
neck, hands and accessories use 12. Omitting `segments` on `model3d.compose`
is still the old 8-segment mesh; these bodies always pass a count.

The reply is `{version:1, operation:"model3d.blob.make", status:"completed",
result:{file, url, rigged_file, rigged_url, clips:[{index, id, name, duration, loop}],
faceAnchor, traits, name, workspace}}`. `faceAnchor` is the head centre, the
radii (half the head scale) and `front` (the centre plus the depth radius on
+Z), for whoever draws the face later. Both GLBs are in the workspace gallery.
The rigged file has a `.humanoid.json` beside it. The same `intent_id` and
body replay the stored result.

A mesh the rig refuses is `not_humanoid` with the rig's own `reason`
(`hands_stuck`, `arms_raised`, `single_leg`, `legs_too_short`, `asymmetry`,
`not_upright`, `turned`, `degenerate`), on HTTP and on MCP. It is not a
generic failure.

Put the rigged file on a Video 3D character slot (`subject_1`), not as an
added prop, and play `Wave`. Flat hands and flat legs stay tubes with an
outline for now. The 2D face and visemes are a later step. Set textures are
out of scope.

See [compose](MODEL3D_COMPOSE.md) for the piece rules and
[the humanoid rig](HUMANOID_RIG.md) for the skeleton.
