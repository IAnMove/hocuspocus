export const REVIEW_DECISIONS_STORAGE_KEY = 'hocuspocus.scene-template-review.v1'
export const REVIEW_DECISIONS_SCHEMA_VERSION = 1 as const

export type ReviewDecision = 'pending' | 'keep' | 'discard'
export type TemplateVersion = string | number

export interface ReviewTemplateRef {
  id: string
  version: TemplateVersion
}

export interface ReviewChoice {
  id: string
  templateVersion: TemplateVersion
  decision: ReviewDecision
  notes: string
}

export interface ReviewChoicesState {
  schemaVersion: typeof REVIEW_DECISIONS_SCHEMA_VERSION
  catalogVersion: string
  choices: Record<string, ReviewChoice>
}

export interface ReviewChoicesParseResult {
  state: ReviewChoicesState
  warning?: string
}

export interface ReviewExport {
  schemaVersion: typeof REVIEW_DECISIONS_SCHEMA_VERSION
  catalogVersion: string
  exportedAt: string
  templates: Array<{
    id: string
    templateVersion: TemplateVersion
    decision: ReviewDecision
    notes: string
  }>
}

const DECISIONS: readonly ReviewDecision[] = ['pending', 'keep', 'discard']

const isDecision = (value: unknown): value is ReviewDecision => DECISIONS.includes(value as ReviewDecision)
const safeVersion = (value: unknown): TemplateVersion | undefined => (
  typeof value === 'string' || typeof value === 'number' ? value : undefined
)
const sameVersion = (left: unknown, right: unknown) => {
  const leftVersion = safeVersion(left)
  const rightVersion = safeVersion(right)
  return leftVersion !== undefined && rightVersion !== undefined && String(leftVersion) === String(rightVersion)
}
const clampNotes = (value: unknown) => typeof value === 'string' ? value.slice(0, 4_000) : ''

const emptyChoices = (catalogVersion: string, templates: readonly ReviewTemplateRef[]): ReviewChoicesState => {
  const choices: Record<string, ReviewChoice> = {}
  for (const template of templates) {
    if (!template || typeof template.id !== 'string' || !template.id.trim()) continue
    const version = safeVersion(template.version)
    if (version === undefined) continue
    choices[template.id] = { id: template.id, templateVersion: version, decision: 'pending', notes: '' }
  }
  return { schemaVersion: REVIEW_DECISIONS_SCHEMA_VERSION, catalogVersion, choices }
}

export function createReviewChoices(
  catalogVersion: string,
  templates: readonly ReviewTemplateRef[],
): ReviewChoicesState {
  return emptyChoices(catalogVersion, templates)
}

const invalidChoices = (
  catalogVersion: string,
  templates: readonly ReviewTemplateRef[],
  warning: string,
): ReviewChoicesParseResult => ({ state: emptyChoices(catalogVersion, templates), warning })

export function parseReviewChoicesResult(
  raw: string | null | undefined,
  catalogVersion: string,
  templates: readonly ReviewTemplateRef[],
): ReviewChoicesParseResult {
  const initial = emptyChoices(catalogVersion, templates)
  if (!raw) return { state: initial }

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return invalidChoices(catalogVersion, templates, 'The saved decisions are not valid JSON; they stay pending.')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return invalidChoices(catalogVersion, templates, 'The saved decisions have an unknown format; they stay pending.')
  }

  const record = parsed as Record<string, unknown>
  if (record.schemaVersion !== REVIEW_DECISIONS_SCHEMA_VERSION || record.catalogVersion !== catalogVersion) {
    return invalidChoices(catalogVersion, templates, 'The decisions belong to another catalog version; old approvals are not imported.')
  }
  if (!record.choices || typeof record.choices !== 'object' || Array.isArray(record.choices)) {
    return invalidChoices(catalogVersion, templates, 'The decisions contain no valid table; they stay pending.')
  }

  const known = new Map(templates.map(template => [template.id, template]))
  let ignored = false
  for (const [id, value] of Object.entries(record.choices as Record<string, unknown>)) {
    const template = known.get(id)
    if (!template || !value || typeof value !== 'object' || Array.isArray(value)) {
      ignored = true
      continue
    }
    const choice = value as Record<string, unknown>
    if (choice.id !== id || !sameVersion(choice.templateVersion, template.version) || !isDecision(choice.decision)) {
      ignored = true
      continue
    }
    initial.choices[id] = {
      id,
      templateVersion: template.version,
      decision: choice.decision,
      notes: clampNotes(choice.notes),
    }
  }
  return ignored
    ? { state: initial, warning: 'Decisions with IDs or versions that no longer match the catalog were ignored.' }
    : { state: initial }
}

export function parseReviewChoices(
  raw: string | null | undefined,
  catalogVersion: string,
  templates: readonly ReviewTemplateRef[],
): ReviewChoicesState {
  return parseReviewChoicesResult(raw, catalogVersion, templates).state
}

export function loadReviewChoicesResult(
  storage: Pick<Storage, 'getItem'> | undefined,
  catalogVersion: string,
  templates: readonly ReviewTemplateRef[],
): ReviewChoicesParseResult {
  if (!storage) return { state: emptyChoices(catalogVersion, templates) }
  try {
    return parseReviewChoicesResult(storage.getItem(REVIEW_DECISIONS_STORAGE_KEY), catalogVersion, templates)
  } catch {
    return invalidChoices(catalogVersion, templates, 'Storage could not be read; decisions stay pending in this session.')
  }
}

export function loadReviewChoices(
  storage: Pick<Storage, 'getItem'> | undefined,
  catalogVersion: string,
  templates: readonly ReviewTemplateRef[],
): ReviewChoicesState {
  return loadReviewChoicesResult(storage, catalogVersion, templates).state
}

export function saveReviewChoices(
  storage: Pick<Storage, 'setItem'> | undefined,
  state: ReviewChoicesState,
): boolean {
  if (!storage) return false
  try {
    storage.setItem(REVIEW_DECISIONS_STORAGE_KEY, serializeReviewChoices(state))
    return true
  } catch {
    return false
  }
}

export function updateReviewChoice(
  state: ReviewChoicesState,
  id: string,
  decision: ReviewDecision,
  notes = state.choices[id]?.notes || '',
): ReviewChoicesState {
  const current = state.choices[id]
  if (!current || !isDecision(decision)) return state
  return { ...state, choices: { ...state.choices, [id]: { ...current, decision, notes: clampNotes(notes) } } }
}

export function serializeReviewChoices(state: ReviewChoicesState): string {
  const choices = Object.fromEntries(Object.keys(state.choices).sort().map(id => {
    const choice = state.choices[id]
    return [id, {
      id,
      templateVersion: choice.templateVersion,
      decision: isDecision(choice.decision) ? choice.decision : 'pending',
      notes: clampNotes(choice.notes),
    }]
  }))
  return JSON.stringify({ schemaVersion: REVIEW_DECISIONS_SCHEMA_VERSION, catalogVersion: state.catalogVersion, choices })
}

export function createReviewExport(state: ReviewChoicesState, exportedAt = new Date().toISOString()): ReviewExport {
  return {
    schemaVersion: REVIEW_DECISIONS_SCHEMA_VERSION,
    catalogVersion: state.catalogVersion,
    exportedAt,
    templates: Object.keys(state.choices).sort().map(id => {
      const choice = state.choices[id]
      return {
        id,
        templateVersion: choice.templateVersion,
        decision: isDecision(choice.decision) ? choice.decision : 'pending',
        notes: clampNotes(choice.notes),
      }
    }),
  }
}

export function serializeReviewExport(state: ReviewChoicesState, exportedAt?: string): string {
  return JSON.stringify(createReviewExport(state, exportedAt), null, 2)
}
