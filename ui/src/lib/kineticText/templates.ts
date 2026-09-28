import textCatalog from '../../../../app/shared/text_templates.json' with { type: 'json' }
import type { KineticText, TextFont } from './types'

export type TextTemplateField = { key: string; labelKey: string; default: string }
export type TextTemplate = {
  id: string
  labelKey: string
  fields: TextTemplateField[]
  build: (values: Record<string, string>, frame: { start: number; duration: number; width: number; height: number }) => KineticText[]
}

const vertical = (height: number, width: number) => height > width
const cue = (id: string, text: string, frame: { start: number; duration: number }, extra: Partial<KineticText>): KineticText => ({
  id, text, start: frame.start, end: frame.start + frame.duration, preset: 'impact', x: 50, y: 80, size: 8, color: '#fff6e8', rotation: 0, ...extra,
})

type RawField = { key: string; default: string; labelKey: string }
type RawText = { id: string; labelKey: string; fields: RawField[] }
type TextFrame = { start: number; duration: number; width: number; height: number }

const RANSOM_FONTS: readonly TextFont[] = ['display', 'marker', 'serif', 'condensed']
const RANSOM_PAPER = ['#f4e7cf', '#f6f1e4', '#f3d2b5', '#e7eef8']
const RANSOM_TILT = [-3, 2, -1, 4, -2, 3, 1, -4]
const INK = { color: '#1c140f', width: 0 } as const
const NO_SHADOW = { color: '#1c140f', blur: 0, x: 0, y: 0 } as const

function ransomWords(line: string) {
  return line.toUpperCase().split(/\s+/).filter(Boolean).slice(0, 8)
}

function ransomCue(word: string, index: number, count: number, frame: TextFrame, tall: boolean): KineticText {
  const cols = tall ? 3 : 4
  const row = Math.floor(index / cols)
  const col = index % cols
  const rowCount = Math.min(cols, count - row * cols)
  const rows = Math.floor((count + cols - 1) / cols)
  const x = 50 + (col - (rowCount - 1) / 2) * (tall ? 22 : 18)
  const y = (tall ? 46 : 48) + (row - (rows - 1) / 2) * 12
  return cue(`word-${index + 1}`, word, frame, {
    x, y, size: tall ? 7 : 8, font: RANSOM_FONTS[index % RANSOM_FONTS.length], weight: 700,
    align: 'center', uppercase: true, rotation: RANSOM_TILT[index % RANSOM_TILT.length], color: '#1c140f',
    start: frame.start + Math.min(index * 0.12, frame.duration * 0.5), end: frame.start + frame.duration,
    enter: { preset: 'impact', duration: 0.2 },
    box: { kind: 'paper', color: RANSOM_PAPER[index % RANSOM_PAPER.length], opacity: 1, padding: 0.28 },
    stroke: { ...INK }, shadow: { ...NO_SHADOW },
  })
}

function buildRansom(values: Record<string, string>, frame: TextFrame) {
  const words = ransomWords(values.line || 'THE BIRD IS FREED')
  const tall = vertical(frame.height, frame.width)
  return words.map((word, index) => ransomCue(word, index, words.length, frame, tall))
}

function dymoTilt(text: string) {
  let sum = 0
  for (const char of text) sum = (sum + char.charCodeAt(0)) % 7
  return [-1.5, -1, -0.5, 0, 0.5, 1, 1.5][sum] ?? 0
}

function dymoDark(background: string) {
  return background.trim().toLowerCase() === 'dark'
}

function dymoLook(text: string, dark: boolean, tall: boolean): Partial<KineticText> {
  return {
    x: 50, y: tall ? 72 : 78, size: tall ? 4.5 : 5, font: 'mono', weight: 700, align: 'center',
    uppercase: true, letterSpacing: 0.06, maxWidth: tall ? 84 : 78, rotation: dymoTilt(text),
    color: dark ? '#141210' : '#f4efe6', enter: { preset: 'words', duration: 0.8 },
    box: { kind: 'tape', color: dark ? '#f2b705' : '#141210', opacity: 1, padding: 0.55, radius: 0.18 },
    stroke: { color: '#141210', width: 0 }, shadow: { color: '#141210', blur: 0, x: 0, y: 0 },
  }
}

function buildDymo(values: Record<string, string>, frame: TextFrame) {
  const text = (values.line || 'KEEP THE LINE').toUpperCase()
  const dark = dymoDark(values.background || 'paper')
  return [cue('tape', text, frame, dymoLook(text, dark, vertical(frame.height, frame.width)))]
}

function buildCard(values: Record<string, string>, frame: TextFrame) {
  const tall = vertical(frame.height, frame.width)
  return [cue('card', values.title || 'Musktopia', frame, {
    x: 50, y: tall ? 44 : 46, size: tall ? 10 : 12, font: 'display', weight: 400, align: 'center',
    rotation: -1, color: '#1a140f', enter: { preset: 'rise', duration: 0.45 },
    box: { kind: 'card', color: '#f7f1e4', opacity: 1, padding: 0.62, radius: 0.08 },
    stroke: { ...INK }, shadow: { ...NO_SHADOW },
  })]
}

const BUILDS: Record<string, TextTemplate['build']> = {
  'lower-third-date': (values, frame) => {
    const y = vertical(frame.height, frame.width) ? 72 : 78
    return [
      cue('date', values.date || '1991', frame, { y: y - 8, size: 14, font: 'display', weight: 400, align: 'left', x: 12, enter: { preset: 'slide-right', duration: 0.45 }, box: { kind: 'bar', color: '#e85d4c', opacity: 1, padding: 0.2 } }),
      cue('caption', values.caption || '', frame, { y, size: 5, font: 'condensed', x: 12, align: 'left', enter: { preset: 'fade', duration: 0.4 } }),
    ]
  },
  'chorus-banner': (values, frame) => [cue('chorus', values.line || '', frame, { font: 'marker', y: vertical(frame.height, frame.width) ? 62 : 48, enter: { preset: 'words', duration: 1.1 }, loop: 'pulse', box: { kind: 'paper', color: '#f4e7cf', opacity: 0.94, padding: 0.4 }, color: '#2a2118' })],
  'title-card': (values, frame) => [cue('title', values.title || '', frame, { font: 'display', weight: 400, size: 16, y: 46, enter: { preset: 'blur', duration: 0.7 }, box: { kind: 'plate', color: '#07080d', opacity: 1, padding: 0 } }), ...(values.subtitle ? [cue('sub', values.subtitle, frame, { y: 62, size: 5, font: 'serif', enter: { preset: 'fade', duration: 0.5 } })] : [])],
  'end-card': (values, frame) => [cue('end', values.title || '', frame, { font: 'display', weight: 400, size: 12, y: 44 }), cue('cta', values.cta || '', frame, { y: 60, size: 5, font: 'sans' })],
  'year-counter': (values, frame) => [cue('count', '{value}', frame, { font: 'display', weight: 400, size: 18, y: 42, counter: { from: Number(values.from) || 0, to: Number(values.to) || 0, decimals: 0, ease: 'ease' } }), ...(values.label ? [cue('label', values.label, frame, { y: 62, size: 5, font: 'condensed' })] : [])],
  quote: (values, frame) => [cue('quote', `“${values.quote || ''}”`, frame, { font: 'serif', italic: true, size: 7, y: 46, maxWidth: vertical(frame.height, frame.width) ? 78 : 60, enter: { preset: 'typewriter', duration: 1.4 } }), ...(values.author ? [cue('author', values.author, frame, { y: 64, size: 4, font: 'sans' })] : [])],
  'trailer-slam': (values, frame) => {
    const lines = (values.lines || '').split('|').map(line => line.trim()).filter(Boolean).slice(0, 8)
    const each = frame.duration / Math.max(1, lines.length)
    return lines.map((line, index) => cue(`slam-${index + 1}`, line, { start: frame.start + each * index, duration: each }, { font: 'display', weight: 400, size: 14, y: 50, enter: { preset: 'impact', duration: 0.18 }, box: { kind: 'plate', color: '#000000', opacity: 1, padding: 0 } }))
  },
  chapter: (values, frame) => [cue('kicker', (values.kicker || '').toUpperCase(), frame, { y: 40, size: 3, font: 'condensed', uppercase: true, letterSpacing: 0.2 }), cue('chapter', values.title || '', frame, { y: 50, size: 12, font: 'display', weight: 400 })],
  'social-caption': (values, frame) => [cue('social', values.caption || '', frame, { y: vertical(frame.height, frame.width) ? 72 : 84, size: 4.5, maxWidth: vertical(frame.height, frame.width) ? 76 : 70, font: 'sans', box: { kind: 'pill', color: '#11131a', opacity: 0.82, padding: 0.45, radius: 0.8 } })],
  ransom: buildRansom,
  dymo: buildDymo,
  card: buildCard,
}

export const TEXT_TEMPLATES: TextTemplate[] = (textCatalog.entries as RawText[]).map(entry => {
  const build = BUILDS[entry.id]
  if (!build) throw new Error(`Text template ${entry.id} has no builder.`)
  return {
    id: entry.id,
    labelKey: entry.labelKey,
    fields: entry.fields.map(field => ({ key: field.key, labelKey: field.labelKey, default: field.default })),
    build,
  }
})

export function buildTextTemplate(id: string, values: Record<string, string>, frame: { start: number; duration: number; width: number; height: number }) {
  const built = TEXT_TEMPLATES.find(template => template.id === id)?.build(values, frame) ?? []
  return built.map(item => ({ ...item, template: id }))
}

export function textTemplatesFromRecipe(raw: unknown, frame: { start: number; duration: number; width: number; height: number }) {
  if (!Array.isArray(raw)) return []
  return raw.slice(0, 9).flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const row = item as { id?: unknown; values?: unknown }
    if (typeof row.id !== 'string' || !TEXT_TEMPLATES.some(template => template.id === row.id)) return []
    const values = row.values && typeof row.values === 'object'
      ? Object.fromEntries(Object.entries(row.values as Record<string, unknown>).map(([key, value]) => [key, String(value ?? '')]))
      : {}
    return buildTextTemplate(row.id, values, frame)
  })
}
