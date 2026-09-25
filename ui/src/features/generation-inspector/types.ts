export const UNKNOWN_LABEL = 'unknown' as const

export type StoredField<T> =
  | { known: true; value: T }
  | { known: false }

export type PromptTransformSource = 'guide' | 'policy' | 'provider' | 'unknown'

export interface PromptChange {
  source: PromptTransformSource
  field: string
  before: StoredField<string>
  after: StoredField<string>
}

export interface CanonicalRef {
  role: string
  assetId: string | null
  filename: string | null
  workspace: string | null
  uri: string | null
  missing: boolean
}

export interface InspectedModel {
  provider: StoredField<string | null>
  id: StoredField<string | null>
  version: StoredField<string | null>
}

export interface InspectedAttempt {
  attemptId: string
  generationId: string | null
  intentId: StoredField<string>
  outputFolder: string
  workspaceId: string | null
  originalPrompt: StoredField<string>
  effectivePrompt: StoredField<string>
  negativePrompt: StoredField<string>
  changes: PromptChange[]
  model: InspectedModel
  params: Record<string, unknown>
  refs: CanonicalRef[]
  product: string | null
  status: string | null
  createdAt: string | null
  mode: string | null
}

export type CloneKind = 'clone' | 'retry'

export type CloneWarningCode =
  | 'model_mismatch'
  | 'version_mismatch'
  | 'missing_ref'
  | 'unknown_field'

export interface CloneWarning {
  code: CloneWarningCode
  message: string
  role?: string
  field?: string
}

export interface ClonePlan {
  kind: CloneKind
  intentId: string
  intentKnown: boolean
  generationId: string
  parentAttemptId: string
  outputFolder: string
  prompt: string
  negativePrompt: string
  params: Record<string, unknown>
  refs: CanonicalRef[]
  model: InspectedModel
  warnings: CloneWarning[]
}

export interface CatalogItem {
  assetId?: string
  filename?: string
  workspace?: string
  name?: string
  id?: string
}

export interface CurrentModel {
  id?: string | null
  version?: string | null
  provider?: string | null
}

export interface CloneEnvironment {
  workspace: string
  catalog?: CatalogItem[]
  currentModel?: CurrentModel
  mint?: (prefix: string) => string
}

export interface PreflightIssue {
  code: string
  message: string
  blocking: boolean
  role?: string
  field?: string
}

export interface PreflightReport {
  ok: boolean
  issues: PreflightIssue[]
}

export interface AttemptDiffField {
  path: string
  left: StoredField<unknown>
  right: StoredField<unknown>
  changed: boolean
}

export interface AttemptDiff {
  leftId: string
  rightId: string
  fields: AttemptDiffField[]
}

export interface PortableRecipe {
  recipe_version: 1
  name: string
  mode: string
  model_type: string
  prompt_example: string
  params: Record<string, unknown>
  refs: CanonicalRef[]
  loras: Array<{ filename: string; multiplier: string | number }>
}

export interface InspectContext {
  workspace: string
  catalog?: CatalogItem[]
}

export type JsonMap = Record<string, unknown>
