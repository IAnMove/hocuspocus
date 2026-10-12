import { fxRandom, type SceneFx } from './types'

/** Digital code rain over the whole frame: columns of glyphs that fall forever. Each stream
 * has its own column, speed, trail length and phase; its head glyph is near-white and its
 * trail fades to the cue colour and then out. The glyph in each cell changes from time to time.
 *
 * The painter is a pure function of (seed, time) and repeats over the cue. Every stream makes
 * a whole number of trips and every cell makes a whole number of glyph changes between `start`
 * and `end`, so the frame at `end` is the frame at `start`. A plate rendered for the cue's
 * length loops with no seam.
 *
 * `size` is the glyph height in % of the frame height. `intensity` sets the density and the
 * brightness. The rain covers the whole frame and does not use x, y and rotation. */
export const CODE_RAIN_KIND = 'code_rain'
/** Half-width katakana, digits and some Latin capitals, as in the film. */
export const CODE_RAIN_GLYPHS = [...'ｦｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789ZTHEKMX:=*+<>']
/** For a browser with no font that has half-width katakana (it would draw empty boxes). */
export const CODE_RAIN_FALLBACK_GLYPHS = [...'0123456789ABCDEFHKMNRTXZ:=*+<>|']
/** Monospace CJK faces on Linux (Noto), Windows (MS Gothic) and macOS (Osaka, Hiragino). */
export const CODE_RAIN_FONT = '"Noto Sans Mono CJK JP", "Noto Sans CJK JP", "MS Gothic", "Osaka-Mono", "Hiragino Sans", "Droid Sans Fallback", monospace'
/** The most glyph changes in one cell per second. */
const CHANGES_PER_SECOND = 3
/** Cells near the head go from near-white to the cue colour in these mixes with white. */
const HEAD_MIX = [.85, .55, .25] as const

type Stream = { column: number; cycles: number; offset: number; trail: number; lead: number; travel: number }

let katakanaDrawn: boolean | undefined

/** True when the browser draws two different katakana glyphs. With no CJK font both are the
 * same empty box (or nothing), and the rain uses digits, Latin capitals and symbols. */
export function codeRainUsesKatakana(): boolean {
  if (katakanaDrawn === undefined) katakanaDrawn = probeKatakana()
  return katakanaDrawn
}

function probeKatakana(): boolean {
  const canvas = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(32, 32)
    : typeof document !== 'undefined' ? Object.assign(document.createElement('canvas'), { width: 32, height: 32 }) : null
  const ctx = canvas?.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null | undefined
  if (!ctx) return true
  const draw = (text: string) => {
    ctx.clearRect(0, 0, 32, 32); ctx.font = `24px ${CODE_RAIN_FONT}`; ctx.fillStyle = '#ffffff'
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, 16, 16)
    return ctx.getImageData(0, 0, 32, 32).data
  }
  try {
    const first = draw('ｱ'), second = draw('ﾈ')
    return first.some((value, index) => value !== second[index])
  } catch {
    return false
  }
}

const frac = (value: number) => value - Math.floor(value)

function mixWithWhite(color: string, amount: number): string {
  const channel = (offset: number) => {
    const value = parseInt(color.slice(offset, offset + 2), 16)
    return Math.round(value + (255 - value) * amount).toString(16).padStart(2, '0')
  }
  return `#${channel(1)}${channel(3)}${channel(5)}`
}

/** Whole trips over the cue: the speed is rounded so that the stream ends where it began. */
function streams(cue: SceneFx, span: number, columns: number, rows: number): Stream[] {
  const count = Math.max(1, Math.round(columns * 1.3 * cue.intensity))
  return Array.from({ length: count }, (_, index) => {
    const random = (slot: number) => fxRandom(cue.seed, index * 8 + slot)
    const trail = Math.max(4, Math.round(rows * (.2 + .6 * random(1))))
    // The cells above the frame before the head comes in: the pause between two drops.
    const lead = rows * (.05 + .9 * random(2))
    const travel = rows + trail + lead
    // Cells per second: a drop crosses the frame in 1 to 3.3 seconds.
    const speed = rows * (.3 + .7 * random(3))
    return { column: Math.floor(random(0) * columns), cycles: Math.max(1, Math.round(span * speed / travel)), offset: random(4), trail, lead, travel }
  })
}

/** The glyph of one cell at loop position `loop` and how bright it is (0.75 to 1). Some cells
 * keep their glyph; the others change a whole number of times over the cue. */
function cellGlyph(cue: SceneFx, glyphs: readonly string[], changes: number, cell: number, loop: number) {
  const hash = fxRandom(cue.seed + 7919, cell)
  const count = hash < .35 ? 0 : Math.max(1, Math.round(changes * (hash - .35) / .65))
  const tick = count ? Math.floor(loop * count + hash * 17) % count : 0
  const pick = fxRandom(Math.floor(hash * 1e9) + 1, tick)
  return { glyph: glyphs[Math.floor(pick * glyphs.length)], shade: .75 + .25 * frac(hash * 101) }
}

export function paintCodeRain(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, width: number, height: number) {
  const span = Math.max(1e-6, cue.end - cue.start)
  // Wrapped first, so the frame at `end` (loop 1) is computed exactly as the frame at `start`.
  const loop = frac(time / span)
  const glyphHeight = Math.max(4, height * cue.size / 100)
  const pitch = glyphHeight * .72, rowHeight = glyphHeight * 1.08
  const columns = Math.ceil(width / pitch), rows = Math.ceil(height / rowHeight)
  const glyphs = codeRainUsesKatakana() ? CODE_RAIN_GLYPHS : CODE_RAIN_FALLBACK_GLYPHS
  const changes = Math.round(span * CHANGES_PER_SECOND)
  const strength = Math.min(1, .45 + .55 * cue.intensity)
  const tones = HEAD_MIX.map(amount => mixWithWhite(cue.color, amount))
  const heads: Array<{ x: number; y: number; glyph: string }> = []
  ctx.save()
  ctx.font = `${Math.round(glyphHeight)}px ${CODE_RAIN_FONT}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  // Mirrored glyphs, as in the film: x is drawn at -x.
  ctx.scale(-1, 1)
  for (const stream of streams(cue, span, columns, rows)) {
    const head = Math.floor(frac(loop * stream.cycles + stream.offset) * stream.travel - stream.lead)
    const x = -(stream.column + .5) * pitch
    for (let step = 0; step < stream.trail && head - step >= 0; step++) {
      const row = head - step
      if (row >= rows) continue
      const { glyph, shade } = cellGlyph(cue, glyphs, changes, stream.column * 4096 + row, loop)
      const y = (row + .5) * rowHeight
      if (step === 0) { heads.push({ x, y, glyph }); continue }
      ctx.globalAlpha = strength * shade * (1 - step / stream.trail) ** 1.4
      ctx.fillStyle = tones[step] ?? cue.color
      ctx.fillText(glyph, x, y)
    }
  }
  ctx.globalAlpha = strength; ctx.fillStyle = tones[0]
  ctx.shadowColor = cue.color; ctx.shadowBlur = glyphHeight * .7 * strength
  for (const head of heads) ctx.fillText(head.glyph, head.x, head.y)
  ctx.restore()
}
