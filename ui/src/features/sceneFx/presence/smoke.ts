import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// smoke: a column of smoke from x/y; size its height. Puffs rise, swell, turn and thin out on a slow wind. Each puff is a
// height field of noise lit from above-left (a lit top, a shaded underside), so it reads as a billow and not as a blot.

const SMOKE = lazyLayer(() => ({
  blend: 'over', composite: 'source-over', maxPixels: 460000, region: [-.8, -1., .8, .65], instances: 44, noise: true,
  particle: `
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float a = rnd(id, 1.), b = rnd(id, 2.), c = rnd(id, 3.), d = rnd(id, 4.), e = rnd(id, 5.);
  float life = fract(uTime * (.15 + .06 * a) + b);
  float x = (c - .5) * .1 + sin(life * 4.2 + d * TAU) * .05 * (.3 + life) + sin(life * 9. + id) * .012 + life * life * .2;
  float radius = (.04 + life * .2) * (.75 + .5 * e);
  centre = vec2(x, .32 - life * .82);
  rad = vec2(radius * 1.3);
  extra = vec4(life, d * TAU + uTime * (a - .5) * .5, e, a);
}`,
  fragment: `
void main() {
  float life = vA.x, ang = vA.y;
  vec2 q = mat2(cos(ang), sin(ang), -sin(ang), cos(ang)) * vQ;
  float r = length(vQ) / .77;
  vec2 uv = q * .3 + .5 + vec2(vA.z * 7.3, vId * .137);
  float h = texture2D(uNoise, uv).r, h2 = texture2D(uNoise, uv * 2.3 + .4).g;
  float lump = h * .65 + h2 * .35;
  float body = 1. - smoothstep(.1, 1., r + (lump - .5) * .95);
  float e = .012;
  vec2 grad = vec2(texture2D(uNoise, uv + vec2(e, 0.)).r - texture2D(uNoise, uv - vec2(e, 0.)).r,
                   texture2D(uNoise, uv + vec2(0., e)).r - texture2D(uNoise, uv - vec2(0., e)).r) / (2. * e);
  // The puff's normal: a dome (more tilted toward its edge) bent by the noise's slope; the light comes from above-left.
  vec3 nrm = normalize(vec3(vQ.x * .55 - grad.x * .12, vQ.y * .55 - grad.y * .12, .75));
  float diff = clamp(dot(nrm, normalize(vec3(-.45, -.7, .55))), 0., 1.);
  float alpha = body * pow(sin(3.1416 * life), 1.1) * .62 * uEnv * min(1.5, uPower);
  vec3 col = mix(uColor * .22, mix(uColor, vec3(1.), .28), smoothstep(.1, .85, diff));
  gl_FragColor = vec4(col * alpha, alpha);
}`,
}))

export const paintSmoke = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => drawLayer(ctx, SMOKE(), frame)
