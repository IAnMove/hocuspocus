import { useEffect, useState } from 'react'
import { Check, Plus, Trash2 } from 'lucide-react'
import * as api from '../../api/client'
import type { ApiOutput } from '../../api/client'
import { AssetInput } from '../asset-picker/AssetInput.tsx'
import { ensureUploadsPath, useWorkspaceImageOutputs } from '../../lib/labsImagePick'
import { createSeriesCharacter, createSeriesLocation, createSeriesProp, createVisualVariant, seriesId } from './model'
import { Pill, SectionCard, SeriesField, seriesStatusLabel } from './components'
import { inputClass, primaryButton, secondaryButton, textareaClass } from './styles'
import type { SeriesProject, SeriesVisualVariant } from './types'
import { useUiTranslation } from '../../i18n'
import { SeriesVoiceFields } from './SeriesVoiceFields'
import { SeriesCharacterSpeech } from './SeriesCharacterSpeech'
import { SeriesReferenceGenerator } from './SeriesReferenceGenerator'
import { seriesAssetUrl, type SeriesReferenceImport } from './referenceImages'

function SeriesReferenceField({
  label, items, disabled, onPick,
}: {
  label: string
  items: ApiOutput[]
  disabled?: boolean
  onPick: (item: ApiOutput) => void
}) {
  return (
    <AssetInput
      label={label}
      placeholder={label}
      items={items}
      accept="image/*"
      disabled={disabled}
      constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
      onChoose={item => { if (item) onPick(item) }}
    />
  )
}

export type CanonTab = 'world' | 'characters' | 'locations' | 'continuity' | 'advanced'
const CANON_TABS: CanonTab[] = ['world', 'characters', 'locations', 'continuity', 'advanced']
const CHARACTER_FIELDS = ['name', 'role', 'personality', 'desire', 'need', 'flaw', 'longArc', 'voiceAndDialogue', 'appearance', 'identityLock'] as const

function ReferenceStrip({ series, assetIds, primaryId, onPrimary, onRemove }: {
  series: SeriesProject; assetIds: string[]; primaryId?: string
  onPrimary?: (id: string) => void; onRemove?: (id: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  if (!assetIds.length) return <span className="text-[10px] text-text-muted">{t('canon.noReference')}</span>
  return <div className="flex flex-wrap gap-2">{assetIds.map(id => {
    const asset = series.assets[id]
    if (!asset) return <Pill key={id} tone="red">{t('canon.missingAsset', { id })}</Pill>
    const previewUrl = seriesAssetUrl(asset)
    return <div key={id} className="w-28 overflow-hidden rounded-lg border border-border bg-bg-primary">
      {asset.kind === 'image' || asset.kind === 'character' || asset.kind === 'location' || asset.kind === 'prop'
        ? <a href={previewUrl} target="_blank" rel="noreferrer"><img className="h-28 w-full object-contain" src={previewUrl} alt={String(asset.metadata.name || t('references.prompt'))} loading="lazy" /></a>
        : <div className="flex h-14 items-center justify-center text-[9px] text-text-muted">{asset.kind}</div>}
      {onPrimary && <button type="button" className="w-full px-1 text-[10px] text-violet-200" aria-pressed={primaryId === id} onClick={() => onPrimary(id)}>{primaryId === id ? t('references.primary') : t('references.usePrimary')}</button>}
      {onRemove && <button type="button" className="w-full px-1 text-[10px] text-red-300" onClick={() => onRemove(id)}>{t('references.remove')}</button>}
    </div>
  })}</div>
}

function VariantEditor({ label, variants, onChange }: {
  label: string
  variants: SeriesVisualVariant[]
  onChange: (variants: SeriesVisualVariant[]) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  return <div className="mt-3 rounded-lg border border-border p-2">
    <div className="mb-2 flex items-center justify-between"><span className="text-[10px] font-semibold uppercase text-text-muted">{label}</span><button className={secondaryButton} onClick={() => onChange([...variants, createVisualVariant(t('canon.variantDefault', { number: variants.length + 1 }))])}><Plus size={12} />{t('canon.namedVariant')}</button></div>
    <div className="space-y-2">{variants.map((variant, index) => <div key={variant.id} className="grid gap-2 md:grid-cols-[150px_1fr_auto]"><input className={inputClass} value={variant.label} placeholder={t('canon.variantName')} onChange={event => onChange(variants.map((item, i) => i === index ? { ...item, label: event.target.value } : item))} /><input className={inputClass} value={variant.description} placeholder={t('canon.variantLock')} onChange={event => onChange(variants.map((item, i) => i === index ? { ...item, description: event.target.value } : item))} /><button onClick={() => onChange(variants.filter((_, i) => i !== index))} aria-label={t('canon.deleteVariant', { label: variant.label })}><Trash2 size={14} className="text-red-400" /></button></div>)}</div>
  </div>
}

export function SeriesCanonPanel({
  series, workspace, update: persistUpdate, replaceSeries, saveNow, onAssetImported, initialTab = 'world', focusCharacterId,
}: {
  series: SeriesProject
  workspace: string
  update: (updater: (series: SeriesProject) => SeriesProject) => void
  replaceSeries: (series: SeriesProject) => void
  saveNow: () => Promise<unknown>
  onAssetImported?: (workspace: string, result: SeriesReferenceImport) => void
  initialTab?: CanonTab
  focusCharacterId?: string
}) {
  const { t } = useUiTranslation('seriesLab')
  const imageItems = useWorkspaceImageOutputs(workspace)
  const acceptAssetImport = onAssetImported || ((_workspace: string, result: SeriesReferenceImport) => replaceSeries(result.series))
  const [tab, setTab] = useState<CanonTab>(initialTab)
  const [focused, setFocused] = useState(focusCharacterId)
  useEffect(() => {
    if (tab === 'characters' && focused) document.getElementById(`series-character-${focused}`)?.scrollIntoView?.({ block: 'start' })
  }, [tab, focused])
  const [uploading, setUploading] = useState('')
  const [approving, setApproving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const update = (updater: (series: SeriesProject) => SeriesProject) => persistUpdate(current => {
    const next = updater(current)
    return { ...next, canon: { ...next.canon, approval: 'draft', approvedAt: '' } }
  })
  const patchCanon = (patch: Partial<SeriesProject['canon']>) => update(current => ({
    ...current, canon: { ...current.canon, ...patch },
  }))
  const patchVoice = (index: number, patch: Record<string, unknown>) => update(current => ({
    ...current,
    characters: current.characters.map((item, i) => i === index
      ? { ...item, voiceProfile: { ...item.voiceProfile, ...patch } } : item),
  }))
  const uploadReference = async (
    item: ApiOutput, ownerType: 'character' | 'location' | 'prop', ownerId: string,
  ) => {
    setUploading(ownerId); setError(null)
    try {
      await saveNow()
      const ensured = await ensureUploadsPath(item)
      const result = await api.importSeriesAsset(workspace, series.id, {
        uploadPath: ensured.path, name: item.name, ownerType, ownerId,
        kind: ownerType, referenceRole: ownerType === 'character' ? 'primary_portrait' : 'reference',
      })
      acceptAssetImport(workspace, result)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('canon.importFailed'))
    } finally { setUploading('') }
  }
  const approveAll = async () => {
    setApproving(true); setError(null)
    try {
      await saveNow()
      replaceSeries(await api.approveSeriesCanon(workspace, series.id, series.canon.revision))
    } catch (reason) { setError((reason as Error).message) }
    finally { setApproving(false) }
  }
  const unapproved = series.characters.filter(item => item.approval !== 'approved').length
    + series.locations.filter(item => item.approval !== 'approved').length
    + series.props.filter(item => item.approval !== 'approved').length
  const approveLabel = series.canon.approval === 'approved'
    ? t('canon.approved', { revision: series.canon.revision })
    : unapproved > 0
      ? t('canon.approveWithEntities', { count: unapproved })
      : t('canon.approve')

  return <div className="space-y-4 pb-10">
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-bg-secondary p-2">
      {CANON_TABS.map(id => <button key={id} onClick={() => setTab(id)} className={`rounded-lg px-3 py-2 text-[11px] ${tab === id ? 'bg-violet-500/20 text-violet-200' : 'text-text-muted hover:bg-bg-hover'}`}>{t(`canon.tabs.${id}`)}</button>)}
      <button className={`ml-auto ${secondaryButton}`} disabled={approving} onClick={() => void approveAll()}><Check size={13} />{approveLabel}</button>
    </div>
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}

    {tab === 'world' && <>
      <SectionCard title={t('canon.worldTitle')} description={t('canon.worldDescription', { revision: series.canon.revision })}>
        <SeriesField label={t('canon.worldSummary')} required><textarea className={textareaClass} value={series.canon.worldSummary} onChange={event => patchCanon({ worldSummary: event.target.value })} /></SeriesField>
      </SectionCard>
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title={t('canon.immutableRules')} action={<button className={secondaryButton} onClick={() => patchCanon({ immutableRules: [...series.canon.immutableRules, { id: seriesId('rule'), description: '', status: 'draft' }] })}><Plus size={13} />{t('canon.rule')}</button>}>
          <div className="space-y-2">{series.canon.immutableRules.map((fact, index) => <div key={fact.id} className="flex gap-2"><input className={inputClass} value={fact.description} onChange={event => patchCanon({ immutableRules: series.canon.immutableRules.map((item, i) => i === index ? { ...item, description: event.target.value } : item) })} /><button onClick={() => patchCanon({ immutableRules: series.canon.immutableRules.filter((_, i) => i !== index) })}><Trash2 size={14} className="text-red-400" /></button></div>)}</div>
        </SectionCard>
        <SectionCard title={t('canon.currentFacts')}><div className="space-y-2">{series.canon.currentFacts.length ? series.canon.currentFacts.map(fact => <div key={fact.id} className="flex items-start gap-2 rounded-lg border border-border p-2 text-xs text-text-secondary"><div className="min-w-0 flex-1"><Pill tone={fact.status === 'approved' ? 'green' : 'neutral'}>{seriesStatusLabel(t, fact.status)}</Pill><span className="ml-2">{fact.description}</span></div><button type="button" className="shrink-0 rounded-md p-1 text-red-400 hover:bg-red-500/10 hover:text-red-300" title={t('canon.deleteFact', { description: fact.description })} aria-label={t('canon.deleteFact', { description: fact.description })} onClick={() => patchCanon({ currentFacts: series.canon.currentFacts.filter(item => item.id !== fact.id) })}><Trash2 size={14} /></button></div>) : <p className="text-xs text-text-muted">{t('canon.noFacts')}</p>}</div></SectionCard>
        <SectionCard title={t('canon.themes')}><input className={inputClass} value={series.canon.themes.join(', ')} onChange={event => patchCanon({ themes: event.target.value.split(',').map(item => item.trim()).filter(Boolean) })} placeholder={t('canon.themesPlaceholder')} /></SectionCard>
        <SectionCard title={t('canon.forbidden')}><textarea className={textareaClass} value={series.canon.forbiddenChanges.join('\n')} onChange={event => patchCanon({ forbiddenChanges: event.target.value.split('\n').map(item => item.trim()).filter(Boolean) })} /></SectionCard>
      </div>
    </>}

    {tab === 'characters' && <SectionCard title={t('canon.charactersTitle')} description={t('canon.charactersDescription')} action={<button className={primaryButton} onClick={() => update(current => ({ ...current, characters: [...current.characters, createSeriesCharacter()] }))}><Plus size={13} />{t('canon.character')}</button>}>
      <div className="grid gap-3 xl:grid-cols-2">{series.characters.map((character, index) => <div id={`series-character-${character.id}`} key={character.id} className="rounded-xl border border-border bg-bg-primary p-3">
        <div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2"><strong className="text-xs text-text-primary">{character.name}</strong><Pill tone={character.approval === 'approved' ? 'green' : 'amber'}>{seriesStatusLabel(t, character.approval)}</Pill></div><button onClick={() => update(current => ({ ...current, characters: current.characters.filter((_, i) => i !== index) }))}><Trash2 size={14} className="text-red-400" /></button></div>
        <div className="grid gap-2 md:grid-cols-2">
          {CHARACTER_FIELDS.map(key => <label key={key} className="text-[10px] uppercase text-text-muted">{t(`canon.fields.${key}`)}<textarea className={`${inputClass} mt-1 min-h-14`} value={character[key]} onChange={event => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, [key]: event.target.value } : item) }))} /></label>)}
        </div>
        <VariantEditor label={t('canon.wardrobeVariants')} variants={character.wardrobeVariants} onChange={variants => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, wardrobeVariants: variants, defaultWardrobeVariantId: variants.some(variant => variant.id === item.defaultWardrobeVariantId) ? item.defaultWardrobeVariantId : variants[0]?.id } : item) }))} />
        {character.wardrobeVariants.length > 0 && <label className="mt-2 block text-[10px] uppercase text-text-muted">{t('canon.defaultWardrobe')}<select className={`${inputClass} mt-1`} value={character.defaultWardrobeVariantId || ''} onChange={event => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, defaultWardrobeVariantId: event.target.value || undefined } : item) }))}><option value="">{t('canon.noDefault')}</option>{character.wardrobeVariants.map(variant => <option key={variant.id} value={variant.id}>{variant.label}</option>)}</select></label>}
        <div className="mt-3"><ReferenceStrip series={series} assetIds={character.referenceAssetIds} primaryId={character.primaryReferenceAssetId}
          onPrimary={id => update(current => ({ ...current, characters: current.characters.map(item => item.id === character.id ? { ...item, primaryReferenceAssetId: id } : item) }))}
          onRemove={id => update(current => ({ ...current, characters: current.characters.map(item => item.id === character.id ? { ...item,
            referenceAssetIds: item.referenceAssetIds.filter(ref => ref !== id),
            primaryReferenceAssetId: item.primaryReferenceAssetId === id ? item.referenceAssetIds.find(ref => ref !== id) : item.primaryReferenceAssetId,
          } : item) }))} /></div>
        <div className="mt-3 space-y-2">
          <SeriesCharacterSpeech key={`${workspace}/${series.id}/${character.id}`} workspace={workspace} series={series} character={character}
            saveNow={saveNow} onPatch={patch => update(current => current.id !== series.id ? current : ({ ...current,
              characters: current.characters.map(item => item.id === character.id ? { ...item, voiceProfile: { ...item.voiceProfile, ...patch } } : item),
            }))} />
          <SeriesReferenceGenerator key={`${workspace}/${series.id}/${character.id}`} workspace={workspace} series={series} target={{ kind: 'character', id: character.id }} saveNow={saveNow} onImported={acceptAssetImport} />
          <SeriesReferenceField label={uploading === character.id ? t('canon.importing') : t('canon.addIdentity')} items={imageItems} disabled={Boolean(uploading)} onPick={item => void uploadReference(item, 'character', character.id)} />
          <button className={secondaryButton} onClick={() => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, approval: item.approval === 'approved' ? 'draft' : 'approved' } : item) }))}>{character.approval === 'approved' ? t('canon.returnDraft') : t('canon.approveCharacter')}</button>
        </div>
      </div>)}</div>
    </SectionCard>}
    {tab === 'characters' && <SectionCard title={t('canon.relationshipsTitle')} action={<button className={primaryButton} disabled={series.characters.length < 2} onClick={() => update(current => ({ ...current, relationships: [...current.relationships, { id: seriesId('relationship'), fromCharacterId: current.characters[0]?.id || '', toCharacterId: current.characters[1]?.id || '', label: '', dynamic: '', evolution: '' }] }))}><Plus size={13} />{t('canon.relationship')}</button>}>
      <div className="space-y-3">{series.relationships.map((relationship, index) => <div key={relationship.id} className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[1fr_1fr_auto]"><select className={inputClass} value={relationship.fromCharacterId} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, fromCharacterId: event.target.value } : item) }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select className={inputClass} value={relationship.toCharacterId} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, toCharacterId: event.target.value } : item) }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button onClick={() => update(current => ({ ...current, relationships: current.relationships.filter((_, i) => i !== index) }))} aria-label={t('canon.deleteRelationship')}><Trash2 size={14} className="text-red-400" /></button><input className={inputClass} value={relationship.label} placeholder={t('canon.relationshipPlaceholder')} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, label: event.target.value } : item) }))} /><textarea className={inputClass} value={relationship.dynamic} placeholder={t('canon.dynamicPlaceholder')} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, dynamic: event.target.value } : item) }))} /><textarea className={inputClass} value={relationship.evolution} placeholder={t('canon.evolutionPlaceholder')} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, evolution: event.target.value } : item) }))} /></div>)}</div>
    </SectionCard>}

    {tab === 'locations' && <SectionCard title={t('canon.locationsTitle')} action={<button className={primaryButton} onClick={() => update(current => ({ ...current, locations: [...current.locations, createSeriesLocation()] }))}><Plus size={13} />{t('canon.location')}</button>}>
      <div className="grid gap-3 xl:grid-cols-2">{series.locations.map((location, index) => <div key={location.id} className="rounded-xl border border-border bg-bg-primary p-3">
        <div className="flex items-center gap-2"><input className={inputClass} value={location.name} onChange={event => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, name: event.target.value } : item) }))} /><Pill tone={location.approval === 'approved' ? 'green' : 'amber'}>{seriesStatusLabel(t, location.approval)}</Pill><button onClick={() => update(current => ({ ...current, locations: current.locations.filter((_, i) => i !== index) }))}><Trash2 size={14} className="text-red-400" /></button></div>
        <textarea className={`${textareaClass} mt-2`} value={location.description} onChange={event => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, description: event.target.value } : item) }))} placeholder={t('canon.locationPlaceholder')} />
        <VariantEditor label={t('canon.locationVariants')} variants={location.variants} onChange={variants => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, variants } : item) }))} />
        <div className="my-3"><ReferenceStrip series={series} assetIds={location.referenceAssetIds}
          onRemove={id => update(current => ({ ...current, locations: current.locations.map(item => item.id === location.id ? { ...item,
            referenceAssetIds: item.referenceAssetIds.filter(ref => ref !== id),
          } : item) }))} /></div>
        <div className="space-y-2">
          <SeriesReferenceGenerator key={`${workspace}/${series.id}/${location.id}`} workspace={workspace} series={series} target={{ kind: 'location', id: location.id }} saveNow={saveNow} onImported={acceptAssetImport} />
          <SeriesReferenceField label={t('canon.addReference')} items={imageItems} disabled={Boolean(uploading)} onPick={item => void uploadReference(item, 'location', location.id)} />
          <button className={secondaryButton} onClick={() => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, approval: item.approval === 'approved' ? 'draft' : 'approved' } : item) }))}>{t('canon.toggleApproval')}</button>
        </div>
      </div>)}</div>
    </SectionCard>}

    {tab === 'advanced' && <SectionCard title={t('canon.propsTitle')} action={<button className={primaryButton} onClick={() => update(current => ({ ...current, props: [...current.props, createSeriesProp()] }))}><Plus size={13} />{t('canon.prop')}</button>}>
      <div className="space-y-3">{series.props.map((prop, index) => <div key={prop.id} className="rounded-xl border border-border p-3"><div className="grid gap-2 md:grid-cols-3"><input className={inputClass} value={prop.name} onChange={event => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, name: event.target.value } : item) }))} /><input className={inputClass} value={prop.kind} placeholder={t('canon.kindPlaceholder')} onChange={event => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, kind: event.target.value } : item) }))} /><button className={secondaryButton} onClick={() => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, approval: item.approval === 'approved' ? 'draft' : 'approved' } : item) }))}>{seriesStatusLabel(t, prop.approval)}</button></div><textarea className={`${textareaClass} mt-2`} value={prop.description} onChange={event => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, description: event.target.value } : item) }))} /><VariantEditor label={t('canon.propVariants')} variants={prop.variants} onChange={variants => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, variants } : item) }))} /><div className="my-2"><ReferenceStrip series={series} assetIds={prop.referenceAssetIds} /></div><SeriesReferenceField label={t('canon.addReference')} items={imageItems} disabled={Boolean(uploading)} onPick={item => void uploadReference(item, 'prop', prop.id)} /></div>)}</div>
    </SectionCard>}

    {tab === 'continuity' && <>
      <SectionCard title={t('canon.arcsTitle')} action={<button className={primaryButton} onClick={() => patchCanon({ longArcs: [...series.canon.longArcs, { id: seriesId('arc'), title: '', description: '', status: 'planned' }] })}><Plus size={13} />{t('canon.arc')}</button>}><div className="space-y-2">{series.canon.longArcs.map((arc, index) => <div key={arc.id} className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[1fr_2fr_auto]"><input className={inputClass} value={arc.title} onChange={event => patchCanon({ longArcs: series.canon.longArcs.map((item, i) => i === index ? { ...item, title: event.target.value } : item) })} /><textarea className={inputClass} value={arc.description} onChange={event => patchCanon({ longArcs: series.canon.longArcs.map((item, i) => i === index ? { ...item, description: event.target.value } : item) })} /><select className={inputClass} value={arc.status} onChange={event => patchCanon({ longArcs: series.canon.longArcs.map((item, i) => i === index ? { ...item, status: event.target.value as typeof item.status } : item) })}><option value="planned">{t('status.planned')}</option><option value="active">{t('status.active')}</option><option value="resolved">{t('status.resolved')}</option><option value="abandoned">{t('status.abandoned')}</option></select></div>)}</div></SectionCard>
      <SectionCard title={t('canon.timelineTitle')} action={<button className={primaryButton} onClick={() => patchCanon({ timeline: [...series.canon.timeline, { id: seriesId('event'), description: '', status: 'draft', occurredAt: '' }] })}><Plus size={13} />{t('canon.event')}</button>}><div className="space-y-2">{series.canon.timeline.map((event, index) => <div key={event.id} className="grid gap-2 md:grid-cols-[1fr_3fr]"><SeriesField label={t('canon.when')}><input className={inputClass} value={event.occurredAt} onChange={change => patchCanon({ timeline: series.canon.timeline.map((item, i) => i === index ? { ...item, occurredAt: change.target.value } : item) })} /></SeriesField><SeriesField label={t('canon.whatHappened')}><input className={inputClass} value={event.description} onChange={change => patchCanon({ timeline: series.canon.timeline.map((item, i) => i === index ? { ...item, description: change.target.value } : item) })} /></SeriesField></div>)}</div></SectionCard>
    </>}

    {tab === 'advanced' && <SectionCard title={t('canon.voicesTitle')} description={t('canon.voicesDescription')}>
      <SeriesVoiceFields series={series} onPatchVoice={patchVoice} onConfigureCharacter={id => { setFocused(id); setTab('characters') }} />
    </SectionCard>}
  </div>
}
