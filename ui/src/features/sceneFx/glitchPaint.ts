import { fxRandom, type SceneFx } from './types'

/** Digital corruption in bursts: horizontal tears that move bands of the picture sideways with
 * their red and blue split apart, a slight RGB split of the whole frame, displaced and noisy
 * blocks, and green phosphor flashes and lines in the cue colour. Between bursts the picture is
 * left as it is.
 *
 * The tears and the split move the real pixels of the frame under the cue (exports paint over
 * it, the editor overlays copy the stage first). Where the pixels cannot be read, only the blocks,
 * lines and flashes are drawn. size is the height of the bands and blocks in % of the frame
 * height; intensity how often the bursts come and how strong they are; x, y and rotation are not
 * used. Pure function of (seed, time): the bursts sit inside the cue and the corruption changes
 * on a whole number of steps over it, so the frame at `end` is the frame at `start`. */
export const GLITCH_KIND = 'glitch'
/** During a burst the corruption changes this many times a second. */
export const GLITCH_STEP_RATE = 18

export type GlitchBurst = { start: number; end: number }
export type GlitchTear = { y: number; height: number; shift: number; split: number }
export type GlitchBlock = { x: number; y: number; width: number; height: number; fromX: number; fromY: number; noise: boolean }
export type GlitchFrame = { step: number; tears: GlitchTear[]; blocks: GlitchBlock[]; lines: number[]; flash: number }

const frac = (value: number) => value - Math.floor(value)

/** Successive random values from one seed. */
function sequence(seed: number) {
  let index = 0
  return () => fxRandom(seed, index++)
}

/** The bursts, in seconds from the start of the cue: about one every 1.8 s at intensity 1 and
 * more at higher intensity, each 0.16 to 0.5 s long, one in each equal slot of the cue. */
export function glitchBursts(cue: Pick<SceneFx, 'start' | 'end' | 'seed' | 'intensity'>): GlitchBurst[] {
  const span = Math.max(1e-6, cue.end - cue.start)
  const amount = Math.min(2, cue.intensity)
  const count = Math.max(1, Math.round(span * .55 * amount))
  const slot = span / count
  return Array.from({ length: count }, (_, index) => {
    const length = Math.min(slot * .85, .16 + .34 * fxRandom(cue.seed + 4441, index * 2) * Math.min(1.4, amount))
    const start = index * slot + fxRandom(cue.seed + 4441, index * 2 + 1) * (slot - length)
    return { start, end: start + length }
  })
}

/** What is corrupted at `time` (seconds from the start of the cue), or null between bursts. */
export function glitchFrame(cue: SceneFx, time: number, width: number, height: number): GlitchFrame | null {
  const span = Math.max(1e-6, cue.end - cue.start)
  // Wrapped first, so the frame at `end` is computed exactly as the frame at `start`.
  const loop = frac(time / span), at = loop * span
  if (!glitchBursts(cue).some(burst => at >= burst.start && at < burst.end)) return null
  const steps = Math.max(1, Math.round(span * GLITCH_STEP_RATE))
  const step = Math.floor(loop * steps) % steps
  const next = sequence(cue.seed * 977 + step * 7919 + 13)
  const amount = Math.min(2, cue.intensity)
  const band = Math.max(2, height * cue.size / 100)
  const tears: GlitchTear[] = []
  // Some steps split the whole frame a little; the tears then move bands of that split frame.
  if (next() < .55) tears.push({ y: 0, height, shift: 0, split: Math.max(1, Math.round(width * .0022 * amount * (1 + next()))) })
  const count = 1 + Math.floor(next() * (2 + 3 * amount))
  for (let index = 0; index < count; index++) {
    const tall = Math.max(1, Math.round(band * (.12 + 1.1 * next() ** 2)))
    const y = Math.min(height - tall, Math.floor(next() * height))
    const shift = Math.round((next() < .5 ? -1 : 1) * width * (.012 + .08 * next()) * amount)
    tears.push({ y: Math.max(0, y), height: Math.min(tall, height), shift, split: Math.round(width * (.002 + .008 * next()) * amount) })
  }
  const blocks: GlitchBlock[] = Array.from({ length: Math.floor(next() * (1 + 3.5 * amount)) }, () => {
    const blockWidth = Math.round(band * (1.5 + 4.5 * next())), blockHeight = Math.round(band * (.5 + 1.5 * next()))
    const x = Math.floor(next() * Math.max(1, width - blockWidth)), y = Math.floor(next() * Math.max(1, height - blockHeight))
    return { x, y, width: blockWidth, height: blockHeight, noise: next() < .45,
      fromX: Math.round(Math.max(0, Math.min(width - blockWidth, x + (next() - .5) * width * .3))),
      fromY: Math.round(Math.max(0, Math.min(height - blockHeight, y + (next() - .5) * height * .12))) }
  })
  const lines = Array.from({ length: Math.floor(next() * 3 * amount) }, () => Math.floor(next() * height))
  const flash = next() < .2 * amount ? .07 + .13 * next() : 0
  return { step, tears, blocks, lines, flash }
}

/** Moves `rows` rows of RGBA `pixels` (`width` wide) sideways by `shift`, with red taken `split`
 * pixels further left and blue `split` pixels further right; what leaves one side comes back on
 * the other. */
export function tearPixels(pixels: Uint8ClampedArray, width: number, rows: number, shift: number, split: number) {
  const copy = new Uint8ClampedArray(pixels)
  const column = (x: number) => (((x % width) + width) % width) * 4
  for (let y = 0; y < rows; y++) {
    const row = y * width * 4
    for (let x = 0; x < width; x++) {
      const i = row + x * 4, green = row + column(x - shift)
      pixels[i] = copy[row + column(x - shift - split)]
      pixels[i + 1] = copy[green + 1]
      pixels[i + 2] = copy[row + column(x - shift + split) + 2]
      pixels[i + 3] = copy[green + 3]
    }
  }
}

function tear(ctx: CanvasRenderingContext2D, tears: readonly GlitchTear[], width: number, height: number) {
  if (!tears.length || typeof ctx.getImageData !== 'function' || typeof ctx.putImageData !== 'function') return
  let image: ImageData
  try { image = ctx.getImageData(0, 0, width, height) } catch { return }
  if (!image?.data || image.data.length < width * height * 4) return
  for (const item of tears) tearPixels(image.data.subarray(item.y * width * 4, (item.y + item.height) * width * 4), width, item.height, item.shift, item.split)
  ctx.putImageData(image, 0, 0)
}

const hex = (value: number) => Math.round(Math.max(0, Math.min(255, value))).toString(16).padStart(2, '0')

export function paintGlitch(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, width: number, height: number) {
  const frame = glitchFrame(cue, time, width, height)
  if (!frame) return
  tear(ctx, frame.tears, width, height)
  const [r, g, b] = [1, 3, 5].map(offset => parseInt(cue.color.slice(offset, offset + 2), 16))
  const palette = ['#000000', cue.color, `#${hex(r * .35)}${hex(g * .35)}${hex(b * .35)}`, `#${hex(r + (255 - r) * .7)}${hex(g + (255 - g) * .7)}${hex(b + (255 - b) * .7)}`]
  ctx.save()
  for (const [index, block] of frame.blocks.entries()) {
    if (!block.noise) {
      // A block of the picture from somewhere else, as when a codec loses a reference.
      if (typeof ctx.drawImage === 'function' && ctx.canvas) ctx.drawImage(ctx.canvas, block.fromX, block.fromY, block.width, block.height, block.x, block.y, block.width, block.height)
      continue
    }
    const cell = Math.max(3, Math.round(block.height / 4))
    for (let y = 0; y < block.height; y += cell) {
      for (let x = 0; x < block.width; x += cell) {
        const pick = fxRandom(cue.seed + frame.step * 131 + index, x * 64 + y)
        ctx.globalAlpha = .55 + .4 * fxRandom(cue.seed + 17, x + y * 64 + index)
        ctx.fillStyle = palette[Math.floor(pick * palette.length)]
        ctx.fillRect(block.x + x, block.y + y, Math.min(cell, block.width - x), Math.min(cell, block.height - y))
      }
    }
  }
  ctx.globalCompositeOperation = 'screen'
  ctx.fillStyle = cue.color
  ctx.globalAlpha = .75
  for (const y of frame.lines) ctx.fillRect(0, y, width, Math.max(1, Math.round(height * .003)))
  if (frame.flash) { ctx.globalAlpha = frame.flash; ctx.fillRect(0, 0, width, height) }
  ctx.restore()
}
