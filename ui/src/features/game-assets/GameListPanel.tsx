import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { codeLabel } from './gameErrors'
import { GameListPasteDialog } from './GameListPasteDialog'
import { SPEC_FIELDS, specPatch, visibleAssets } from './listModel'
import { useGameAssetsStore } from './store'
import { buttonClass, errorClass, fieldClass, panelClass } from './styles'
import type { GameAsset } from './types'

export function GameListPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const selectedIds = useGameAssetsStore(state => state.selectedIds)
  const toggleSelected = useGameAssetsStore(state => state.toggleSelected)
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [paste, setPaste] = useState(false)
  const assets = game?.assets || []
  const kinds = [...new Set(assets.map(asset => asset.kind))]
  const statuses = [...new Set(assets.map(asset => asset.status))]
  const rows = visibleAssets(assets, { kind, status, query })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} onClick={() => setPaste(true)}>{t('paste')}</button>
        <input aria-label={t('search')} className={`${fieldClass} max-w-xs`} value={query} onChange={event => setQuery(event.target.value)} placeholder={t('search')} />
        <select aria-label={t('kind')} className={`${fieldClass} w-auto`} value={kind} onChange={event => setKind(event.target.value)}>
          <option value="">{t('allKinds')}</option>
          {kinds.map(item => <option key={item} value={item}>{codeLabel('kinds', item)}</option>)}
        </select>
        <select aria-label={t('status')} className={`${fieldClass} w-auto`} value={status} onChange={event => setStatus(event.target.value)}>
          <option value="">{t('allStatuses')}</option>
          {statuses.map(item => <option key={item} value={item}>{codeLabel('statuses', item)}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        {rows.map(asset => (
          <AssetRow key={asset.id} asset={asset} selected={selectedIds.includes(asset.id)} onToggle={() => toggleSelected(asset.id)} />
        ))}
        {!rows.length && <p className="text-sm text-muted-foreground">{t('listEmpty')}</p>}
      </div>
      {paste && <GameListPasteDialog onClose={() => setPaste(false)} />}
    </div>
  )
}

function initialDraft(asset: GameAsset): Record<string, string> {
  const draft: Record<string, string> = { name: asset.name, description: asset.description }
  for (const field of SPEC_FIELDS[asset.kind] || []) {
    const value = asset.spec[field.key]
    draft[field.key] = value === undefined || value === null ? '' : String(value)
  }
  return draft
}

/** The editable part of an asset; a new server copy of it replaces the draft. */
function editableSignature(asset: GameAsset): string {
  return JSON.stringify([asset.name, asset.description, asset.spec])
}

function AssetRow({ asset, selected, onToggle }: { asset: GameAsset; selected: boolean; onToggle: () => void }) {
  const { t } = useUiTranslation('gameAssets')
  const saveAsset = useGameAssetsStore(state => state.saveAsset)
  const signature = editableSignature(asset)
  const [edit, setEdit] = useState<{ signature: string; draft: Record<string, string> } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const draft = edit?.signature === signature ? edit.draft : initialDraft(asset)
  const fields = SPEC_FIELDS[asset.kind] || []
  const change = (key: string, value: string) => setEdit({ signature, draft: { ...draft, [key]: value } })

  const save = async () => {
    setSaving(true)
    setError('')
    const saved = await saveAsset(asset.id, specPatch(asset, draft))
    setSaving(false)
    if (saved) setEdit(null)
    else setError(useGameAssetsStore.getState().error || t('actions.saveAsset'))
  }

  return (
    <article className={panelClass}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <input type="checkbox" aria-label={t('selectAsset', { id: asset.id })} checked={selected} onChange={onToggle} />
        <span>{codeLabel('kinds', asset.kind)}</span>
        <span className="font-mono">{asset.id}</span>
        <span>{codeLabel('statuses', asset.status)}</span>
        <span>{t('candidates')}: {asset.candidates}</span>
        {asset.locked && <span>{t('assetLocked')}</span>}
        {asset.dependsOn.length > 0 && <span>{t('dependsOn', { ids: asset.dependsOn.join(', ') })}</span>}
      </div>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <input aria-label={`${t('name')} ${asset.id}`} placeholder={t('name')} className={fieldClass} value={draft.name || ''} onChange={event => change('name', event.target.value)} />
        <input aria-label={`${t('description')} ${asset.id}`} placeholder={t('description')} className={fieldClass} value={draft.description || ''} onChange={event => change('description', event.target.value)} />
        {fields.map(field => {
          const label = codeLabel('specFields', field.key)
          return (
            <input key={field.key} aria-label={`${label} ${asset.id}`} placeholder={label} type={field.input === 'number' ? 'number' : 'text'}
              className={fieldClass} value={draft[field.key] || ''} onChange={event => change(field.key, event.target.value)} />
          )
        })}
      </div>
      <button type="button" className={`${buttonClass} mt-2`} disabled={saving} onClick={() => { void save() }}>{t('saveAsset')}</button>
      {error && <p role="alert" className={`${errorClass} mt-1`}>{error}</p>}
    </article>
  )
}
