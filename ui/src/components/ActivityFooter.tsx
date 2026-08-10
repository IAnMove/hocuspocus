import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, ListVideo, Loader2 } from 'lucide-react'
import * as api from '../api/client'
import { useStore } from '../stores/useStore'
import type { GenerationDetails } from '../types'
import type { SeriesJobStatus } from '../features/series/types'

const PHASE_LABELS: Record<string, string> = {
  planning: 'Planning',
  writing_scenes: 'Writing scenes',
  writing_prompts: 'Writing prompts',
  polishing_prompts: 'Polishing prompts',
  generating_images: 'Generating images',
  regenerating_styled_references: 'Regenerating styled references',
  preview_ready: 'Ready for review',
  generating_video: 'Generating video',
  post_processing: 'Post-processing',
  preparing_comic_video: 'Preparing comic video',
  uploading_artwork: 'Uploading artwork',
  rendering_animatic: 'Rendering animatic',
  story_planning: 'Story Lab planning',
  story_music: 'Story Lab music',
  music_planning: 'Planning music',
  writing_song: 'Writing song',
  generating_music: 'Generating music',
  music_queue: 'Music queue',
  uploading_music_reference: 'Uploading music reference',
  uploading_audio: 'Uploading audio',
  trimming_audio: 'Trimming audio',
  analyzing_audio: 'Analyzing audio',
  loading_audio: 'Loading audio',
  detecting_beats: 'Detecting beats',
  identifying_sections: 'Identifying sections',
  loading_vocal_model: 'Loading vocal model',
  extracting_vocals: 'Extracting vocals',
  loading_transcription_model: 'Loading transcription model',
  transcribing: 'Transcribing',
  loading_diarization_model: 'Loading speaker model',
  identifying_speakers: 'Identifying speakers',
  finalizing: 'Finalizing analysis',
  classifying_sections: 'Classifying song sections',
  planning_clips: 'Planning clips',
  ready_for_visual_brief: 'Ready for visual brief',
  preparing_music_video: 'Preparing music video',
  known_series_research: 'Building series bible',
  applying_draft: 'Applying series draft',
  canon: 'Preparing series canon',
}

type ActivityStatus = 'queued' | 'running' | 'completed' | 'failed'

interface ActivityView {
  id: string
  title: string
  status: ActivityStatus
  phase: string
  message: string
  current: number
  total: number
  percent: number
  detailMessage?: string
  detailCurrent?: number
  detailTotal?: number
  resourceMessage?: string
  generationDetails?: GenerationDetails
  tokenUsage?: {
    promptTokens?: number
    completionTokens?: number
    totalTokens?: number
    calls?: number
  }
  startedAt?: number
  phaseStartedAt?: number
  phaseCurrent?: number
  phaseTotal?: number
  updatedAt: number
  dismissible?: 'activity' | 'job' | 'series-plan' | 'series-render'
}

interface SeriesActivityJob {
  kind: 'plan' | 'render'
  job: SeriesJobStatus
}

function exactModelLabel(name?: string, modelType?: string): string {
  const cleanName = name?.trim()
  const cleanType = modelType?.trim()
  if (cleanName && cleanType && cleanName !== cleanType) return `${cleanName} (${cleanType})`
  return cleanName || cleanType || ''
}

function currentModelLabel(details?: GenerationDetails, phase = ''): string {
  if (!details) return ''
  if (phase.includes('image')) {
    return exactModelLabel(details.image_model_name, details.image_model_type)
      || exactModelLabel(details.model_name, details.model_type)
  }
  if (phase.includes('video') || phase.includes('render') || phase.includes('post_process')) {
    return exactModelLabel(details.video_model_name, details.video_model_type)
      || exactModelLabel(details.model_name, details.model_type)
  }
  if (phase.includes('planning') || phase.includes('writing') || phase.includes('prompt')) {
    return [details.text_provider, details.text_model].filter(Boolean).join(' / ')
      || exactModelLabel(details.model_name, details.model_type)
  }
  return exactModelLabel(details.model_name, details.model_type)
    || exactModelLabel(details.video_model_name, details.video_model_type)
    || exactModelLabel(details.image_model_name, details.image_model_type)
    || [details.text_provider, details.text_model].filter(Boolean).join(' / ')
}

function humanReadableActivityMessage(row: ActivityView): string {
  if (row.status === 'running' && row.id.startsWith('pipeline:') && row.phase === 'planning') {
    const planner = [row.generationDetails?.text_provider, row.generationDetails?.text_model]
      .filter(Boolean)
      .join(' / ')
    const clipCount = row.generationDetails?.clip_count
    const target = clipCount ? `${clipCount} timed shot${clipCount === 1 ? '' : 's'}` : 'the timed shot plan'
    return `${planner || 'The planning LLM'} is writing ${target}: scene, action, camera and final generation prompt. Waiting for the remote response; image and video generation have not started.`
  }
  return row.detailMessage || row.message
}

function generationRecipe(details?: GenerationDetails, phase = ''): string {
  if (!details) return ''
  const parts: string[] = []
  const currentModel = currentModelLabel(details, phase)
  if (currentModel) parts.push(`Using: ${currentModel}`)

  const imageModel = exactModelLabel(details.image_model_name, details.image_model_type)
  const videoModel = exactModelLabel(details.video_model_name, details.video_model_type)
  const textModel = [details.text_provider, details.text_model].filter(Boolean).join(' / ')
  if (textModel && textModel !== currentModel) parts.push(`text ${textModel}`)
  if (imageModel && imageModel !== currentModel) parts.push(`image ${imageModel}`)
  if (videoModel && videoModel !== currentModel) parts.push(`video ${videoModel}`)

  const resolution = phase.includes('image')
    ? details.image_resolution || details.resolution
    : phase.includes('video') || videoModel
      ? details.video_resolution || details.resolution
      : details.resolution || details.image_resolution
  const steps = phase.includes('image')
    ? details.image_steps || details.steps
    : phase.includes('video') || videoModel
      ? details.video_steps || details.steps
      : details.steps || details.image_steps
  if (resolution) parts.push(String(resolution))
  if (details.seed !== undefined) parts.push(`seed ${details.seed}`)
  if (steps !== undefined) parts.push(`${steps} steps`)
  if (details.guidance !== undefined) parts.push(`guidance ${details.guidance}`)
  if (details.frames !== undefined) parts.push(`${details.frames} frames`)
  if (details.duration_seconds !== undefined) parts.push(`${details.duration_seconds}s`)
  if (details.repeat !== undefined && details.repeat > 1) parts.push(`${details.repeat} outputs`)
  if (details.clip_count !== undefined) parts.push(`${details.clip_count} clips`)
  if (details.profile) parts.push(`profile ${details.profile}`)
  if (details.flow_shift !== undefined) parts.push(`flow shift ${details.flow_shift}`)
  if (details.audio_shift !== undefined) parts.push(`audio shift ${details.audio_shift}`)
  if (details.turbo !== undefined) parts.push(`Turbo ${details.turbo ? 'on' : 'off'}`)
  return parts.join(' · ')
}

function generationTitle(details?: GenerationDetails): string {
  switch (details?.generation_mode) {
    case 'image': return 'Image generation'
    case 'video': return 'Video generation'
    case 'audio':
    case 'music': return 'Music generation'
    case 'model3d': return '3D generation'
    case 'avatar': return 'Video edit'
    default: return 'Generation job'
  }
}

function resourceMessage(schedule?: import('../api/client').PipelineResourceSchedule): string | undefined {
  if (!schedule?.lanes) return undefined
  const planning = schedule.lanes.planning?.label
  const images = schedule.lanes.images?.label
  const video = schedule.lanes.video?.label
  if (schedule.mode === 'remote-images+local-video') {
    const ready = schedule.images_total
      ? ` · images ${schedule.images_ready || 0}/${schedule.images_total}`
      : ''
    return `Parallel resources · ${images} → ${video}${ready}`
  }
  return `Resources · planning: ${planning || 'unknown'} · images: ${images || 'unknown'} · video: ${video || 'unknown'}`
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
}

function activityProgress(current: number, total: number, explicit?: number): number {
  if (total > 0) return clampPercent((current / total) * 100)
  return clampPercent((explicit || 0) * (explicit && explicit <= 1 ? 100 : 1))
}

function epochMilliseconds(value?: number): number | undefined {
  if (!value || !Number.isFinite(value)) return undefined
  return value < 1_000_000_000_000 ? value * 1000 : value
}

function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return hours > 0
    ? `${hours}:${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`
    : `${minutes}:${remainder.toString().padStart(2, '0')}`
}

function formatEstimate(milliseconds: number): string {
  const minutes = Math.max(1, Math.ceil(milliseconds / 60_000))
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`
}

function estimatedRemaining(row: ActivityView, now: number): string {
  if (row.status !== 'running') return ''
  const current = row.phaseCurrent ?? row.current
  const total = row.phaseTotal ?? row.total
  const startedAt = row.phaseStartedAt || row.startedAt
  if (!startedAt || current <= 0 || total <= current) return ''
  const elapsed = now - startedAt
  // A first very short sample is too noisy to be useful.
  if (elapsed < 10_000) return ''
  const remaining = (elapsed / current) * (total - current)
  if (!Number.isFinite(remaining) || remaining <= 0) return ''
  return `ETA ~${formatEstimate(remaining)}`
}

/**
 * App-wide activity readout. Durable generation jobs and Director pipelines
 * are normalized together with user-visible foreground workflows, but each
 * row keeps its own message and progress so concurrent work is never mixed.
 */
export function ActivityFooter() {
  const jobs = useStore(s => s.jobs)
  const pipelineStatus = useStore(s => s.pipelineStatus)
  const activeDirectorPipelines = useStore(s => s.activeDirectorPipelines)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const activities = useStore(s => s.activities)
  const stopGeneration = useStore(s => s.stopGeneration)
  const stopPipeline = useStore(s => s.stopPipeline)
  const removeActivity = useStore(s => s.removeActivity)
  const dismissJob = useStore(s => s.dismissJob)
  const setVideoWorkflowsOpen = useStore(s => s.setDashboardOpen)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [cancellingIds, setCancellingIds] = useState<Set<string>>(() => new Set())
  const [seriesJobs, setSeriesJobs] = useState<SeriesActivityJob[]>([])
  const [clock, setClock] = useState(() => Date.now())

  useEffect(() => {
    let mounted = true
    const refresh = async () => {
      try {
        const [plans, renders] = await Promise.all([
          api.fetchSeriesPlanRecovery(activeWorkspace),
          api.fetchSeriesRenderRecovery(activeWorkspace),
        ])
        if (!mounted) return
        setSeriesJobs([
          ...plans.jobs.map(job => ({ kind: 'plan' as const, job })),
          ...renders.jobs.map(job => ({ kind: 'render' as const, job })),
        ])
      } catch {
        // Series Lab may be unavailable during a rolling backend update. Other
        // footer sources must remain visible instead of turning this into a UI error.
      }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2000)
    return () => { mounted = false; window.clearInterval(timer) }
  }, [activeWorkspace])

  const rows = useMemo<ActivityView[]>(() => {
    const registered = Object.values(activities).map(activity => ({
      id: activity.id,
      title: activity.title || 'Maestro',
      status: activity.status,
      phase: activity.phase,
      message: activity.error || activity.message,
      current: activity.current || 0,
      total: activity.total || 0,
      percent: activityProgress(activity.current || 0, activity.total || 0, activity.progress),
      detailMessage: activity.detailMessage,
      detailCurrent: activity.detailCurrent,
      detailTotal: activity.detailTotal,
      generationDetails: activity.generationDetails,
      tokenUsage: activity.tokenUsage,
      startedAt: activity.startedAt,
      updatedAt: activity.updatedAt || activity.startedAt || 3,
      dismissible: activity.status === 'failed' ? 'activity' as const : undefined,
    }))

    const recoveredPipelines: ActivityView[] = activeDirectorPipelines.map(pipeline => ({
      id: `pipeline:${pipeline.id}`,
      title: pipeline.pipeline_type === 'music_video' ? 'Music video' : 'Director pipeline',
      status: pipeline.status === 'paused' ? 'queued' : 'running',
      phase: pipeline.phase,
      message: pipeline.error || pipeline.progress?.message || 'Director is working…',
      current: pipeline.progress?.total_steps ? pipeline.progress.step : pipeline.progress?.current || 0,
      total: pipeline.progress?.total_steps || pipeline.progress?.total || 0,
      percent: activityProgress(
        pipeline.progress?.total_steps ? pipeline.progress.step : pipeline.progress?.current || 0,
        pipeline.progress?.total_steps || pipeline.progress?.total || 0,
      ),
      resourceMessage: resourceMessage(pipeline.resource_schedule),
      generationDetails: pipeline.generation_details,
      startedAt: epochMilliseconds(pipeline.created_at),
      phaseStartedAt: epochMilliseconds(pipeline.phase_started_at),
      phaseCurrent: pipeline.progress?.current || 0,
      phaseTotal: pipeline.progress?.total || 0,
      updatedAt: epochMilliseconds(pipeline.updated_at || pipeline.created_at) || 2,
    }))

    const pipeline: ActivityView[] = pipelineStatus
      && ['running', 'failed', 'completed'].includes(pipelineStatus.status)
      && !activeDirectorPipelines.some(pipeline => pipeline.id === pipelineStatus.id)
      ? [{
          id: `pipeline:${pipelineStatus.id}`,
          title: 'Director pipeline',
          status: pipelineStatus.status === 'failed'
            ? 'failed'
            : pipelineStatus.status === 'completed' ? 'completed' : 'running',
          phase: pipelineStatus.phase,
          message: pipelineStatus.error || pipelineStatus.progress?.message || 'Director is working…',
          current: pipelineStatus.progress?.total_steps
            ? pipelineStatus.progress.step
            : pipelineStatus.progress?.current || 0,
          total: pipelineStatus.progress?.total_steps || pipelineStatus.progress?.total || 0,
          percent: activityProgress(
            pipelineStatus.progress?.total_steps ? pipelineStatus.progress.step : pipelineStatus.progress?.current || 0,
            pipelineStatus.progress?.total_steps || pipelineStatus.progress?.total || 0,
          ),
          resourceMessage: resourceMessage(pipelineStatus.resource_schedule),
          generationDetails: pipelineStatus.generation_details,
          startedAt: epochMilliseconds(pipelineStatus.created_at),
          phaseStartedAt: epochMilliseconds(pipelineStatus.phase_started_at),
          phaseCurrent: pipelineStatus.progress?.current || 0,
          phaseTotal: pipelineStatus.progress?.total || 0,
          updatedAt: epochMilliseconds(pipelineStatus.updated_at || pipelineStatus.created_at) || 2,
        }]
      : []

    const visibleJobs = jobs
      .filter((job, index) => !activities[job.id]
        && (job.status === 'running'
          || job.status === 'queued'
          || (index === 0 && (job.status === 'completed' || job.status === 'failed'))))
      .map((job): ActivityView => ({
        id: `job:${job.id}`,
        title: generationTitle(job.generationDetails),
        status: job.status === 'failed'
          ? 'failed'
          : job.status === 'completed' || job.status === 'cancelled'
            ? 'completed'
            : job.status === 'queued' ? 'queued' : 'running',
        phase: job.phase,
        message: job.error
          || (job.status === 'queued' && job.queuePosition
            ? `Queued · position ${job.queuePosition}`
            : job.message)
          || (job.status === 'queued' ? 'Queued' : 'Generation is running…'),
        current: job.totalSteps ? job.step : 0,
        total: job.totalSteps || 0,
        percent: activityProgress(job.step, job.totalSteps, job.progress),
        generationDetails: job.generationDetails,
        // Ordinary jobs deliberately omit queue wait from their timer. A
        // Director/music-video pipeline above keeps created_at as its total
        // workflow clock, including planning, generation and assembly.
        startedAt: job.startedAt,
        updatedAt: job.finishedAt || job.startedAt || job.createdAt || 1,
        dismissible: job.status === 'failed' ? 'job' as const : undefined,
      }))

    const visibleSeriesJobs: ActivityView[] = seriesJobs.map(({ job, kind }) => {
      const failed = job.status === 'failed'
      const terminal = failed || job.status === 'cancelled'
      return {
        id: `${kind === 'plan' ? 'series-plan' : 'series-render'}:${job.jobId}`,
        title: kind === 'render'
          ? 'Series Lab · Video generation'
          : job.bootstrapKnownSeries
            ? 'Series Lab · Known-series bible'
            : job.jobType === 'canon' ? 'Series Lab · Canon' : 'Series Lab · Episode planning',
        status: failed ? 'failed' : job.status === 'cancelled' ? 'completed'
          : job.status === 'queued' ? 'queued' : 'running',
        phase: job.stage,
        message: job.error || job.message || (job.status === 'queued' ? 'Queued' : 'Series Lab is working…'),
        current: job.current || 0,
        total: job.total || 0,
        percent: activityProgress(job.current || 0, job.total || 0),
        startedAt: epochMilliseconds(job.createdAt),
        updatedAt: epochMilliseconds(job.updatedAt || job.createdAt) || 1,
        dismissible: terminal ? (kind === 'plan' ? 'series-plan' : 'series-render') : undefined,
      }
    })

    return [...registered, ...recoveredPipelines, ...pipeline, ...visibleJobs, ...visibleSeriesJobs]
      .sort((left, right) => right.updatedAt - left.updatedAt)
  }, [activities, jobs, pipelineStatus, activeDirectorPipelines, seriesJobs])

  const activeRows = rows
    .filter(row => row.status === 'running' || row.status === 'queued')
    .sort((left, right) => {
      if (left.status !== right.status) return left.status === 'running' ? -1 : 1
      return right.updatedAt - left.updatedAt
    })
  const failedRows = rows.filter(row => row.status === 'failed')
  const completedRows = rows.filter(row => row.status === 'completed')
  // Prefer a cancellable backend job/pipeline over a foreground wrapper. A
  // wrapper may be newer because it mirrors the same child progress, but it
  // cannot stop the GPU worker itself and used to hide the useful Cancel.
  const primary = activeRows.find(row => (
    row.id.startsWith('job:')
    || row.id.startsWith('audio-analysis-')
    || row.id.startsWith('pipeline:')
  )) || activeRows[0] || failedRows[0] || completedRows[0] || null
  const isActive = activeRows.length > 0
  const hasError = !isActive && failedRows.length > 0
  const phase = primary
    ? PHASE_LABELS[primary.phase] || primary.phase?.replaceAll('_', ' ')
    : ''
  const message = primary ? humanReadableActivityMessage(primary) : 'Ready — no active jobs'
  const primaryModel = primary ? currentModelLabel(primary.generationDetails, primary.phase) : ''
  useEffect(() => {
    if (!activeRows.length) return
    const interval = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [activeRows.length])
  const elapsed = (row: ActivityView) => row.startedAt
    ? formatElapsed((row.status === 'running' || row.status === 'queued' ? clock : row.updatedAt) - row.startedAt)
    : ''
  const phaseElapsed = (row: ActivityView) => row.phaseStartedAt
    ? formatElapsed((row.status === 'running' || row.status === 'queued' ? clock : row.updatedAt) - row.phaseStartedAt)
    : ''
  const canCancel = (row: ActivityView) => (
    (row.status === 'running' || row.status === 'queued')
    && (
      row.id.startsWith('job:') || row.id.startsWith('audio-analysis-')
      || row.id.startsWith('pipeline:') || row.id.startsWith('series-plan:')
      || row.id.startsWith('series-render:')
    )
  )
  const cancelRow = (row: ActivityView) => {
    if (!canCancel(row) || cancellingIds.has(row.id)) return
    setCancellingIds(current => new Set(current).add(row.id))
    const operation = row.id.startsWith('pipeline:')
      ? stopPipeline(row.id.slice('pipeline:'.length))
      : row.id.startsWith('series-plan:')
        ? api.cancelSeriesPlanJob(row.id.slice('series-plan:'.length))
        : row.id.startsWith('series-render:')
          ? api.cancelSeriesRenderJob(row.id.slice('series-render:'.length))
          : Promise.resolve(stopGeneration(row.id.startsWith('job:') ? row.id.slice(4) : row.id))
    void operation.catch(error => {
      console.error('Failed to cancel activity:', error)
    }).finally(() => {
      setCancellingIds(current => {
        const next = new Set(current)
        next.delete(row.id)
        return next
      })
    })
  }
  const dismissRow = (row: ActivityView) => {
    if (row.dismissible === 'job') {
      dismissJob(row.id.slice(4))
      return
    }
    if (row.dismissible === 'activity') {
      removeActivity(row.id)
      return
    }
    const operation = row.dismissible === 'series-plan'
      ? api.discardSeriesPlanJob(row.id.slice('series-plan:'.length))
      : row.dismissible === 'series-render'
        ? api.discardSeriesRenderJob(row.id.slice('series-render:'.length))
        : null
    if (!operation) return
    void operation.then(() => {
      setSeriesJobs(current => current.filter(item => item.job.jobId !== row.id.split(':').slice(1).join(':')))
    }).catch(error => console.error('Failed to dismiss Series Lab activity:', error))
  }

  return (
    <footer className="relative h-10 shrink-0 border-t border-border bg-bg-secondary px-3 sm:px-4 flex items-center gap-3 text-[10px] z-40">
      {detailsOpen && rows.length > 0 && (
        <div className="absolute bottom-full left-3 mb-2 w-[min(44rem,calc(100vw-1.5rem))] max-h-72 overflow-y-auto rounded-lg border border-border bg-bg-secondary p-2 shadow-2xl">
          <div className="mb-1.5 flex items-center justify-between px-1">
            <span className="font-semibold text-text-primary">{activeRows.length ? 'Current activity' : 'Recent activity'}</span>
            <span className="text-text-muted">{activeRows.length} active</span>
          </div>
          <div className="space-y-1.5">
            {rows.map(row => (
              <div key={row.id} className="rounded-md border border-border bg-bg-primary p-2">
                <div className="flex items-start gap-2">
                  {row.status === 'running' || row.status === 'queued'
                    ? <Loader2 size={12} className="mt-0.5 shrink-0 animate-spin text-accent-blue" />
                    : row.status === 'failed'
                      ? <AlertCircle size={12} className="mt-0.5 shrink-0 text-red-400" />
                      : <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-emerald-400" />}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-text-primary">{row.title}</span>
                      <div className="flex items-center gap-2">
                        {elapsed(row) && <span className="shrink-0 tabular-nums text-text-muted">{elapsed(row)}</span>}
                        {phaseElapsed(row) && (
                          <span className="shrink-0 tabular-nums text-text-muted" title="Elapsed time in the current phase">
                            phase {phaseElapsed(row)}
                          </span>
                        )}
                        {estimatedRemaining(row, clock) && (
                          <span
                            className="shrink-0 tabular-nums text-accent-blue"
                            title={`Approximate time remaining for this phase · phase elapsed ${phaseElapsed(row) || elapsed(row)}`}
                          >
                            {estimatedRemaining(row, clock)}
                          </span>
                        )}
                        <span className="shrink-0 capitalize text-text-muted">{PHASE_LABELS[row.phase] || row.phase?.replaceAll('_', ' ')}</span>
                        {canCancel(row) && (
                          <button
                            type="button"
                            className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted hover:border-red-400/50 hover:text-red-400"
                            disabled={cancellingIds.has(row.id)}
                            onClick={() => cancelRow(row)}
                          >
                            {cancellingIds.has(row.id) ? 'Cancelling…' : 'Cancel'}
                          </button>
                        )}
                        {(row.status === 'failed' || row.status === 'completed') && row.dismissible && (
                          <button
                            type="button"
                            className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted hover:text-text-primary"
                            onClick={() => dismissRow(row)}
                          >
                            Dismiss
                          </button>
                        )}
                      </div>
                    </div>
                    <p className={row.status === 'failed' ? 'text-red-400' : 'text-text-secondary'}>{humanReadableActivityMessage(row)}</p>
                    {row.detailMessage && (
                      <p className="truncate text-text-muted" title={row.detailMessage}>{row.detailMessage}</p>
                    )}
                    {generationRecipe(row.generationDetails, row.phase) && (
                      <p
                        className="mt-0.5 break-words text-[9px] text-amber-300"
                        title={generationRecipe(row.generationDetails, row.phase)}
                      >
                        {generationRecipe(row.generationDetails, row.phase)}
                      </p>
                    )}
                    {row.resourceMessage && (
                      <p className="truncate text-[9px] text-accent-blue" title={row.resourceMessage}>{row.resourceMessage}</p>
                    )}
                    {!!row.tokenUsage?.totalTokens && (
                      <p className="mt-1 tabular-nums text-text-muted" title={`Input: ${(row.tokenUsage.promptTokens || 0).toLocaleString()} · Output: ${(row.tokenUsage.completionTokens || 0).toLocaleString()} · Calls: ${row.tokenUsage.calls || 0}`}>
                        {(row.tokenUsage.totalTokens || 0).toLocaleString()} tokens
                        {' · '}{(row.tokenUsage.promptTokens || 0).toLocaleString()} input
                        {' · '}{(row.tokenUsage.completionTokens || 0).toLocaleString()} output
                      </p>
                    )}
                    {(row.status === 'running' || row.status === 'queued') && !!row.detailTotal && (
                      <div className="mt-1.5 flex items-center gap-2" title={row.detailMessage}>
                        <div className="h-1 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
                          <div
                            className="h-full rounded-full bg-amber-400 transition-[width] duration-300"
                            style={{ width: `${Math.max(((row.detailCurrent || 0) / row.detailTotal) * 100, row.detailCurrent ? 2 : 0)}%` }}
                          />
                        </div>
                        <span className="w-10 text-right tabular-nums text-text-muted">
                          {row.detailCurrent || 0}/{row.detailTotal}
                        </span>
                      </div>
                    )}
                    {(row.status === 'running' || row.status === 'queued') && (
                      <div className="mt-1.5 flex items-center gap-2">
                        <div className="h-1 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
                          <div className="h-full rounded-full bg-accent-blue transition-[width] duration-300" style={{ width: `${Math.max(row.percent, row.percent > 0 ? 2 : 0)}%` }} />
                        </div>
                        <span className="w-10 text-right tabular-nums text-text-muted">
                          {row.total > 0 ? `${row.current}/${row.total}` : `${Math.round(row.percent)}%`}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => setDetailsOpen(open => !open)}
        className="flex items-center gap-1.5 shrink-0"
        aria-expanded={detailsOpen}
        title="Show activity history"
      >
        {isActive ? (
          <Loader2 size={13} className="animate-spin text-accent-blue" />
        ) : hasError ? (
          <AlertCircle size={13} className="text-red-400" />
        ) : (
          <CheckCircle2 size={13} className="text-emerald-400" />
        )}
        <span className="font-medium text-text-primary">Activity</span>
        {activeRows.length > 0 && (
          <span className="rounded-full bg-accent-blue/15 px-1.5 py-0.5 text-accent-blue tabular-nums">
            {activeRows.length}
          </span>
        )}
        {detailsOpen ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
      </button>

      <div className="min-w-0 flex-1 flex items-center gap-2">
        {phase && primary && (
          <span className="hidden sm:inline shrink-0 text-text-muted capitalize">{phase}</span>
        )}
        {primary && elapsed(primary) && (
          <span className="shrink-0 tabular-nums text-text-muted">{elapsed(primary)}</span>
        )}
        {primary && estimatedRemaining(primary, clock) && (
          <span
            className="hidden sm:inline shrink-0 tabular-nums text-accent-blue"
            title={`Approximate time remaining for this phase · phase elapsed ${phaseElapsed(primary) || elapsed(primary)}`}
          >
            {estimatedRemaining(primary, clock)}
          </span>
        )}
        {primaryModel && (
          <span
            className="hidden md:inline max-w-64 shrink-0 truncate rounded border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-amber-300"
            title={generationRecipe(primary?.generationDetails, primary?.phase)}
          >
            {primaryModel}
          </span>
        )}
        <span
          className={`truncate ${hasError ? 'text-red-400' : isActive ? 'text-text-secondary' : 'text-text-muted'}`}
          title={message}
        >
          {message}
        </span>
      </div>

      {isActive && primary && (
        <div className="hidden sm:flex items-center gap-2 w-52 shrink-0">
          {!!primary.detailTotal && (
            <span className="shrink-0 tabular-nums text-amber-300" title={primary.detailMessage}>
              {primary.detailCurrent || 0}/{primary.detailTotal}
            </span>
          )}
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
            <div
              className="h-full rounded-full bg-accent-blue transition-[width] duration-500"
              style={{ width: `${Math.max(primary.percent, primary.percent > 0 ? 2 : 0)}%` }}
            />
          </div>
          <span className="w-9 text-right tabular-nums text-text-secondary">
            {primary.total > 0 ? `${primary.current}/${primary.total}` : `${Math.round(primary.percent)}%`}
          </span>
        </div>
      )}

      {primary && canCancel(primary) && (
        <button
          type="button"
          disabled={cancellingIds.has(primary.id)}
          onClick={() => cancelRow(primary)}
          className="flex shrink-0 items-center gap-1 rounded-md border border-red-400/40 px-2 py-1 text-red-300 transition-colors hover:border-red-300 hover:text-red-200 disabled:opacity-50"
          title="Cancel this complete generation workflow"
        >
          {cancellingIds.has(primary.id) && <Loader2 size={11} className="animate-spin" />}
          <span>{cancellingIds.has(primary.id) ? 'Cancelling…' : 'Cancel'}</span>
        </button>
      )}

      <button
        onClick={() => setVideoWorkflowsOpen(true)}
        className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-text-secondary hover:border-accent-blue/50 hover:text-accent-blue transition-colors shrink-0"
        title="Open independent video creations and edit their clips"
      >
        <ListVideo size={12} />
        <span className="hidden sm:inline">Video workflows</span>
      </button>
    </footer>
  )
}
