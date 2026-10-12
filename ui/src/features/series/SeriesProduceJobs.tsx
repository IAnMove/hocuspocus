import { useCallback, useEffect, useState } from 'react'
import { controlSeriesProduction, listSeriesProductions, type SeriesProduceJob } from '../../api/seriesProduce'
import { useUiTranslation } from '../../i18n'
import { formatAppTimestamp } from '../../lib/locale'
import { openActivityArtifact } from '../activity/openTargets'
import { secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject } from './types'

const LIVE = new Set(['queued', 'running', 'cancelling'])
const RESUMABLE = new Set(['failed', 'cancelled', 'interrupted', 'waiting'])
const POLL_MS = 4000

function chapterFiles(job: SeriesProduceJob): Array<{ language: string; file: string; subtitled: boolean }> {
  return Object.entries(job.chapters || {}).flatMap(([language, chapter]) => [
    ...(chapter.file ? [{ language, file: chapter.file, subtitled: false }] : []),
    ...(chapter.subtitledFile ? [{ language, file: chapter.subtitledFile, subtitled: true }] : []),
  ])
}

/**
 * The episode's productions (``series.episode.produce``, started by an agent, the Wizard or a person): status, each
 * render and cut step, the chapter files, and resume or stop. Nothing shows until the episode has one.
 */
export function SeriesProduceJobs({ workspace, series, episode }: { workspace: string; series: SeriesProject; episode: SeriesEpisode }) {
  const { t } = useUiTranslation('seriesLab')
  const [jobs, setJobs] = useState<SeriesProduceJob[]>([])
  const [error, setError] = useState(''), [busy, setBusy] = useState('')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const abort = new AbortController()
    listSeriesProductions(workspace, { seriesId: series.id, episodeId: episode.id, limit: 5 }, abort.signal)
      .then(found => { if (!abort.signal.aborted) { setJobs(found); setError('') } })
      .catch(cause => { if (!abort.signal.aborted && (cause as Error).name !== 'AbortError') setError((cause as Error).message) })
    return () => abort.abort()
  }, [workspace, series.id, episode.id, tick])

  const live = jobs.some(job => LIVE.has(job.status))
  useEffect(() => {
    if (!live) return
    const timer = window.setInterval(() => setTick(value => value + 1), POLL_MS)
    return () => window.clearInterval(timer)
  }, [live])

  const act = useCallback(async (job: SeriesProduceJob, action: 'cancel' | 'resume') => {
    setBusy(job.jobId); setError('')
    try {
      const next = await controlSeriesProduction(workspace, job.jobId, action)
      setJobs(current => current.map(item => item.jobId === next.jobId ? next : item))
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy('')
    }
  }, [workspace])

  if (!jobs.length && !error) return null
  return <section aria-label={t('productions.title')} className="space-y-2 rounded-lg border border-border p-3" data-testid="series-productions">
    <h3 className="text-sm font-semibold">{t('productions.title')}</h3>
    <p className="text-xs text-text-secondary">{t('productions.hint')}</p>
    <ul className="space-y-2">
      {jobs.map(job => <li key={job.jobId} data-testid={`series-production-${job.jobId}`} className="space-y-1 rounded border border-border/60 p-2 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{formatAppTimestamp(job.createdAt) || job.jobId}</span>
          <span data-status={job.status} className="rounded bg-bg-tertiary px-1.5 py-0.5">
            {t(`productions.status.${job.status}`, { defaultValue: job.status })}</span>
          {job.languages?.length ? <span className="text-text-muted">{job.languages.join(' · ')}</span> : null}
          <span className="ml-auto flex gap-1">
            {LIVE.has(job.status) && <button type="button" className={secondaryButton} disabled={busy === job.jobId || job.status === 'cancelling'}
              onClick={() => void act(job, 'cancel')}>{t('productions.stop')}</button>}
            {RESUMABLE.has(job.status) && <button type="button" className={secondaryButton} disabled={busy === job.jobId}
              onClick={() => void act(job, 'resume')}>{t('productions.resume')}</button>}
          </span>
        </div>
        {job.message && <p className="text-text-secondary">{job.message}</p>}
        <ol className="space-y-0.5">
          {job.steps.map(step => <li key={`${step.kind}-${step.language}`} data-step-status={step.status}>
            {t(`productions.step.${step.kind}`, { language: step.language })} · {t(`productions.stepStatus.${step.status}`, { defaultValue: step.status })}
            {step.progress && step.status === 'running' && <span className="text-text-muted"> · {step.progress}</span>}
            {step.error && <span className="text-red-300"> · {step.error}</span>}
          </li>)}
        </ol>
        {chapterFiles(job).length > 0 && <div className="flex flex-wrap gap-1">
          {chapterFiles(job).map(item => <button key={item.file} type="button" className="rounded border border-border px-1.5 py-0.5 hover:bg-bg-hover"
            title={item.file} onClick={() => openActivityArtifact(item.file)}>
            {t(item.subtitled ? 'productions.chapterSubtitled' : 'productions.chapter', { language: item.language })}
          </button>)}
        </div>}
      </li>)}
    </ul>
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </section>
}
