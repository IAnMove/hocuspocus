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

/** Slots that cycle: stars twinkle, windows switch on and off, fireflies pulse. */
function writeCycling(bytes: Uint8Array, palette: PixelPalette, seconds: number) {
  for (let star = 0; star < INDEX.starSteps; star++) {
    const twinkle = .3 + .7 * (.5 + .5 * Math.sin(seconds * 1.9 + star * 2.1))
    writeColor(bytes, INDEX.star + star, mixHex(palette.sky[0], palette.stars, twinkle))
  }
  for (let slot = 0; slot < INDEX.windowSteps; slot++) {
    // Most rooms stay lit; each slot goes dark for a while on its own clock.
    const lit = Math.sin(seconds * (.21 + slot * .037) + slot * 1.7) > -.55
    const flicker = slot === 7 ? .75 + .25 * Math.sin(seconds * 23) : 1
    writeColor(bytes, INDEX.window + slot, lit ? mixHex(palette.near[0], palette.windows, flicker) : mixHex(palette.near[0], palette.windows, .12))
  }
  for (let band = 0; band < INDEX.bandSteps; band++) {
    // Cloud bands trade tones slowly, so the planet's weather drifts.
    const drift = .5 + .5 * Math.sin(seconds * .55 + band * Math.PI / 2)
    writeColor(bytes, INDEX.band + band, mixHex(palette.moon, palette.far[1], drift * .65))
  }
  for (let fly = 0; fly < INDEX.fireflySteps; fly++) {
    const glow = Math.pow(Math.max(0, Math.sin(seconds * (1.4 + fly * .23) + fly * 1.9)), 3)
    writeColor(bytes, INDEX.firefly + fly, mixHex(palette.trees, palette.windows, glow))
  }
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
