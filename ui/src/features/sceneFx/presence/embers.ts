import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// embers: sparks rising from the bottom of the cue (a brazier, a candle, a pyre). Each starts near white, takes the cue colour
// and cools to a dull red glow as it climbs, flickers, and stretches along its path by its speed. intensity sets how many.

const EMBERS = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 700000, region: [-.9, -.95, .9, .75], instances: 120,
  particle: `
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float a = rnd(id, 1.), b = rnd(id, 2.), c = rnd(id, 3.), d = rnd(id, 4.), e = rnd(id, 5.), f = rnd(id, 6.), g = rnd(id, 7.);
  float period = 2.4 + 2.6 * a, life = fract((uTime + b * period) / period);
  float start = (c - .5) * 1.2 * (.35 + .65 * d), drift = (e - .5) * .25;
  float rise = .75 + .4 * f;
  float x = start + drift * life + sin(life * TAU * (.5 + .9 * g) + f * TAU) * .05 * (.25 + life);
  float y = .5 - life * rise;
  float speed = rise * (1. + .5 * cos(life * TAU * (.5 + .9 * g) + f * TAU)) / period;
  float size = .0022 + .0056 * d * d + .003 * step(.92, d);
  // The spark: a little glow, drawn longer along its way the faster it goes.
  rad = vec2(size * 3.6, size * 3.6 * (1. + .9 * speed)) * step(g * 1.25, uPower);
  centre = vec2(x, y);
  extra = vec4(life, a, 1. - smoothstep(.7, 1., length(vec2(x / .78, (y + .1) / .62))), g);
}`,
  fragment: `
void main() {
  float life = vA.x;
  float d = length(vQ * vec2(1., .55));
  float flicker = .55 + .45 * sin(uTime * (8. + 14. * vA.y) + vId * 2.1);
  float k = (exp(-d * d * 6.) * .6 + exp(-d * d * 34.) * 1.9) * pow(sin(3.1416 * life), .5) * flicker * vA.z * uEnv;
  vec3 hot = vec3(1., .93, .78), cool = uColor * .42;
  vec3 tone = life < .3 ? mix(hot, uColor, life / .3) : mix(uColor, cool, (life - .3) / .7);
  gl_FragColor = vec4(mix(tone, vec3(1., .95, .85), exp(-d * d * 30.) * .5) * k, clamp(k, 0., 1.));
}`,
}))

export const paintEmbers = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => drawLayer(ctx, EMBERS(), frame)
