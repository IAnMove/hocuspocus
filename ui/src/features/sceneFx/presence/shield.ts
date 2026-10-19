import { shieldState, SHIELD_ASPECT } from '../radiancePaint'
import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// shield: a dome of energy round x/y; size its height. Seen as a lit sphere: its rim is a thin bright line, its skin a
// field of hexagonal cells that light one by one, a pulse of light crosses it and ripples spread from points that are hit.
// Timing (rise, breath, fall) is the 2D shield's own (`shieldState`).

const REGION = [-.75, -.75, .75, .75] as const

const DOME = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 520000, region: REGION,
  extra: { uLight: { value: 1 }, uRadius: { value: .46 } },
  fragment: `
uniform float uLight, uRadius;
float hexEdge(vec2 uv, out vec2 id) {
  vec2 r = vec2(1., 1.7320508), h = r * .5;
  vec2 a = mod(uv, r) - h, b = mod(uv - h, r) - h;
  vec2 gv = dot(a, a) < dot(b, b) ? a : b;
  id = uv - gv;
  vec2 q = abs(gv);
  return .5 - max(dot(q, vec2(.5, .8660254)), q.x);
}
float ripple(vec3 n, float seed, float t) {
  float period = 2.6 + 1.6 * hash(vec2(seed, uSeed));
  float life = fract(t / period + hash(vec2(seed + 9., uSeed)));
  float cell = floor(t / period + hash(vec2(seed + 9., uSeed)));
  vec3 at = normalize(vec3(hash(vec2(seed, cell + 3.)) * 1.6 - .8, hash(vec2(seed + 4., cell + 7.)) * 1.6 - .8, .6));
  float away = acos(clamp(dot(n, at), -1., 1.));
  return exp(-pow((away - life * 1.5) / .16, 2.)) * (1. - life) * (1. - life);
}
void main() {
  vec2 p = vP / vec2(uRadius * ${SHIELD_ASPECT.toFixed(3)}, uRadius);
  float r = length(p), t = uTime;
  float z = sqrt(max(0., 1. - r * r)), disc = 1. - smoothstep(.985, 1., r);
  vec3 n = vec3(p, z);
  float fres = pow(1. - z, 2.6);
  // The skin: hexagons in a stereographic map of the sphere, so they shrink toward the rim as they do on a ball.
  vec2 id;
  vec2 map = n.xy / (1. + z) * 3.3 + vec2(uSeed * .31, 0.);
  float edge = hexEdge(map, id);
  float line = (1. - smoothstep(.0, .045, edge)) * disc;
  float cellLight = pow(hash(id * 1.7 + uSeed), 3.) * (.55 + .45 * sin(t * (.8 + hash(id) * 1.6) + hash(id + 3.) * TAU));
  float fill = smoothstep(.04, .3, edge) * cellLight * disc;
  // A band of light sweeps over it, tilted, and comes round again.
  float sweep = pow(.5 + .5 * sin((n.y * 1.3 + n.x * .7) * 4.2 - t * 1.25), 5.);
  float body = .03 + .2 * pow(1. - z, 1.4);
  // The rim is a Fresnel glow, brightest at the silhouette and uneven round it, not a drawn circle.
  float wave = .55 + .9 * fbm(vec2(atan(p.y, p.x) * 2.4 + t * .35, t * .22 + uSeed));
  float rim = (exp(-pow((r - .98) / .085, 2.)) * .45 + pow(1. - z, 3.) * .75 * disc) * wave;
  float halo = exp(-max(0., r - 1.) * 8.) * .42 * step(1., r) * (.7 + .5 * wave) + exp(-pow((r - .98) / .16, 2.)) * .2;
  float ring = (ripple(n, 1., t) + ripple(n, 2., t + 1.7) + ripple(n, 3., t + 3.1)) * disc;
  float k = body * disc + line * (.1 + .55 * fres) * (.55 + .9 * sweep) + fill * .22 + ring * .3 + rim * .7 + halo;
  // Soft at the hit rim, never a hard disc.
  vec3 hot = whiten(uColor, .55);
  vec3 col = mix(uColor, hot, clamp(rim * .8 + ring * .6 + line * fres * .4, 0., 1.));
  float lit = k * uLight * uEnv * uPower * (1. - smoothstep(1.5, 1.9, r));
  gl_FragColor = vec4(col * lit, clamp(lit * .9, 0., 1.));
}`,
}))

const MOTES = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 520000, region: REGION, instances: 36,
  particle: `
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float a = rnd(id, 1.), b = rnd(id, 2.), c = rnd(id, 3.), d = rnd(id, 4.);
  float period = 5. + 6. * a, phase = fract(uTime / period + b);
  float r = .46, y = r * (.9 - 1.95 * phase), across = sqrt(max(.06, 1. - (y / r) * (y / r)));
  float x = (c * 2. - 1.) * r * ${SHIELD_ASPECT.toFixed(3)} * .88 * across + sin(uTime * (.5 + d) + c * TAU) * r * .05;
  centre = vec2(x, y);
  rad = vec2(.005 + .007 * d);
  extra = vec4(phase, d, a, 0.);
}`,
  fragment: `
void main() {
  float d = length(vQ);
  if (d > 1.) discard;
  float twinkle = .55 + .45 * sin(uTime * (2.5 + 4. * vA.z) + vId * 1.9);
  float k = (exp(-d * d * 5.) * .55 + exp(-d * d * 30.)) * pow(sin(3.1416 * vA.x), .7) * twinkle * uEnv * min(1., uPower);
  gl_FragColor = vec4(mix(uColor, vec3(1.), exp(-d * d * 12.) * .7) * k, clamp(k, 0., 1.));
}`,
}))

export function paintShield(ctx: CanvasRenderingContext2D, frame: PresenceFrame): boolean {
  const state = shieldState(frame.cue, frame.time)
  if (state.light <= .003) return true
  return drawLayer(ctx, DOME(), frame, { uLight: state.light * state.power, uRadius: state.radius }) && drawLayer(ctx, MOTES(), frame)
}

export const shieldEffect = { paint: paintShield, layers: [DOME, MOTES] }
