import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// stars: a night sky over the cue: faint clouds of nebula and stars of every brightness, each twinkling at its own pace,
// the brightest with a soft glint. The field thins out toward an ellipse (1.5 wide, 1 high in cue units) so it has no edge.
// size scales the field; the stars drift slowly sideways, nearer ones faster.

const REGION = [-.9, -.62, .9, .62] as const
const WINDOW = 'float fieldWindow(vec2 p) { return 1. - smoothstep(.7, 1., length(p / vec2(.78, .5))); }'

const NEBULA = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 300000, region: REGION, noise: true,
  fragment: `
${WINDOW}
void main() {
  vec2 p = vP;
  float n = texture2D(uNoise, p * .9 + vec2(uSeed * .11, uTime * .002)).r;
  float m = texture2D(uNoise, p * 2.1 + vec2(.3, uSeed * .05) + n * .35).g;
  float cloud = smoothstep(.42, .88, n * .6 + m * .55) * fieldWindow(p);
  float tint = texture2D(uNoise, p * .6 + .5).b;
  vec3 col = mix(uColor * vec3(.55, .7, 1.1), uColor * vec3(1., .72, .85), tint);
  float k = cloud * .1 * uEnv * min(1.5, uPower);
  gl_FragColor = vec4(col * k, clamp(k, 0., 1.));
}`,
}))

const STARS = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 900000, region: REGION, instances: 380,
  particle: `
${WINDOW}
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float a = rnd(id, 1.), b = rnd(id, 2.), c = rnd(id, 3.), d = rnd(id, 4.), e = rnd(id, 5.);
  float depth = .3 + .7 * e;
  float x = (a - .5) * 1.56 + uTime * .004 * depth;
  x = (fract(x / 1.56 + .5) - .5) * 1.56;
  float y = (b - .5) * 1.04;
  // Magnitude: many faint, few bright.
  float mag = pow(c, 2.6);
  centre = vec2(x, y);
  float big = step(.93, c);
  float size = .0016 + .0042 * mag + .006 * step(.985, c);
  rad = vec2(size * (1. + 3.4 * big)) * step(.01, fieldWindow(vec2(x, y)));
  extra = vec4(mag, d, fieldWindow(vec2(x, y)), big);
}`,
  fragment: `
void main() {
  float mag = vA.x, temp = vA.y, win = vA.z, glint = vA.w;
  float d = length(vQ);
  float twinkle = .62 + .38 * sin(uTime * (1.6 + 4. * temp) + vId * 3.7);
  float core = exp(-d * d * 55.), halo = exp(-d * d * 6.) * .3;
  float spikes = (exp(-abs(vQ.x) * 34. - abs(vQ.y) * 4.) + exp(-abs(vQ.y) * 34. - abs(vQ.x) * 4.)) * glint * .55;
  float k = (core * 1.3 + halo * (.3 + mag) + spikes) * (.5 + .6 * mag) * twinkle * win * uEnv * min(1.5, uPower);
  vec3 tone = mix(vec3(.72, .82, 1.), vec3(1., .88, .66), temp);
  vec3 col = mix(tone, uColor, .4);
  gl_FragColor = vec4(mix(col, vec3(1.), core * .6) * k, clamp(k, 0., 1.));
}`,
}))

export const paintStars = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) =>
  drawLayer(ctx, NEBULA(), frame) && drawLayer(ctx, STARS(), frame)
