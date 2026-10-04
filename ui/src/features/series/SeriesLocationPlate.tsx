import { useEffect, useState } from 'react'
import { fetchOutputs, type ApiOutput } from '../../api/client'
import { fetchSeriesLocationPlate, startSeriesLocationPlate, type SeriesLocationPlate as Plate } from '../../api/series'
import { useUiTranslation } from '../../i18n'
import { isWorld3DOutput } from '../scene3d/sceneLibrary'
import { useSeriesStore } from './store'
import { inputClass, secondaryButton } from './styles'
import type { SeriesLocation, SeriesProject } from './types'

const POLL_MS = 4000

/** Pick a saved Video 3D scene; the server renders it once as this location's looping 2D background. */
export function SeriesLocationPlate({ workspace, series, location, pollMs = POLL_MS }: {
  workspace: string; series: SeriesProject; location: SeriesLocation; pollMs?: number
}) {
  const { t } = useUiTranslation('seriesLab')
  const reload = useSeriesStore(state => state.reload)
  const [scenes, setScenes] = useState<ApiOutput[]>([])
  const [scene, setScene] = useState(''), [seconds, setSeconds] = useState(6)
  const [plate, setPlate] = useState<Plate | null>(null), [error, setError] = useState('')
  const hasPlate = Boolean(location.layout2d?.plateAssetId)

  useEffect(() => {
    const abort = new AbortController()
    void fetchOutputs(0, 0, { mediaType: 'scene', workspace, signal: abort.signal })
      .then(result => { if (!abort.signal.aborted) setScenes(result.outputs.filter(isWorld3DOutput)) }).catch(() => {})
    void fetchSeriesLocationPlate(workspace, series.id, location.id).then(next => { if (!abort.signal.aborted) setPlate(next) }).catch(() => {})
    return () => abort.abort()
  }, [workspace, series.id, location.id])

  useEffect(() => {
    if (plate?.status !== 'rendering') return
    const timer = setTimeout(() => {
      void fetchSeriesLocationPlate(workspace, series.id, location.id).then(next => {
        setPlate(next)
        if (next.status === 'done') void reload()
      }).catch(cause => setError((cause as Error).message))
    }, pollMs)
    return () => clearTimeout(timer)
  }, [plate, workspace, series.id, location.id, reload, pollMs])

  const start = async () => {
    setError('')
    try { setPlate(await startSeriesLocationPlate(workspace, series.id, location.id, scene, seconds)) } catch (cause) { setError((cause as Error).message) }
  }
  const rendering = plate?.status === 'rendering'
  return <div className="space-y-2 rounded-lg border border-border p-2" data-testid={`series-location-plate-${location.id}`}>
    <p className="text-xs font-semibold">{t('plates.title')}</p>
    <p className="text-[10px] text-text-muted">{hasPlate ? t('plates.active') : t('plates.hint')}</p>
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-[10px]">{t('plates.scene')}
        <select className={inputClass} value={scene} disabled={rendering} onChange={event => setScene(event.target.value)}>
          <option value="">{scenes.length ? t('plates.choose') : t('plates.noScenes')}</option>
          {scenes.map(item => <option key={item.name} value={item.name}>{item.name.replace(/\.world3d\.scene\.json$/, '')}</option>)}
        </select></label>
      <label className="text-[10px]">{t('plates.seconds')}
        <input className={`${inputClass} w-20`} type="number" min={2} max={20} step={1} value={seconds} disabled={rendering}
          onChange={event => setSeconds(Math.min(20, Math.max(2, Number(event.target.value) || 6)))} /></label>
      <button className={secondaryButton} disabled={!scene || rendering} onClick={() => void start()}>{t('plates.render')}</button>
    </div>
    {plate && <PlateStatus plate={plate} />}
    {error && <p role="alert" className="text-[10px] text-red-300">{error}</p>}
  </div>
}

function PlateStatus({ plate }: { plate: Plate }) {
  const { t } = useUiTranslation('seriesLab')
  if (plate.status === 'rendering') return <p role="status" className="text-[10px]">{t('plates.rendering', { progress: Math.round((plate.progress ?? 0) * 100) })}</p>
  if (plate.status === 'done') return <p role="status" className="text-[10px] text-emerald-200">{t('plates.done')}</p>
  if (plate.status === 'failed') return <p role="alert" className="text-[10px] text-red-300">{t('plates.failed', { error: plate.error ?? '' })}</p>
  return null
}
