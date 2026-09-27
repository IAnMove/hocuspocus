import { TEXT_FONT_STACK } from './fonts'
import type { LyricLine, LyricWord, SceneLyrics } from './lyrics'

const activeLine = (lines: readonly LyricLine[], seconds: number) =>
  lines.findIndex(line => seconds >= line.start && seconds < line.end)

function drawWord(ctx: CanvasRenderingContext2D, word: string, x: number, y: number, color: string) {
  ctx.fillStyle = color
  ctx.fillText(word, x, y)
}

function wordPaint(word: LyricWord, seconds: number, mode: SceneLyrics['mode']) {
  if (mode === 'word-pop' && seconds < word.start) return null
  const age = seconds - word.start
  const span = Math.max(0.02, word.end - word.start)
  const inside = seconds >= word.start && seconds < word.end
  const pop = mode === 'word-pop' && age < 0.18 ? 1 + (1 - age / 0.18) * 0.25 : 1
  const dy = mode === 'bounce' && inside ? Math.sin(age * 10) * 0.18 : 0
  const clip = mode === 'karaoke' && inside ? (seconds - word.start) / span : seconds >= word.end ? 1 : 0
  return { pop, dy, clip, active: inside || seconds >= word.end }
}

export function paintSceneLyrics(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, lyrics?: SceneLyrics) {
  if (!lyrics) return
  const index = activeLine(lyrics.lines, seconds)
  if (index < 0) return
  const shown = lyrics.style.visibleLines === 2 ? lyrics.lines.slice(index, index + 2) : [lyrics.lines[index]]
  const size = height * lyrics.style.size / 100
  ctx.save()
  ctx.font = `${lyrics.style.weight ?? 700} ${size}px ${TEXT_FONT_STACK[lyrics.style.font]}`
  ctx.textAlign = lyrics.style.align
  ctx.textBaseline = 'middle'
  ctx.lineJoin = 'round'
  if (lyrics.style.stroke) { ctx.strokeStyle = lyrics.style.stroke.color; ctx.lineWidth = size * lyrics.style.stroke.width }
  if (lyrics.style.shadow) {
    ctx.shadowColor = lyrics.style.shadow.color
    ctx.shadowBlur = size * lyrics.style.shadow.blur
    ctx.shadowOffsetX = size * lyrics.style.shadow.x
    ctx.shadowOffsetY = size * lyrics.style.shadow.y
  }
  shown.forEach((line, row) => {
    const text = lyrics.style.uppercase ? line.words.map(word => word.text.toUpperCase()) : line.words.map(word => word.text)
    const y = height * lyrics.style.y / 100 + row * size * 1.25
    let cursor = width * lyrics.style.x / 100
    if (lyrics.style.align === 'center') cursor -= text.reduce((sum, word) => sum + ctx.measureText(`${word} `).width, 0) / 2
    if (lyrics.style.align === 'right') cursor -= text.reduce((sum, word) => sum + ctx.measureText(`${word} `).width, 0)
    const fade = lyrics.mode === 'line-fade' ? Math.min(1, (seconds - line.start) / 0.25, (line.end - seconds) / 0.25) : 1
    ctx.globalAlpha = Math.max(0, fade)
    line.words.forEach((word, wordIndex) => {
      const paint = wordPaint(word, seconds, lyrics.mode)
      const label = `${text[wordIndex]} `
      if (!paint) { cursor += ctx.measureText(label).width; return }
      ctx.save()
      ctx.translate(cursor, y + paint.dy * size)
      ctx.scale(paint.pop, paint.pop)
      const color = paint.active && lyrics.mode !== 'karaoke' ? lyrics.style.activeColor : lyrics.style.color
      if (lyrics.style.stroke) ctx.strokeText(text[wordIndex], 0, 0)
      if (lyrics.mode === 'karaoke') {
        ctx.fillStyle = lyrics.style.color
        ctx.fillText(text[wordIndex], 0, 0)
        ctx.save()
        ctx.beginPath()
        ctx.rect(0, -size, ctx.measureText(text[wordIndex]).width * paint.clip, size * 2)
        ctx.clip()
        ctx.fillStyle = lyrics.style.activeColor
        ctx.fillText(text[wordIndex], 0, 0)
        ctx.restore()
      } else drawWord(ctx, text[wordIndex], 0, 0, color)
      ctx.restore()
      cursor += ctx.measureText(label).width
    })
  })
  ctx.restore()
}
