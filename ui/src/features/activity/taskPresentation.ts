import { isLiveStatus, type ActivityTaskLike } from './lineage'

export const PHASE_KEYS: Record<string, string> = {
  planning: 'planning',
  known_series_research: 'knownSeriesResearch',
  canon: 'canon',
  outline: 'outline',
  script: 'script',
  shots: 'shots',
  canon_validation: 'canonValidation',
  canon_delta: 'canonDelta',
  rendering: 'rendering',
  generating_images: 'generatingImages',
  generating_video: 'generatingVideo',
  post_processing: 'postProcessing',
  waiting_resource: 'waitingResource',
  cancelling: 'cancelling',
  completed: 'completed',
  failed: 'failed',
  cancelled: 'cancelled',
  interrupted: 'interrupted',
}

function epochMs(value?: number | null): number | undefined {
  if (!value || !Number.isFinite(value)) return undefined
  return value < 1_000_000_000_000 ? value * 1000 : value
}

export function elapsedSeconds(task: ActivityTaskLike, now: number): number | undefined {
  const start = epochMs(task.started_at || task.queued_at || task.created_at)
  if (!start) return undefined
  const end = isLiveStatus(task.status)
    ? now
    : epochMs(task.completed_at || task.updated_at) || now
  return Math.max(0, (end - start) / 1000)
}

export function formatElapsed(task: ActivityTaskLike, now: number): string {
  const total = elapsedSeconds(task, now)
  if (total === undefined) return ''
  const seconds = Math.floor(total)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return hours
    ? `${hours}:${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`
    : `${minutes}:${remainder.toString().padStart(2, '0')}`
}

export function estimatedRemainingSeconds(task: ActivityTaskLike, now: number): number | undefined {
  if (!isLiveStatus(task.status)) return undefined
  const elapsed = elapsedSeconds(task, now)
  const total = Number(task.total || 0)
  const current = Number(task.current || 0)
  const fraction = total > 0
    ? Math.max(0, Math.min(1, current / total))
    : Math.max(0, Math.min(1, Number(task.progress || 0)))
  if (!elapsed || elapsed < 3 || fraction < 0.01 || fraction >= 1) return undefined
  return Math.max(1, Math.round(elapsed * ((1 - fraction) / fraction)))
}

export function formatEta(seconds: number | undefined): string {
  if (seconds === undefined) return ''
  const rounded = Math.max(1, Math.round(seconds))
  const hours = Math.floor(rounded / 3600)
  const minutes = Math.floor((rounded % 3600) / 60)
  const remainder = rounded % 60
  if (hours) return `~${hours}h ${minutes.toString().padStart(2, '0')}m`
  if (minutes) return `~${minutes}m ${remainder.toString().padStart(2, '0')}s`
  return `~${remainder}s`
}

export function fallbackPhaseLabel(task: ActivityTaskLike): string {
  return task.phase?.replaceAll('_', ' ') || task.status
}

export function phaseCatalogKey(task: ActivityTaskLike): string {
  return PHASE_KEYS[task.phase || ''] || 'fallback'
}

export function translatedPhase(
  t: (key: string, options?: object) => string,
  task: ActivityTaskLike,
): string {
  return t(`phases.${phaseCatalogKey(task)}`, { phase: fallbackPhaseLabel(task), defaultValue: fallbackPhaseLabel(task) })
}

export function resourceSummary(task: ActivityTaskLike): { kind: 'using' | 'waiting' | 'required'; value: string } | '' {
  const acquired = task.acquired_resources || []
  const required = task.resource_requirements || []
  if (acquired.length) return { kind: 'using', value: acquired.join(' · ') }
  if (task.status === 'waiting_resource' && required.length) return { kind: 'waiting', value: required.join(' · ') }
  return required.length ? { kind: 'required', value: required.join(' · ') } : ''
}

function recipeDetails(task: ActivityTaskLike): Record<string, unknown> {
  const metadata = task.metadata || {}
  const details = metadata.generation_details || metadata.settings
  if (details && typeof details === 'object' && !Array.isArray(details)) return details as Record<string, unknown>
  return {}
}

function firstDefined(...values: unknown[]): unknown {
  for (const value of values) {
    if (value === undefined) continue
    if (value === null) continue
    return value
  }
  return undefined
}

function pushUniqueModel(parts: string[], label: string, value: unknown): void {
  if (!value) return
  const model = String(value)
  if (parts.some(part => part === model || part.endsWith(` ${model}`))) return
  parts.push(label ? `${label} ${model}` : model)
}

function appendRecipeModels(parts: string[], details: Record<string, unknown>): void {
  pushUniqueModel(parts, '', firstDefined(details.model_name, details.model_type))
  pushUniqueModel(parts, 'text', details.text_model)
  pushUniqueModel(parts, 'image', firstDefined(details.image_model_name, details.image_model_type))
  pushUniqueModel(parts, 'video', firstDefined(details.video_model_name, details.video_model_type))
}

function appendDefined(parts: string[], value: unknown, label: (item: unknown) => string): void {
  if (value === undefined) return
  parts.push(label(value))
}

function appendRecipeCore(parts: string[], details: Record<string, unknown>): void {
  if (details.simulated === true) parts.push('SIMULATED')
  else if (details.execution_mode === 'simulate') parts.push('SIMULATED')
  const resolution = firstDefined(details.video_resolution, details.image_resolution, details.resolution)
  if (resolution) parts.push(String(resolution))
  appendDefined(parts, details.seed, value => `seed ${value}`)
  const steps = firstDefined(details.video_steps, details.image_steps, details.steps, details.numInferenceSteps)
  appendDefined(parts, steps, value => `${value} steps`)
  appendDefined(parts, details.guidance, value => `guidance ${value}`)
  appendDefined(parts, details.frames, value => `${value} frames`)
  appendDefined(parts, details.duration_seconds, value => `${value}s`)
}

function h3Minimum(details: Record<string, unknown>): string {
  if (details.dialogue_duration_minimum_limited) return ' · H3 minimum applied'
  return ''
}

function dialogueLine(details: Record<string, unknown>): string {
  if (details.dialogue_syllables !== undefined) {
    return `dialogue ${details.dialogue_syllables} syllables × ${details.dialogue_seconds_per_syllable}s → ${details.dialogue_duration_calculated}s calculated${h3Minimum(details)}`
  }
  if (details.dialogue_words !== undefined) {
    return `dialogue ${details.dialogue_words} words → ${details.dialogue_duration_calculated}s calculated${h3Minimum(details)}`
  }
  return ''
}

function cacheLine(details: Record<string, unknown>): string {
  if (details.cache === undefined) return ''
  if (!details.cache) return 'Cache off'
  if (details.cache_type) return `Cache on (${details.cache_type})`
  return 'Cache on'
}

function loraLine(details: Record<string, unknown>): string {
  if (details.lora_count === undefined) return ''
  if (!details.lora_count) return 'LoRAs off'
  const loras = Array.isArray(details.loras) ? details.loras.map(String).filter(Boolean) : []
  const suffix = Number(details.lora_count) === 1 ? '' : 's'
  const names = loras.length ? ` (${loras.join(', ')})` : ''
  return `${details.lora_count} LoRA${suffix}${names}`
}

function appendRecipeFlags(parts: string[], details: Record<string, unknown>): void {
  if (details.profile) parts.push(`profile ${details.profile}`)
  const flow = firstDefined(details.flow_shift, details.flowShift)
  appendDefined(parts, flow, value => `flow shift ${value}`)
  const audio = firstDefined(details.audio_shift, details.audioShift)
  appendDefined(parts, audio, value => `audio shift ${value}`)
  if (details.turbo !== undefined) parts.push(`Turbo ${details.turbo ? 'on' : 'off'}`)
  const cache = cacheLine(details)
  if (cache) parts.push(cache)
  const loras = loraLine(details)
  if (loras) parts.push(loras)
  appendDefined(parts, details.clip_count, value => `${value} clips`)
}

export function generationRecipe(task: ActivityTaskLike): string {
  const details = recipeDetails(task)
  const parts = [task.provider, task.model].filter(Boolean) as string[]
  appendRecipeModels(parts, details)
  appendRecipeCore(parts, details)
  const dialogue = dialogueLine(details)
  if (dialogue) parts.push(dialogue)
  appendRecipeFlags(parts, details)
  return parts.join(' · ')
}

export function generationPrompt(task: ActivityTaskLike): string {
  const metadata = task.metadata || {}
  const details = recipeDetails(task)
  const value = firstDefined(details.prompt, metadata.prompt, metadata.prompt_preview)
  if (typeof value === 'string') return value.trim()
  return ''
}

function directorInitiator(task: ActivityTaskLike, mode: string): string {
  if (task.parent_id?.startsWith('task-director-')) return directorLabel(mode)
  if (task.workflow === 'director') return directorLabel(mode)
  return ''
}

function directorLabel(mode: string): string {
  if (!mode) return 'Director'
  if (mode === 'music video') return 'Director · Music video'
  return `Director · ${mode}`
}

function studioInitiator(mode: string): string {
  if (mode === 'model3d') return 'Studio · 3D'
  if (mode) return `Studio · ${mode[0].toUpperCase()}${mode.slice(1)}`
  return 'Studio · Generation'
}

export function generationInitiator(task: ActivityTaskLike): string {
  const metadata = task.metadata || {}
  const details = recipeDetails(task)
  const explicit = firstDefined(details.initiator, metadata.initiator)
  if (typeof explicit === 'string' && explicit.trim()) return explicit.trim()
  const mode = String(firstDefined(details.generation_mode, task.kind, '')).replaceAll('_', ' ')
  if (task.parent_id?.startsWith('task-series-')) return 'Series Lab · Chapter'
  if ((task.workflow || '').startsWith('series')) return 'Series Lab · Chapter'
  const director = directorInitiator(task, mode)
  if (director) return director
  if (task.workflow === 'audio-analysis') return 'Story/Director · Audio analysis'
  if (task.workflow === 'generation') return studioInitiator(mode)
  if (task.workflow) return task.workflow.replaceAll('_', ' ')
  return ''
}

export function truncatePrompt(prompt: string, limit = 180): string {
  const oneLine = prompt.replace(/\s+/g, ' ').trim()
  return oneLine.length > limit ? `${oneLine.slice(0, limit - 1)}…` : oneLine
}
