import { useCallback, useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import {
  controlSeriesServerRender, fetchSeriesServerRender, fetchSeriesServerRenders, startSeriesServerRender, type SeriesServerRenderJob,
} from '../../api/series'
import { useSeriesStore } from './store'
import { primaryButton, secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject } from './types'

const LIVE = new Set(['queued', 'running', 'cancelling'])

/** Render every 2D shot on the server: no tab has to stay open, and a stopped job resumes. */
export function SeriesServerRender({ workspace, series, episode, language }: { workspace: string; series: SeriesProject; episode: SeriesEpisode
  /** A language version; omitted renders the original. */
  language?: string }) {
  const { t } = useUiTranslation('seriesLab')
  const [job, setJob] = useState<SeriesServerRenderJob>()
  const [approve, setApprove] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const reload = useSeriesStore(state => state.reload)

  useEffect(() => {
    let alive = true
    fetchSeriesServerRenders(workspace).then(jobs => {
      const latest = jobs.filter(item => item.seriesId === series.id && item.episodeId === episode.id && (!language || item.language === language))
        .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))[0]
      if (alive && latest) setJob(latest)
    }).catch(() => {})
    return () => { alive = false }
  }, [workspace, series.id, episode.id, language])

  useEffect(() => {
    if (!job || !LIVE.has(job.status)) return
    const timer = window.setInterval(() => {
      fetchSeriesServerRender(workspace, job.jobId).then(next => {
        setJob(next)
        if (!LIVE.has(next.status)) void reload().catch(() => {})
      }).catch(cause => setError((cause as Error).message))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [workspace, job, reload])

  const act = useCallback(async (task: () => Promise<SeriesServerRenderJob>) => {
    setBusy(true); setError('')
    try { setJob(await task()) } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }, [])

  const live = Boolean(job && LIVE.has(job.status))
  const done = job ? job.items.filter(item => item.status === 'done').length : 0
  return <div className="space-y-2 rounded-lg border border-border p-3" data-testid="series-server-render">
    <p className="text-xs text-text-secondary">{t('serverRender.hint')}</p>
    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={approve} disabled={live || busy}
      onChange={event => setApprove(event.target.checked)} />{t('serverRender.approve')}</label>
    <div className="flex flex-wrap gap-2">
      <button className={primaryButton} disabled={live || busy} onClick={() => void act(() => startSeriesServerRender(workspace, series.id, episode.id, approve, language))}>
        {t('serverRender.start')}</button>
      {live && <button className={secondaryButton} disabled={busy || job?.status === 'cancelling'}
        onClick={() => void act(() => controlSeriesServerRender(workspace, job!.jobId, 'cancel'))}>{t('serverRender.stop')}</button>}
      {job && ['failed', 'cancelled', 'interrupted'].includes(job.status) && <button className={secondaryButton} disabled={busy}
        onClick={() => void act(() => controlSeriesServerRender(workspace, job.jobId, 'resume'))}>{t('serverRender.resume')}</button>}
    </div>
    {job && <p role="status" className="text-xs">{t('serverRender.progress', { done, total: job.items.length, status: t(`serverRender.status.${job.status}`) })}</p>}
    {job && <ul className="space-y-1 text-xs">
      {job.items.map(item => <li key={item.shotId} data-testid={`server-render-${item.shotId}`}>
        <span className="font-mono">{item.shotId}</span> · {t(`serverRender.stage.${item.stage}`)}
        {item.status === 'failed' && <span className="text-red-300"> · {item.error}</span>}
        {item.warning && <span className="text-amber-300"> · {item.warning}</span>}
      </li>)}
    </ul>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </div>
}
