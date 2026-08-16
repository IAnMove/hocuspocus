import type {
  OutputMetadata,
  PipelineClipState,
  PipelineVideoAttempt,
  SavedPipelineState,
} from '../../types'

export const DIRECTOR_CLIP_REPLACEMENT_TARGET_KEY = 'maestro-director-clip-replacement-target-v1'
export const DIRECTOR_CLIP_REPLACEMENT_RESULT_KEY = 'maestro-director-clip-replacement-result-v1'

export interface DirectorClipReplacementTarget {
  pipelineId: string
  clipIndex: number
  workspace: string
  sourceAttemptFilename: string
  requestedAt: number
}

export interface DirectorClipReplacementResult {
  pipelineId: string
  clipIndex: number
  filename: string
  selectedAt: number
}

function readStored<T>(key: string): T | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || 'null')
    return value && typeof value === 'object' ? value as T : null
  } catch {
    return null
  }
}

export function readDirectorClipReplacementTarget(): DirectorClipReplacementTarget | null {
  const value = readStored<DirectorClipReplacementTarget>(DIRECTOR_CLIP_REPLACEMENT_TARGET_KEY)
  if (!value || typeof value.pipelineId !== 'string' || !Number.isInteger(value.clipIndex)) return null
  return value
}

export function writeDirectorClipReplacementTarget(value: DirectorClipReplacementTarget): void {
  window.localStorage.setItem(DIRECTOR_CLIP_REPLACEMENT_TARGET_KEY, JSON.stringify(value))
  window.localStorage.removeItem(DIRECTOR_CLIP_REPLACEMENT_RESULT_KEY)
}

export function clearDirectorClipReplacementTarget(): void {
  window.localStorage.removeItem(DIRECTOR_CLIP_REPLACEMENT_TARGET_KEY)
}

export function readDirectorClipReplacementResult(): DirectorClipReplacementResult | null {
  const value = readStored<DirectorClipReplacementResult>(DIRECTOR_CLIP_REPLACEMENT_RESULT_KEY)
  if (!value || typeof value.pipelineId !== 'string' || !Number.isInteger(value.clipIndex)) return null
  return value
}

export function writeDirectorClipReplacementResult(value: DirectorClipReplacementResult): void {
  window.localStorage.setItem(DIRECTOR_CLIP_REPLACEMENT_RESULT_KEY, JSON.stringify(value))
  clearDirectorClipReplacementTarget()
}

export function clearDirectorClipReplacementResult(): void {
  window.localStorage.removeItem(DIRECTOR_CLIP_REPLACEMENT_RESULT_KEY)
}

function indexedValue(value: unknown, index: number): unknown {
  return Array.isArray(value) ? value[index] : value
}

/** Turn a multi-clip Director sidecar into one editable standalone Studio job. */
export function directorClipCreatorMetadata(
  pipeline: SavedPipelineState,
  clip: PipelineClipState,
  attempt: PipelineVideoAttempt,
  metadata: OutputMetadata,
): OutputMetadata {
  const source = metadata.params || {}
  const params: Record<string, unknown> = { ...source }
  const perClipFrames = Array.isArray(source.per_clip_frames) ? source.per_clip_frames : []
  const matchingSegment = (clip.h3_segments || []).find(segment => segment.filename === attempt.filename)
  const planned = (clip.planned_clip || {}) as unknown as Record<string, unknown>
  const durationFrames = attempt.video_length
    || matchingSegment?.frames
    || Number(perClipFrames[clip.index] || 0)
    || Number(planned.duration_frames || 0)
  const startImage = indexedValue(source.image_start, clip.index)
    || clip.start_image_filename || undefined
  const endImage = indexedValue(source.image_end, clip.index)
    || (clip as unknown as Record<string, unknown>).end_image_filename || undefined
  const perClipReferences = Array.isArray(source.per_clip_minimax_h3_references)
    ? source.per_clip_minimax_h3_references[clip.index]
    : undefined

  const directorRuntimeKeys = [
    'multi_prompts_gen_type', 'multi_clip_audio_start_sec', 'multi_clip_concat_audio',
    'per_clip_frames', 'per_clip_seeds', 'per_clip_negative_prompts',
    'per_clip_continue_from_previous', 'per_clip_minimax_h3_references',
    '_director_pipeline_id', '_director_clip_index', '_director_clip_index_map',
    '_director_detached_operation', '_director_repair_operation_id',
    '_director_h3_segment_index',
  ]
  for (const key of directorRuntimeKeys) delete params[key]

  params.model_type = attempt.model_type || pipeline.video_model
  params.prompt = attempt.prompt || clip.video_prompt || ''
  params.generation_mode = 'video'
  params.image_mode = 0
  params.repeat_generation = 1
  if (attempt.seed != null) params.seed = attempt.seed
  if (attempt.resolution || pipeline.video_params?.resolution) {
    params.resolution = attempt.resolution || pipeline.video_params?.resolution
  }
  if (durationFrames > 0) params.video_length = durationFrames
  if (startImage) params.image_start = startImage
  else delete params.image_start
  if (endImage) params.image_end = endImage
  else delete params.image_end
  params.image_prompt_type = startImage ? (endImage ? 'SE' : 'S') : ''
  if (perClipReferences) params.minimax_h3_references = perClipReferences

  const rawUploads = (metadata.upload_filenames || {}) as Record<string, unknown>
  const uploadFilenames: Record<string, string> = {}
  for (const [key, value] of Object.entries(rawUploads)) {
    const selected = indexedValue(value, clip.index)
    if (typeof selected === 'string' && selected) uploadFilenames[key] = selected
  }

  return {
    ...metadata,
    params,
    upload_filenames: uploadFilenames,
  }
}
