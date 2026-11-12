import type { StoreApi } from 'zustand'
import * as api from '../api/client'
import { isHttpStatus } from '../api/http'
import { isGenerationJobActive, isGenerationJobInterrupted } from '../lib/generationJobState'
import type { GenerationJob } from '../types'
import { _jobTimingPatch } from '../features/studio/store/toolsSlice'
import { _downloadTimestampMs } from './civitaiSlice'
import { markJobsCancelling, removeJob, withJobs } from './jobReducers'
import type { SliceCreator } from './storeApi'
import type { AppState } from './useStore'

const RECONNECT_POLL_MS = 2000
// Consecutive failed polls before the tile says the connection is lost.
const RECONNECT_OFFLINE_AFTER = 3
const RECONNECT_OFFLINE_MESSAGE = 'Connection lost — retrying…'

function _jobStatusPatch(job: GenerationJob, status: api.ApiJobStatus): GenerationJob {
  return {
    ...job,
    status: status.status,
    progress: status.progress / 100,
    step: status.step ?? 0,
    totalSteps: status.total_steps ?? 0,
    phase: status.phase ?? '',
    message: status.message,
    outputFiles: status.output_files,
    error: status.error,
    oomInfo: status.oom_info ?? null,
    taskTimings: status.task_timings ?? [],
    h3WindowPlan: status.h3_window_plan ?? job.h3WindowPlan ?? null,
    ..._jobTimingPatch(status),
  }
}

/** Follow a job restored on page load. A backend restart or a proxy 502
 *  keeps the tile and retries with backoff; only a 404 means the job is gone. */
function _pollReconnectedJob(
  jobId: string,
  set: StoreApi<AppState>['setState'],
  get: StoreApi<AppState>['getState'],
): void {
  let failures = 0
  const patchJob = (update: (job: GenerationJob) => GenerationJob) =>
    set(s => ({ jobs: s.jobs.map(j => j.id === jobId ? update(j) : j) }))
  const tick = async () => {
    if (!get().jobs.some(j => j.id === jobId)) return
    try {
      const status = await api.fetchJobStatus(jobId)
      failures = 0
      patchJob(j => _jobStatusPatch(j, status))
      if (isGenerationJobInterrupted(status.status)) {
        set(s => withJobs(s.jobs))
        return
      }
      if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
        set(s => removeJob(s.jobs, j => j.id === jobId))
        void get().maybeRefreshGallery({ message: 'New output ready' })
        return
      }
    } catch (reason) {
      if (isHttpStatus(reason, 404)) {
        set(s => removeJob(s.jobs, j => j.id === jobId))
        return
      }
      failures += 1
      if (failures >= RECONNECT_OFFLINE_AFTER) {
        patchJob(j => ({ ...j, phase: RECONNECT_OFFLINE_MESSAGE, message: RECONNECT_OFFLINE_MESSAGE }))
      }
    }
    window.setTimeout(() => void tick(), RECONNECT_POLL_MS * 2 ** Math.min(failures, 4))
  }
  window.setTimeout(() => void tick(), RECONNECT_POLL_MS)
}

export type JobsSlice = {
  jobs: GenerationJob[]
  isGenerating: boolean
  stopGeneration: (jobId?: string) => void
  dismissJob: (jobId: string) => void
  reconnectJobs: () => Promise<void>
}

/** Queue tiles and the reconnect poll. The host is AppState so the restored-job poll keeps its StoreApi<AppState> set and get parameters. */
export const createJobsSlice: SliceCreator<JobsSlice, AppState> = (set, get) => ({
  jobs: [],
  isGenerating: false,
  stopGeneration: (jobId) => {
    const currentJobs = get().jobs
    const targetIds = jobId
      ? currentJobs
          .filter(j => j.id === jobId && isGenerationJobActive(j.status) && j.status !== 'cancelling')
          .map(j => j.id)
      : currentJobs
          .filter(j => j.id && isGenerationJobActive(j.status) && j.status !== 'cancelling')
          .map(j => j.id)
    if (targetIds.length === 0) return
    const previousStatuses = new Map(
      currentJobs
        .filter(j => targetIds.includes(j.id))
        .map(j => [j.id, j.status] as const),
    )

    // Keep the job visible while the worker unwinds. Removing it immediately
    // made a still-running model download look as if Cancel had done nothing
    // and hid backend errors. Existing status polling will publish the final
    // cancelled state once the endpoint acknowledges the request.
    const targets = new Set(targetIds)
    set(s => markJobsCancelling(s.jobs, targets))
    targetIds.forEach(id => {
      void api.cancelJob(id).catch(e => {
        const message = e instanceof Error ? e.message : 'Cancel failed'
        console.error('Cancel failed:', e)
        set(s => ({
          jobs: s.jobs.map(j => j.id === id
            ? {
                ...j,
                status: j.status === 'cancelling'
                  ? (previousStatuses.get(id) ?? 'running')
                  : j.status,
                message: `Cancel failed: ${message}`,
                phase: j.phase,
              }
            : j),
        }))
      })
    })
  },
  // UI-only removal of a job tile (e.g. dismissing a failed/cancelled
  // placeholder). No backend call — the job is already terminal.
  dismissJob: (jobId) => {
    set(s => removeJob(s.jobs, j => j.id === jobId))
  },
  reconnectJobs: async () => {
    // On page load, check backend for any active jobs and restore them
    try {
      const data = await api.fetchActiveJobs()
      if (data.jobs.length > 0) {
        const existingIds = new Set(get().jobs.map(j => j.id))
        const newJobs: GenerationJob[] = data.jobs
          .filter(j => !existingIds.has(j.job_id))
          .map(j => ({
            id: j.job_id,
            status: j.status as GenerationJob['status'],
            progress: j.progress / 100,
            step: j.step,
            totalSteps: j.total_steps,
            phase: j.phase,
            message: j.message,
            outputFiles: j.output_files,
            error: j.error,
            createdAt: j.created_at < 1_000_000_000_000 ? j.created_at * 1000 : j.created_at,
            startedAt: _downloadTimestampMs(j.started_at) ?? undefined,
            finishedAt: _downloadTimestampMs(j.finished_at) ?? undefined,
            queuePosition: j.queue_position,
            oomInfo: (j as { oom_info?: import('../types').OomInfo | null }).oom_info ?? null,
            taskTimings: j.task_timings ?? [],
            h3WindowPlan: j.h3_window_plan ?? null,
            generationDetails: j.generation_details,
          }))
        if (newJobs.length > 0) {
          set(s => withJobs([...s.jobs, ...newJobs]))
          newJobs.forEach(job => _pollReconnectedJob(job.id, set, get))
          console.log(`[Queue] Reconnected to ${newJobs.length} active job(s)`)
        }
      }
    } catch {
      // Backend might not have the endpoint yet, silently ignore
    }
  },
})
