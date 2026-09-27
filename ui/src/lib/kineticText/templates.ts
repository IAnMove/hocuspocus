import type { KineticText } from './types'

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

const field = (key: string, labelKey: string, fallback: string): TextTemplateField => ({ key, labelKey, default: fallback })

export const TEXT_TEMPLATES: TextTemplate[] = [
  { id: 'lower-third-date', labelKey: 'templates.lower-third-date', fields: [field('date', 'fields.date', '1991'), field('caption', 'fields.caption', 'A city keeps its name')], build: (values, frame) => {
    const y = vertical(frame.height, frame.width) ? 72 : 78
    return [
      cue('date', values.date || '1991', frame, { y: y - 8, size: 14, font: 'display', weight: 400, align: 'left', x: 12, enter: { preset: 'slide-right', duration: 0.45 }, box: { kind: 'bar', color: '#e85d4c', opacity: 1, padding: 0.2 } }),
      cue('caption', values.caption || '', frame, { y, size: 5, font: 'condensed', x: 12, align: 'left', enter: { preset: 'fade', duration: 0.4 } }),
    ]
  } },
  { id: 'chorus-banner', labelKey: 'templates.chorus-banner', fields: [field('line', 'fields.line', 'The bird is freed')], build: (values, frame) => [cue('chorus', values.line || '', frame, { font: 'marker', y: vertical(frame.height, frame.width) ? 62 : 48, enter: { preset: 'words', duration: 1.1 }, loop: 'pulse', box: { kind: 'paper', color: '#f4e7cf', opacity: 0.94, padding: 0.4 }, color: '#2a2118' })] },
  { id: 'title-card', labelKey: 'templates.title-card', fields: [field('title', 'fields.title', 'Musktopia'), field('subtitle', 'fields.subtitle', '')], build: (values, frame) => [cue('title', values.title || '', frame, { font: 'display', weight: 400, size: 16, y: 46, enter: { preset: 'blur', duration: 0.7 }, box: { kind: 'plate', color: '#07080d', opacity: 1, padding: 0 } }), ...(values.subtitle ? [cue('sub', values.subtitle, frame, { y: 62, size: 5, font: 'serif', enter: { preset: 'fade', duration: 0.5 } })] : [])] },
  { id: 'end-card', labelKey: 'templates.end-card', fields: [field('title', 'fields.title', 'Coming soon'), field('cta', 'fields.cta', '@studio')], build: (values, frame) => [cue('end', values.title || '', frame, { font: 'display', weight: 400, size: 12, y: 44 }), cue('cta', values.cta || '', frame, { y: 60, size: 5, font: 'sans' })] },
  { id: 'year-counter', labelKey: 'templates.year-counter', fields: [field('from', 'fields.from', '1990'), field('to', 'fields.to', '2000'), field('label', 'fields.label', 'Year')], build: (values, frame) => [cue('count', '{value}', frame, { font: 'display', weight: 400, size: 18, y: 42, counter: { from: Number(values.from) || 0, to: Number(values.to) || 0, decimals: 0, ease: 'ease' } }), ...(values.label ? [cue('label', values.label, frame, { y: 62, size: 5, font: 'condensed' })] : [])] },
  { id: 'quote', labelKey: 'templates.quote', fields: [field('quote', 'fields.quote', 'Keep the line.'), field('author', 'fields.author', '')], build: (values, frame) => [cue('quote', `“${values.quote || ''}”`, frame, { font: 'serif', italic: true, size: 7, y: 46, maxWidth: vertical(frame.height, frame.width) ? 78 : 60, enter: { preset: 'typewriter', duration: 1.4 } }), ...(values.author ? [cue('author', values.author, frame, { y: 64, size: 4, font: 'sans' })] : [])] },
  { id: 'trailer-slam', labelKey: 'templates.trailer-slam', fields: [field('lines', 'fields.lines', 'One|Two|Three')], build: (values, frame) => {
    const lines = (values.lines || '').split('|').map(line => line.trim()).filter(Boolean).slice(0, 8)
    const each = frame.duration / Math.max(1, lines.length)
    return lines.map((line, index) => cue(`slam-${index + 1}`, line, { start: frame.start + each * index, duration: each }, { font: 'display', weight: 400, size: 14, y: 50, enter: { preset: 'impact', duration: 0.18 }, box: { kind: 'plate', color: '#000000', opacity: 1, padding: 0 } }))
  } },
  { id: 'chapter', labelKey: 'templates.chapter', fields: [field('kicker', 'fields.kicker', 'CHAPTER'), field('title', 'fields.title', 'One')], build: (values, frame) => [cue('kicker', (values.kicker || '').toUpperCase(), frame, { y: 40, size: 3, font: 'condensed', uppercase: true, letterSpacing: 0.2 }), cue('chapter', values.title || '', frame, { y: 50, size: 12, font: 'display', weight: 400 })] },
  { id: 'social-caption', labelKey: 'templates.social-caption', fields: [field('caption', 'fields.caption', 'Read this')], build: (values, frame) => [cue('social', values.caption || '', frame, { y: vertical(frame.height, frame.width) ? 72 : 84, size: 4.5, maxWidth: vertical(frame.height, frame.width) ? 76 : 70, font: 'sans', box: { kind: 'pill', color: '#11131a', opacity: 0.82, padding: 0.45, radius: 0.8 } })] },
]

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
