import type { PipelineClipState, PipelineVideoAttempt, PlannedDirectorClip, SavedPipelineState } from '../../types'

export function hydratePipelineQueue(pipeline: SavedPipelineState): SavedPipelineState {
  if (pipeline.clips?.length) return pipeline
  const planned = pipeline.planned_clips || []
  const plans = pipeline.clip_plans || []
  const source = plans.length ? plans : planned
  if (!source.length) return pipeline
  return {
    ...pipeline,
    queue_source: plans.length ? 'clip_plans' : 'planned',
    clips: source.map((item, index) => {
      const record = item as Record<string, unknown>
      const plannedItem = (planned[index] || record) as PlannedDirectorClip
      const videoPrompt = String(
        record.video_prompt
        || plannedItem._director_h3_source_prompt
        || plannedItem.suggested_prompt_hint
        || '',
      )
      return {
        index,
        shot_id: String(record.shot_id || plannedItem.shot_id || ''),
        seed: typeof record.seed === 'number' ? record.seed : undefined,
        duration_seconds: plannedItem.duration_sec ?? plannedItem._director_duration_sec,
        planned_clip: plannedItem as unknown as PipelineClipState['planned_clip'],
        image_prompt: String(record.image_prompt || ''),
        video_prompt: videoPrompt,
        keyframe_prompts: Array.isArray(record.keyframe_prompts) ? record.keyframe_prompts as string[] : [],
        window_prompts: Array.isArray(record.window_prompts) ? record.window_prompts as string[] : [],
        window_count: Number(record.window_count || 1),
        image_prompt_pre_polish: null,
        video_prompt_pre_polish: null,
        window_prompts_pre_polish: null,
        keyframe_prompts_pre_polish: null,
        start_image_filename: null,
        keyframe_filenames: [],
        video_filename: null,
        video_attempts: [],
        tag: null,
        image_gen_time_sec: null,
        video_gen_time_sec: null,
        _director_h3_source_prompt: plannedItem._director_h3_source_prompt || videoPrompt,
        _director_audio_plan: plannedItem._director_audio_plan,
        _director_dialogue_beats: plannedItem._director_dialogue_beats,
        _director_subjects_on_screen: plannedItem._director_subjects_on_screen,
        _director_h3_prompt_mode: plannedItem._director_h3_prompt_mode,
      }
    }),
  }
}

export function attemptsForClip(clip: PipelineClipState): PipelineVideoAttempt[] {
  if (clip.video_attempts?.length) return clip.video_attempts
  return clip.video_filename ? [{
    id: clip.video_filename,
    filename: clip.video_filename,
    created_at: 0,
    seed: clip.seed,
    prompt: clip.video_prompt,
    source: 'recovered',
  }] : []
}

export function selectedAttempt(clip: PipelineClipState): PipelineVideoAttempt | null {
  const attempts = attemptsForClip(clip)
  const selected = clip.selected_video_filename || clip.video_filename
  return attempts.find(attempt => attempt.filename === selected)
    || attempts[attempts.length - 1]
    || null
}

export function shotDuration(clip: PipelineClipState): number | null {
  const planned = clip.planned_clip as { duration_sec?: number } | null
  const value = clip.duration_seconds ?? planned?.duration_sec
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function shotPrompt(clip: PipelineClipState): string {
  return clip.video_prompt
    || clip._director_h3_source_prompt
    || clip.image_prompt
    || ''
}

export function fileLabel(path: string | null | undefined): string {
  return String(path || '').split(/[\\/]/).pop() || String(path || '')
}

export function pipelineBusy(pipeline: SavedPipelineState | null): boolean {
  const status = (pipeline?.status || '').toLowerCase()
  const repair = pipeline?.repair?.status
  return ['queued', 'planning', 'running', 'resuming', 'cancelling'].includes(status)
    || repair === 'queued'
    || repair === 'running'
    || repair === 'cancelling'
}

export function pipelineCanLaunch(pipeline: SavedPipelineState | null): boolean {
  if (!pipeline) return false
  const status = (pipeline.status || '').toLowerCase()
  return ['failed', 'crashed', 'cancelled', 'paused', 'interrupted'].includes(status)
    && (pipeline.clips?.length || 0) > 0
}

export function pipelineLabel(item: { pipeline_type?: string; scene_description?: string }): string {
  const type = (item.pipeline_type || 'thread').replace(/_/g, ' ')
  const scene = (item.scene_description || '').trim()
  return scene || type
}
