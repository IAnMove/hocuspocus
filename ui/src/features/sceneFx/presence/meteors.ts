import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// meteor_shower: burning stones fall across the cue, each with a white-hot head and a tail of flame that thins out and
// flickers as it trails. intensity sets how many (ten at 1). Every stone repeats its fall every 1.67 s from its own place.

const MAX = 20

const METEORS = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 700000, region: [-1.1, -1., 1.1, 1.], instances: MAX,
  particle: `
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float p = fract(uTime * .6 + rnd(id, 1.));
  float x = rnd(id, 2.) * 1.5 - .75 + p * .35, y = p * 1.4 - .7;
  float length_ = .34 + .22 * rnd(id, 3.), width = .018 + .014 * rnd(id, 4.);
  turn = atan(1.4, .35);
  vec2 dir = vec2(cos(turn), sin(turn));
  // The quad's right end is the head: its centre sits half a length behind it.
  centre = vec2(x, y) - dir * (length_ * .5 - width * .8);
  rad = vec2(length_ * .5, width * 2.4) * step(id + .5, 10. * uPower);
  extra = vec4(sin(3.1416 * p), rnd(id, 5.), width / (width * 2.4), length_);
}`,
  fragment: `
void main() {
  float along = vQ.x * .5 + .5, across = vQ.y;
  float tail = pow(along, 2.4);
  float taper = mix(.1, 1., pow(along, .8));
  float flame = .55 + .9 * fbm(vec2(along * 5. - uTime * 7. + vA.y * 9., across * 2.5 + vId));
  float body = exp(-across * across / (taper * taper * .05)) * tail * flame;
  float head = exp(-(pow((vQ.x - .72) * 2.6, 2.) + across * across * 2.6) * 5.);
  float core = exp(-(pow((vQ.x - .74) * 4.5, 2.) + across * across * 5.) * 6.);
  float edge = smoothstep(0., .08, along) * (1. - smoothstep(.82, .98, along));
  float k = (body * .9 + head * .8) * edge * vA.x * uEnv;
  vec3 col = mix(uColor, vec3(1., .94, .8), clamp(core * 1.4 + head * .3, 0., 1.));
  gl_FragColor = vec4(col * (k + core * .8 * vA.x * uEnv), clamp(k + core * vA.x * uEnv, 0., 1.));
}`,
}))

export const paintMeteors = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => drawLayer(ctx, METEORS(), frame)
