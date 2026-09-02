import { AlertTriangle, Loader2, Play, RotateCcw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import * as api from '../api/client'
import { useUiTranslation } from '../i18n'
import { useStore } from '../stores/useStore'

const LIVE_JOB_STATUSES = new Set(['queued', 'running', 'waiting_resource', 'cancelling'])

export function QueueRecoveryDialog() {
  const { t } = useUiTranslation('director')
  const reconnectJobs = useStore(state => state.reconnectJobs)
  const [jobs, setJobs] = useState<api.RecoverableGenerationJob[]>([])
  const [liveBusyCount, setLiveBusyCount] = useState(0)
  const [checking, setChecking] = useState(true)
  const [action, setAction] = useState<'resume' | 'discard' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const inspect = async () => {
    setChecking(true)
    setError(null)
    try {
      const [result, active] = await Promise.all([
        api.fetchGenerationQueueRecovery(),
        api.fetchActiveJobs().catch(() => ({ jobs: [] as Array<{ status: string }> })),
      ])
      setJobs(result.jobs)
      setLiveBusyCount(
        (active.jobs || []).filter(job => LIVE_JOB_STATUSES.has(job.status)).length,
      )
    } catch {
      // Supports opening a new UI build momentarily against an older backend
      // during updates without presenting a false recovery failure.
      setJobs([])
      setLiveBusyCount(0)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    void inspect()
  }, [])

  if (checking || jobs.length === 0) return null

  const resume = async () => {
    setAction('resume')
    setError(null)
    try {
      await api.resumeGenerationQueue()
      setJobs([])
      await reconnectJobs()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setAction(null)
    }
  }

  const discard = async () => {
    setAction('discard')
    setError(null)
    try {
      await api.discardGenerationQueue()
      setJobs([])
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setAction(null)
    }
  }

  const hadRunningJob = jobs.some(job => job.previous_status === 'running')
  const resumeWouldDuplicate = liveBusyCount > 0

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="queue-recovery-title"
        className="flex max-h-[82vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-amber-400/35 bg-bg-secondary shadow-2xl"
      >
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="mt-0.5 rounded-xl bg-amber-400/10 p-2 text-amber-300"><RotateCcw size={20} /></div>
          <div>
            <h2 id="queue-recovery-title" className="text-base font-semibold text-text-primary">
              {resumeWouldDuplicate
                ? t('queueRecovery.titleBusy')
                : t('queueRecovery.titleIdle')}
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-text-muted">
              {resumeWouldDuplicate
                ? t('queueRecovery.bodyBusy', { count: liveBusyCount })
                : t('queueRecovery.bodyIdle', { count: jobs.length })}
            </p>
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
          {jobs.map((job, index) => (
            <div key={job.job_id} className="rounded-xl border border-border bg-bg-tertiary px-3 py-2.5">
              <div className="flex items-center gap-2 text-[11px]">
                <span className="rounded bg-bg-active px-1.5 py-0.5 font-mono text-text-muted">{index + 1}</span>
                <span className="truncate font-medium text-text-secondary">{job.model_type || t('queueRecovery.unknownModel')}</span>
                <span className="ml-auto shrink-0 text-[10px] text-text-muted">
                  {job.previous_status === 'running' ? t('queueRecovery.interrupted') : t('queueRecovery.waiting')}
                </span>
              </div>
              {job.prompt_preview && (
                <p className="mt-1.5 line-clamp-2 whitespace-pre-line text-[10px] leading-relaxed text-text-muted">
                  {job.prompt_preview}
                </p>
              )}
              <p className="mt-1 text-[9px] text-text-muted">Workspace: {job.workspace}</p>
            </div>
          ))}
        </div>

        {(hadRunningJob || resumeWouldDuplicate) && (
          <div className="mx-4 mb-3 flex gap-2 rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[10px] leading-relaxed text-amber-200/90">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {resumeWouldDuplicate
              ? t('queueRecovery.duplicateWarning')
              : t('queueRecovery.rerunWarning')}
          </div>
        )}

        {error && <p className="mx-4 mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>}

        <div className="flex flex-col-reverse gap-2 border-t border-border p-4 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={() => void discard()}
            disabled={action !== null}
            className={resumeWouldDuplicate
              ? 'flex items-center justify-center gap-2 rounded-lg bg-accent-blue px-4 py-2.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50'
              : 'flex items-center justify-center gap-2 rounded-lg border border-red-400/30 px-4 py-2.5 text-xs text-red-300 transition-colors hover:bg-red-500/10 disabled:opacity-50'}
          >
            {action === 'discard' ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            {t('queueRecovery.discardClean')}
          </button>
          <button
            type="button"
            onClick={() => void resume()}
            disabled={action !== null}
            className={resumeWouldDuplicate
              ? 'flex items-center justify-center gap-2 rounded-lg border border-amber-400/30 px-4 py-2.5 text-xs text-amber-200 transition-colors hover:bg-amber-400/10 disabled:opacity-50'
              : 'flex items-center justify-center gap-2 rounded-lg bg-accent-blue px-4 py-2.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50'}
          >
            {action === 'resume' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {resumeWouldDuplicate ? t('queueRecovery.resumeAnyway') : t('queueRecovery.resumeQueue')}
          </button>
        </div>
      </div>
    </div>
  )
}
