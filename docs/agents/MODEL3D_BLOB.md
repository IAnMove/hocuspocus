# A round-headed body

`model3d.blob.make` builds one person from traits or a preset, composes the
mesh on CPU and rigs it in the same call. There is no job and no
`model3d.rig.status`. The same body is the Wizard action `blob_make`, the
Studio 3D panel (next to the existing 3D models) and `POST /api/v1/model3d/blob`.
`model3d.blob.presets` (`POST /api/v1/model3d/blob/presets`) lists the limits
and the fifteen presets. No GPU.

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

`preset` is one of `sailor`, `cashier`, `boss`, `kid`, `big`, `lanky`,
`blob_chef`, `blob_pirate`, `blob_scout`, `anime_girl`, `anime_boy`,
`anime_senpai`, `chibi_kid`, `chibi_mage`, `chibi_knight`. `traits` override
the same fields. Omitting both uses the defaults (1.8 m, average, family
`blob`, a large round head, no hair). Unknown fields are refused.

Traits: `height` (metres, 1.2–2.2), `build` (`slim`, `average`, `round`,
`pear`), `family` (`blob`, `anime`, `chibi`; omit it for a blob), `head`
(`width`, `height`, `depth` as fractions of the body height, `shape` `sphere`,
`egg`, `anime` or `chibi`), `arms` and `legs` (`length`, `thickness`,
fractions of height), `hands` (`ball` or `mitten`), `feet` (`shoe`, `ball` or
`boot`), `hair` (`style` `none`, `short`, `bangs`, `spiky`, `long`,
`ponytail`, `twin_tails` or `bun`, plus `color`), `colors`, `accessories`.
Colors are nested under `colors` because `head` is already the shape: `head`,
`top`, `sleeves`, `bottom`, `shoes`, `hands`, each `#RRGGBB`. An egg is at
least 1.12 times as tall as it is wide, and no deeper than 0.92 of that width.
Head width is 0.12–0.46 of the body height. Arm thickness is drawn no wider
than 45% of the torso so the rig can peel the arms; the returned traits keep
the requested number. A blob head stays wider than its chest. An anime body is
about 7 heads tall, with shoulders wider than the small head and a narrower
neck between them. A chibi is about 2.5–3 heads tall. Blob and chibi arms are
drawn no longer than 0.30 and 0.26 of the height: a longer arm's wave meets
the wide head; anime arms no longer than 0.42, and they are one smooth tube
(the elbow sphere and the forearm keep the upper arm's diameter, the shoulder
sphere stays inside the sleeve) so no ink ring marks the elbow. The stored
trait keeps the requested length. Pieces overlap, the arms are a T, and the
feet sit on y = 0.

`mesh: "loft"` (anime family only) replaces the primitives with one smooth
lofted mesh in the spirit of a PS2 humanoid: elliptical rings strung along
each limb, so an elbow or a knee is a run of rings the rig blends, a torso that
tapers to the waist and out at the hips, a real neck, an egg head with a jaw
(`blob_loft.egg_scale`, the same formula as the face cap's `taper`), mittens
with a thumb, shoes with a sole, and hair as geometry in `hair.color` (a helmet
round the crown and back, side locks and a fall for `long`, spikes for `spiky`,
flat strands on the forehead only for `bangs`: a painted fringe draws its own).
Accessories become colour regions of that mesh: `skirt` (two thin pleated
sheets, knee socks), `school_collar` (a collar and a ribbon, or the shirt V of a
`jacket`), `tie`. About 3–4k triangles. The default body is unchanged.

Accessories, each at most once, up to six: `cap`, `sailor_cap`, `top_hat`,
`beanie`, `bucket_hat`, `apron`, `tie`, `collar`, `belt`, `backpack`, `scarf`,
`skirt`, `jacket`, `sleeves_long`, `shorts`, `school_collar`, `cape`. A skirt
is two thin sheets, so the rig still sees the legs and reports `covered_legs`
when the feet show. A moustache, glasses, brows and freckles are the face, not
accessories. Hair sits on the skull and stays off the face; long hair hangs
down the back.

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
added prop, and play `Wave`. Every preset uses the same 25 Mixamo bones, so a
Mixamo, Meshy or VRM clip can be retargeted onto it. The 2D face and visemes
are a separate call. Set textures, separate fingers and body expressions are
out of scope.

See [compose](MODEL3D_COMPOSE.md) for the piece rules and
[the humanoid rig](HUMANOID_RIG.md) for the skeleton.
