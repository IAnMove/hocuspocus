import { useState, useEffect, useMemo, useCallback } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import { useStore } from '../stores/useStore'
import type { OomInfo } from '../types'

/**
 * OomRecoveryBanner — surfaces a "Lower VRAM headroom?" banner when
 * the latest job or pipeline failure was an OOM (CUDA out of memory).
 *
 * Watches:
 *   - useStore(s => s.jobs)        — Studio job failures (jobs stay in
 *     the array after failing so the placeholder remains visible)
 *   - useStore(s => s.pipelineStatus) — Director pipeline failure
 *
 * Backend tags failures with `oom_info: { current_coefficient,
 * suggested_coefficient, message }` via app/services/oom_detect.py.
 *
 * V1 scope (decided 2026-05-02): shows the OOM and offers a single
 * one-click permanent fix. Does NOT automatically retry — user re-runs
 * the failed generation themselves after the coefficient is lowered.
 * Deferred to a later phase: "Apply & retry clip N" (needs Director
 * pipeline resume from start_clip_index) and "Just retry as-is".
 *
 * Dismissal: tracked locally per-failure-key (job id or pipeline
 * status hash). Once dismissed, the banner doesn't re-appear for
 * that specific failure even if the user keeps the page open.
 */
export function OomRecoveryBanner() {
  const { t } = useUiTranslation('shell')
  const jobs = useStore(s => s.jobs)
  const pipelineStatus = useStore(s => s.pipelineStatus)
  const systemDetect = useStore(s => s.systemDetect)
  const updateSystemConfig = useStore(s => s.updateSystemConfig)
  // Once user dismisses a specific failure, we suppress the banner
  // for that failure key. Persisted in component state — fresh on
  // page reload, which is fine because failed jobs also don't survive
  // reload (they live in store memory only).
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [applying, setApplying] = useState(false)
  const [appliedToast, setAppliedToast] = useState<string | null>(null)

  // Find the most relevant OOM failure to show. Studio jobs and the
  // pipeline are independent surfaces — if both have OOM failures
  // (rare), prefer the most recent. We don't bother with timestamps;
  // pipeline takes precedence because Director runs are typically
  // longer (more lost work, more user attention), so it's more likely
  // to be the active concern.
  const activeOom: { key: string; oom: OomInfo; context: string } | null = useMemo(() => {
    if (pipelineStatus?.status === 'failed' && pipelineStatus.oom_info) {
      const failedClipIdx = pipelineStatus.clip_images?.length ?? 0
      const totalClips = pipelineStatus.clip_plans?.length ?? 0
      const context = totalClips > 0
        ? t('oom.directorFailedClip', { current: failedClipIdx + 1, total: totalClips })
        : t('oom.directorFailed')
      return { key: `pipeline:${pipelineStatus.id}`, oom: pipelineStatus.oom_info, context }
    }
    // Latest failed studio job with oom_info
    const failedJob = [...jobs].reverse().find(j => j.status === 'failed' && j.oomInfo)
    if (failedJob && failedJob.oomInfo) {
      return { key: `job:${failedJob.id}`, oom: failedJob.oomInfo, context: t('oom.generationFailed') }
    }
    return null
  }, [jobs, pipelineStatus, t])

  // Auto-clear the toast after 3 seconds.
  useEffect(() => {
    if (!appliedToast) return
    const t = setTimeout(() => setAppliedToast(null), 3000)
    return () => clearTimeout(t)
  }, [appliedToast])

  const handleDismiss = useCallback(() => {
    if (activeOom) {
      setDismissed(d => new Set(d).add(activeOom.key))
    }
  }, [activeOom])

  const handleApply = useCallback(async () => {
    if (!activeOom?.oom.suggested_coefficient) return
    setApplying(true)
    try {
      await updateSystemConfig({ vram_safety_coefficient: activeOom.oom.suggested_coefficient })
      setAppliedToast(t('oom.applied', { value: activeOom.oom.suggested_coefficient.toFixed(2) }))
      setDismissed(d => new Set(d).add(activeOom.key))
    } catch (e) {
      console.error('apply coefficient failed:', e)
    } finally {
      setApplying(false)
    }
  }, [activeOom, t, updateSystemConfig])

  // Toast stays visible for 3s after apply; banner hides as soon as
  // it's dismissed (the OOM key is in the dismissed set).
  if (appliedToast) {
    return (
      <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 max-w-md">
        <div className="bg-green-500/90 text-white text-sm rounded-lg shadow-xl px-4 py-2.5">
          {appliedToast}
        </div>
      </div>
    )
  }

  if (!activeOom || dismissed.has(activeOom.key)) return null

  const { oom, context } = activeOom
  const vramGb = systemDetect?.hardware?.gpu_vram_gb
  const vramHint = vramGb ? t('oom.vramHint', { vram: vramGb }) : ''
  const canLower = oom.suggested_coefficient !== null

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 max-w-xl w-[calc(100%-2rem)]">
      <div className="bg-bg-secondary border border-amber-500/40 rounded-lg shadow-2xl overflow-hidden">
        {/* Header strip */}
        <div className="flex items-start gap-2.5 px-4 py-3 bg-amber-500/10">
          <AlertTriangle size={18} className="text-indicator-warning shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-text-primary">{t('oom.title')}</div>
            <div className="text-[12px] text-text-secondary mt-0.5">
              {context} {vramHint}
            </div>
          </div>
          <button
            onClick={handleDismiss}
            className="text-text-muted hover:text-text-primary p-0.5 rounded transition-colors shrink-0"
            title={t('oom.dismissTitle')}
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-3 space-y-2.5">
          {canLower ? (
            <>
              <div className="text-[12px] text-text-secondary leading-snug">
                {t('oom.lowerBody', { current: oom.current_coefficient.toFixed(2), suggested: oom.suggested_coefficient!.toFixed(2) })}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleApply}
                  disabled={applying}
                  className="flex-1 px-3 py-2 rounded-md bg-amber-500 hover:bg-amber-400 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-wait"
                >
                  {applying ? t('oom.applying') : t('oom.lowerAction', { value: oom.suggested_coefficient!.toFixed(2) })}
                </button>
                <button
                  onClick={handleDismiss}
                  className="px-3 py-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-tertiary text-sm transition-colors"
                >
                  {t('oom.dismiss')}
                </button>
              </div>
              <div className="text-[10px] text-text-muted">
                {t('oom.afterApply')}
              </div>
            </>
          ) : (
            // current_coefficient is at the 0.50 floor — coefficient
            // can't help anymore. Need a different fix.
            <>
              <div className="text-[12px] text-text-secondary leading-snug">
                {t('oom.atFloor', { value: oom.current_coefficient.toFixed(2) })}
              </div>
              <div className="flex justify-end">
                <button
                  onClick={handleDismiss}
                  className="px-3 py-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-tertiary text-sm transition-colors"
                >
                  {t('oom.dismiss')}
                </button>
              </div>
            </>
          )}

          {/* Truncated original error — collapsed by default to avoid
              overwhelming the user with stack-trace-flavored text */}
          <details className="text-[10px] text-text-muted">
            <summary className="cursor-pointer hover:text-text-secondary">{t('oom.showDetails')}</summary>
            <div className="mt-1 font-mono text-[10px] bg-bg-primary/40 rounded px-2 py-1.5 break-all">
              {oom.message}
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
