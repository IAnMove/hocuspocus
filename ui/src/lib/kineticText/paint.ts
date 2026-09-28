import { INK_TRAP_PAPER, reserveBlackPlate, type InkTrapPaint } from '../scene2d/inkTrap'
import { TEXT_FONT_STACK } from './fonts'
import { displayedKineticText, wrapKineticLines } from './layout'
import { paintLegacyCue } from './legacy'
import { isLegacyKineticText } from './parse'
import { kineticTextState } from './state'
import type { KineticText, TextAlign, TextMotion } from './types'

export type TextInkTrap = { riso?: boolean; paper?: string }

const hashId = (id: string) => {
  let hash = 2166136261
  for (let index = 0; index < id.length; index += 1) hash = Math.imul(hash ^ id.charCodeAt(index), 16777619)
  return (hash >>> 0) || 1
}
const unit = (seed: number, index: number) => {
  let value = Math.imul(seed ^ (index + 1), 0x45d9f3b)
  value = Math.imul(value ^ (value >>> 16), 0x45d9f3b)
  return ((value ^ (value >>> 16)) >>> 0) / 4294967296
}

function fontCss(cue: KineticText, pixels: number) {
  const weight = cue.weight ?? (cue.font === 'mono' ? 700 : 900)
  const family = TEXT_FONT_STACK[cue.font ?? 'sans']
  return `${cue.italic ? 'italic ' : ''}${weight} ${pixels}px ${family}`
}

function takeUnits(text: string, count: number, words: boolean) {
  if (!words) return Array.from(text).slice(0, Math.max(0, count)).join('')
  let seen = 0
  let out = ''
  for (const part of text.split(/(\s+)/)) {
    if (part.trim()) {
      if (seen >= count) break
      seen += 1
    }
    out += part
  }
  return out.replace(/\s+$/, '')
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  const r = Math.max(0, Math.min(radius, width / 2, height / 2))
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + width, y, x + width, y + height, r)
  ctx.arcTo(x + width, y + height, x, y + height, r)
  ctx.arcTo(x, y + height, x, y, r)
  ctx.arcTo(x, y, x + width, y, r)
  ctx.closePath()
}

function paintPaper(ctx: CanvasRenderingContext2D, width: number, height: number, seed: number, color: string) {
  ctx.save()
  ctx.rotate((unit(seed, 1) - .5) * .08)
  ctx.beginPath()
  for (let step = 0; step < 14; step += 1) {
    const angle = step / 14 * Math.PI * 2
    const wobble = 1 + (unit(seed, step + 3) - .5) * .14
    const x = Math.cos(angle) * width * .5 * wobble
    const y = Math.sin(angle) * height * .5 * wobble
    if (step === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
  const ink = ctx.globalAlpha
  for (let speck = 0; speck < 16; speck += 1) {
    ctx.globalAlpha = ink * .35
    ctx.fillStyle = unit(seed, speck) > .5 ? '#6b4b32' : '#f4efe4'
    ctx.fillRect((unit(seed, speck + 20) - .5) * width, (unit(seed, speck + 40) - .5) * height, 1.4, 1.4)
  }
  ctx.globalAlpha = ink
  ctx.restore()
}

function paintTapeFace(ctx: CanvasRenderingContext2D, width: number, height: number, radius?: number) {
  const curve = Math.min(height / 2, (radius ?? 0.2) * height)
  roundRect(ctx, -width / 2, -height / 2, width, height, curve)
  ctx.fill()
}

function paintHalftone(ctx: CanvasRenderingContext2D, width: number, height: number, seed: number) {
  const step = Math.max(3.5, Math.min(width, height) * 0.09)
  const left = -width / 2
  const top = -height / 2
  ctx.save()
  ctx.translate(Math.max(4, width * 0.06), Math.max(5, height * 0.14))
  ctx.fillStyle = '#16130f'
  const ink = ctx.globalAlpha * 0.9
  for (let row = 0, y = top; y < top + height; row += 1, y += step) {
    for (let column = 0, x = left; x < left + width; column += 1, x += step) {
      if ((column + row + (seed % 2)) % 2 === 0) continue
      ctx.globalAlpha = ink
      ctx.beginPath()
      ctx.arc(x + step * 0.35, y + step * 0.35, Math.max(0.8, step * 0.18), 0, Math.PI * 2)
      ctx.fill()
    }
  }
  ctx.restore()
}

function paintCardFace(ctx: CanvasRenderingContext2D, width: number, height: number, color: string, radius: number | undefined, seed: number) {
  paintHalftone(ctx, width, height, seed)
  ctx.fillStyle = color
  roundRect(ctx, -width / 2, -height / 2, width, height, Math.min(height / 2, (radius ?? 0.08) * height))
  ctx.fill()
  ctx.strokeStyle = '#1c140f'
  ctx.lineWidth = Math.max(2, height * 0.035)
  ctx.stroke()
}

function tapeCutsLetters(color: string) {
  const red = Number.parseInt(color.slice(1, 3), 16)
  const green = Number.parseInt(color.slice(3, 5), 16)
  const blue = Number.parseInt(color.slice(5, 7), 16)
  if (!Number.isFinite(red) || !Number.isFinite(green) || !Number.isFinite(blue)) return false
  return red * 0.2126 + green * 0.7152 + blue * 0.0722 >= 160
}

function prepareTapeCut(ctx: CanvasRenderingContext2D, cue: KineticText) {
  if (cue.box?.kind !== 'tape' || !tapeCutsLetters(cue.color)) return
  ctx.globalCompositeOperation = 'destination-out'
  ctx.shadowColor = 'transparent'
  ctx.shadowBlur = 0
  ctx.lineWidth = 0
}

function paintBox(ctx: CanvasRenderingContext2D, cue: KineticText, blockWidth: number, blockHeight: number) {
  const box = cue.box
  if (!box || box.kind === 'none') return
  const pad = box.padding * (blockHeight / Math.max(1, cue.text.split('\n').length))
  const width = blockWidth + pad * 2
  const height = blockHeight + pad * 2
  ctx.save()
  ctx.globalAlpha *= box.opacity
  ctx.fillStyle = box.color
  if (box.kind === 'paper') paintPaper(ctx, width, height, hashId(cue.id), box.color)
  else if (box.kind === 'pill') { roundRect(ctx, -width / 2, -height / 2, width, height, (box.radius ?? .6) * height); ctx.fill() }
  else if (box.kind === 'underline') ctx.fillRect(-blockWidth / 2, blockHeight * .35, blockWidth, Math.max(2, blockHeight * .06))
  else if (box.kind === 'bar') ctx.fillRect(-width / 2, -height / 2, width, height)
  else if (box.kind === 'tape') paintTapeFace(ctx, width, height, box.radius)
  else if (box.kind === 'card') paintCardFace(ctx, width, height, box.color, box.radius, hashId(cue.id))
  else ctx.fillRect(-width / 2, -height / 2, width, height)
  ctx.restore()
}

function paintPlate(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, opacity: number) {
  if (cue.box?.kind !== 'plate') return
  ctx.save()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.globalAlpha = opacity * cue.box.opacity
  ctx.fillStyle = cue.box.color
  ctx.fillRect(0, 0, width, height)
  ctx.restore()
}

function lineOrigin(align: TextAlign, blockWidth: number) {
  if (align === 'left') return { x: -blockWidth / 2, align: 'left' as const }
  if (align === 'right') return { x: blockWidth / 2, align: 'right' as const }
  return { x: 0, align: 'center' as const }
}

// x is the left or right edge. Center and omitted align stay on the block center.
function anchorOffset(align: TextAlign, blockWidth: number) {
  if (align === 'left') return blockWidth / 2
  if (align === 'right') return -blockWidth / 2
  return 0
}

function paintGlyphs(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, size: number, elapsed: number, wave: boolean, ink: InkTrapPaint) {
  if (!wave) {
    ctx.strokeText(text, x, y)
    reserveBlackPlate(ctx, text, x, y, size, ink)
    ctx.fillText(text, x, y)
    return
  }
  const width = ctx.measureText(text).width
  let cursor = ctx.textAlign === 'center' ? x - width / 2 : ctx.textAlign === 'right' ? x - width : x
  const previous = ctx.textAlign
  ctx.textAlign = 'left'
  Array.from(text).forEach((letter, index) => {
    const dy = Math.sin(elapsed * 5.6 - index * .42) * size * .14
    ctx.strokeText(letter, cursor, y + dy)
    reserveBlackPlate(ctx, letter, cursor, y + dy, size, ink)
    ctx.fillText(letter, cursor, y + dy)
    cursor += ctx.measureText(letter).width
  })
  ctx.textAlign = previous
}

function applyInk(ctx: CanvasRenderingContext2D, cue: KineticText, size: number, blockWidth: number, blockHeight: number) {
  const stroke = cue.stroke ?? { color: '#07101e', width: .085 }
  const shadow = cue.shadow ?? { color: '#020711', blur: .12, x: 0, y: .065 }
  ctx.lineJoin = 'round'
  ctx.strokeStyle = stroke.color
  ctx.lineWidth = Math.max(stroke.width === 0 ? 0 : 3, size * stroke.width)
  ctx.shadowColor = shadow.color
  ctx.shadowBlur = size * shadow.blur
  ctx.shadowOffsetX = size * shadow.x
  ctx.shadowOffsetY = size * shadow.y
  if (cue.fill?.kind === 'gradient') {
    const angle = cue.fill.angle * Math.PI / 180
    const dx = Math.cos(angle) * blockWidth / 2
    const dy = Math.sin(angle) * blockHeight / 2
    const gradient = ctx.createLinearGradient(-dx, -dy, dx, dy)
    gradient.addColorStop(0, cue.fill.from)
    gradient.addColorStop(1, cue.fill.to)
    ctx.fillStyle = gradient
  } else ctx.fillStyle = cue.color
}

function paintV2Cue(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, cue: KineticText, pulse = 1, ink: InkTrapPaint = { trap: false, color: cue.color }) {
  const motion = kineticTextState(cue, seconds) as TextMotion | null
  if (!motion || !('clip' in motion)) return
  const text = displayedKineticText(cue, seconds)
  const shown = takeUnits(text, motion.letters, cue.enter?.preset === 'words')
  let size = height * cue.size / 100
  ctx.save()
  ctx.font = fontCss(cue, size)
  const maxWidth = cue.maxWidth != null ? width * cue.maxWidth / 100 : 0
  const lines = wrapKineticLines(ctx, shown, maxWidth)
  const textWidth = Math.max(1, ...lines.map(line => ctx.measureText(line).width || 1))
  if (cue.maxWidth == null) size *= Math.min(1, width * .86 / textWidth)
  ctx.font = fontCss(cue, size)
  const measured = lines.map(line => ctx.measureText(line).width)
  const blockWidth = Math.max(1, ...measured)
  const lineHeight = size * (cue.lineHeight ?? 1.12)
  const blockHeight = Math.max(lineHeight, lines.length * lineHeight)
  paintPlate(ctx, cue, width, height, motion.opacity)
  ctx.translate(width * (cue.x / 100 + motion.dx), height * (cue.y / 100 + motion.dy))
  ctx.rotate(cue.rotation * Math.PI / 180)
  ctx.scale(motion.scale * pulse, motion.scale * pulse)
  ctx.translate(anchorOffset(cue.align ?? 'center', blockWidth), 0)
  ctx.globalAlpha = motion.opacity
  if (motion.blur > .2 && 'filter' in ctx) ctx.filter = `blur(${motion.blur}px)`
  if ('letterSpacing' in ctx) (ctx as CanvasRenderingContext2D & { letterSpacing: string }).letterSpacing = `${cue.letterSpacing ?? 0}em`
  paintBox(ctx, cue, blockWidth, blockHeight)
  if (motion.clip < .999) {
    ctx.beginPath()
    ctx.rect(-blockWidth / 2, -blockHeight / 2, blockWidth * motion.clip, blockHeight)
    ctx.clip()
  }
  applyInk(ctx, cue, size, blockWidth, blockHeight)
  prepareTapeCut(ctx, cue)
  ctx.textBaseline = 'middle'
  const origin = lineOrigin(cue.align ?? 'center', blockWidth)
  ctx.textAlign = origin.align
  lines.forEach((line, index) => {
    const y = (index - (lines.length - 1) / 2) * lineHeight
    paintGlyphs(ctx, line, origin.x, y, size, motion.elapsed, motion.wave, { ...ink, color: cue.color, fill: cue.fill?.kind })
  })
  ctx.restore()
}

export function paintKineticTexts(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, cues: readonly KineticText[] = [], envelope = 0, ink?: TextInkTrap) {
  const paper = ink?.paper || INK_TRAP_PAPER
  const riso = ink?.riso === true
  for (const cue of cues) {
    if (seconds < cue.start || seconds >= cue.end) continue
    const pulse = 1 + (cue.beatPulse ?? 0) * envelope
    const trap = riso || cue.trap === true
    if (isLegacyKineticText(cue)) paintLegacyCue(ctx, width, height, seconds, cue, pulse, { trap, color: cue.color, paper })
    else paintV2Cue(ctx, width, height, seconds, cue, pulse, { trap, color: cue.color, paper, fill: cue.fill?.kind })
  }
}
