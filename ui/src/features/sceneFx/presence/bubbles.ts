import { drawLayer, lazyLayer, type PresenceFrame } from './stage'

// bubbles: soap bubbles drifting up through the cue. Each one is nearly clear in the middle, its skin shows thin-film colour
// toward the rim, and two windows of light mirror in it. They wobble as they rise and thin out toward an ellipse (1.5 wide,
// 1 high in cue units), so the field has no edge. size scales the field and the bubbles with it.

const BUBBLES = lazyLayer(() => ({
  blend: 'over', composite: 'source-over', maxPixels: 700000, region: [-.9, -.62, .9, .62], instances: 34,
  particle: `
void particle(float id, out vec2 centre, out vec2 rad, out vec4 extra) {
  float a = rnd(id, 1.), b = rnd(id, 2.), c = rnd(id, 3.), d = rnd(id, 4.);
  float phase = fract(uTime * (.05 + .05 * b) + a);
  float x = (c - .5) * 1.5 + sin(uTime * (.5 + b) + id * 2.) * .035;
  float y = .5 - phase;
  float size = .014 + .03 * d * d;
  float win = 1. - smoothstep(.7, 1., length(vec2(x / .78, y / .5)));
  float wob = .06 * sin(uTime * (1.3 + b) + id);
  centre = vec2(x, y);
  rad = vec2(size * (1. + wob), size * (1. - wob)) * step(.01, win);
  extra = vec4(win * sin(3.1416 * phase) * .9 + win * .1, a, b, d);
}`,
  fragment: `
void main() {
  float r = length(vQ);
  if (r > 1.) discard;
  float skin = pow(r, 3.2);
  // Thin-film colour: a hue that turns with the distance from the middle and the bubble's own offset.
  vec3 film = .55 + .45 * cos(TAU * (r * 1.15 + vA.y + vec3(0., .33, .67)));
  vec3 tint = mix(uColor, film, .55);
  vec2 hi = vQ - vec2(-.38, -.42);
  float window = exp(-dot(hi * vec2(1.4, 2.6), hi * vec2(1.4, 2.6)) * 9.) * .95;
  vec2 lo = vQ - vec2(.42, .5);
  float bounce = exp(-dot(lo * vec2(2.2, 1.4), lo * vec2(2.2, 1.4)) * 14.) * .4;
  float edge = 1. - smoothstep(.93, 1., r);
  float alpha = (skin * .5 + .05 + window * .55 + bounce * .4) * edge * vA.x * uEnv * min(1.5, uPower);
  vec3 col = tint * (skin * .75 + .1) + vec3(1.) * (window + bounce * .7);
  gl_FragColor = vec4(col * edge * vA.x * uEnv * min(1.5, uPower), clamp(alpha, 0., 1.));
}`,
}))

export const paintBubbles = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => drawLayer(ctx, BUBBLES(), frame)

export const bubblesEffect = { paint: paintBubbles, layers: [BUBBLES] }
