import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// anime_aura: heat rising round a figure. x/y the middle of the body, size the aura's height (about a body and a half of
// flame at 100). A hollow shell of fire follows the outline and leans into tongues above; sparks climb off it.

const BODY = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 520000, region: [-.95, -1.2, .95, .8],
  fragment: `
void main() {
  vec2 p = vP, e = (p - vec2(0., .02)) / vec2(.3, .47);
  float t = uTime, r = length(e);
  // Two octaves of noise scroll upward and bend each other: tongues, not blobs.
  vec2 q = vec2(p.x * 3.4, p.y * 2.2 + t * 1.5);
  float n1 = fbm(q + uSeed * 1.7);
  float n2 = fbm(q * 2. + vec2(n1 * 1.8, -t * .6) + 11.3);
  float flick = n1 * .6 + n2 * .4;
  float top = smoothstep(.3, -.5, p.y);
  float reach = 1.02 + (flick - .5) * 1.05 + top * .6;
  float inside = 1. - smoothstep(reach - .7, reach, r);
  float shell = smoothstep(.12, .9, r);
  float rim = exp(-pow((r - .9) / .24, 2.)) * inside;
  float core = inside * shell;
  float breath = .9 + .1 * sin(t * 2.1);
  // Sharper tongues ride the body of the glow, and the outer flame runs warmer than its root.
  float wisps = smoothstep(.4, .82, n2) * inside * smoothstep(.3, 1., r);
  float light = (core * .38 + rim * .5 + wisps * .5 + inside * .05) * breath;
  vec3 warm = uColor * vec3(1., .78, .52);
  vec3 col = mix(uColor, warm, smoothstep(.9, 1.5, r));
  col = mix(col, whiten(uColor, .35), clamp(rim * .7 + wisps * .35, 0., 1.));
  float edge = ell(p - vec2(0., -.15), vec2(.9, 1.02), .55);
  float k = light * edge * uEnv * uPower;
  gl_FragColor = vec4(col * k, clamp(k * .8, 0., 1.));
}`,
}))

const SPARKS = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 520000, region: [-.95, -1.2, .95, .8], instances: 64,
  particle: `
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float a = rnd(id, 1.), b = rnd(id, 2.), c = rnd(id, 3.), d = rnd(id, 4.);
  float period = 2. + 2.4 * a, life = fract(uTime / period + b);
  float angle = c * TAU;
  vec2 root = vec2(cos(angle) * .3 * (.7 + .3 * d), .12 + sin(angle) * .3 * (.7 + .3 * d));
  centre = root + vec2(sin(life * 7. + id) * .035 + (b - .5) * .1 * life, -life * (.45 + .5 * a));
  float size = (.007 + .013 * d) * (1. - life * .45) * smoothstep(0., .08, life);
  rad = vec2(size);
  extra = vec4(life, c, a, 0.);
}`,
  fragment: `
void main() {
  float life = vA.x, d = length(vQ);
  if (d > 1.) discard;
  float flicker = .6 + .4 * sin(uTime * (7. + 9. * vA.z) + vId * 2.3);
  float k = (exp(-d * d * 4.5) * .8 + exp(-d * d * 26.) * 1.6) * sin(3.1416 * life) * flicker * uEnv * uPower;
  vec3 col = mix(uColor, vec3(1.), exp(-d * d * 14.) * .8);
  gl_FragColor = vec4(col * k, clamp(k, 0., 1.));
}`,
}))

export const paintAura = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) =>
  drawLayer(ctx, BODY(), frame) && drawLayer(ctx, SPARKS(), frame)

export const auraEffect = { paint: paintAura, layers: [BODY, SPARKS] }
