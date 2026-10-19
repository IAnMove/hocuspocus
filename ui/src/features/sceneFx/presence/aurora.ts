import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// aurora: curtains of light hanging in the sky of the cue: a bright lower edge that waves, vertical rays above it that
// flicker and fade upward from the colour of the cue to violet. The curtains thin out toward both ends and the top.

const CURTAINS = lazyLayer(() => ({
  blend: 'add', composite: 'lighter', maxPixels: 460000, region: [-.95, -.62, .95, .55],
  fragment: `
float curtain(vec2 p, float t, float shift, float seed, out float up) {
  float base = sin(p.x * 3.1 + t * .33 + shift) * .12 + sin(p.x * 6.4 - t * .5 + shift * 1.7) * .045 + shift * .04 - .02;
  float h = base - p.y;
  up = h;
  float rays = fbm(vec2(p.x * 13. + sin(t * .2 + p.x * 2.) * .9 + seed, t * .08 + h * .7));
  float fine = fbm(vec2(p.x * 31. - t * .17 + seed * 2., h * 1.1 + 3.));
  float edge = smoothstep(-.012, .018, h);
  float reach = exp(-max(h, 0.) * 2.4);
  float lip = exp(-pow((h - .02) / .09, 2.)) * .22;
  return edge * reach * (.3 + rays * 1.15) * (.45 + .55 * fine) + lip * (.6 + rays) * edge;
}
void main() {
  vec2 p = vP;
  float u1, u2;
  float c1 = curtain(p, uTime, 0., uSeed * .7, u1), c2 = curtain(p * vec2(1., 1.), uTime * .8, 1.9, uSeed * 1.3 + 5., u2) * .6;
  float ends = 1. - smoothstep(.5, .92, abs(p.x));
  float top = 1. - smoothstep(.15, .5, max(u1, u2));
  vec3 high = uColor * vec3(.85, .45, 1.15);
  vec3 col1 = mix(uColor, high, smoothstep(.02, .38, u1)), col2 = mix(uColor * vec3(.7, 1., .9), high, smoothstep(.02, .38, u2));
  vec3 col = (col1 * c1 + col2 * c2) / max(c1 + c2, 1e-3);
  float k = (c1 + c2) * ends * mix(1., top, .6) * .7 * uEnv * min(1.5, uPower);
  gl_FragColor = vec4(col * k, clamp(k, 0., 1.));
}`,
}))

export const paintAurora = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => drawLayer(ctx, CURTAINS(), frame)
