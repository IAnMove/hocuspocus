import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, ListVideo, Loader2 } from 'lucide-react'
import { useStore } from '../stores/useStore'

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
  tokenUsage?: {
    promptTokens?: number
    completionTokens?: number
    totalTokens?: number
    calls?: number
  }
  startedAt?: number
  updatedAt: number
  dismissible?: 'activity' | 'job'
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

/**
 * App-wide activity readout. Durable generation jobs and Director pipelines
 * are normalized together with user-visible foreground workflows, but each
 * row keeps its own message and progress so concurrent work is never mixed.
 */
export function ActivityFooter() {
  const jobs = useStore(s => s.jobs)
  const pipelineStatus = useStore(s => s.pipelineStatus)
  const activeDirectorPipelines = useStore(s => s.activeDirectorPipelines)
  const activities = useStore(s => s.activities)
  const stopGeneration = useStore(s => s.stopGeneration)
  const removeActivity = useStore(s => s.removeActivity)
  const dismissJob = useStore(s => s.dismissJob)
  const setVideoWorkflowsOpen = useStore(s => s.setDashboardOpen)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [clock, setClock] = useState(() => Date.now())

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
      startedAt: epochMilliseconds(pipeline.created_at),
      updatedAt: pipeline.updated_at || pipeline.created_at || 2,
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
          updatedAt: 2,
        }]
      : []

    const visibleJobs = jobs
      .filter((job, index) => !activities[job.id]
        && (job.status === 'running' || job.status === 'queued' || index === 0))
      .map((job): ActivityView => ({
        id: `job:${job.id}`,
        title: 'Generation job',
        status: job.status === 'failed'
          ? 'failed'
          : job.status === 'completed' ? 'completed' : 'running',
        phase: job.phase,
        message: job.error || job.message || 'Generation is running…',
        current: job.totalSteps ? job.step : 0,
        total: job.totalSteps || 0,
        percent: activityProgress(job.step, job.totalSteps, job.progress),
        startedAt: job.createdAt,
        updatedAt: 1,
        dismissible: job.status === 'failed' ? 'job' as const : undefined,
      }))

    return [...registered, ...recoveredPipelines, ...pipeline, ...visibleJobs]
      .sort((left, right) => right.updatedAt - left.updatedAt)
  }, [activities, jobs, pipelineStatus, activeDirectorPipelines])

  const activeRows = rows.filter(row => row.status === 'running' || row.status === 'queued')
  const failedRows = rows.filter(row => row.status === 'failed')
  const completedRows = rows.filter(row => row.status === 'completed')
  const primary = activeRows[0] || failedRows[0] || completedRows[0] || null
  const isActive = activeRows.length > 0
  const hasError = !isActive && failedRows.length > 0
  const phase = primary
    ? PHASE_LABELS[primary.phase] || primary.phase?.replaceAll('_', ' ')
    : ''
  const message = primary?.detailMessage || primary?.message || 'Ready — no active jobs'
  useEffect(() => {
    if (!activeRows.length) return
    const interval = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [activeRows.length])
  const elapsed = (row: ActivityView) => row.startedAt
    ? formatElapsed((row.status === 'running' || row.status === 'queued' ? clock : row.updatedAt) - row.startedAt)
    : ''

  return (
    <footer className="relative h-10 shrink-0 border-t border-border bg-bg-secondary px-3 sm:px-4 flex items-center gap-3 text-[10px] z-40">
      {detailsOpen && rows.length > 0 && (
        <div className="absolute bottom-full left-3 mb-2 w-[min(34rem,calc(100vw-1.5rem))] max-h-72 overflow-y-auto rounded-lg border border-border bg-bg-secondary p-2 shadow-2xl">
          <div className="mb-1.5 flex items-center justify-between px-1">
            <span className="font-semibold text-text-primary">Current activity</span>
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
                        <span className="shrink-0 capitalize text-text-muted">{PHASE_LABELS[row.phase] || row.phase?.replaceAll('_', ' ')}</span>
                        {(row.status === 'running' || row.status === 'queued')
                          && (row.id.startsWith('job:') || row.id.startsWith('audio-analysis-')) && (
                          <button
                            type="button"
                            className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted hover:border-red-400/50 hover:text-red-400"
                            onClick={() => stopGeneration(row.id.startsWith('job:') ? row.id.slice(4) : row.id)}
                          >
                            Cancel
                          </button>
                        )}
                        {row.status === 'failed' && row.dismissible && (
                          <button
                            type="button"
                            className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted hover:text-text-primary"
                            onClick={() => row.dismissible === 'job'
                              ? dismissJob(row.id.slice(4))
                              : removeActivity(row.id)}
                          >
                            Dismiss
                          </button>
                        )}
                      </div>
                    </div>
                    <p className={row.status === 'failed' ? 'text-red-400' : 'text-text-secondary'}>{row.message}</p>
                    {row.detailMessage && (
                      <p className="truncate text-text-muted" title={row.detailMessage}>{row.detailMessage}</p>
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
        title="Show all current activities"
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
