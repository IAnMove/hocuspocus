import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { characterCutout, prepareCharacterCutout } from './characterCutout'
import { seriesEntityImage } from './shotReferences'
import { seriesAssetUrl, type SeriesReferenceImport } from './referenceImages'
import type { SeriesCharacter, SeriesProject } from './types'
import { secondaryButton } from './styles'

export function SeriesCharacterCutout({ workspace, series, character, saveNow, onImported }: {
  workspace: string; series: SeriesProject; character: SeriesCharacter
  saveNow: () => Promise<unknown>; onImported: (workspace: string, result: SeriesReferenceImport) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const source = seriesEntityImage(character, series.assets)
  const cutout = source && characterCutout(series, source)
  const clean = async () => {
    if (!source || busy) return
    setBusy(true); setError('')
    try { await saveNow(); onImported(workspace, await prepareCharacterCutout(workspace, series, source)) }
    catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  return <div className="mt-3 space-y-2 rounded border border-border p-3">
    <button className={secondaryButton} disabled={!source || busy || Boolean(cutout)} onClick={() => void clean()}>{t(busy ? 'native.cleaning' : cutout ? 'native.cleaned' : 'native.removeBackground')}</button>
    <p className="text-xs text-text-muted">{t('native.cutoutHint')}</p>
    {cutout && <img className="h-40 rounded bg-bg-tertiary object-contain" src={seriesAssetUrl(cutout)} alt={t('native.cutoutAlt', { name: character.name })} />}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </div>
}
