import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'
import { ensureUploadsPath } from '../../lib/labsImagePick'
import { useStore } from '../../stores/useStore'
import { AssetInput } from '../asset-picker/AssetInput'
import { allowedSeriesMethods, seriesShotMethod } from './productionMethods'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'
import { secondaryButton, selectClass } from './styles'
import { useSeriesStore } from './store'
import { seriesShotReferences, type OpenSeriesReference } from './shotReferences'
import { SeriesShotReferencePanel } from './SeriesShotReferencePanel'

const METHOD_HINT = { generated_video: 'production.importHint', animation_2d: 'production.scene2dHint', animation_3d: 'production.scene3dHint', imported_video: 'production.importHint' } as const

export function SeriesShotProduction({ workspace, series, episode, shot, onChange, saveNow, onOpenReferences, onOpenEpisode, onConfigureMethods }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; shot: SeriesShot
  onChange: (shot: SeriesShot) => void; saveNow: () => Promise<unknown>
  onOpenReferences?: OpenSeriesReference; onOpenEpisode?: () => void
  onConfigureMethods?: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const allowed = allowedSeriesMethods(series), method = seriesShotMethod(series, shot)
  const permitted = allowed.includes(method)
  const animation = method === 'animation_2d' || method === 'animation_3d'
  const references = animation ? seriesShotReferences(series, episode, shot) : null
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [videos, setVideos] = useState<api.ApiOutput[]>([])
  useEffect(() => {
    if (method === 'generated_video') return
    let active = true
    void api.fetchOutputs(200, 0, { workspace, mediaType: 'video' }).then(result => { if (active) setVideos(result.outputs) }).catch(() => {})
    return () => { active = false }
  }, [method, workspace])
  const prepare = async () => {
    setBusy(true); setError('')
    try {
      const saved = await saveNow() as SeriesProject | null
      const current = saved?.id === series.id ? saved : series
      const actualEpisode = current.episodesById[episode.id] || episode
      const actualShot = actualEpisode.shots.find(item => item.id === shot.id) || shot
      const [{ buildSeriesShotScene }, { presentSceneDocument }] = await Promise.all([import('./shotScene'), import('../sceneFx/handoff')])
      const prepared = buildSeriesShotScene(workspace, current, actualEpisode, actualShot)
      const stillHere = () => useStore.getState().activeWorkspace === workspace
      if (!stillHere()) throw new Error(t('production.workspaceChanged'))
      sessionStorage.setItem(`hocuspocus:series-scene:${workspace}:${series.id}:${episode.id}:${shot.id}`, JSON.stringify(prepared.document))
      const state = useStore.getState()
      state.setSettingsOpen(false); state.setDashboardOpen(false)
      state.setMediaFilter(prepared.dimension === '2d' ? 'scene3d' : 'world3d')
      await presentSceneDocument(prepared.dimension, prepared.document, stillHere)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const importTake = async (item: api.ApiOutput) => {
    setBusy(true); setError('')
    try {
      await saveNow()
      const uploaded = await ensureUploadsPath(item)
      const result = await api.importSeriesAsset(workspace, series.id, { uploadPath: uploaded.path, name: item.name,
        ownerType: 'shot', ownerId: shot.id, kind: 'video', asTake: true })
      useSeriesStore.getState().acceptAssetImport(workspace, result)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  return <div className="mt-3 space-y-2 rounded-lg border border-violet-500/25 p-3">
    <label className="block text-xs text-text-secondary">{t('production.shotMethod', { order: shot.order })}
      <select className={`${selectClass} mt-1`} disabled={busy} value={method} onChange={event => onChange({ ...shot, productionMethod: event.target.value as SeriesShot['productionMethod'] })}>
        {!permitted && <option value={method}>{t(`production.methods.${method}`)} · {t('production.notAllowed')}</option>}
        {allowed.map(value => <option key={value} value={value}>{t(`production.methods.${value}`)}</option>)}
      </select>
    </label>
    {onConfigureMethods && <button type="button" className="text-xs text-violet-300 underline underline-offset-2" onClick={onConfigureMethods}>{t('production.configureMethods')}</button>}
    {!permitted && <p role="alert" className="text-xs text-amber-300">{t('production.chooseAllowed')}</p>}
    {permitted && method !== 'generated_video' && <>
      {references && <SeriesShotReferencePanel references={references} shot={shot} busy={busy} onChange={onChange}
        onOpenReferences={onOpenReferences} onOpenEpisode={onOpenEpisode} />}
      {animation && <button type="button" className={secondaryButton} disabled={busy || !references?.ready} onClick={() => void prepare()}>{t(method === 'animation_2d' ? 'production.open2d' : 'production.open3d')}</button>}
      <p className="text-[11px] text-text-muted">{t(METHOD_HINT[method])}</p>
      <AssetInput label={t('production.importTake')} placeholder={t('production.importTake')} items={videos} accept="video/*" disabled={busy}
        constraints={{ kinds: ['video'], maxCount: 1, optional: false }} onChoose={item => { if (item) void importTake(item) }} />
    </>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </div>
}
