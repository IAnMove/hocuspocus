import { Vector4 } from 'three'
import { fxRandom } from '../../sceneFx/types'
import { hexRgb, type PixelPalette } from './pixelPalettes'
import { INDEX } from './pixelPaint'
import type { MeteorDirection } from './pixelScene'

const METEOR_LIFE = 1.3

function writeColor(bytes: Uint8Array, index: number, hex: string) {
  const [r, g, b] = hexRgb(hex)
  bytes.set([Math.round(r * 255), Math.round(g * 255), Math.round(b * 255), 255], index * 4)
}

export function mixHex(a: string, b: string, t: number) {
  const x = hexRgb(a), y = hexRgb(b)
  return '#' + x.map((v, i) => Math.round((v + (y[i] - v) * Math.max(0, Math.min(1, t))) * 255).toString(16).padStart(2, '0')).join('')
}

/** The year runs over 24 s: spring, summer, autumn and winter, 6 s each. */
export const YEAR_SECONDS = 24
const LEAVES: [string, string, string][] = [
  ['#4a8a3a', '#8ac860', '#f0a8c8'], ['#1e5a2a', '#3a8a3a', '#7ac050'],
  ['#8a2a14', '#d8641e', '#f4b040'], ['#8a98b0', '#c8d4e4', '#f4f8ff'],
]

/** Foliage for `seconds` into the year: each season holds, then turns. */
function leafAt(seconds: number, k: number) {
  const phase = ((seconds % YEAR_SECONDS) + YEAR_SECONDS) % YEAR_SECONDS / (YEAR_SECONDS / 4)
  const season = Math.floor(phase), turn = Math.max(0, (phase - season - .55) / .45)
  return mixHex(LEAVES[season][k], LEAVES[(season + 1) % 4][k], turn)
}

/** How deep the snow lies: it falls through winter and melts in early spring. */
export function snowCover(seconds: number) {
  const t = ((seconds % YEAR_SECONDS) + YEAR_SECONDS) % YEAR_SECONDS, winter = YEAR_SECONDS * .75
  if (t < 2) return 1 - t / 2
  return Math.max(0, Math.min(1, (t - winter + 1) / 5))
}

/** Glass hues: ruby, sapphire, emerald, gold, amethyst, amber. */
export const GLASS = ['#d82a3a', '#2a5ad8', '#2aa860', '#f0c030', '#9a3ad0', '#f07a20']

/** Letter `k` of a five-letter sign at `t` in a 6 s cycle: letters come on
 *  one by one, the word holds, flashes twice, then goes dark. */
function spelled(t: number, k: number) {
  const c = ((t % 6) + 6) % 6
  if (c < 3) return c >= k * .5
  if (c < 4.6) return true
  return c < 5.4 && Math.floor((c - 4.6) / .2) % 2 === 0
}

type Cycler = { start: number; steps: number; color: (palette: PixelPalette, seconds: number, k: number) => string }
const pulse = (k: number, steps: number, seconds: number, speed: number) => ((k / steps - seconds * speed) % 1 + 1) % 1

/** Slots that cycle, each range with its own rule. The world is painted
 *  once; only these colours change from frame to frame. */
const CYCLERS: Cycler[] = [
  // Stars twinkle.
  { start: INDEX.star, steps: INDEX.starSteps, color: (p, t, k) => mixHex(p.sky[0], p.stars, .3 + .7 * (.5 + .5 * Math.sin(t * 1.9 + k * 2.1))) },
  // Most rooms stay lit; each slot goes dark for a while on its own clock, one flickers.
  { start: INDEX.window, steps: INDEX.windowSteps, color: (p, t, k) => Math.sin(t * (.21 + k * .037) + k * 1.7) > -.55
    ? mixHex(p.near[0], p.windows, k === 7 ? .75 + .25 * Math.sin(t * 23) : 1) : mixHex(p.near[0], p.windows, .12) },
  // A planet's cloud bands trade tones slowly, so its weather drifts.
  { start: INDEX.band, steps: INDEX.bandSteps, color: (p, t, k) => mixHex(p.moon, p.far[1], (.5 + .5 * Math.sin(t * .55 + k * Math.PI / 2)) * .65) },
  // Sunlight through moving water: each slot brightens and dims in turn.
  { start: INDEX.ray, steps: INDEX.raySteps, color: (p, t, k) => mixHex(p.sky[1], p.moon, .25 + (.5 + .5 * Math.sin(t * 2.4 - k * Math.PI / 4)) * .5) },
  // Marquee chase: every fourth bulb is lit and the lit ones march round.
  { start: INDEX.bulb, steps: INDEX.bulbSteps, color: (p, t, k) => {
    const hue = k % 2 ? p.windows : '#ff5a8a'
    return (k - Math.floor(t * 6)) % 4 === 0 ? mixHex(hue, '#ffffff', .25) : mixHex(p.near[0], hue, .35)
  } },
  // The bright slot walks down the water column, so streaks pour downward.
  { start: INDEX.fall, steps: INDEX.fallSteps, color: (p, t, k) => mixHex(mixHex(p.water, p.far[1], .4), mixHex(p.sky[2], '#ffffff', .55), Math.pow(1 - pulse(k, INDEX.fallSteps, t, 1.8), 1.5)) },
  // Nebula gas breathes slowly, its brighter folds most of all.
  { start: INDEX.nebula, steps: 4, color: (p, t, k) => mixHex(p.sky[1], p.aurora, (.25 + k * .22) * (.85 + .15 * Math.sin(t * .6 + k * .9))) },
  // Now and then a driver touches the brake.
  { start: INDEX.tail, steps: 2, color: (_p, t, k) => Math.sin(t * (.7 + k * .3) + k * 2) > .92 ? '#ff4a52' : '#9a1420' },
  // A bright pulse walks down the lava slots, so the rivers run downhill.
  { start: INDEX.lava, steps: INDEX.lavaSteps, color: (_p, t, k) => {
    const heat = Math.pow(1 - pulse(k, INDEX.lavaSteps, t, .9), 2)
    return heat > .5 ? mixHex('#ff4a0c', '#ffd878', (heat - .5) * 2) : mixHex('#5c0a04', '#ff4a0c', heat * 2)
  } },
  // Neon tubes: steady, but each buzzes off for an instant now and then.
  { start: INDEX.neon, steps: 4, color: (p, t, k) => {
    const tube = ['#ff3aa0', '#3ae8ff', '#b4ff3a', '#ff8a3a'][k]
    const buzz = Math.sin(t * (13 + k * 7)) * Math.sin(t * (.9 + k * .4) + k) > .82
    return buzz ? mixHex(p.near[0], tube, .25) : mixHex(tube, '#ffffff', .15)
  } },
  // Waves roll in: a bright crest walks from the water's edge toward the viewer,
  // glowing with the tide's bioluminescence as it breaks.
  { start: INDEX.wave, steps: INDEX.waveSteps, color: (p, t, k) => {
    const crest = Math.pow(1 - pulse(k, INDEX.waveSteps, t, .35), 3)
    return mixHex(mixHex(p.water, p.near[0], .3), mixHex('#5affea', '#ffffff', crest * .3), crest)
  } },
  // Paper lanterns: warm, each slot flickering on its own clock.
  { start: INDEX.flame, steps: INDEX.flameSteps, color: (p, t, k) => {
    const flicker = .75 + .25 * Math.sin(t * (7 + k * 2.3) + k) * Math.sin(t * (2.1 + k) + k * 3)
    return mixHex(mixHex('#c8401a', '#ffb04a', flicker), p.light.color, .12)
  } },
  // Raindrops slide down the glass: a bright bead walks down each trail.
  { start: INDEX.drop, steps: INDEX.dropSteps, color: (p, t, k) => mixHex(mixHex(p.sky[1], p.windows, .15), '#e8f0ff', Math.pow(1 - pulse(k, INDEX.dropSteps, t, -.7), 4) * .8) },
  // Foliage turns with the seasons.
  { start: INDEX.leaf, steps: 3, color: (p, t, k) => mixHex(leafAt(t, k), p.light.color, .12) },
  // Snow piles up level by level as winter deepens, on the far range and the hills.
  { start: INDEX.snowFar, steps: 4, color: (p, t, k) => snowCover(t) > (k + .5) / 4 ? mixHex('#f4f8ff', p.light.color, .2) : p.far[0] },
  { start: INDEX.snowNear, steps: 4, color: (p, t, k) => snowCover(t) > (k + .5) / 4 ? mixHex('#f4f8ff', p.light.color, .2) : p.near[0] },
  // Stained glass: each hue glows brighter in turn as the sun moves round.
  { start: INDEX.glass, steps: INDEX.glassSteps, color: (_p, t, k) => mixHex(mixHex(GLASS[k], '#000000', .45), mixHex(GLASS[k], '#ffffff', .2), .5 + .5 * Math.sin(t * .5 - k * 1.05)) },
  // The grid pulses to a 120 BPM beat: a flash on each beat that decays.
  { start: INDEX.grid, steps: 2, color: (p, t, k) => mixHex(mixHex(p.trees, p.aurora, .4), mixHex(p.far[1], '#ffffff', .25), (.55 + .45 * Math.exp(-((t * 2) % 1) * 5)) * (k ? .5 : 1)) },
  // Crystals: a wave of light walks across them, cyan into violet.
  { start: INDEX.crystal, steps: INDEX.crystalSteps, color: (p, t, k) => {
    const glow = Math.pow(1 - pulse(k, INDEX.crystalSteps, t, .22), 3)
    return mixHex(mixHex(p.far[0], '#3a2a8a', .5), mixHex('#7af0ff', '#e8b0ff', .5 + .5 * Math.sin(t * .3 + k)), .25 + glow * .75)
  } },
  // Painted swirls: a light band travels round every spiral, so they turn.
  { start: INDEX.swirl, steps: 8, color: (p, t, k) => mixHex(mixHex(p.sky[0], p.far[1], .55), mixHex(p.moon, p.aurora, .4), Math.pow(1 - pulse(k, 8, t, .45), 2)) },
  // Star halos pulse outward ring by ring.
  { start: INDEX.halo, steps: 3, color: (p, t, k) => mixHex(p.sky[1], p.moon, (.7 - k * .22) * (.7 + .3 * Math.sin(t * 2 - k))) },
  // A neon sign spells itself out letter by letter, flashes, then starts over;
  // the VACANCY line buzzes on and off.
  { start: INDEX.sign, steps: 6, color: (p, t, k) => {
    const lit = k === 5 ? Math.sin(t * 17) * Math.sin(t * 1.3) < .55 : spelled(t, k)
    const tube = k === 5 ? '#6affb4' : '#ff4a8a'
    return lit ? mixHex(tube, '#ffffff', .2) : mixHex(p.trees, tube, .18)
  } },
  // Fireflies pulse on and off.
  { start: INDEX.firefly, steps: INDEX.fireflySteps, color: (p, t, k) => mixHex(p.trees, p.windows, Math.pow(Math.max(0, Math.sin(t * (1.4 + k * .23) + k * 1.9)), 3)) },
]

function writeCycling(bytes: Uint8Array, palette: PixelPalette, seconds: number) {
  for (const cycler of CYCLERS) for (let k = 0; k < cycler.steps; k++) writeColor(bytes, cycler.start + k, cycler.color(palette, seconds, k))
  // A candle-lit room: warm wall, lit wall, wood, curtain; tinted by the night outside.
  ;['#2a1a1c', '#6a3a26', '#3a2218', '#5a1e2a', '#3a6a3c', '#e8d8b8'].forEach((tone, i) => writeColor(bytes, INDEX.room + i, mixHex(tone, palette.near[0], .15)))
  writeColor(bytes, INDEX.fallWater, mixHex(mixHex(palette.water, palette.far[1], .4), mixHex(palette.sky[2], '#ffffff', .55), .45))
  ;['#e8384a', '#f5c542', '#f07ab0', '#8a5ad8'].forEach((bloom, row) => writeColor(bytes, INDEX.tulip + row, mixHex(bloom, palette.light.color, .2)))
  // A swimming pool: deep to shallow blue, and the stone coping.
  ;['#0c4f86', '#1780b8', '#34b0da', '#8ae2f2', '#f0e8d6'].forEach((tone, step) => writeColor(bytes, INDEX.pool + step, mixHex(tone, palette.light.color, .16)))
  // Ripe wheat, shadowed stalks to sunlit ears, lit by the hour.
  ;['#5a3e18', '#a87a2a', '#dcaa46', '#f6dc8a'].forEach((tone, step) => writeColor(bytes, INDEX.wheat + step, mixHex(mixHex(tone, palette.near[0], .25 - step * .06), palette.light.color, .22)))
  ;['#ff6a6a', '#ffb45a', '#fff27a', '#7aff9a', '#7ab4ff'].forEach((hue, band) => writeColor(bytes, INDEX.rainbow + band, mixHex(palette.far[0], hue, .55)))
}

/** Every palette slot for this moment: the mood plus the cycling ranges. */
export function writePalette(bytes: Uint8Array, palette: PixelPalette, seconds: number) {
  for (let step = 0; step < INDEX.skySteps; step++) {
    const t = step / (INDEX.skySteps - 1)
    writeColor(bytes, INDEX.sky + step, t < .55 ? mixHex(palette.sky[0], palette.sky[1], t / .55) : mixHex(palette.sky[1], palette.sky[2], (t - .55) / .45))
  }
  writeColor(bytes, INDEX.moon, palette.moon)
  writeColor(bytes, INDEX.moonShade, mixHex(palette.moon, palette.sky[1], .28))
  writeColor(bytes, INDEX.moonDark, mixHex(palette.moon, palette.sky[1], .72))
  writeColor(bytes, INDEX.haloInner, mixHex(palette.sky[1], palette.moon, .42))
  writeColor(bytes, INDEX.haloOuter, mixHex(palette.sky[1], palette.moon, .18))
  writeColor(bytes, INDEX.far, palette.far[0]); writeColor(bytes, INDEX.farRim, palette.far[1])
  writeColor(bytes, INDEX.farShade, mixHex(palette.far[0], palette.sky[0], .45))
  writeColor(bytes, INDEX.near, palette.near[0]); writeColor(bytes, INDEX.nearRim, palette.near[1])
  writeColor(bytes, INDEX.trees, palette.trees)
  for (let step = 0; step < INDEX.sandSteps; step++) {
    const t = step / (INDEX.sandSteps - 1)
    writeColor(bytes, INDEX.sand + step, t < .6 ? mixHex(mixHex(palette.sky[2], palette.water, .45), palette.water, t / .6) : mixHex(palette.water, palette.near[0], (t - .6) * .6))
  }
  writeColor(bytes, INDEX.lamp, palette.windows)
  // A pond: lily green and a lotus, shallow and deep water from the mood.
  ;['#2e6a34', '#5aa04a', '#f4a0c8'].forEach((green, i) => writeColor(bytes, INDEX.pad + i, mixHex(green, palette.light.color, .15)))
  writeColor(bytes, INDEX.pond, mixHex(palette.water, palette.far[1], .25))
  writeColor(bytes, INDEX.pond + 1, mixHex(palette.water, palette.trees, .35))
  // The new moon: the sky's own blue by day, a black disc against the corona.
  // It hangs where the sky gradient reaches its middle tone.
  writeColor(bytes, INDEX.umbra, palette.sky[1])
  // Balloon cloth keeps its colours in any mood, warmed by the light.
  ;['#d8402e', '#f2b33c', '#2e9aa0', '#f4ead2'].forEach((cloth, i) => writeColor(bytes, INDEX.balloon + i, mixHex(cloth, palette.light.color, .18)))
  writeColor(bytes, INDEX.balloon + 4, mixHex('#fff4dc', palette.light.color, .3))
  // Blossom keeps its pink in any mood, drawn slightly towards the land's light.
  writeColor(bytes, INDEX.blossom, mixHex('#f4a2c6', palette.near[1], .22))
  writeColor(bytes, INDEX.blossom + 1, mixHex('#ffd8e8', palette.moon, .2))
  writeColor(bytes, INDEX.blossom + 2, mixHex('#b05a86', palette.near[0], .35))
  writeColor(bytes, INDEX.ring, mixHex(palette.moon, palette.stars, .35))
  writeColor(bytes, INDEX.ringShade, mixHex(palette.moon, palette.sky[1], .6))
  writeCycling(bytes, palette, seconds)
}

function heading(direction: MeteorDirection, left: boolean, fall: number) {
  const toLeft = direction === 'left' || (direction === 'both' && left)
  return toLeft ? Math.PI - fall : fall
}

/** Shooting stars on a seeded schedule: [x, y, heading, age 0..1] in sky
 *  texels, y counted down from the top of the sky. */
export function meteorsAt(seconds: number, rate: number, sky: [number, number], seed = 5, direction: MeteorDirection = 'both'): Vector4[] {
  const out = [new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0)]
  if (rate <= 0) return out
  const mean = 7 / rate
  let at = fxRandom(seed, 0) * mean * .5, slot = 0
  for (let k = 0; at <= seconds && k < 4000; k++) {
    const age = (seconds - at) / METEOR_LIFE
    if (age >= 0 && age < 1 && slot < 3) {
      const angle = heading(direction, fxRandom(seed, k * 5 + 1) > .5, .25 + fxRandom(seed, k * 5 + 2) * .45)
      const travel = age * METEOR_LIFE * (150 + fxRandom(seed, k * 5 + 3) * 90)
      const x0 = sky[0] * (.12 + fxRandom(seed, k * 5 + 4) * .76)
      const y0 = sky[1] * (.06 + fxRandom(seed, k * 5 + 5) * .34)
      out[slot++].set(x0 + Math.cos(angle) * travel, y0 + Math.sin(angle) * travel, angle, Math.max(.001, age))
    }
    at += mean * (.35 + fxRandom(seed, k + 9000) * 1.3)
  }
  return out
}

const BURST_LIFE = 1.9
const BURST_COLORS = ['#ff5a6a', '#ffd25a', '#6affd0', '#b48aff', '#ff9ae0', '#8ad4ff']

/** Fireworks on a seeded schedule: [x, y, age 0..1, seed] in sky texels
 *  (y down from the top) and a colour each. Negative time means none. */
export function fireworksAt(seconds: number, sky: [number, number], seed = 3) {
  const out = [0, 1, 2, 3].map(() => ({ at: new Vector4(0, 0, 0, 0), color: '#ffffff' }))
  if (seconds < 0) return out
  let at = .3, slot = 0
  for (let k = 0; at <= seconds && k < 4000; k++) {
    const age = (seconds - at) / BURST_LIFE
    if (age >= 0 && age < 1 && slot < 4) {
      out[slot].at.set(sky[0] * (.3 + fxRandom(seed, k * 3) * .4), sky[1] * (.4 + fxRandom(seed, k * 3 + 1) * .2), Math.max(.001, age), fxRandom(seed, k * 3 + 2) * 100)
      out[slot++].color = BURST_COLORS[Math.floor(fxRandom(seed, k + 500) * BURST_COLORS.length)]
    }
    at += .3 + fxRandom(seed, k + 900) * .8
  }
  return out
}
