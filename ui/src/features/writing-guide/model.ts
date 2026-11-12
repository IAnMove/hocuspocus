import rawCatalog from '../../../../app/shared/writing_guide.json' with { type: 'json' }
import { randomUuid } from '../../lib/uuid'
import { normalizeSection } from './normalize'

export type GuideAction = 'examples' | 'fill' | 'develop' | 'review'
export type GuideScope = keyof typeof rawCatalog.scopes
export type GuideField = { id: string; path: string | null; advanced: boolean; codec?: string }
export type GuideUsage = { prompt_tokens: number; completion_tokens: number; total_tokens: number; calls: number }
export type GuideResult = {
  suggestions: Array<{ field: string; value: string; reason: string }>
  examples: string[]
  review: Array<{ field: string; issue: string; suggestion: string }>
  usage: GuideUsage | null
  elapsedSeconds: number
  provider: string
  model: string
}
export type GuidePending = GuideResult & {
  action: GuideAction; questionId: string; base: Record<string, string>; selected: string[]; createdAt: string
}
export type GuideSection = {
  notes: Record<string, string>
  pending?: GuidePending
  undo?: { before: Record<string, string>; after: Record<string, string> }
}
export type WritingGuideState = { version: 1; sections: Record<string, GuideSection> }
export type GuideData = { values: Record<string, string>; section: GuideSection }
export type GuideUpdate = (current: GuideData) => GuideData
export const MAX_ANSWER = 6000
/** Below the server's 24000-character bound, so a proposal request is never refused for its context. */
export const MAX_CONTEXT = 20000
export const catalog = rawCatalog as {
  scopes: Record<GuideScope, GuideField[]>
  questions: Record<string, { question: Record<string, string>; hint: Record<string, string>; example: Record<string, string> }>
}

export function normalizeGuide(value: unknown): WritingGuideState {
  if (!value || typeof value !== 'object') return { version: 1, sections: {} }
  const raw = value as Partial<WritingGuideState>
  if (!raw.sections || typeof raw.sections !== 'object' || Array.isArray(raw.sections)) return { version: 1, sections: {} }
  const sections = Object.fromEntries(Object.entries(raw.sections).filter(([key, item]) =>
    Object.hasOwn(catalog.scopes, key.split(':')[0]) && item && typeof item === 'object',
  ).slice(0, 500).map(([key, item]) => {
    const fields = catalog.scopes[key.split(':')[0] as GuideScope]
    return [key, normalizeSection(item, fields.map(f => f.id), fields.filter(f => !f.path).map(f => f.id))]
  }))
  return { version: 1, sections }
}

export function extraDecisions(value: WritingGuideState | undefined): Record<string, Record<string, string>> {
  return Object.fromEntries(Object.entries(normalizeGuide(value).sections)
    .map(([key, section]) => [key, section.notes] as const).filter(([, notes]) => Object.values(notes).some(v => v.trim())))
}

type Entity = Record<string, unknown>
const object = (value: unknown): Entity => value && typeof value === 'object' && !Array.isArray(value) ? value as Entity : {}
const text = (value: unknown): string => typeof value === 'string' ? value : ''
function getPath(entity: Entity, path: string): unknown {
  return path.split('.').reduce<unknown>((current, key) => object(current)[key], entity)
}
function setPath(entity: Entity, path: string, value: unknown): void {
  const parts = path.split('.'), last = parts.pop()!
  let current = entity
  for (const part of parts) { current[part] = { ...object(current[part]) }; current = object(current[part]) }
  current[last] = value
}

function readField(entity: Entity, field: GuideField): string {
  const value = getPath(entity, field.path!)
  if (!field.codec) return text(value)
  if (!Array.isArray(value)) return ''
  return value.map(item => field.codec === 'lines' ? text(item) :
    text(object(item)[field.codec === 'rules' ? 'description' : 'summary'])).join('\n')
}
function writeField(entity: Entity, field: GuideField, value: string): void {
  if (!field.codec) { setPath(entity, field.path!, value); return }
  const lines = value.split('\n').filter(line => line.trim())
  if (field.codec === 'lines') { setPath(entity, field.path!, lines); return }
  const previous = getPath(entity, field.path!)
  const old = Array.isArray(previous) ? previous : []
  const property = field.codec === 'rules' ? 'description' : 'summary'
  const used = new Set<number>()
  const rows = lines.map((line, index) => {
    const match = old.findIndex((row, i) => !used.has(i) && object(row)[property] === line)
    const slot = match >= 0 ? match : used.has(index) ? -1 : index
    const prior = slot >= 0 ? object(old[slot]) : {}
    if (slot >= 0) used.add(slot)
    return { ...prior, id: prior.id || `guide-${randomUuid()}`, [property]: line,
      ...(field.codec === 'rules' ? { status: match >= 0 ? prior.status || 'draft' : 'draft' } : { kind: prior.kind || 'action' }) }
  })
  setPath(entity, field.path!, rows)
}

/** Canonical fields are read directly; only additional coaching decisions live in notes. */
export function readGuide(entity: Entity, state: WritingGuideState | undefined, scope: GuideScope, id: string): GuideData {
  const section = normalizeGuide(state).sections[`${scope}:${id}`] || { notes: {} }
  return { section, values: Object.fromEntries(catalog.scopes[scope].map(field =>
    [field.id, field.path ? readField(entity, field) : section.notes[field.id] || ''])) }
}

export function editGuide(entity: Entity, state: WritingGuideState | undefined, scope: GuideScope, id: string, update: GuideUpdate) {
  const before = readGuide(entity, state, scope, id), after = update(before)
  const next = { ...entity }, notes = { ...before.section.notes }
  let changed = false
  for (const field of catalog.scopes[scope]) {
    const value = after.values[field.id]
    if (typeof value !== 'string' || value === before.values[field.id]) continue
    changed = true
    if (field.path) writeField(next, field, value)
    else notes[field.id] = value
  }
  const guide = normalizeGuide(state)
  return { entity: next, changed, guide: { ...guide, sections: { ...guide.sections,
    [`${scope}:${id}`]: { ...after.section, notes } } } }
}

/** A late proposal or undo may not replace a field edited since its snapshot. */
export function applyChanges(data: GuideData, expected: Record<string, string>, changes: Record<string, string>): GuideData {
  const keys = Object.keys(changes)
  if (!keys.length || keys.some(key => !Object.hasOwn(data.values, key) || data.values[key] !== expected[key])) return data
  return { values: { ...data.values, ...changes }, section: { ...data.section, pending: undefined,
    undo: { before: Object.fromEntries(keys.map(key => [key, data.values[key]])), after: changes } } }
}

export function undoChanges(data: GuideData): GuideData {
  const undo = data.section.undo
  if (!undo || Object.keys(undo.after).some(key => data.values[key] !== undo.after[key])) return data
  return { values: { ...data.values, ...undo.before }, section: { ...data.section, undo: undefined } }
}

/** Send narrative facts only, never media, credentials, previous proposals or undo history. */
export function guideContext(project: Entity, target: Entity, decisions: WritingGuideState | undefined): Entity {
  const keys = ['id', 'title', 'name', 'premise', 'logline', 'synopsis', 'theme', 'ending', 'genre', 'tone', 'audience',
    'summary', 'worldSummary', 'rules', 'immutableRules', 'forbiddenChanges', 'description', 'role', 'personality',
    'desire', 'need', 'flaw', 'conflict', 'arc', 'longArc', 'voice', 'voiceAndDialogue', 'appearance', 'identityLock',
    'label', 'dynamic', 'evolution', 'fromCharacterId', 'toCharacterId', 'purpose', 'entryState', 'exitState',
    'goal', 'turn', 'beats', 'participatingCharacterIds', 'locationId', 'text', 'characterId', 'dialogue']
  let limit = 500, rows = 12
  const compact = (value: unknown, depth = 0): unknown => {
    if (typeof value === 'string') return value.slice(0, limit)
    if (depth > 5) return undefined
    if (Array.isArray(value)) return value.slice(0, rows).map(v => compact(v, depth + 1))
    return Object.fromEntries(Object.entries(object(value)).filter(([key]) => keys.includes(key)).map(([key, v]) => [key, compact(v, depth + 1)]))
  }
  const build = () => ({ project: compact(project), world: compact(project.world || project.canon),
    characters: compact(project.characters), relationships: compact(project.relationships),
    episode: compact(project.writingEpisode), target: compact(target),
    decisions: compactDecisions(extraDecisions(decisions), limit) })
  const tooLong = (value: unknown) => JSON.stringify(value).length > MAX_CONTEXT
  let context: Entity = build()
  // Shorten texts first, then fewer rows (a long episode has 12 scenes × 12 lines), then texts again.
  while (tooLong(context) && (limit > 30 || rows > 3)) {
    if (limit > 200 || rows <= 3) limit = Math.max(30, Math.floor(limit / 2))
    else rows = Math.max(3, Math.floor(rows / 2))
    context = build()
  }
  // The server rejects anything above its limit, so the question must still reach it with its own target.
  if (tooLong(context)) context = { project: compact(project), target: compact(target), decisions: {} }
  return context
}

function compactDecisions(value: Record<string, Record<string, string>>, limit: number) {
  return Object.fromEntries(Object.entries(value).slice(0, 24).map(([key, notes]) =>
    [key, Object.fromEntries(Object.entries(notes).map(([q, v]) => [q, v.slice(0, limit)]))]))
}
