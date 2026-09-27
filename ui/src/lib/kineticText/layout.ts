import type { KineticText } from './types'

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

export function displayedKineticText(cue: KineticText, seconds: number) {
  let text = cue.text
  if (cue.counter) {
    const span = Math.max(0.001, cue.end - cue.start)
    const t = clamp((seconds - cue.start) / span, 0, 1)
    const eased = cue.counter.ease === 'ease' ? t * t * (3 - 2 * t) : t
    const value = cue.counter.from + (cue.counter.to - cue.counter.from) * eased
    text = text.replaceAll('{value}', value.toFixed(cue.counter.decimals))
  }
  return cue.uppercase ? text.toUpperCase() : text
}

/** Wrap on spaces inside maxWidth. Explicit newlines stay as paragraphs. */
export function wrapKineticLines(ctx: CanvasRenderingContext2D, text: string, maxWidth: number) {
  if (!(maxWidth > 0)) return text.split('\n')
  const lines: string[] = []
  for (const paragraph of text.split('\n')) {
    const words = paragraph.split(/\s+/).filter(Boolean)
    let line = ''
    if (!words.length) { lines.push(''); continue }
    for (const word of words) {
      const next = line ? `${line} ${word}` : word
      if (line && ctx.measureText(next).width > maxWidth) { lines.push(line); line = word }
      else line = next
    }
    lines.push(line)
  }
  return lines
}
