import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { refreshSeriesEpisodeReferences } from '../../api/series'
import { useStore } from '../../stores/useStore'
import { useSeriesStore } from './store'
import type { SeriesEpisode, SeriesProject } from './types'
import type { OpenSeriesReference } from './shotReferences'
import { episodeNeedsReferences, episodeReferenceTargets, generateMissingEpisodeReferences } from './episodeReferencePreparation'
import { primaryButton, secondaryButton } from './styles'

export function SeriesEpisodeReferences({ workspace, series, episode, onOpenReferences }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode
  onOpenReferences?: OpenSeriesReference
}) {
  const { t } = useUiTranslation('seriesLab')
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(''), [error, setError] = useState('')
  const alive = useRef(true), running = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const targets = episodeReferenceTargets(series, episode)
  const missing = targets.filter(item => !item.asset)
  const needsReferences = episodeNeedsReferences(series, episode)
  const source = () => {
    const state = useSeriesStore.getState()
    if (!alive.current || useStore.getState().activeWorkspace !== workspace || state.workspace !== workspace || state.activeSeriesId !== series.id) {
      throw new Error(t('referenceBatch.sourceChanged'))
    }
    const saved = state.library.seriesById[series.id]
    if (!saved?.episodesById[episode.id]) throw new Error(t('referenceBatch.sourceChanged'))
    return saved
  }
  const current = async () => {
    source()
    await useSeriesStore.getState().saveNow()
    return source()
  }
  const run = async (action: () => Promise<void>) => {
    if (running.current) return
    running.current = true; setBusy(true); setError(''); setNotice('')
    try { await action() }
    catch (cause) { if (alive.current) setError((cause as Error).message) }
    finally { running.current = false; if (alive.current) setBusy(false) }
  }
  const generate = () => run(async () => {
    await generateMissingEpisodeReferences({ workspace, episodeId: episode.id, current,
      accept: result => useSeriesStore.getState().acceptAssetImport(workspace, result),
      progress: (name, current, total) => setNotice(t('setup.generatingImage', { name, current, total })),
    })
    if (alive.current) setNotice(t('referenceBatch.generated'))
  })
  const incorporate = () => run(async () => {
    const saved = await current()
    const updated = await refreshSeriesEpisodeReferences(workspace, series.id, episode.id, saved.revision)
    await current()
    useSeriesStore.getState().adoptRemoteSeries(updated)
    setNotice(t('referenceBatch.incorporated'))
  })
  if (!episode.shots.length) return null
  return <section aria-label={t('referenceBatch.title')} className="space-y-3 rounded-xl border border-violet-500/30 bg-violet-500/5 p-4">
    <h3 className="text-sm font-semibold">{t('referenceBatch.title')}</h3>
    <p className="text-xs text-text-secondary">{t(missing.length ? 'referenceBatch.missing' : needsReferences ? 'referenceBatch.available' : 'referenceBatch.ready', { count: missing.length })}</p>
    <div className="flex flex-wrap gap-2">
      <button className={primaryButton} disabled={busy || !missing.length} onClick={() => void generate()}>{t('referenceBatch.generate', { count: missing.length })}</button>
      {onOpenReferences && <button className={secondaryButton} disabled={busy} onClick={() => onOpenReferences(missing[0]?.kind === 'location' ? 'locations' : 'characters')}>{t('referenceBatch.review')}</button>}
      <button className={secondaryButton} disabled={busy || series.canon.approval !== 'approved' || !needsReferences} onClick={() => void incorporate()}>{t('referenceBatch.incorporate')}</button>
    </div>
    <p className="text-xs text-text-muted">{t('referenceBatch.hint')}</p>
    {notice && <p role="status" className="text-xs">{notice}</p>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </section>
}
