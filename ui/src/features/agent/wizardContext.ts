import { useStore } from '../../stores/useStore'
import { emptyCharacterKitLibrary } from '../../lib/characterKit'
import { comicArtworkInventory } from '../comics/generateArtwork'
import { useComicStore } from '../comics/store'
import { loadEditorDraft } from '../video-editor/editorDraft'
import { sequenceTotalDuration } from '../video-editor/editorTimeline'
import { useSeriesStore } from '../series/store'
import { useStoryStore } from '../stories/store'
import { rememberedCharacterKitLibrary, rememberedVideo3dScene } from './wizardLabSession'
import type { MediaFilter } from '../../types'

/**
 * Version of the context sent to the Wizard.  This is deliberately separate
 * from the versions of the individual lab documents: a context snapshot is a
 * short-lived read model and can evolve without changing Story/Series data.
 */
export const WIZARD_CONTEXT_VERSION = 1 as const
export const WIZARD_CONTEXT_SCHEMA = 'hocuspocus.wizard_context' as const

export type WizardContextVersion = typeof WIZARD_CONTEXT_VERSION

export interface WizardCanonicalRef {
  /** Stable application identity. Never inferred from `label`. */
  id: string
  kind: string
  workspace_id: string
  /** Human-readable display-only metadata. */
  label: string
  version: number | null
  source: 'store' | 'session' | 'output' | 'draft' | 'workflow'
}

export interface WizardArtifactRef extends WizardCanonicalRef {
  kind: 'output' | 'artifact' | 'scene' | 'asset' | string
  uri: string
  task_id: string
  metadata: Record<string, unknown>
}

export interface WizardTaskRef extends WizardCanonicalRef {
  kind: 'job' | 'task'
  status: string
  phase: string
  progress: number | null
  message: string
}

export interface WizardPipelineRef extends WizardCanonicalRef {
  kind: 'pipeline'
  status: string
  phase: string
  progress: number | null
  message: string
  output_ids: string[]
}

export interface WizardContextLocation {
  area: string
  tab: string
  section: string
}

export interface WizardContextActive {
  workspace_id: string
  location: WizardContextLocation
  entity: WizardCanonicalRef | null
  project: WizardCanonicalRef | null
  cue: WizardCanonicalRef | null
  /** The production is distinct from its source project and music cue. */
  production: WizardCanonicalRef | null
  output: WizardArtifactRef | null
  job: WizardTaskRef | null
  pipeline: WizardPipelineRef | null
}

export interface WizardContextSelection {
  page_id: string
  element_id: string
  series_id: string
  episode_id: string
  shot_id: string
  layer_id: string
  kit_id: string
  clip_index: number | null
}

export interface WizardDraftSnapshot {
  dirty: boolean
  /** Persisted content revision, when the owning store exposes one. */
  version: number | null
  /** Schema/document version, kept distinct from content revision. */
  schema_version: number | null
  library_revision: number | null
  updated_at: string
  source: 'store' | 'session' | 'draft' | 'none'
}

export type WizardDrafts = Record<string, WizardDraftSnapshot>

export interface WizardWorkflowContext {
  id: string
  type: string
  state: string
  step_id: string
  step_index: number | null
  total_steps: number | null
  attempt: number
  task_ids: string[]
  pipeline_ids: string[]
  output_ids: string[]
  resolved_entity_ids: Record<string, string>
  updated_at: number | null
}

export interface WizardPendingQuestion {
  id: string
  workflow_id: string
  step_id: string
  reason: string
  fields: string[]
  options: Array<{ value: string; label: string }>
  recommended_value: string
  resolved_entity_ids: Record<string, string>
  answer: unknown
  created_at: number | null
  version: number | null
}

export interface WizardContextCapabilities {
  available: string[]
  blocked: Array<{ name: string; reason: string }>
}

export interface WizardContextSnapshot {
  schema: typeof WIZARD_CONTEXT_SCHEMA
  version: WizardContextVersion
  captured_at: string
  workspace: {
    id: string
    name: string
    path: string
  }
  active: WizardContextActive
  selection: WizardContextSelection
  drafts: WizardDrafts
  /** Relevant persisted outputs, in addition to the currently selected one. */
  artifacts: WizardArtifactRef[]
  /** Relevant queue tasks and Director pipelines, keyed by their real IDs. */
  tasks: WizardTaskRef[]
  pipelines: WizardPipelineRef[]
  workflow: WizardWorkflowContext | null
  pending_question: WizardPendingQuestion | null
  capabilities: WizardContextCapabilities
  /** Existing compact lab summaries remain available to current consumers. */
  labs: WizardLabSnapshots
}

export interface WizardContextPresenceInput {
  area?: string
  tab?: string
  section?: string
  entity_id?: string
  project_id?: string
  cue_id?: string
  production_id?: string
  output_id?: string
  job_id?: string
  pipeline_id?: string
  page_id?: string
  element_id?: string
  series_id?: string
  episode_id?: string
  shot_id?: string
  layer_id?: string
  kit_id?: string
  clip_index?: number
}

export interface BuildWizardContextOptions {
  /** UI presence supplied by a mounted panel; all values are exact IDs. */
  presence?: WizardContextPresenceInput
  workflow?: unknown
  pending_question?: unknown
  /** Optional server/registry capability projection for later integration. */
  capabilities?: unknown
  captured_at?: string
}

export interface WizardLabSnapshots {
  story: {
    project_id: string
    title: string
    project_type: string
    characters: number
    productions: number
    visual_jobs: number
    active_cue_title: string
    selected_song_name: string
    selected_song_id: string
    state: string
  }
  series: {
    series_id: string
    title: string
    episode_id: string
    episode_title: string
    shots: number
    approved: number
    failed: number
    state: string
  }
  video_3d: {
    scene_id: string
    title: string
    layers: number
    state: string
  }
  character_kit: {
    kit_id: string
    title: string
    poses: number
    mouth: number
    eyes: number
    state: string
  }
  video_editor: {
    project_id: string
    title: string
    clips: number
    duration: number
    export_job: string
    state: string
  }
}

type UnknownRecord = Record<string, unknown>
type WizardRefSource = WizardCanonicalRef['source']

const EMPTY_LOCATION: WizardContextLocation = { area: '', tab: '', section: '' }
const EMPTY_SELECTION: WizardContextSelection = {
  page_id: '', element_id: '', series_id: '', episode_id: '', shot_id: '',
  layer_id: '', kit_id: '', clip_index: null,
}

function record(value: unknown): UnknownRecord {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord : {}
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value.trim() : fallback
}

function idValue(value: unknown): string {
  // Do not coerce labels, numbers or arbitrary objects into identities. The
  // backend uses opaque strings for durable IDs, and an absent ID must remain
  // absent so a caller cannot accidentally target a same-titled document.
  return typeof value === 'string' ? value.trim() : ''
}

function integerValue(value: unknown, fallback: number | null = null): number | null {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(number) && number >= 0 ? number : fallback
}

function versionValue(value: unknown): number | null {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(number) && number > 0 ? number : null
}

function progressValue(value: unknown): number | null {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : null
}

function uniqueStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return [...new Set(value.filter(item => typeof item === 'string').map(item => item.trim()).filter(Boolean))]
}

/**
 * Convert the small read model to JSON-safe data. This intentionally drops
 * functions/symbols and replaces circular references instead of serializing
 * live Zustand state (which may contain File objects or callbacks).
 */
export function toWizardSerializable(value: unknown): unknown {
  // Track the current recursion path, not every object ever visited. A read
  // model may intentionally reference the same artifact from `active` and
  // from the top-level index; shared values should be emitted twice, while a
  // true cycle must still be cut.
  const ancestors = new WeakSet<object>()
  const visit = (item: unknown, depth: number): unknown => {
    if (item == null || typeof item === 'string' || typeof item === 'boolean') return item
    if (typeof item === 'number') return Number.isFinite(item) ? item : null
    if (typeof item === 'bigint') return item.toString()
    if (typeof item !== 'object' || depth > 12) return undefined
    if (ancestors.has(item)) return undefined
    ancestors.add(item)
    try {
      if (item instanceof Date) return item.toISOString()
      if (Array.isArray(item)) return item.map(child => visit(child, depth + 1)).filter(child => child !== undefined)
      const result: UnknownRecord = {}
      Object.entries(item as UnknownRecord).forEach(([key, child]) => {
        const serialized = visit(child, depth + 1)
        if (serialized !== undefined) result[key] = serialized
      })
      return result
    } finally {
      ancestors.delete(item)
    }
  }
  return visit(value, 0)
}

function safeSource(value: unknown, fallback: WizardRefSource): WizardRefSource {
  return value === 'store' || value === 'session' || value === 'output'
    || value === 'draft' || value === 'workflow' ? value : fallback
}

function objectRecord(value: unknown): value is UnknownRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function makeRef(
  id: unknown,
  kind: string,
  workspaceId: string,
  label = '',
  version: unknown = null,
  source: WizardRefSource = 'store',
): WizardCanonicalRef | null {
  const canonicalId = idValue(id)
  if (!canonicalId) return null
  return {
    id: canonicalId,
    kind: stringValue(kind, 'entity'),
    workspace_id: workspaceId,
    label: stringValue(label),
    version: versionValue(version),
    source,
  }
}

function normalizeRef(value: unknown, workspaceId: string, fallbackKind = 'entity'): WizardCanonicalRef | null {
  const raw = record(value)
  const referencedWorkspace = idValue(raw.workspace_id || raw.workspaceId)
  // A snapshot is scoped to one workspace. Silently re-scoping a reference
  // from another workspace would make a later command target the wrong
  // resource, so reject it instead of trusting a display label.
  if (referencedWorkspace && referencedWorkspace !== workspaceId) return null
  const ref = makeRef(
    raw.id,
    stringValue(raw.kind || raw.type, fallbackKind),
    workspaceId,
    stringValue(raw.label || raw.title || raw.name),
    raw.version,
    safeSource(raw.source, 'store'),
  )
  return ref
}

function normalizeArtifact(value: unknown, workspaceId: string): WizardArtifactRef | null {
  const raw = record(value)
  const ref = normalizeRef({ ...raw, id: raw.id || raw.output_id || raw.outputId || raw.artifact_id || raw.artifactId }, workspaceId, 'output')
  if (!ref) return null
  return {
    ...ref,
    kind: stringValue(raw.kind || raw.type, 'output'),
    uri: stringValue(raw.uri || raw.url || raw.source),
    task_id: idValue(raw.task_id || raw.taskId),
    metadata: (toWizardSerializable(raw.metadata) || {}) as Record<string, unknown>,
  }
}

function normalizeTask(value: unknown, workspaceId: string): WizardTaskRef | null {
  const raw = record(value)
  const ref = normalizeRef({ ...raw, id: raw.id || raw.task_id || raw.taskId || raw.job_id || raw.jobId }, workspaceId, 'job')
  if (!ref) return null
  return {
    ...ref,
    kind: stringValue(raw.kind || raw.type, 'job') === 'task' ? 'task' : 'job',
    status: stringValue(raw.status, 'unknown'),
    phase: stringValue(raw.phase),
    progress: progressValue(raw.progress),
    message: stringValue(raw.message),
  }
}

function normalizePipeline(value: unknown, workspaceId: string): WizardPipelineRef | null {
  const raw = record(value)
  const ref = normalizeRef({ ...raw, id: raw.id || raw.pipeline_id || raw.pipelineId }, workspaceId, 'pipeline')
  if (!ref) return null
  return {
    ...ref,
    kind: 'pipeline',
    status: stringValue(raw.status, 'unknown'),
    phase: stringValue(raw.phase),
    progress: progressValue(raw.progress),
    message: stringValue(raw.message),
    output_ids: uniqueStrings(raw.output_ids || raw.outputIds || raw.output_files || raw.outputFiles),
  }
}

function normalizeLocation(value: unknown): WizardContextLocation {
  const raw = record(value)
  return {
    area: stringValue(raw.area, EMPTY_LOCATION.area),
    tab: stringValue(raw.tab, EMPTY_LOCATION.tab),
    section: stringValue(raw.section, EMPTY_LOCATION.section),
  }
}

function normalizeSelection(value: unknown): WizardContextSelection {
  const raw = record(value)
  return {
    page_id: idValue(raw.page_id || raw.pageId) || EMPTY_SELECTION.page_id,
    element_id: idValue(raw.element_id || raw.elementId) || EMPTY_SELECTION.element_id,
    series_id: idValue(raw.series_id || raw.seriesId) || EMPTY_SELECTION.series_id,
    episode_id: idValue(raw.episode_id || raw.episodeId) || EMPTY_SELECTION.episode_id,
    shot_id: idValue(raw.shot_id || raw.shotId) || EMPTY_SELECTION.shot_id,
    layer_id: idValue(raw.layer_id || raw.layerId) || EMPTY_SELECTION.layer_id,
    kit_id: idValue(raw.kit_id || raw.kitId) || EMPTY_SELECTION.kit_id,
    clip_index: integerValue(raw.clip_index ?? raw.clipIndex),
  }
}

function normalizeDraft(value: unknown): WizardDraftSnapshot {
  const raw = record(value)
  const source = raw.source === 'store' || raw.source === 'session' || raw.source === 'draft'
    ? raw.source : 'none'
  return {
    dirty: raw.dirty === true,
    version: versionValue(raw.version),
    schema_version: versionValue(raw.schema_version || raw.schemaVersion),
    library_revision: integerValue(raw.library_revision ?? raw.libraryRevision),
    updated_at: stringValue(raw.updated_at || raw.updatedAt),
    source,
  }
}

function normalizeDrafts(value: unknown): WizardDrafts {
  const raw = record(value)
  const drafts: WizardDrafts = {}
  Object.entries(raw).forEach(([key, item]) => { drafts[key] = normalizeDraft(item) })
  return drafts
}

function normalizeIdMap(value: unknown): Record<string, string> {
  const result: Record<string, string> = {}
  Object.entries(record(value)).forEach(([key, item]) => {
    const id = idValue(item)
    if (key.trim() && id) result[key.trim()] = id
  })
  return result
}

function normalizeWorkflow(value: unknown): WizardWorkflowContext | null {
  const raw = record(value)
  const id = idValue(raw.id || raw.workflow_id || raw.workflowId)
  if (!id) return null
  const steps = Array.isArray(raw.steps) ? raw.steps : []
  const step = record(raw.step)
  const stepIndex = integerValue(raw.step_index ?? raw.stepIndex ?? raw.current_step ?? raw.currentStep)
  const indexedStep = stepIndex == null ? undefined : steps[stepIndex]
  const indexedStepRecord = record(indexedStep)
  const stepId = idValue(
    raw.step_id || raw.stepId
      || step.id || step.step_id || step.stepId
      || (typeof indexedStep === 'string' ? indexedStep : '')
      || indexedStepRecord.id || indexedStepRecord.step_id || indexedStepRecord.stepId,
  )
  return {
    id,
    type: stringValue(raw.type),
    state: stringValue(raw.state, 'prepared'),
    step_id: stepId,
    step_index: stepIndex,
    total_steps: integerValue(raw.total_steps ?? raw.totalSteps, steps.length || null),
    attempt: integerValue(raw.attempt ?? raw.attempts, 0) || 0,
    task_ids: uniqueStrings(raw.task_ids || raw.taskIds),
    pipeline_ids: uniqueStrings(raw.pipeline_ids || raw.pipelineIds),
    output_ids: uniqueStrings(raw.output_ids || raw.outputIds || raw.output_refs || raw.outputRefs),
    resolved_entity_ids: normalizeIdMap(raw.resolved_entity_ids || raw.resolvedEntityIds),
    updated_at: integerValue(raw.updated_at ?? raw.updatedAt),
  }
}

function normalizeQuestionOption(value: unknown): { value: string; label: string } | null {
  if (typeof value === 'string') {
    const option = value.trim()
    return option ? { value: option, label: option } : null
  }
  const raw = record(value)
  const optionValue = idValue(raw.value || raw.id)
  if (!optionValue) return null
  return { value: optionValue, label: stringValue(raw.label || raw.title, optionValue) }
}

function normalizePendingQuestion(
  value: unknown,
  workflowFallback?: WizardWorkflowContext | null,
): WizardPendingQuestion | null {
  const raw = record(value)
  const workflowId = idValue(raw.workflow_id || raw.workflowId) || workflowFallback?.id || ''
  const stepId = idValue(raw.step_id || raw.stepId) || workflowFallback?.step_id || ''
  const explicitId = idValue(raw.id || raw.question_id || raw.questionId)
  // A question without both canonical owners cannot be safely resumed. Even
  // an explicit question ID is insufficient because it would not identify
  // which workflow step receives the answer.
  if (!workflowId || !stepId) return null
  const options = (Array.isArray(raw.options) ? raw.options : [])
    .map(normalizeQuestionOption)
    .filter((item): item is { value: string; label: string } => Boolean(item))
    .filter((item, index, list) => list.findIndex(candidate => candidate.value === item.value) === index)
  const questionResolvedIds = normalizeIdMap(raw.resolved_entity_ids || raw.resolvedEntityIds)
  return {
    // A generated question ID is derived only from already canonical workflow
    // and step IDs; it is never based on a human title or question text.
    id: explicitId || `question:${workflowId}:${stepId}`,
    workflow_id: workflowId,
    step_id: stepId,
    reason: stringValue(raw.reason || raw.message),
    fields: uniqueStrings(raw.fields || raw.required_fields || raw.requiredFields),
    options,
    recommended_value: idValue(raw.recommended_value || raw.recommendedValue || raw.recommended || raw.default),
    resolved_entity_ids: Object.keys(questionResolvedIds).length
      ? questionResolvedIds : workflowFallback ? { ...workflowFallback.resolved_entity_ids } : {},
    answer: raw.answer === undefined ? null : toWizardSerializable(raw.answer),
    created_at: integerValue(raw.created_at ?? raw.createdAt),
    version: versionValue(raw.version),
  }
}

function normalizeArtifacts(value: unknown, workspaceId: string): WizardArtifactRef[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value
    .map(item => normalizeArtifact(item, workspaceId))
    .filter((item): item is WizardArtifactRef => Boolean(item))
    .filter(item => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })
}

function normalizeTasks(value: unknown, workspaceId: string): WizardTaskRef[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value
    .map(item => normalizeTask(item, workspaceId))
    .filter((item): item is WizardTaskRef => Boolean(item))
    .filter(item => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })
}

function normalizePipelines(value: unknown, workspaceId: string): WizardPipelineRef[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value
    .map(item => normalizePipeline(item, workspaceId))
    .filter((item): item is WizardPipelineRef => Boolean(item))
    .filter(item => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })
}

function normalizeCapabilities(value: unknown): WizardContextCapabilities {
  const raw = Array.isArray(value) ? { available: value } : record(value)
  const available = uniqueStrings(raw.available || raw.allowed || raw.capability_ids || raw.capabilities)
  const blocked = (Array.isArray(raw.blocked) ? raw.blocked : [])
    .map(item => {
      const itemRecord = record(item)
      const name = idValue(itemRecord.name || itemRecord.id)
      return name ? { name, reason: stringValue(itemRecord.reason) } : null
    })
    .filter((item): item is { name: string; reason: string } => Boolean(item))
    .filter((item, index, list) => list.findIndex(candidate => candidate.name === item.name) === index)
  return { available, blocked }
}

function normalizeLabSnapshots(value: unknown): WizardLabSnapshots {
  const raw = record(value)
  const story = record(raw.story)
  const series = record(raw.series)
  const video3d = record(raw.video_3d || raw.video3d)
  const kit = record(raw.character_kit || raw.characterKit)
  const editor = record(raw.video_editor || raw.videoEditor)
  const count = (item: unknown): number => integerValue(item, 0) || 0
  return {
    story: {
      project_id: idValue(story.project_id || story.projectId), title: stringValue(story.title),
      project_type: stringValue(story.project_type || story.projectType), characters: count(story.characters),
      productions: count(story.productions), visual_jobs: count(story.visual_jobs || story.visualJobs),
      active_cue_title: stringValue(story.active_cue_title || story.activeCueTitle),
      selected_song_name: stringValue(story.selected_song_name || story.selectedSongName),
      selected_song_id: idValue(story.selected_song_id || story.selectedSongId), state: stringValue(story.state, 'empty'),
    },
    series: {
      series_id: idValue(series.series_id || series.seriesId), title: stringValue(series.title),
      episode_id: idValue(series.episode_id || series.episodeId), episode_title: stringValue(series.episode_title || series.episodeTitle),
      shots: count(series.shots), approved: count(series.approved), failed: count(series.failed), state: stringValue(series.state, 'empty'),
    },
    video_3d: {
      scene_id: idValue(video3d.scene_id || video3d.sceneId), title: stringValue(video3d.title),
      layers: count(video3d.layers), state: stringValue(video3d.state, 'empty'),
    },
    character_kit: {
      kit_id: idValue(kit.kit_id || kit.kitId), title: stringValue(kit.title), poses: count(kit.poses),
      mouth: count(kit.mouth), eyes: count(kit.eyes), state: stringValue(kit.state, 'empty'),
    },
    video_editor: {
      project_id: idValue(editor.project_id || editor.projectId), title: stringValue(editor.title),
      clips: count(editor.clips), duration: Number.isFinite(Number(editor.duration)) ? Number(editor.duration) : 0,
      export_job: idValue(editor.export_job || editor.exportJob), state: stringValue(editor.state, 'empty'),
    },
  }
}

/**
 * Normalize a context received from a store, API or persisted workflow. It is
 * intentionally lossy: only the stable-ID read model is retained, while
 * labels remain display metadata and can never become a target identifier.
 */
export function normalizeWizardContextSnapshot(
  value: unknown,
  fallbackWorkspace = 'default',
): WizardContextSnapshot {
  const raw = record(value)
  const workspaceRaw = record(raw.workspace)
  const workspaceId = idValue(workspaceRaw.id || raw.workspace_id || raw.workspaceId)
    || idValue(fallbackWorkspace) || 'default'
  const activeRaw = record(raw.active)
  const location = normalizeLocation(activeRaw.location || raw.location)
  const workspacePath = stringValue(workspaceRaw.path || raw.workspace_path || raw.workspacePath)
  // There is one workspace scope per snapshot. Keep the active scope aligned
  // with the top-level workspace rather than allowing stale nested metadata
  // to make the LLM believe it is looking at two workspaces at once.
  const activeWorkspaceId = workspaceId
  const workflow = normalizeWorkflow(raw.workflow)
  const pendingQuestion = normalizePendingQuestion(
    raw.pending_question || raw.pendingQuestion || record(raw.workflow).pendingInput,
    workflow,
  )
  if (pendingQuestion && workflow && workflow.state !== 'awaiting_input') workflow.state = 'awaiting_input'
  const active = {
    workspace_id: activeWorkspaceId,
    location,
    entity: normalizeRef(activeRaw.entity || raw.entity, activeWorkspaceId),
    project: normalizeRef(activeRaw.project || raw.project, activeWorkspaceId, 'project'),
    cue: normalizeRef(activeRaw.cue || raw.cue, activeWorkspaceId, 'cue'),
    production: normalizeRef(activeRaw.production || raw.production, activeWorkspaceId, 'production'),
    output: normalizeArtifact(activeRaw.output || raw.output, activeWorkspaceId),
    job: normalizeTask(activeRaw.job || raw.job, activeWorkspaceId),
    pipeline: normalizePipeline(activeRaw.pipeline || raw.pipeline, activeWorkspaceId),
  }
  const capturedAt = stringValue(raw.captured_at || raw.capturedAt)
  const normalized: WizardContextSnapshot = {
    schema: WIZARD_CONTEXT_SCHEMA,
    version: WIZARD_CONTEXT_VERSION,
    captured_at: capturedAt || new Date().toISOString(),
    workspace: { id: workspaceId, name: stringValue(workspaceRaw.name, workspaceId), path: workspacePath },
    active,
    selection: normalizeSelection(raw.selection),
    drafts: normalizeDrafts(raw.drafts),
    artifacts: normalizeArtifacts(raw.artifacts || raw.outputs || raw.available_artifacts || raw.availableArtifacts, workspaceId),
    tasks: normalizeTasks(raw.tasks || raw.jobs, workspaceId),
    pipelines: normalizePipelines(raw.pipelines, workspaceId),
    workflow,
    pending_question: pendingQuestion,
    capabilities: normalizeCapabilities(raw.capabilities),
    labs: normalizeLabSnapshots(raw.labs),
  }
  // Every field above is primitive/JSON-safe. Run the complete object through
  // the serializer once so this guarantee remains true if a future read model
  // adds a non-JSON value to metadata or a pending answer.
  return toWizardSerializable(normalized) as WizardContextSnapshot
}

export function serializeWizardContextSnapshot(value: unknown, fallbackWorkspace = 'default'): string {
  return JSON.stringify(normalizeWizardContextSnapshot(value, fallbackWorkspace))
}

export function isWizardContextSnapshot(value: unknown): value is WizardContextSnapshot {
  const raw = record(value)
  const workspace = raw.workspace
  const active = raw.active
  return raw.schema === WIZARD_CONTEXT_SCHEMA && raw.version === WIZARD_CONTEXT_VERSION
    && objectRecord(workspace) && typeof workspace.id === 'string' && Boolean(workspace.id.trim())
    && objectRecord(active) && typeof active.workspace_id === 'string'
    && objectRecord(active.location)
}

function storySnapshot(): WizardLabSnapshots['story'] {
  const { project } = useStoryStore.getState()
  const visualJobs = project.visualJobs ? Object.keys(project.visualJobs).length : 0
  const running = Object.values(project.visualJobs || {}).some(status => /run|queue/i.test(String(status)))
  const cue = project.music?.cues?.find(item => (
    item.selectedCandidateId && item.candidates.some(candidate => candidate.id === item.selectedCandidateId)
  )) || project.music?.cues?.find(item => item.kind === 'story')
  const selectedId = cue?.selectedCandidateId || project.music?.selectedCandidateId || ''
  const candidate = cue?.candidates.find(item => item.id === selectedId)
    || project.music?.candidates?.find(item => item.id === selectedId)
  return {
    project_id: project.id || '',
    title: project.title || '',
    project_type: project.projectType || '',
    characters: project.characters?.length || 0,
    productions: project.productions?.length || 0,
    visual_jobs: visualJobs,
    active_cue_title: cue?.title || '',
    selected_song_name: candidate?.displayName || candidate?.title || candidate?.name || '',
    selected_song_id: candidate?.id || '',
    state: running ? 'running' : project.title && project.title !== 'Untitled story' ? 'ready' : 'empty',
  }
}

function seriesSnapshot(): WizardLabSnapshots['series'] {
  const state = useSeriesStore.getState()
  const series = state.library.seriesById[state.activeSeriesId]
  const episode = series?.episodesById[state.activeEpisodeId]
  const shots = episode?.shots || []
  const approved = shots.filter(shot => Boolean(shot.approvedAttemptId)).length
  const failed = shots.filter(shot => shot.attempts?.some(attempt => attempt.status === 'failed')).length
  return {
    series_id: series?.id || '',
    title: series?.title || '',
    episode_id: episode?.id || '',
    episode_title: episode?.title || '',
    shots: shots.length,
    approved,
    failed,
    state: state.renderRecovery.length ? 'running' : episode ? 'ready' : 'empty',
  }
}

function video3dSnapshot(): WizardLabSnapshots['video_3d'] {
  const remembered = rememberedVideo3dScene()
  if (remembered) return remembered
  const latest = useStore.getState().outputs.find(output => output.type === 'scene')
  return {
    scene_id: latest?.name || '',
    title: latest?.name || '',
    layers: 0,
    state: latest ? 'saved' : 'empty',
  }
}

function characterKitSnapshot(): WizardLabSnapshots['character_kit'] {
  const library = rememberedCharacterKitLibrary() || emptyCharacterKitLibrary()
  const kit = library.kits[library.activeId] || Object.values(library.kits)[0]
  if (!kit) {
    return { kit_id: '', title: '', poses: 0, mouth: 0, eyes: 0, state: 'empty' }
  }
  const poses = Number(Boolean(kit.base)) + Object.keys(kit.poses || {}).length
  return {
    kit_id: kit.id,
    title: kit.name,
    poses,
    mouth: Object.keys(kit.mouth || {}).length,
    eyes: Object.keys(kit.eyes || {}).length,
    state: kit.base?.reviewState === 'approved' ? 'ready' : 'draft',
  }
}

function videoEditorSnapshot(): WizardLabSnapshots['video_editor'] {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const draft = loadEditorDraft(workspace)
  let exportJob = ''
  try {
    exportJob = window.localStorage.getItem(`maestro-video-editor-export-v1:${encodeURIComponent(workspace)}`) || ''
  } catch {
    exportJob = ''
  }
  return {
    project_id: draft.projectName || 'my_video',
    title: draft.projectName || 'my_video',
    clips: draft.clips.length,
    duration: Math.round(sequenceTotalDuration(draft.clips) * 10) / 10,
    export_job: exportJob,
    state: exportJob ? 'exporting' : draft.clips.length ? 'ready' : 'empty',
  }
}

export function buildWizardLabSnapshots(): WizardLabSnapshots {
  return {
    story: storySnapshot(),
    series: seriesSnapshot(),
    video_3d: video3dSnapshot(),
    character_kit: characterKitSnapshot(),
    video_editor: videoEditorSnapshot(),
  }
}

export function comicLabSnapshot() {
  const inventory = comicArtworkInventory(useComicStore.getState().project)
  return {
    project_id: inventory.projectId,
    title: inventory.title,
    pages: inventory.pages,
    panels: inventory.panels,
    completed: inventory.completed,
    failed: inventory.failed,
    provider: inventory.provider,
    active_page: inventory.activePage,
  }
}

function inferredLocation(state: ReturnType<typeof useStore.getState>): WizardContextLocation {
  if (state.settingsOpen) return { area: 'settings', tab: 'settings', section: state.settingsTab || '' }
  if (state.dashboardOpen) return { area: 'productions', tab: 'productions', section: 'queue' }
  if (state.sidebarMode === 'director' && state.sidebarOpen) {
    return { area: 'director', tab: 'director', section: state.directorStep || '' }
  }
  if (state.sidebarMode === 'studio' && state.sidebarOpen) {
    const section = state.generationMode === 'audio'
      ? state.audioSubMode
      : state.generationMode === 'avatar' ? state.editSubMode : state.generationMode
    return { area: 'studio', tab: 'studio', section: section || '' }
  }
  const media = state.mediaFilter as MediaFilter
  const locations: Partial<Record<MediaFilter, WizardContextLocation>> = {
    images: { area: 'gallery', tab: 'images', section: 'images' },
    videos: { area: 'gallery', tab: 'videos', section: 'videos' },
    audio: { area: 'gallery', tab: 'audio', section: 'audio' },
    model3d: { area: 'gallery', tab: '3d', section: 'model3d' },
    scenes: { area: 'gallery', tab: '3d', section: 'scenes' },
    stories: { area: 'story_lab', tab: 'story_lab', section: '' },
    series: { area: 'series_lab', tab: 'series_lab', section: '' },
    comics: { area: 'comics', tab: 'comics', section: '' },
    videoeditor: { area: 'video_editor', tab: 'video_editor', section: '' },
    scene3d: { area: 'video_3d', tab: 'video_3d', section: '' },
    animate3d: { area: 'video_3d', tab: 'animate_3d', section: 'animate' },
    characters: { area: 'character_kit', tab: 'character_kit', section: '' },
    workspaces: { area: 'workspaces', tab: 'workspaces', section: '' },
    videoclips: { area: 'gallery', tab: 'videos', section: 'videoclips' },
    trailers: { area: 'gallery', tab: 'videos', section: 'trailers' },
    series_episodes: { area: 'gallery', tab: 'videos', section: 'series_episodes' },
    styles: { area: 'gallery', tab: 'images', section: 'styles' },
    avatars: { area: 'gallery', tab: 'videos', section: 'avatars' },
    multiclip: { area: 'gallery', tab: 'videos', section: 'multiclip' },
    favorites: { area: 'gallery', tab: 'all', section: 'favorites' },
    auditdev: { area: 'gallery', tab: 'all', section: 'auditdev' },
  }
  return locations[media] || { area: 'gallery', tab: 'all', section: media || 'all' }
}

function withPresenceLocation(
  inferred: WizardContextLocation,
  presence?: WizardContextPresenceInput,
): WizardContextLocation {
  return {
    area: idValue(presence?.area) || inferred.area,
    tab: idValue(presence?.tab) || inferred.tab,
    section: idValue(presence?.section) || inferred.section,
  }
}

function activeStoryRefs(
  workspaceId: string,
  project: ReturnType<typeof useStoryStore.getState>['project'],
  handoff: ReturnType<typeof useStore.getState>['directorStoryProductionHandoff'],
): {
  project: WizardCanonicalRef | null
  cue: WizardCanonicalRef | null
  output: WizardArtifactRef | null
  production: WizardCanonicalRef | null
} {
  const projectRef = makeRef(project?.id, 'story_project', workspaceId, project?.title, project?.revision)
  const cues = project?.music?.cues || []
  const globalSelectedId = idValue(project?.music?.selectedCandidateId)
  const cue = cues.find(item => item.selectedCandidateId
    && item.candidates.some(candidate => candidate.id === item.selectedCandidateId))
    || cues.find(item => item.candidates.some(candidate => candidate.id === globalSelectedId))
    || cues.find(item => item.kind === 'story')
  const selectedId = idValue(cue?.selectedCandidateId) || globalSelectedId
  const candidate = cue?.candidates.find(item => item.id === selectedId)
    || project?.music?.candidates?.find(item => item.id === selectedId)
  const cueRef = makeRef(cue?.id, 'story_music_cue', workspaceId, cue?.title)
  const productionId = handoff?.projectId === project?.id ? handoff.productionId : ''
  const production = project?.productions?.find(item => item.id === productionId)
  const productionRef = makeRef(production?.id, 'story_production', workspaceId, production?.title, production?.sourceVersion)
  if (!candidate) return { project: projectRef, cue: cueRef, output: null, production: productionRef }
  // Candidate IDs are the durable Story identity. The provider filename is an
  // output detail/URI, never the identity used to select a song.
  const output = makeRef(
    candidate.id,
    'output',
    workspaceId,
    candidate.displayName || candidate.title || candidate.name,
    candidate.version,
    'output',
  )
  return {
    project: projectRef,
    cue: cueRef,
    output: output ? {
      ...output,
      kind: 'output',
      uri: candidate.source || candidate.name,
      task_id: idValue(candidate.taskId),
      metadata: {
        candidate_id: candidate.id,
        output_name: candidate.name,
        provider: candidate.provider,
        model: candidate.model,
        language: candidate.language || null,
      },
    } : null,
    production: productionRef,
  }
}

function selectedOutputRef(
  state: ReturnType<typeof useStore.getState>,
  workspaceId: string,
): WizardArtifactRef | null {
  const filtered = state.filteredOutputs()
  const selected = filtered[state.selectedOutput] || state.outputs.find(output => output.name === state.selectedOutputMeta?.params?.output_name)
  if (!selected?.name) return null
  return {
    id: selected.name,
    kind: selected.type === 'scene' ? 'scene' : 'output',
    workspace_id: workspaceId,
    label: selected.name,
    version: null,
    source: 'output',
    uri: selected.url || selected.name,
    task_id: idValue(state.selectedOutputMeta?.task_id || state.selectedOutputMeta?.job_id),
    metadata: {
      type: selected.type,
      result_kind: selected.result_kind || null,
      created_at: selected.created_at,
    },
  }
}

function artifactRefsFromStore(
  state: ReturnType<typeof useStore.getState>,
  workspaceId: string,
): WizardArtifactRef[] {
  const artifacts: WizardArtifactRef[] = []
  const seen = new Set<string>()
  for (const output of state.outputs || []) {
    if (!output?.name || seen.has(output.name)) continue
    const artifact = normalizeArtifact({
      id: output.name,
      kind: output.type,
      workspace_id: workspaceId,
      label: output.name,
      uri: output.url || output.name,
      metadata: {
        type: output.type,
        mode: output.mode,
        created_at: output.created_at,
        favorite: output.favorite,
      },
    }, workspaceId)
    if (artifact) {
      artifacts.push(artifact)
      seen.add(artifact.id)
    }
    // Keep the context bounded even when a workspace has a large gallery.
    if (artifacts.length >= 100) break
  }
  return artifacts
}

function activeTaskRef(
  state: ReturnType<typeof useStore.getState>,
  workspaceId: string,
  candidateTaskId = '',
): WizardTaskRef | null {
  const activeStatuses = new Set(['queued', 'waiting_resource', 'running', 'cancelling', 'created', 'waiting'])
  const jobs = state.jobs || []
  const byCandidate = candidateTaskId ? jobs.find(job => job.id === candidateTaskId) : undefined
  const activeJob = byCandidate || jobs
    .filter(job => activeStatuses.has(job.status))
    .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))[0]
  const activity = state.foregroundActivity
    || Object.values(state.activities || {})
      .filter(item => item.status === 'queued' || item.status === 'running')
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0]
  if (activeJob) {
    return {
      id: activeJob.id,
      kind: 'job',
      workspace_id: workspaceId,
      label: activeJob.message || activeJob.phase,
      version: null,
      source: 'store',
      status: activeJob.status,
      phase: activeJob.phase,
      progress: progressValue(activeJob.progress),
      message: activeJob.message,
    }
  }
  if (activity && (activity.status === 'queued' || activity.status === 'running')) {
    return {
      id: activity.id,
      kind: 'task',
      workspace_id: workspaceId,
      label: activity.title || activity.message,
      version: null,
      source: 'store',
      status: activity.status,
      phase: activity.phase,
      progress: progressValue(activity.progress),
      message: activity.message,
    }
  }
  if (candidateTaskId) {
    return {
      id: candidateTaskId,
      kind: 'task',
      workspace_id: workspaceId,
      label: '',
      version: null,
      source: 'workflow',
      status: 'unknown',
      phase: '',
      progress: null,
      message: '',
    }
  }
  return null
}

function taskRefsFromStore(
  state: ReturnType<typeof useStore.getState>,
  workspaceId: string,
): WizardTaskRef[] {
  const refs: WizardTaskRef[] = []
  const seen = new Set<string>()
  for (const job of state.jobs || []) {
    const task = normalizeTask({
      id: job.id,
      kind: 'job',
      workspace_id: workspaceId,
      label: job.message || job.phase,
      status: job.status,
      phase: job.phase,
      progress: job.progress,
      message: job.message,
    }, workspaceId)
    if (!task || seen.has(task.id)) continue
    refs.push(task)
    seen.add(task.id)
    if (refs.length >= 100) break
  }
  return refs
}

function activePipelineRef(state: ReturnType<typeof useStore.getState>, workspaceId: string): WizardPipelineRef | null {
  const id = idValue(state.pipelineId)
  const status = state.pipelineStatus
  if (id) {
    const progress = status?.progress
    return {
      id,
      kind: 'pipeline',
      workspace_id: workspaceId,
      label: status?.generation_mode || 'Director pipeline',
      version: null,
      source: 'store',
      status: status?.status || 'unknown',
      phase: status?.phase || '',
      progress: progress ? progress.total > 0 ? Math.max(0, Math.min(1, progress.current / progress.total)) : null : null,
      message: progress?.message || '',
      output_ids: uniqueStrings(status?.output_files),
    }
  }
  const active = (state.activeDirectorPipelines || [])
    .filter(item => !item.workspace || item.workspace === state.activeWorkspace)
    .sort((a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0))[0]
  if (!active?.id) return null
  return {
    id: active.id,
    kind: 'pipeline',
    workspace_id: workspaceId,
    label: active.pipeline_type || 'Director pipeline',
    version: null,
    source: 'store',
    status: active.status,
    phase: active.phase,
    progress: active.progress.total > 0 ? Math.max(0, Math.min(1, active.progress.current / active.progress.total)) : null,
    message: active.progress.message,
    output_ids: uniqueStrings(active.output_files),
  }
}

function pipelineRefsFromStore(
  state: ReturnType<typeof useStore.getState>,
  workspaceId: string,
): WizardPipelineRef[] {
  const refs: WizardPipelineRef[] = []
  const seen = new Set<string>()
  const push = (value: unknown) => {
    const pipeline = normalizePipeline(value, workspaceId)
    if (!pipeline || seen.has(pipeline.id)) return
    refs.push(pipeline)
    seen.add(pipeline.id)
  }
  if (state.pipelineStatus?.id) {
    const status = state.pipelineStatus
    push({
      id: status.id,
      kind: 'pipeline',
      workspace_id: workspaceId,
      label: status.generation_mode || 'Director pipeline',
      status: status.status,
      phase: status.phase,
      progress: status.progress?.total > 0
        ? status.progress.current / status.progress.total : null,
      message: status.progress?.message || '',
      output_ids: status.output_files,
    })
  }
  for (const pipeline of state.activeDirectorPipelines || []) {
    if (pipeline.workspace && pipeline.workspace !== state.activeWorkspace) continue
    push({
      ...pipeline,
      workspace_id: workspaceId,
      output_ids: pipeline.output_files,
      progress: pipeline.progress?.total > 0
        ? pipeline.progress.current / pipeline.progress.total : null,
    })
    if (refs.length >= 100) break
  }
  return refs
}

function contextCapabilities(location: WizardContextLocation): WizardContextCapabilities {
  const common = ['open_tab', 'inspect_queue', 'select_workspace']
  const byTab: Record<string, string[]> = {
    studio: ['prepare_video', 'prepare_image', 'prepare_audio', 'prepare_3d', 'start_generation'],
    story_lab: ['open_story_section', 'create_story', 'update_story', 'generate_story_section', 'apply_story_proposal', 'approve_story_section', 'approve_story_visuals', 'generate_story_visuals', 'configure_story_song', 'generate_story_song', 'stage_story_music_video', 'start_director_production'],
    series_lab: ['open_series_section', 'create_series_episode', 'update_series_episode', 'generate_series_plan', 'apply_series_plan', 'render_series_shots', 'review_series_attempts', 'assemble_series_episode', 'commit_series_canon'],
    comics: ['create_comic', 'generate_comic', 'generate_comic_panel'],
    video_3d: ['open_3d_scene', 'create_3d_scene', 'set_3d_scene_properties', 'add_3d_scene_layer', 'update_3d_scene_layer', 'remove_3d_scene_layer', 'attach_3d_scene_audio', 'analyze_3d_scene_audio', 'apply_3d_choreography', 'save_3d_scene', 'export_3d_scene'],
    animate_3d: ['open_3d_scene', 'apply_3d_rhythm', 'apply_3d_choreography'],
    video_editor: ['create_video_editor_project', 'open_video_editor_project', 'add_video_editor_clips', 'order_video_editor_clips', 'trim_video_editor_clip', 'add_video_editor_audio', 'validate_video_editor_timeline', 'export_video_editor'],
    character_kit: ['create_character_kit', 'open_character_kit', 'update_character_kit', 'attach_character_kit_references', 'build_character_kit', 'open_character_kit_rig', 'apply_character_kit_preset', 'track_character_kit_job'],
    director: ['start_director_production'],
    workspaces: ['create_workspace_collection', 'update_workspace_collection'],
  }
  return { available: [...new Set([...common, ...(byTab[location.tab] || [])])], blocked: [] }
}

function draftSnapshots(
  app: ReturnType<typeof useStore.getState>,
  story: ReturnType<typeof useStoryStore.getState>,
  series: ReturnType<typeof useSeriesStore.getState>,
  comic: ReturnType<typeof useComicStore.getState>,
): WizardDrafts {
  const storyProject = story.project
  const seriesProject = series.library.seriesById[series.activeSeriesId]
  const editor = loadEditorDraft(app.activeWorkspace || 'default')
  const rememberedKit = rememberedCharacterKitLibrary()
  return {
    story_lab: {
      dirty: story.dirty,
      version: versionValue(storyProject?.revision),
      schema_version: versionValue(storyProject?.version),
      library_revision: integerValue(story.libraryRevision),
      updated_at: stringValue(storyProject?.updatedAt),
      source: 'store',
    },
    series_lab: {
      dirty: series.dirty,
      version: versionValue(seriesProject?.revision),
      schema_version: versionValue(seriesProject?.version),
      library_revision: integerValue(series.serverRevision),
      updated_at: stringValue(seriesProject?.updatedAt),
      source: 'store',
    },
    comics: {
      dirty: comic.dirty,
      version: null,
      schema_version: versionValue(comic.project?.version),
      library_revision: null,
      updated_at: stringValue(comic.project?.updatedAt),
      source: 'store',
    },
    character_kit: {
      dirty: false,
      version: null,
      schema_version: null,
      library_revision: null,
      updated_at: '',
      source: rememberedKit ? 'session' : 'none',
    },
    video_3d: {
      dirty: false,
      version: null,
      schema_version: null,
      library_revision: null,
      updated_at: '',
      source: rememberedVideo3dScene() ? 'session' : 'none',
    },
    video_editor: {
      dirty: false,
      version: null,
      schema_version: null,
      library_revision: null,
      updated_at: '',
      source: editor.clips.length || editor.projectName !== 'my_video' ? 'draft' : 'none',
    },
  }
}

function applyPresenceRef(
  ref: WizardCanonicalRef | null,
  id: unknown,
  workspaceId: string,
  kind: string,
): WizardCanonicalRef | null {
  const canonicalId = idValue(id)
  if (!canonicalId) return ref
  return makeRef(canonicalId, ref?.kind || kind, workspaceId, ref?.label, ref?.version, ref?.source || 'session')
}

function applyPresenceArtifact(
  ref: WizardArtifactRef | null,
  id: unknown,
  workspaceId: string,
): WizardArtifactRef | null {
  const canonicalId = idValue(id)
  if (!canonicalId) return ref
  if (ref && ref.id === canonicalId) return ref
  return {
    ...(ref || {
      id: canonicalId,
      kind: 'output',
      workspace_id: workspaceId,
      label: '',
      version: null,
      source: 'session' as const,
      uri: '',
      task_id: '',
      metadata: {},
    }),
    id: canonicalId,
    workspace_id: workspaceId,
    source: 'session',
  }
}

function applyPresenceTask(
  ref: WizardTaskRef | null,
  id: unknown,
  workspaceId: string,
): WizardTaskRef | null {
  const canonicalId = idValue(id)
  if (!canonicalId) return ref
  if (ref && ref.id === canonicalId) return ref
  return {
    ...(ref || {
      id: canonicalId,
      kind: 'task' as const,
      workspace_id: workspaceId,
      label: '',
      version: null,
      source: 'session' as const,
      status: 'unknown',
      phase: '',
      progress: null,
      message: '',
    }),
    id: canonicalId,
    workspace_id: workspaceId,
    source: 'session',
  }
}

function applyPresencePipeline(
  ref: WizardPipelineRef | null,
  id: unknown,
  workspaceId: string,
): WizardPipelineRef | null {
  const canonicalId = idValue(id)
  if (!canonicalId) return ref
  if (ref && ref.id === canonicalId) return ref
  return {
    ...(ref || {
      id: canonicalId,
      kind: 'pipeline' as const,
      workspace_id: workspaceId,
      label: '',
      version: null,
      source: 'session' as const,
      status: 'unknown',
      phase: '',
      progress: null,
      message: '',
      output_ids: [],
    }),
    id: canonicalId,
    workspace_id: workspaceId,
    source: 'session',
  }
}

/**
 * Build the canonical read model from the current stores. A mounted lab can
 * pass exact UI presence IDs while its internal tab is local React state; no
 * title lookup is performed here, so stale labels cannot move a workflow to a
 * different same-named project.
 */
export function buildWizardContextSnapshot(options: BuildWizardContextOptions = {}): WizardContextSnapshot {
  const app = useStore.getState()
  const story = useStoryStore.getState()
  const series = useSeriesStore.getState()
  const comic = useComicStore.getState()
  const workspaceId = idValue(app.activeWorkspace) || 'default'
  const workspace = app.workspaces.find(item => item.name === workspaceId)
  const location = withPresenceLocation(inferredLocation(app), options.presence)
  const storyRefs = activeStoryRefs(workspaceId, story.project, app.directorStoryProductionHandoff)
  const storyProject = storyRefs.project
  const seriesProject = series.library.seriesById[series.activeSeriesId]
  const episode = seriesProject?.episodesById[series.activeEpisodeId]
  const seriesEntity = makeRef(episode?.id || seriesProject?.id, episode ? 'series_episode' : 'series_project', workspaceId, episode?.title || seriesProject?.title, seriesProject?.revision)
  const comicProject = comic.project
  const comicEntity = makeRef(comicProject?.id, 'comic_project', workspaceId, comicProject?.title)
  const rememberedScene = rememberedVideo3dScene()
  const sceneEntity = makeRef(rememberedScene?.scene_id, 'video_3d_scene', workspaceId, rememberedScene?.title, null, 'session')
  const kitLibrary = rememberedCharacterKitLibrary()
  const kit = kitLibrary?.kits[kitLibrary.activeId] || (kitLibrary ? Object.values(kitLibrary.kits)[0] : null)
  const kitEntity = makeRef(kit?.id, 'character_kit', workspaceId, kit?.name, null, 'session')
  const editorDraft = loadEditorDraft(workspaceId)
  // Video Editor drafts currently have no server UUID. Scope the local draft
  // to the workspace instead of using its editable project name as an ID.
  const editorEntity = editorDraft.clips.length || editorDraft.projectName !== 'my_video'
    ? makeRef(`video-editor-draft:${workspaceId}`, 'video_editor_draft', workspaceId, editorDraft.projectName, null, 'draft')
    : null
  const pipeline = activePipelineRef(app, workspaceId)
  const task = activeTaskRef(app, workspaceId, idValue(storyRefs.output?.task_id))
  const galleryOutput = selectedOutputRef(app, workspaceId)
  const output = storyRefs.output || galleryOutput
  const artifacts = artifactRefsFromStore(app, workspaceId)
  if (output && !artifacts.some(item => item.id === output.id)) artifacts.unshift(output)
  const tasks = taskRefsFromStore(app, workspaceId)
  if (task && !tasks.some(item => item.id === task.id)) tasks.unshift(task)
  const pipelines = pipelineRefsFromStore(app, workspaceId)
  if (pipeline && !pipelines.some(item => item.id === pipeline.id)) pipelines.unshift(pipeline)
  const project = storyProject
    || (location.tab === 'series_lab' ? makeRef(seriesProject?.id, 'series_project', workspaceId, seriesProject?.title, seriesProject?.revision) : null)
    || (location.tab === 'comics' ? comicEntity : null)
    || (location.tab === 'video_editor' ? editorEntity : null)
  let entity = project
  if (location.tab === 'series_lab') entity = seriesEntity || project
  else if (location.tab === 'video_3d' || location.tab === 'animate_3d') entity = sceneEntity
  else if (location.tab === 'character_kit' || location.tab === 'character_creator') entity = kitEntity
  else if (location.tab === 'director') entity = pipeline || project
  else if (location.area === 'gallery') entity = output || task || project
  else if (location.area === 'productions') entity = pipeline || project
  const presence = options.presence
  const active: WizardContextActive = {
    workspace_id: workspaceId,
    location,
    entity: applyPresenceRef(entity, presence?.entity_id, workspaceId, 'entity'),
    project: applyPresenceRef(project, presence?.project_id, workspaceId, 'project'),
    cue: applyPresenceRef(storyRefs.cue, presence?.cue_id, workspaceId, 'cue'),
    production: applyPresenceRef(storyRefs.production, presence?.production_id, workspaceId, 'production'),
    output: applyPresenceArtifact(output, presence?.output_id, workspaceId),
    job: applyPresenceTask(task, presence?.job_id, workspaceId),
    pipeline: applyPresencePipeline(pipeline, presence?.pipeline_id, workspaceId),
  }
  // Presence can refer to a resource that has just mounted but has not yet
  // arrived in the store snapshot. Keep the top-level indexes consistent
  // with the active refs so the LLM sees the same canonical target either way.
  if (active.output && !artifacts.some(item => item.id === active.output?.id)) artifacts.unshift(active.output)
  if (active.job && !tasks.some(item => item.id === active.job?.id)) tasks.unshift(active.job)
  if (active.pipeline && !pipelines.some(item => item.id === active.pipeline?.id)) pipelines.unshift(active.pipeline)
  artifacts.splice(100)
  tasks.splice(100)
  pipelines.splice(100)
  const selection = normalizeSelection({
    page_id: presence?.page_id || (location.tab === 'comics' ? comic.currentPageId : ''),
    element_id: presence?.element_id || (location.tab === 'comics' ? comic.selectedId : ''),
    series_id: presence?.series_id || (location.tab === 'series_lab' ? series.activeSeriesId : ''),
    episode_id: presence?.episode_id || (location.tab === 'series_lab' ? series.activeEpisodeId : ''),
    shot_id: presence?.shot_id,
    layer_id: presence?.layer_id,
    kit_id: presence?.kit_id || (location.tab === 'character_kit' || location.tab === 'character_creator' ? kit?.id : ''),
    clip_index: presence?.clip_index,
  })
  const capabilities = options.capabilities === undefined
    ? contextCapabilities(location) : normalizeCapabilities(options.capabilities)
  return normalizeWizardContextSnapshot({
    schema: WIZARD_CONTEXT_SCHEMA,
    version: WIZARD_CONTEXT_VERSION,
    captured_at: options.captured_at || new Date().toISOString(),
    workspace: { id: workspaceId, name: workspaceId, path: workspace?.path || '' },
    active,
    selection,
    drafts: draftSnapshots(app, story, series, comic),
    artifacts,
    tasks,
    pipelines,
    workflow: options.workflow,
    pending_question: options.pending_question,
    capabilities,
    labs: buildWizardLabSnapshots(),
  }, workspaceId)
}
