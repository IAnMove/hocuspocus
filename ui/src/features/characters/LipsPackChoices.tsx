import { useEffect, useState } from 'react'
import { fetchLipsLibrary } from '../../api/lipsCreator'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import { applyLipsPack, missingLipsSounds } from '../../lib/lipsCreator'
import { LipsThumbnail } from './LipsThumbnail'

/** Collections share the existing placement controls and the character's save operation. */
export function LipsPackChoices({ workspace, kit, poseId, disabled, onApply }: {
  workspace: string; kit: CharacterKit; poseId: string; disabled: boolean; onApply: (kit: CharacterKit) => void
}) {
  const { t } = useUiTranslation('characters')
  const [reload, setReload] = useState(0), [expanded, setExpanded] = useState(false)
  return <details className="rounded-lg border border-cyan-300/30 p-3" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary className="cursor-pointer text-sm font-medium">{t('lips.useCollection')}</summary>
    {expanded && <LipsPackList key={`${workspace}:${reload}`} workspace={workspace} kit={kit} poseId={poseId} disabled={disabled} onApply={onApply} onReload={() => setReload(value => value + 1)} />}
  </details>
}

function LipsPackList({ workspace, kit, poseId, disabled, onApply, onReload }: {
  workspace: string; kit: CharacterKit; poseId: string; disabled: boolean
  onApply: (kit: CharacterKit) => void; onReload: () => void
}) {
  const { t } = useUiTranslation('characters')
  const [packs, setPacks] = useState<CharacterKit[]>([])
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const abort = new AbortController()
    void fetchLipsLibrary(workspace, abort.signal).then(library => {
      if (abort.signal.aborted) return
      setPacks(Object.values(library.kits).sort((a, b) => a.name.localeCompare(b.name)))
    }).catch(cause => { if (!abort.signal.aborted) setError((cause as Error).message) })
      .finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [workspace])
  const pack = packs.find(item => item.id === selected)
  const missing = pack ? missingLipsSounds(pack) : []
  return <div className="mt-3 space-y-2">
      <label className="block text-xs text-text-secondary">{t('lips.collection')}
        <select aria-label={t('lips.useCollection')} value={selected} disabled={disabled || loading} onChange={event => { setSelected(event.target.value); setError('') }} className="mt-1 w-full rounded border border-border bg-bg-primary p-2 text-sm">
          <option value="">{loading ? t('lips.loading') : t('lips.chooseCollection')}</option>
          {packs.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      {!loading && !packs.length && <p className="text-xs text-text-muted">{t('lips.createCollectionFirst')}</p>}
      {pack && <>
        <LipsThumbnail pack={pack} />
        {missing.length > 0 && <p className="text-xs text-amber-200">{t('lips.reviewBeforeUse', { sounds: missing.join(', ') })}</p>}
        <button type="button" disabled={disabled || missing.length > 0} onClick={() => {
          try { onApply(applyLipsPack(pack, kit, poseId)); setError('') }
          catch (cause) { setError((cause as Error).message) }
        }} className="min-h-10 w-full rounded border border-cyan-300/40 bg-cyan-400/10 p-2 text-sm disabled:opacity-40">{t('lips.applyCollection')}</button>
        <p className="text-xs text-text-muted">{t('lips.placeCollection')}</p>
      </>}
      {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
      <button type="button" disabled={disabled || loading} onClick={onReload} className="text-xs text-text-secondary underline disabled:opacity-40">{t('lips.reload')}</button>
    </div>
}
