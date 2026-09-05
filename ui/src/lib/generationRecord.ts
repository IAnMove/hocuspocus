/**
 * Portable GenerationRecord v1 helpers. Keep this aligned with
 * app/services/generation_record.py; it must not import stores or launch.
 */

export const GENERATION_RECORD_SCHEMA = 'hocuspocus.generation-record' as const
export const GENERATION_RECORD_SCHEMA_VERSION = 1 as const
export const PROMPT_DISPLAY_MAX = 180
export const ATTEMPT_IDENTITY_POLICY = 'new_generation_id' as const

export const GENERATION_PRODUCTS = [
  'studio',
  'story_lab',
  'series_lab',
  'director',
  'comic',
  'tools',
  'wizard',
  'video_editor',
  'video_3d',
  'character_kit',
  'system',
  'unknown',
] as const

export const GENERATION_STATUSES = [
  'planned',
  'queued',
  'running',
  'completed',
  'failed',
  'cancelled',
] as const

export type GenerationProduct = typeof GENERATION_PRODUCTS[number]
export type GenerationStatus = typeof GENERATION_STATUSES[number]

export const LEGAL_GENERATION_TRANSITIONS: Record<GenerationStatus, readonly GenerationStatus[]> = {
  planned: ['queued', 'cancelled'],
  queued: ['running', 'cancelled'],
  running: ['queued', 'completed', 'failed', 'cancelled'],
  completed: [],
  failed: [],
  cancelled: [],
}

const PRODUCT_SET = new Set<string>(GENERATION_PRODUCTS)
const STATUS_SET = new Set<string>(GENERATION_STATUSES)
const PRODUCT_ALIASES: Record<string, GenerationProduct> = {
  'studio-image': 'studio',
  'studio-video': 'studio',
  'studio-audio': 'studio',
  'story-lab': 'story_lab',
  'story-music-video': 'story_lab',
  'series-lab': 'series_lab',
  comics: 'comic',
  'video-editor': 'video_editor',
  'scene-animator-3d': 'video_3d',
  hunyuan3d: 'video_3d',
  '3d': 'video_3d',
  'character-kit': 'character_kit',
  'filesystem-import': 'system',
  legacy: 'unknown',
  upscale: 'tools',
  revoice: 'tools',
  remove_background: 'tools',
}
const PRODUCT_FROM_CAPABILITY: Record<string, GenerationProduct> = {
  generate_story_song: 'story_lab',
  start_director_production: 'director',
  upscale: 'tools',
  revoice: 'tools',
  remove_background: 'tools',
}
const SENSITIVE_KEYS = new Set([
  'api_key', 'apikey', 'authorization', 'credential', 'credentials',
  'password', 'secret', 'token', 'access_token', 'refresh_token',
  'bearer_token', 'auth_token', 'private_key',
])

export interface GenerationLineageRef {
  generation_id?: string
  asset_id?: string
  kind?: string
  uri?: string
}

export interface GenerationRecord {
  schema: typeof GENERATION_RECORD_SCHEMA
  schema_version: typeof GENERATION_RECORD_SCHEMA_VERSION
  generation_id: string
  asset_id: string
  product: GenerationProduct
  workspace_id: string
  output_folder: string
  project_id: string | null
  production_id: string | null
  cue_id: string | null
  candidate_id: string | null
  song_version: string | null
  prompt_full: string
  prompt_display: string
  model: {
    provider: string | null
    id: string | null
    version: string | null
    configuration: Record<string, unknown>
  }
  languages: {
    conversation_language: string | null
    content_language: string | null
    spoken_language: string | null
    technical_prompt_language: string | null
  }
  timestamps: {
    created_at: string | null
    queued_at: string | null
    started_at: string | null
    completed_at: string | null
    duration_ms: number | null
  }
  status: GenerationStatus
  lineage: {
    parents: GenerationLineageRef[]
    derivatives: GenerationLineageRef[]
  }
  error: { code?: string; message?: string; details?: Record<string, unknown> } | null
  retry_count: number
  cancellation: { requested: boolean; at: string | null; reason: string | null }
  location: { filename: string | null; uri: string | null; sidecar: string | null }
  links: { activity_id: string | null; catalog_id: string | null; ui_href: string | null }
  result: { kind: string | null }
}

type JsonMap = Record<string, unknown>

function text(value: unknown): string | null {
  if (typeof value !== 'string') return value == null ? null : String(value).trim() || null
  return value.trim() || null
}

function asMap(value: unknown): JsonMap {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonMap : {}
}

export function isHostPath(value: string | null | undefined): boolean {
  const candidate = (value || '').trim()
  if (!candidate) return false
  if (candidate.startsWith('/') || candidate.startsWith('\\')) return true
  return candidate.length >= 3 && candidate[1] === ':' && (candidate[2] === '/' || candidate[2] === '\\')
}

export function portableFilename(value: unknown): string | null {
  const candidate = text(value)
  if (!candidate) return null
  const name = candidate.replace(/\\/g, '/').split('/').pop() || ''
  if (!name || name === '.' || name === '..' || isHostPath(name)) return null
  return name
}

export function truncatePromptDisplay(value: unknown, limit = PROMPT_DISPLAY_MAX): string {
  const candidate = String(value || '').trim()
  if (candidate.length <= limit) return candidate
  if (limit <= 1) return '…'
  return `${candidate.slice(0, limit - 1).trimEnd()}…`
}

export function redactSecrets(value: unknown, key = ''): unknown {
  const lowered = key.toLowerCase().replace(/-/g, '_')
  if (
    SENSITIVE_KEYS.has(lowered)
    || lowered.endsWith('_api_key')
    || lowered.endsWith('_password')
    || lowered.endsWith('_secret')
    || lowered.endsWith('_token')
  ) {
    return '[REDACTED]'
  }
  if (value == null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value
  }
  if (Array.isArray(value)) return value.map(item => redactSecrets(item))
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as JsonMap).map(([child, item]) => [child, redactSecrets(item, child)]),
    )
  }
  return String(value)
}

export function mapGenerationProduct(value: unknown, capability?: unknown): GenerationProduct {
  const token = (text(value) || '').toLowerCase().replace(/ /g, '_')
  if (PRODUCT_SET.has(token)) return token as GenerationProduct
  if (token in PRODUCT_ALIASES) return PRODUCT_ALIASES[token]
  const mapped = PRODUCT_FROM_CAPABILITY[text(capability) || '']
  return mapped || 'unknown'
}

export function mapAssetManifestStatus(
  status: unknown,
  hasFilename = false,
): { status: GenerationStatus; resultKind: string | null; error: GenerationRecord['error'] } {
  const raw = (text(status) || '').toLowerCase()
  if (raw === 'prepared') return { status: 'planned', resultKind: null, error: null }
  if (raw === 'partial') {
    if (hasFilename) return { status: 'completed', resultKind: 'partial', error: null }
    return {
      status: 'failed',
      resultKind: null,
      error: { code: 'partial', message: 'Generation finished without a complete artifact' },
    }
  }
  if (STATUS_SET.has(raw)) {
    return { status: raw as GenerationStatus, resultKind: null, error: null }
  }
  if (!raw) return { status: 'planned', resultKind: null, error: null }
  return {
    status: 'failed',
    resultKind: null,
    error: { code: 'invalid_status', message: `Unsupported status '${raw}'` },
  }
}

export function mapGenerationStatusToManifest(
  status: GenerationStatus,
  resultKind?: string | null,
): string {
  if (status === 'planned') return 'prepared'
  if (status === 'completed' && resultKind === 'partial') return 'completed'
  return status
}

export function isLegalGenerationTransition(current: GenerationStatus, target: GenerationStatus): boolean {
  return LEGAL_GENERATION_TRANSITIONS[current].includes(target)
}

export function recordBelongsToWorkspace(record: Pick<GenerationRecord, 'workspace_id'>, workspaceId: string): boolean {
  return Boolean(workspaceId) && record.workspace_id === workspaceId
}

function sidecarName(filename: string | null): string | null {
  if (!filename) return null
  const dot = filename.lastIndexOf('.')
  const stem = dot > 0 ? filename.slice(0, dot) : filename
  return `${stem}.meta.json`
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    const candidate = text(value)
    if (candidate) return candidate
  }
  return null
}

function lineageRef(value: unknown): GenerationLineageRef | null {
  const raw = asMap(value)
  const generationId = text(raw.generation_id)
  const assetId = firstText(raw.asset_id, raw.id)
  if (!generationId && !assetId) return null
  const item: GenerationLineageRef = {}
  if (generationId) item.generation_id = generationId
  if (assetId) item.asset_id = assetId
  const kind = firstText(raw.kind, raw.role)
  if (kind) item.kind = kind
  const uri = portableFilename(raw.uri)
  if (uri) item.uri = uri
  return item
}

function lineageParents(value: unknown): GenerationLineageRef[] {
  if (!Array.isArray(value)) return []
  return value.map(lineageRef).filter((item): item is GenerationLineageRef => item != null)
}

function manifestPrompt(prompts: JsonMap): string {
  return firstText(prompts.effective, prompts.original, prompts.audio) || ''
}

function manifestError(execution: JsonMap, fallback: GenerationRecord['error']): GenerationRecord['error'] {
  const error = asMap(execution.error)
  if (error.code || error.message) return error as GenerationRecord['error']
  return fallback
}

export function projectFromAssetManifest(manifest: unknown): GenerationRecord {
  const value = asMap(manifest)
  const asset = asMap(value.asset)
  const origin = asMap(value.origin)
  const execution = asMap(value.execution)
  const generation = asMap(value.generation)
  const timing = asMap(value.timing)
  const technical = asMap(value.technical)
  const model = asMap(generation.model)
  const prompts = asMap(generation.prompts)
  const languages = asMap(generation.languages)
  const filename = portableFilename(firstText(asset.filename, asset.uri))
  const mapped = mapAssetManifestStatus(execution.status, Boolean(filename))
  const assetId = firstText(asset.id) || 'asset_unknown'
  const workspaceId = firstText(origin.workspace_id) || 'unknown'
  const prompt = manifestPrompt(prompts)
  return {
    schema: GENERATION_RECORD_SCHEMA,
    schema_version: GENERATION_RECORD_SCHEMA_VERSION,
    generation_id: firstText(technical.generation_id, execution.job_id) || `gen_${assetId}`,
    asset_id: assetId,
    product: mapGenerationProduct(origin.tool, origin.capability),
    workspace_id: workspaceId,
    output_folder: portableFilename(origin.output_folder) || workspaceId,
    project_id: text(asMap(origin.project).id),
    production_id: text(asMap(origin.production).id),
    cue_id: text(execution.cue_id),
    candidate_id: text(execution.candidate_id),
    song_version: text(execution.song_version),
    prompt_full: prompt,
    prompt_display: truncatePromptDisplay(prompt),
    model: {
      provider: text(model.provider),
      id: text(model.id),
      version: firstText(model.version, model.revision),
      configuration: redactSecrets(asMap(generation.parameters)) as Record<string, unknown>,
    },
    languages: {
      conversation_language: text(languages.conversation_language),
      content_language: firstText(languages.content_language, prompts.language),
      spoken_language: text(languages.spoken_language),
      technical_prompt_language: text(languages.technical_prompt_language),
    },
    timestamps: {
      created_at: text(timing.created_at),
      queued_at: text(timing.queued_at),
      started_at: text(timing.started_at),
      completed_at: text(timing.completed_at),
      duration_ms: typeof timing.total_ms === 'number' ? timing.total_ms : null,
    },
    status: mapped.status,
    lineage: { parents: lineageParents(asMap(value.lineage).parents), derivatives: [] },
    error: manifestError(execution, mapped.error),
    retry_count: 0,
    cancellation: { requested: false, at: null, reason: null },
    location: { filename, uri: filename, sidecar: sidecarName(filename) },
    links: {
      activity_id: firstText(technical.activity_id, execution.task_id),
      catalog_id: assetId,
      ui_href: null,
    },
    result: { kind: mapped.resultKind },
  }
}

export function toAssetManifestPatch(record: GenerationRecord): JsonMap {
  const filename = record.location.filename
  const parents = record.lineage.parents.flatMap(item => (
    item.asset_id ? [{ id: item.asset_id, kind: item.kind || 'other', ...(item.uri ? { uri: item.uri } : {}) }] : []
  ))
  return {
    asset: { id: record.asset_id, filename, uri: record.location.uri || filename },
    origin: {
      tool: record.product,
      workspace_id: record.workspace_id,
      output_folder: record.output_folder,
      project: record.project_id ? { kind: 'project', id: record.project_id } : null,
      production: record.production_id ? { kind: 'production', id: record.production_id } : null,
    },
    execution: {
      status: mapGenerationStatusToManifest(record.status, record.result.kind),
      error: record.error,
      cue_id: record.cue_id,
      candidate_id: record.candidate_id,
      song_version: record.song_version,
    },
    generation: {
      prompts: { original: record.prompt_full, effective: record.prompt_full },
      model: { provider: record.model.provider, id: record.model.id, revision: record.model.version },
      parameters: record.model.configuration,
      inputs: parents,
    },
    timing: {
      created_at: record.timestamps.created_at,
      queued_at: record.timestamps.queued_at,
      started_at: record.timestamps.started_at,
      completed_at: record.timestamps.completed_at,
      total_ms: record.timestamps.duration_ms,
    },
    lineage: { parents, transformations: [] },
    technical: { generation_id: record.generation_id, result: record.result },
  }
}

function mintAttemptId(prefix: string): string {
  const token = globalThis.crypto?.randomUUID?.().replace(/-/g, '')
    || `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`
  return `${prefix}_${token.slice(0, 24)}`
}

export function retryGeneration(record: GenerationRecord, sameArtifact = false): Pick<
  GenerationRecord,
  'asset_id' | 'generation_id' | 'retry_count' | 'lineage' | 'status' | 'workspace_id'
> {
  return {
    generation_id: mintAttemptId('gen'),
    asset_id: sameArtifact ? record.asset_id : mintAttemptId('asset'),
    retry_count: record.retry_count + 1,
    status: 'planned',
    workspace_id: record.workspace_id,
    lineage: {
      parents: [{
        generation_id: record.generation_id,
        asset_id: record.asset_id,
        kind: 'attempt',
      }],
      derivatives: [],
    },
  }
}

export function requestCancel(record: GenerationRecord): Pick<GenerationRecord, 'status' | 'cancellation'> {
  if (record.status === 'completed' || record.status === 'failed' || record.status === 'cancelled') {
    return { status: record.status, cancellation: record.cancellation }
  }
  const cancellation = { requested: true, at: record.cancellation.at, reason: record.cancellation.reason }
  if (record.status === 'planned' || record.status === 'queued') {
    return { status: 'cancelled', cancellation }
  }
  return { status: record.status, cancellation }
}

export function applyCancel(record: GenerationRecord): Pick<GenerationRecord, 'status' | 'cancellation'> {
  if (record.status === 'completed' || record.status === 'failed' || record.status === 'cancelled') {
    return { status: record.status, cancellation: record.cancellation }
  }
  return {
    status: 'cancelled',
    cancellation: { requested: true, at: record.cancellation.at, reason: record.cancellation.reason },
  }
}
