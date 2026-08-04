import { AlertCircle, CheckCircle2, ListVideo, Loader2 } from 'lucide-react'
import { useStore } from '../stores/useStore'

const PHASE_LABELS: Record<string, string> = {
  planning: 'Planning',
  polishing_prompts: 'Polishing prompts',
  generating_images: 'Generating images',
  preview_ready: 'Ready for review',
  generating_video: 'Generating video',
  post_processing: 'Post-processing',
  preparing_comic_video: 'Preparing comic video',
  uploading_artwork: 'Uploading artwork',
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
}

/**
 * Persistent, app-wide activity readout. Unlike a page-local spinner, this is
 * backed by Maestro's durable job queue, so reloading or navigating elsewhere
 * immediately reconnects it to work that is still running on the server.
 */
export function ActivityFooter() {
  const jobs = useStore(s => s.jobs)
  const pipelineStatus = useStore(s => s.pipelineStatus)
  const foregroundActivity = useStore(s => s.foregroundActivity)
  const setProductionsOpen = useStore(s => s.setDashboardOpen)

  const activeJobs = jobs.filter(job => job.status === 'running' || job.status === 'queued')
  const primaryJob = activeJobs[0] ?? null
  const failedJob = jobs.find(job => job.status === 'failed') ?? null
  const pipelineRunning = pipelineStatus?.status === 'running'
  const pipelineFailed = pipelineStatus?.status === 'failed'
  const foregroundRunning = foregroundActivity?.status === 'running'
  const foregroundFailed = foregroundActivity?.status === 'failed'
  const isActive = Boolean(primaryJob || pipelineRunning || foregroundRunning)
  const hasError = Boolean(!isActive && (failedJob || pipelineFailed || foregroundFailed))

  const pipelineSteps = pipelineRunning ? pipelineStatus?.progress : undefined
  const currentStep = primaryJob?.totalSteps
    ? primaryJob.step
    : pipelineSteps?.total_steps
      ? pipelineSteps.step
      : foregroundRunning
        ? foregroundActivity?.current || 0
        : 0
  const totalSteps = primaryJob?.totalSteps
    || pipelineSteps?.total_steps
    || (foregroundRunning ? foregroundActivity?.total : 0)
    || 0
  const percent = clampPercent(
    totalSteps > 0
      ? (currentStep / totalSteps) * 100
      : primaryJob
        ? primaryJob.progress * 100
        : pipelineSteps?.total
          ? (pipelineSteps.current / pipelineSteps.total) * 100
          : foregroundRunning && foregroundActivity?.total
            ? ((foregroundActivity.current || 0) / foregroundActivity.total) * 100
          : 0,
  )

  const phase = pipelineRunning
    ? PHASE_LABELS[pipelineStatus?.phase || ''] || pipelineStatus?.phase?.replaceAll('_', ' ')
    : primaryJob?.phase?.replaceAll('_', ' ')
      || (foregroundRunning
        ? PHASE_LABELS[foregroundActivity?.phase || ''] || foregroundActivity?.phase?.replaceAll('_', ' ')
        : undefined)
  const message = isActive
    ? pipelineSteps?.message || primaryJob?.message || foregroundActivity?.message || phase || 'Working…'
    : hasError
      ? pipelineStatus?.error
        || failedJob?.error
        || failedJob?.message
        || foregroundActivity?.error
        || foregroundActivity?.message
        || 'The latest job failed'
      : 'Ready — no active jobs'
  const activeCount = activeJobs.length + (pipelineRunning ? 1 : 0) + (foregroundRunning ? 1 : 0)

  return (
    <footer className="h-10 shrink-0 border-t border-border bg-bg-secondary px-3 sm:px-4 flex items-center gap-3 text-[10px] z-40">
      <div className="flex items-center gap-1.5 shrink-0">
        {isActive ? (
          <Loader2 size={13} className="animate-spin text-accent-blue" />
        ) : hasError ? (
          <AlertCircle size={13} className="text-red-400" />
        ) : (
          <CheckCircle2 size={13} className="text-emerald-400" />
        )}
        <span className="font-medium text-text-primary">Activity</span>
        {activeCount > 1 && (
          <span className="rounded-full bg-accent-blue/15 px-1.5 py-0.5 text-accent-blue tabular-nums">
            {activeCount}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1 flex items-center gap-2">
        {phase && isActive && (
          <span className="hidden sm:inline shrink-0 text-text-muted capitalize">{phase}</span>
        )}
        <span
          className={`truncate ${hasError ? 'text-red-400' : isActive ? 'text-text-secondary' : 'text-text-muted'}`}
          title={message}
        >
          {message}
        </span>
      </div>

      {isActive && (
        <div className="hidden sm:flex items-center gap-2 w-44 shrink-0">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
            <div
              className="h-full rounded-full bg-accent-blue transition-[width] duration-500"
              style={{ width: `${Math.max(percent, percent > 0 ? 2 : 0)}%` }}
            />
          </div>
          <span className="w-9 text-right tabular-nums text-text-secondary">
            {totalSteps > 0 ? `${currentStep}/${totalSteps}` : `${Math.round(percent)}%`}
          </span>
        </div>
      )}

      <button
        onClick={() => setProductionsOpen(true)}
        className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-text-secondary hover:border-accent-blue/50 hover:text-accent-blue transition-colors shrink-0"
        title="Open current and past Director productions"
      >
        <ListVideo size={12} />
        <span className="hidden sm:inline">Productions</span>
      </button>
    </footer>
  )
}
