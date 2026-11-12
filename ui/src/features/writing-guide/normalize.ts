import type { GuidePending, GuideSection } from './model'

const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value)
  ? value as Record<string, unknown> : {}
const texts = (value: unknown, allowed: Set<string>): Record<string, string> =>
  Object.fromEntries(Object.entries(object(value)).filter(([key, text]) => allowed.has(key) && typeof text === 'string')
    .map(([key, text]) => [key, (text as string).slice(0, 6000)]))

function pending(value: unknown, allowed: Set<string>): GuidePending | undefined {
  const p = object(value)
  if (!['examples', 'fill', 'develop', 'review'].includes(String(p.action)) || !allowed.has(String(p.questionId))
    || !Array.isArray(p.selected) || !Array.isArray(p.examples) || !Array.isArray(p.suggestions) || !Array.isArray(p.review)) return undefined
  if (p.suggestions.some(row => !allowed.has(object(row).field as string) || typeof object(row).value !== 'string' || typeof object(row).reason !== 'string')
    || p.review.some(row => !allowed.has(object(row).field as string) || typeof object(row).issue !== 'string' || typeof object(row).suggestion !== 'string')
    || p.examples.some(item => typeof item !== 'string')) return undefined
  const usage = object(p.usage)
  return { ...p, base: texts(p.base, allowed),
    selected: p.selected.filter((key): key is string => typeof key === 'string' && allowed.has(key)),
    usage: ['prompt_tokens', 'completion_tokens', 'total_tokens', 'calls'].every(key => typeof usage[key] === 'number' && Number.isFinite(usage[key])) ? usage : null,
  } as GuidePending
}

export function normalizeSection(value: unknown, ids: string[], notes: string[]): GuideSection {
  const raw = object(value), allowed = new Set(ids), undo = object(raw.undo)
  return { notes: texts(raw.notes, new Set(notes)), pending: pending(raw.pending, allowed),
    ...(undo.before && undo.after ? { undo: { before: texts(undo.before, allowed), after: texts(undo.after, allowed) } } : {}) }
}
