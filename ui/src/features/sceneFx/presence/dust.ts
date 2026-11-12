import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// dust: a low bank of dust rolling along the ground of the cue (a haze thickest near y = .28) and motes that catch the
// light as they drift up through it, some soft and large (out of focus), some small and sharp. size scales both.

const REGION = [-.85, -.8, .85, .6] as const

const HAZE = lazyLayer(() => ({
  blend: 'over', composite: 'source-over', maxPixels: 360000, region: REGION, noise: true,
  fragment: `
void main() {
  vec2 p = vP, t = vec2(uTime * .1, 0.);
  float n = texture2D(uNoise, p * vec2(.55, 1.1) + vec2(uSeed * .13, 0.) - t).r;
  float m = texture2D(uNoise, p * vec2(1.3, 2.4) + vec2(.37, uSeed * .07) - t * 1.7).g;
  float bank = exp(-pow((p.y - .27 + (n - .5) * .22) / .17, 2.));
  float dens = smoothstep(.28, .8, n * .65 + m * .45) * bank;
  float across = ell(vec2(p.x, 0.), vec2(.8, 1.), .35) * (1. - smoothstep(.3, .6, p.y));
  float alpha = dens * across * .6 * uEnv * min(1.5, uPower);
  float lit = clamp(.5 + (texture2D(uNoise, p * vec2(.55, 1.1) + vec2(uSeed * .13, 0.) - t + vec2(0., .01)).r - n) * 14., 0., 1.);
  vec3 col = mix(uColor * .62, mix(uColor, vec3(1.), .3), lit);
  gl_FragColor = vec4(col * alpha, alpha);
}`,
}))

const MOTES = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 700000, region: REGION, instances: 150,
  particle: `
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float a = rnd(id, 1.), b = rnd(id, 2.), c = rnd(id, 3.), d = rnd(id, 4.);
  float life = fract(uTime * (.05 + .06 * a) + b);
  float x = (c - .5) * 1.25 + sin(uTime * (.4 + d) + id) * .03 + life * .05;
  float y = .34 - life * .5 - d * .06;
  // Mostly small and sharp, one in six large and soft.
  float big = step(.84, d);
  centre = vec2(x, y);
  float inside = 1. - smoothstep(.55, .85, length(vec2(x / .75, (y + .1) / .45)));
  rad = vec2((.0025 + .0035 * a + big * (.012 + .016 * b))) * step(.02, inside);
  extra = vec4(life, big, inside, a);
}`,
  fragment: `
void main() {
  float d = length(vQ);
  if (d > 1.) discard;
  float soft = vA.y;
  float shape = mix(exp(-d * d * 6.) + exp(-d * d * 30.) * .8, (1. - smoothstep(.5, 1., d)) * .35, soft);
  float twinkle = .6 + .4 * sin(uTime * (1.5 + 3. * vA.w) + vId * 2.1);
  float k = shape * sin(3.1416 * vA.x) * vA.z * twinkle * (soft > .5 ? .3 : 1.25) * uEnv * min(1.5, uPower);
  gl_FragColor = vec4(mix(uColor, vec3(1., .96, .86), .5) * k, clamp(k, 0., 1.));
}`,
}))

export const paintDust = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) =>
  drawLayer(ctx, HAZE(), frame) && drawLayer(ctx, MOTES(), frame)

export const dustEffect = { paint: paintDust, layers: [HAZE, MOTES] }
