import {
  ALL_SCENE_TEMPLATES,
  CATALOG_VERSION,
  CANDIDATE_SCENE_TEMPLATES,
  EXPANDED_CATALOG_VERSION,
} from './catalog'
import {
  REVIEW_DECISIONS_STORAGE_KEY,
  createReviewChoices,
  parseReviewChoicesResult,
  serializeReviewChoices,
  type ReviewChoicesState,
  type ReviewTemplateRef,
} from './reviewDecisions'

export const CATALOG_REVIEW_STORAGE_KEY = `${REVIEW_DECISIONS_STORAGE_KEY}.${EXPANDED_CATALOG_VERSION}`

/** Never overwrite the legacy decisions: an older build must still read them. */
export function saveCatalogReview(storage: Pick<Storage, 'setItem'>, state: ReviewChoicesState): boolean {
  if (state.catalogVersion !== EXPANDED_CATALOG_VERSION) return false
  try {
    storage.setItem(CATALOG_REVIEW_STORAGE_KEY, serializeReviewChoices(state))
    return true
  } catch {
    return false
  }
}

export interface CatalogReviewLoadResult {
  state: ReviewChoicesState
  warning?: string
}

const reviewRefs = (templates: readonly { id: string; version: string | number }[]): ReviewTemplateRef[] => (
  templates.map(template => ({ id: template.id, version: template.version }))
)

const LEGACY_REFS = reviewRefs(CANDIDATE_SCENE_TEMPLATES)
const EXPANDED_REFS = reviewRefs(ALL_SCENE_TEMPLATES)

const blankExpandedReview = () => createReviewChoices(EXPANDED_CATALOG_VERSION, EXPANDED_REFS)

const rawCatalogVersion = (raw: string): unknown => {
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return undefined
    return (parsed as Record<string, unknown>).catalogVersion
  } catch {
    return undefined
  }
}

const migrationWarning = (legacyWarning?: string) => [
  'Valid decisions for the 24 previous templates were kept; the 24 new templates stay pending and are not auto-approved.',
  legacyWarning,
].filter(Boolean).join(' ')

const migrateLegacyChoices = (legacyState: ReviewChoicesState): ReviewChoicesState => {
  const state = blankExpandedReview()
  const legacyVersions = new Map(LEGACY_REFS.map(template => [template.id, String(template.version)]))

  for (const [id, choice] of Object.entries(legacyState.choices)) {
    const expectedVersion = legacyVersions.get(id)
    if (expectedVersion === undefined || String(choice.templateVersion) !== expectedVersion) continue
    state.choices[id] = { ...choice, templateVersion: legacyState.choices[id].templateVersion }
  }
  return state
}

/**
 * Loads the expanded candidate gallery without treating the legacy review
 * file as approval for newly-added templates. Valid legacy rows are migrated
 * by ID and template version; every new row starts pending.
 */
export function loadCatalogReview(storage: Pick<Storage, 'getItem'>): CatalogReviewLoadResult {
  let raw: string | null
  try {
    raw = storage.getItem(CATALOG_REVIEW_STORAGE_KEY)
    if (raw !== null) return parseReviewChoicesResult(raw, EXPANDED_CATALOG_VERSION, EXPANDED_REFS)
    raw = storage.getItem(REVIEW_DECISIONS_STORAGE_KEY)
  } catch {
    return {
      state: blankExpandedReview(),
      warning: 'Storage could not be read; decisions stay pending in this session.',
    }
  }

  if (rawCatalogVersion(raw || '') === CATALOG_VERSION) {
    const legacy = parseReviewChoicesResult(raw, CATALOG_VERSION, LEGACY_REFS)
    return { state: migrateLegacyChoices(legacy.state), warning: migrationWarning(legacy.warning) }
  }

  return parseReviewChoicesResult(raw, EXPANDED_CATALOG_VERSION, EXPANDED_REFS)
}
