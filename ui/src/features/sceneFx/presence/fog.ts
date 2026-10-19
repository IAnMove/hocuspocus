import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// fog: banks of mist that thicken toward the bottom of the frame and drift slowly. It fills the frame, not the cue's box:
// x, y, size and rotation do not apply, intensity is the density and the colour the mist. Three depths of warped noise
// slide at different speeds; each is lit from above, so a bank has a bright back and a shaded belly.

const MIST = lazyLayer(() => ({
  blend: 'over', composite: 'source-over', maxPixels: 230000, frame: true,
  fragment: `
float bank(vec2 uv, float asp, float depth, float t, out float lit) {
  float f = depth;
  vec2 q = vec2(uv.x * asp * (.62 + f * .42) + t * (.009 + .007 * f) + uSeed * 3.1 + f * 17., uv.y * (1.25 + f * .5));
  float w = fbm(q + vec2(0., t * .006 * (1. + f)));
  float n = fbm(q * 1.3 + w * 1.1 + f * 4.1);
  float up = fbm(q * 1.3 + w * 1.1 + f * 4.1 - vec2(0., .07));
  lit = clamp(.5 + (up - n) * 7., 0., 1.);
  float height = smoothstep(.4 - .1 * f, 1., uv.y);
  return smoothstep(.2 + .04 * f, .72, n) * (.1 + .9 * height);
}
void main() {
  vec2 uv = vP / uFrame;
  float asp = uFrame.x / uFrame.y, t = uTime;
  float alpha = 0., light = 0.;
  for (int i = 0; i < 3; i++) {
    float l, d = bank(uv, asp, float(i), t, l);
    float a = d * (.5 - .09 * float(i));
    light = mix(light, l, a / max(alpha + a, 1e-3));
    alpha = alpha + a * (1. - alpha);
  }
  alpha = min(.78, alpha * 1.3) * uEnv * min(1.6, uPower);
  vec3 shade = uColor * .55, high = mix(uColor, vec3(1.), .32);
  vec3 col = mix(shade, high, light);
  gl_FragColor = vec4(col * alpha, alpha);
}`,
}))

export const paintFog = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => drawLayer(ctx, MIST(), frame)
