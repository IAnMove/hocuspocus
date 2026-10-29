import type { ParseKeys } from 'i18next'
import i18n from 'i18next'
import { isLiveStatus, type ActivityTaskLike } from './lineage'

const footerKey = (value: string) => value as ParseKeys<'activity'>

/** Composed footer phrases. ``defaultValue`` keeps the previous English if a catalog is not loaded. */
function footer(key: string, options: Record<string, unknown> & { defaultValue: string }): string {
  return i18n.t(footerKey(key), { ns: 'activity', ...options })
}

export const PHASE_KEYS: Record<string, string> = {
  loading_model: 'loadingModel',
  encoding_text: 'encodingText',
  encoding_images: 'encodingImages',
  inference: 'inference',
  decoding: 'decoding',
  downloading_output: 'saving',
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
  const phase = phaseCatalogKey(task)
  if (['loadingModel', 'encodingText', 'encodingImages', 'decoding', 'saving'].includes(phase)) return undefined
  const inferenceStart = epochMs(Number(task.metadata?.inference_started_at))
  if (phase === 'inference' && inferenceStart) {
    return samplingRemainingSeconds(task, now, inferenceStart)
  }
  // Local inference should wait for measured steps instead of extrapolating
  // loading/encoding time or a synthetic progress percentage.
  if (task.provider === 'local' && task.metadata?.adapter === 'generation') return undefined
  return progressRemainingSeconds(task, now)
}

function samplingRemainingSeconds(task: ActivityTaskLike, now: number, inferenceStart: number): number | undefined {
  const current = Number(task.current || 0)
  const measured = current - Number(task.metadata?.inference_start_step || 0)
  const remaining = Number(task.total || 0) - current
  if (measured < 2 || remaining <= 0) return undefined
  return Math.max(1, Math.round((now - inferenceStart) / 1000 / measured * remaining))
}

function progressRemainingSeconds(task: ActivityTaskLike, now: number): number | undefined {
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
  const phase = String(task.phase || '').toLowerCase()
  if (PHASE_KEYS[phase]) return PHASE_KEYS[phase]
  if (phase.includes('denoising') || phase.startsWith('inference_stage_')) return 'inference'
  if (phase.includes('encoding reference') || phase.includes('encoding source')) return 'encodingImages'
  if (phase.includes('encoding prompt') || phase.includes('enhancing prompt')) return 'encodingText'
  if (phase.includes('vae decoding') || phase.includes('decoding')) return 'decoding'
  if (phase.includes('loading')) return 'loadingModel'
  return 'fallback'
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

function pushUniqueModel(parts: string[], kind: '' | 'text' | 'image' | 'video', value: unknown): void {
  if (!value) return
  const model = String(value)
  if (parts.some(part => part === model || part.endsWith(` ${model}`))) return
  if (kind === 'text') parts.push(footer('footer.textModel', { model, defaultValue: `text ${model}` }))
  else if (kind === 'image') parts.push(footer('footer.imageModel', { model, defaultValue: `image ${model}` }))
  else if (kind === 'video') parts.push(footer('footer.videoModel', { model, defaultValue: `video ${model}` }))
  else parts.push(model)
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
  if (details.simulated === true || details.execution_mode === 'simulate') {
    parts.push(footer('footer.simulated', { defaultValue: 'SIMULATED' }))
  }
  const resolution = firstDefined(details.video_resolution, details.image_resolution, details.resolution)
  if (resolution) parts.push(String(resolution))
  appendDefined(parts, details.seed, value => footer('footer.seed', { value, defaultValue: `seed ${value}` }))
  const steps = firstDefined(details.video_steps, details.image_steps, details.steps, details.numInferenceSteps)
  appendDefined(parts, steps, value => footer('footer.steps', { value, defaultValue: `${value} steps` }))
  appendDefined(parts, details.guidance, value => footer('footer.guidance', { value, defaultValue: `guidance ${value}` }))
  appendDefined(parts, details.frames, value => footer('footer.frames', { value, defaultValue: `${value} frames` }))
  appendDefined(parts, details.duration_seconds, value => `${value}s`)
}

function h3Minimum(details: Record<string, unknown>): string {
  if (details.dialogue_duration_minimum_limited) return footer('footer.h3Minimum', { defaultValue: ' · H3 minimum applied' })
  return ''
}

function dialogueLine(details: Record<string, unknown>): string {
  const minimum = h3Minimum(details)
  const calculated = details.dialogue_duration_calculated
  if (details.dialogue_syllables !== undefined) {
    const syllables = details.dialogue_syllables
    const rate = details.dialogue_seconds_per_syllable
    return footer('footer.dialogueSyllables', {
      syllables, rate, calculated, minimum,
      defaultValue: `dialogue ${syllables} syllables × ${rate}s → ${calculated}s calculated${minimum}`,
    })
  }
  if (details.dialogue_words !== undefined) {
    const words = details.dialogue_words
    return footer('footer.dialogueWords', {
      words, calculated, minimum,
      defaultValue: `dialogue ${words} words → ${calculated}s calculated${minimum}`,
    })
  }
  return ''
}

function cacheLine(details: Record<string, unknown>): string {
  if (details.cache === undefined) return ''
  if (!details.cache) return footer('footer.cacheOff', { defaultValue: 'Cache off' })
  if (details.cache_type) return footer('footer.cacheOnTyped', { type: details.cache_type, defaultValue: `Cache on (${details.cache_type})` })
  return footer('footer.cacheOn', { defaultValue: 'Cache on' })
}

function loraLine(details: Record<string, unknown>): string {
  if (details.lora_count === undefined) return ''
  if (!details.lora_count) return footer('footer.lorasOff', { defaultValue: 'LoRAs off' })
  const count = Number(details.lora_count)
  const loras = Array.isArray(details.loras) ? details.loras.map(String).filter(Boolean) : []
  const names = loras.length ? ` (${loras.join(', ')})` : ''
  const base = footer('footer.lora', { count, defaultValue: count === 1 ? `${count} LoRA` : `${count} LoRAs` })
  return `${base}${names}`
}

function appendRecipeFlags(parts: string[], details: Record<string, unknown>): void {
  if (details.profile) parts.push(footer('footer.profile', { name: details.profile, defaultValue: `profile ${details.profile}` }))
  const flow = firstDefined(details.flow_shift, details.flowShift)
  appendDefined(parts, flow, value => footer('footer.flowShift', { value, defaultValue: `flow shift ${value}` }))
  const audio = firstDefined(details.audio_shift, details.audioShift)
  appendDefined(parts, audio, value => footer('footer.audioShift', { value, defaultValue: `audio shift ${value}` }))
  if (details.turbo !== undefined) {
    parts.push(details.turbo
      ? footer('footer.turboOn', { defaultValue: 'Turbo on' })
      : footer('footer.turboOff', { defaultValue: 'Turbo off' }))
  }
  const cache = cacheLine(details)
  if (cache) parts.push(cache)
  const loras = loraLine(details)
  if (loras) parts.push(loras)
  appendDefined(parts, details.clip_count, value => footer('footer.clips', { value, defaultValue: `${value} clips` }))
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
  const value = firstDefined(metadata.display_prompt, details.prompt, metadata.prompt, metadata.prompt_preview)
  if (typeof value === 'string') return value.trim()
  return ''
}

function directorInitiator(task: ActivityTaskLike, mode: string): string {
  if (task.parent_id?.startsWith('task-director-')) return directorLabel(mode)
  if (task.workflow === 'director') return directorLabel(mode)
  return ''
}

function namedMode(english: string, key: string): string {
  return footer(key, { defaultValue: english })
}

function directorModeName(mode: string): string {
  if (mode === 'short film') return namedMode('short film', 'footer.modes.shortFilm')
  if (mode === 'comic') return namedMode('comic', 'footer.modes.comic')
  if (mode === 'video podcast') return namedMode('video podcast', 'footer.modes.videoPodcast')
  if (mode === 'viral video') return namedMode('viral video', 'footer.modes.viralVideo')
  return mode
}

function studioModeName(mode: string): string {
  if (mode === 'image') return namedMode('Image', 'footer.modes.image')
  if (mode === 'video') return namedMode('Video', 'footer.modes.video')
  if (mode === 'audio') return namedMode('Audio', 'footer.modes.audio')
  if (mode === 'avatar') return namedMode('Avatar', 'footer.modes.avatar')
  return `${mode[0].toUpperCase()}${mode.slice(1)}`
}

function directorLabel(mode: string): string {
  if (!mode) return footer('footer.director', { defaultValue: 'Director' })
  if (mode === 'music video') return footer('footer.directorMusic', { defaultValue: 'Director · Music video' })
  const name = directorModeName(mode)
  return footer('footer.directorMode', { mode: name, defaultValue: `Director · ${mode}` })
}

function studioInitiator(mode: string): string {
  if (mode === 'model3d') return footer('footer.studio3d', { defaultValue: 'Studio · 3D' })
  if (mode) {
    const name = studioModeName(mode)
    const english = `${mode[0].toUpperCase()}${mode.slice(1)}`
    return footer('footer.studioMode', { mode: name, defaultValue: `Studio · ${english}` })
  }
  return footer('footer.studioGeneration', { defaultValue: 'Studio · Generation' })
}

export function generationInitiator(task: ActivityTaskLike): string {
  const metadata = task.metadata || {}
  const details = recipeDetails(task)
  const explicit = firstDefined(details.initiator, metadata.initiator)
  if (typeof explicit === 'string' && explicit.trim()) return explicit.trim()
  const mode = String(firstDefined(details.generation_mode, task.kind, '')).replaceAll('_', ' ')
  if (task.parent_id?.startsWith('task-series-') || (task.workflow || '').startsWith('series')) {
    return footer('footer.seriesChapter', { defaultValue: 'Series Lab · Chapter' })
  }
  const director = directorInitiator(task, mode)
  if (director) return director
  if (task.workflow === 'audio-analysis') return footer('footer.audioAnalysis', { defaultValue: 'Story/Director · Audio analysis' })
  if (task.workflow === 'generation') return studioInitiator(mode)
  if (task.workflow) return task.workflow.replaceAll('_', ' ')
  return ''
}

export function truncatePrompt(prompt: string, limit = 180): string {
  const oneLine = prompt.replace(/\s+/g, ' ').trim()
  return oneLine.length > limit ? `${oneLine.slice(0, limit - 1)}…` : oneLine
}


export function generationResolution(task: ActivityTaskLike): string {
  const resolution = recipeDetails(task).resolution
  return typeof resolution === 'string' ? resolution.replace('x', '×') : ''
}
