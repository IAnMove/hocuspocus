import { ENERGY_NOISE } from '../energyShaders'

/** What every presence layer is given by the stage (see `drawLayer`): the window it paints in cue units (y down), the
 * effect's clock, seed, colour (0-1 channels), intensity, fade envelope, pixels per cue unit and the frame in pixels. */
export const PRESENCE_UNIFORMS = `uniform vec4 uWin; uniform float uTime, uSeed, uPower, uEnv, uUnit; uniform vec3 uColor; uniform vec2 uFrame;`

/** Noise, shared by the fragment and the vertex stages: the integer lattice hash of the world effects (see
 * `ENERGY_NOISE`), a per-particle random and the soft shapes the layers are made of. `rnd(id, salt)` is one number in
 * [0, 1) per particle and salt, fixed by the cue's seed: nothing is stored between frames. */
export const PRESENCE_LIB = `${PRESENCE_UNIFORMS}
${ENERGY_NOISE}
// Three octaves, a softer noise than fbm (five): for mist and haze.
float fbm3(vec2 p) { float s = 0., a = .5; for (int i = 0; i < 3; i++) { s += a * noise2(p); p = p * 2.03 + vec2(17.2, 31.7); a *= .5; } return s * 1.14; }
float fbm4(vec2 p) { float s = 0., a = .5; for (int i = 0; i < 4; i++) { s += a * noise2(p); p = p * 2.05 + vec2(17.2, 31.7); a *= .5; } return s * 1.07; }
float rnd(float id, float salt) { return hash(vec2(id + salt * 4099., uSeed)); }
vec3 whiten(vec3 c, float k) { return mix(c, vec3(1.), clamp(k, 0., 1.)); }
float ell(vec2 p, vec2 radius, float from) { return 1. - smoothstep(from, 1., length(p / radius)); }
const float TAU = 6.2831853;`

/** One quad that is the whole window: `vP` is the cue-space point of the fragment (y down), `vUv` the quad's 0-1 coordinates. */
export const WINDOW_VERTEX = `${PRESENCE_UNIFORMS}
varying vec2 vP; varying vec2 vUv;
void main() {
  vec2 t = position.xy + .5; vUv = t;
  vP = vec2(mix(uWin.x, uWin.z, t.x), mix(uWin.w, uWin.y, t.y));
  gl_Position = vec4(position.xy * 2., 0., 1.);
}`

/** Clip-space position of a cue-space point. */
export const CUE_TO_CLIP = `vec4 cueToClip(vec2 c) {
  vec2 n = (c - uWin.xy) / (uWin.zw - uWin.xy);
  return vec4(n.x * 2. - 1., 1. - n.y * 2., 0., 1.);
}`

/** The vertex stage of instanced quads: the body of `particle(id, out centre, out rad, out extra)` sets the particle's
 * centre and half-size in cue units and up to four numbers for the fragment (`vA`); it may also set the global `turn`
 * (radians, in cue space, y down) to turn the quad about its centre. `vQ` is the quad's local -1..1 coordinate. */
export function instancedVertex(particle: string) {
  return `${PRESENCE_LIB}
attribute float aId;
varying vec2 vQ; varying vec4 vA; varying float vId;
float turn = 0.;
${CUE_TO_CLIP}
${particle}
void main() {
  vec2 centre = vec2(0.), rad = vec2(.01); vec4 extra = vec4(0.);
  particle(aId, centre, rad, extra);
  vQ = position.xy * 2.; vA = extra; vId = aId;
  vec2 off = position.xy * 2. * rad;
  gl_Position = cueToClip(centre + vec2(cos(turn) * off.x - sin(turn) * off.y, sin(turn) * off.x + cos(turn) * off.y));
  // A particle that is not there (no size) is moved off the frame.
  if (rad.x <= 0. || rad.y <= 0.) gl_Position = vec4(2., 2., 2., 1.);
}`
}

/** The fragment stage's head for the layers above: varyings, uniforms and the library. */
export const WINDOW_FRAGMENT_HEAD = `varying vec2 vP; varying vec2 vUv; ${PRESENCE_LIB}`
export const INSTANCED_FRAGMENT_HEAD = `varying vec2 vQ; varying vec4 vA; varying float vId; ${PRESENCE_LIB}`
