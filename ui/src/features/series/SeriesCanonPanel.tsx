import { useState } from 'react'
import { Check, Plus, Trash2, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { createSeriesCharacter, createSeriesLocation, createSeriesProp, createVisualVariant, seriesId } from './model'
import { Pill, SectionCard, SeriesField, seriesStatusLabel } from './components'
import { inputClass, primaryButton, secondaryButton, textareaClass } from './styles'
import type { SeriesProject, SeriesVisualVariant } from './types'
import { useUiTranslation } from '../../i18n'

type CanonTab = 'world' | 'characters' | 'relationships' | 'locations' | 'props' | 'arcs' | 'timeline' | 'voices'
const CANON_TABS: CanonTab[] = ['world', 'characters', 'relationships', 'locations', 'props', 'arcs', 'timeline', 'voices']
const CHARACTER_FIELDS = ['name', 'role', 'personality', 'desire', 'need', 'flaw', 'longArc', 'voiceAndDialogue', 'appearance', 'identityLock'] as const

function ReferenceStrip({ series, assetIds }: { series: SeriesProject; assetIds: string[] }) {
  const { t } = useUiTranslation('seriesLab')
  if (!assetIds.length) return <span className="text-[10px] text-text-muted">{t('canon.noReference')}</span>
  return <div className="flex flex-wrap gap-2">{assetIds.map(id => {
    const asset = series.assets[id]
    if (!asset) return <Pill key={id} tone="red">{t('canon.missingAsset', { id })}</Pill>
    const filename = asset.uri.replace(/^outputs\//, '')
    const previewUrl = /^https?:\/\//i.test(asset.uri)
      ? asset.uri
      : api.getOutputThumbnailUrl(filename)
    return <div key={id} className="w-20 overflow-hidden rounded-lg border border-border bg-bg-primary">
      {asset.kind === 'image' || asset.kind === 'character' || asset.kind === 'location' || asset.kind === 'prop'
        ? <img className="h-14 w-full object-cover" src={previewUrl} alt="" loading="lazy" />
        : <div className="flex h-14 items-center justify-center text-[9px] text-text-muted">{asset.kind}</div>}
      <div className="truncate px-1 py-1 text-[8px] text-text-muted" title={id}>{id}</div>
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
  series, workspace, update: persistUpdate, replaceSeries, saveNow,
}: {
  series: SeriesProject
  workspace: string
  update: (updater: (series: SeriesProject) => SeriesProject) => void
  replaceSeries: (series: SeriesProject) => void
  saveNow: () => Promise<unknown>
}) {
  const { t } = useUiTranslation('seriesLab')
  const [tab, setTab] = useState<CanonTab>('world')
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
    file: File, ownerType: 'character' | 'location' | 'prop', ownerId: string,
  ) => {
    setUploading(ownerId); setError(null)
    try {
      await saveNow()
      const upload = await api.uploadImage(file)
      const result = await api.importSeriesAsset(workspace, series.id, {
        uploadPath: upload.path, name: file.name, ownerType, ownerId,
        kind: ownerType, referenceRole: ownerType === 'character' ? 'primary_portrait' : 'reference',
      })
      replaceSeries(result.series)
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
      <div className="grid gap-3 xl:grid-cols-2">{series.characters.map((character, index) => <div key={character.id} className="rounded-xl border border-border bg-bg-primary p-3">
        <div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2"><strong className="text-xs text-text-primary">{character.name}</strong><Pill tone={character.approval === 'approved' ? 'green' : 'amber'}>{seriesStatusLabel(t, character.approval)}</Pill></div><button onClick={() => update(current => ({ ...current, characters: current.characters.filter((_, i) => i !== index) }))}><Trash2 size={14} className="text-red-400" /></button></div>
        <div className="grid gap-2 md:grid-cols-2">
          {CHARACTER_FIELDS.map(key => <label key={key} className="text-[10px] uppercase text-text-muted">{t(`canon.fields.${key}`)}<textarea className={`${inputClass} mt-1 min-h-14`} value={character[key]} onChange={event => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, [key]: event.target.value } : item) }))} /></label>)}
        </div>
        <VariantEditor label={t('canon.wardrobeVariants')} variants={character.wardrobeVariants} onChange={variants => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, wardrobeVariants: variants, defaultWardrobeVariantId: variants.some(variant => variant.id === item.defaultWardrobeVariantId) ? item.defaultWardrobeVariantId : variants[0]?.id } : item) }))} />
        {character.wardrobeVariants.length > 0 && <label className="mt-2 block text-[10px] uppercase text-text-muted">{t('canon.defaultWardrobe')}<select className={`${inputClass} mt-1`} value={character.defaultWardrobeVariantId || ''} onChange={event => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, defaultWardrobeVariantId: event.target.value || undefined } : item) }))}><option value="">{t('canon.noDefault')}</option>{character.wardrobeVariants.map(variant => <option key={variant.id} value={variant.id}>{variant.label}</option>)}</select></label>}
        <div className="mt-3"><ReferenceStrip series={series} assetIds={character.referenceAssetIds} /></div>
        <div className="mt-3 flex gap-2"><label className={secondaryButton}><Upload size={13} />{uploading === character.id ? t('canon.importing') : t('canon.addIdentity')}<input type="file" accept="image/*" className="hidden" disabled={Boolean(uploading)} onChange={event => { const file = event.target.files?.[0]; if (file) void uploadReference(file, 'character', character.id) }} /></label><button className={secondaryButton} onClick={() => update(current => ({ ...current, characters: current.characters.map((item, i) => i === index ? { ...item, approval: item.approval === 'approved' ? 'draft' : 'approved' } : item) }))}>{character.approval === 'approved' ? t('canon.returnDraft') : t('canon.approveCharacter')}</button></div>
      </div>)}</div>
    </SectionCard>}

    {tab === 'locations' && <SectionCard title={t('canon.locationsTitle')} action={<button className={primaryButton} onClick={() => update(current => ({ ...current, locations: [...current.locations, createSeriesLocation()] }))}><Plus size={13} />{t('canon.location')}</button>}>
      <div className="grid gap-3 xl:grid-cols-2">{series.locations.map((location, index) => <div key={location.id} className="rounded-xl border border-border bg-bg-primary p-3">
        <div className="flex items-center gap-2"><input className={inputClass} value={location.name} onChange={event => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, name: event.target.value } : item) }))} /><Pill tone={location.approval === 'approved' ? 'green' : 'amber'}>{seriesStatusLabel(t, location.approval)}</Pill><button onClick={() => update(current => ({ ...current, locations: current.locations.filter((_, i) => i !== index) }))}><Trash2 size={14} className="text-red-400" /></button></div>
        <textarea className={`${textareaClass} mt-2`} value={location.description} onChange={event => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, description: event.target.value } : item) }))} placeholder={t('canon.locationPlaceholder')} />
        <VariantEditor label={t('canon.locationVariants')} variants={location.variants} onChange={variants => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, variants } : item) }))} />
        <div className="my-3"><ReferenceStrip series={series} assetIds={location.referenceAssetIds} /></div>
        <div className="flex gap-2"><label className={secondaryButton}><Upload size={13} />{t('canon.addReference')}<input type="file" accept="image/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) void uploadReference(file, 'location', location.id) }} /></label><button className={secondaryButton} onClick={() => update(current => ({ ...current, locations: current.locations.map((item, i) => i === index ? { ...item, approval: item.approval === 'approved' ? 'draft' : 'approved' } : item) }))}>{t('canon.toggleApproval')}</button></div>
      </div>)}</div>
    </SectionCard>}

    {tab === 'props' && <SectionCard title={t('canon.propsTitle')} action={<button className={primaryButton} onClick={() => update(current => ({ ...current, props: [...current.props, createSeriesProp()] }))}><Plus size={13} />{t('canon.prop')}</button>}>
      <div className="space-y-3">{series.props.map((prop, index) => <div key={prop.id} className="rounded-xl border border-border p-3"><div className="grid gap-2 md:grid-cols-3"><input className={inputClass} value={prop.name} onChange={event => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, name: event.target.value } : item) }))} /><input className={inputClass} value={prop.kind} placeholder={t('canon.kindPlaceholder')} onChange={event => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, kind: event.target.value } : item) }))} /><button className={secondaryButton} onClick={() => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, approval: item.approval === 'approved' ? 'draft' : 'approved' } : item) }))}>{seriesStatusLabel(t, prop.approval)}</button></div><textarea className={`${textareaClass} mt-2`} value={prop.description} onChange={event => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, description: event.target.value } : item) }))} /><VariantEditor label={t('canon.propVariants')} variants={prop.variants} onChange={variants => update(current => ({ ...current, props: current.props.map((item, i) => i === index ? { ...item, variants } : item) }))} /><div className="my-2"><ReferenceStrip series={series} assetIds={prop.referenceAssetIds} /></div><label className={secondaryButton}><Upload size={13} />{t('canon.addReference')}<input type="file" accept="image/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) void uploadReference(file, 'prop', prop.id) }} /></label></div>)}</div>
    </SectionCard>}

    {tab === 'relationships' && <SectionCard title={t('canon.relationshipsTitle')} action={<button className={primaryButton} disabled={series.characters.length < 2} onClick={() => update(current => ({ ...current, relationships: [...current.relationships, { id: seriesId('relationship'), fromCharacterId: current.characters[0]?.id || '', toCharacterId: current.characters[1]?.id || '', label: '', dynamic: '', evolution: '' }] }))}><Plus size={13} />{t('canon.relationship')}</button>}>
      <div className="space-y-3">{series.relationships.map((relationship, index) => <div key={relationship.id} className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[1fr_1fr_auto]"><select className={inputClass} value={relationship.fromCharacterId} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, fromCharacterId: event.target.value } : item) }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select className={inputClass} value={relationship.toCharacterId} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, toCharacterId: event.target.value } : item) }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button onClick={() => update(current => ({ ...current, relationships: current.relationships.filter((_, i) => i !== index) }))} aria-label={t('canon.deleteRelationship')}><Trash2 size={14} className="text-red-400" /></button><input className={inputClass} value={relationship.label} placeholder={t('canon.relationshipPlaceholder')} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, label: event.target.value } : item) }))} /><textarea className={inputClass} value={relationship.dynamic} placeholder={t('canon.dynamicPlaceholder')} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, dynamic: event.target.value } : item) }))} /><textarea className={inputClass} value={relationship.evolution} placeholder={t('canon.evolutionPlaceholder')} onChange={event => update(current => ({ ...current, relationships: current.relationships.map((item, i) => i === index ? { ...item, evolution: event.target.value } : item) }))} /></div>)}</div>
    </SectionCard>}

    {tab === 'arcs' && <SectionCard title={t('canon.arcsTitle')} action={<button className={primaryButton} onClick={() => patchCanon({ longArcs: [...series.canon.longArcs, { id: seriesId('arc'), title: '', description: '', status: 'planned' }] })}><Plus size={13} />{t('canon.arc')}</button>}><div className="space-y-2">{series.canon.longArcs.map((arc, index) => <div key={arc.id} className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[1fr_2fr_auto]"><input className={inputClass} value={arc.title} onChange={event => patchCanon({ longArcs: series.canon.longArcs.map((item, i) => i === index ? { ...item, title: event.target.value } : item) })} /><textarea className={inputClass} value={arc.description} onChange={event => patchCanon({ longArcs: series.canon.longArcs.map((item, i) => i === index ? { ...item, description: event.target.value } : item) })} /><select className={inputClass} value={arc.status} onChange={event => patchCanon({ longArcs: series.canon.longArcs.map((item, i) => i === index ? { ...item, status: event.target.value as typeof item.status } : item) })}><option value="planned">{t('status.planned')}</option><option value="active">{t('status.active')}</option><option value="resolved">{t('status.resolved')}</option><option value="abandoned">{t('status.abandoned')}</option></select></div>)}</div></SectionCard>}

    {tab === 'timeline' && <SectionCard title={t('canon.timelineTitle')} action={<button className={primaryButton} onClick={() => patchCanon({ timeline: [...series.canon.timeline, { id: seriesId('event'), description: '', status: 'draft', occurredAt: '' }] })}><Plus size={13} />{t('canon.event')}</button>}><div className="space-y-2">{series.canon.timeline.map((event, index) => <div key={event.id} className="grid gap-2 md:grid-cols-[1fr_3fr]"><input className={inputClass} value={event.occurredAt} placeholder={t('canon.when')} onChange={change => patchCanon({ timeline: series.canon.timeline.map((item, i) => i === index ? { ...item, occurredAt: change.target.value } : item) })} /><input className={inputClass} value={event.description} placeholder={t('canon.whatHappened')} onChange={change => patchCanon({ timeline: series.canon.timeline.map((item, i) => i === index ? { ...item, description: change.target.value } : item) })} /></div>)}</div></SectionCard>}

    {tab === 'voices' && <SectionCard title={t('canon.voicesTitle')} description={t('canon.voicesDescription')}>
      <div className="space-y-3">{series.characters.map((character, index) => <div key={character.id} className="rounded-lg border border-border p-3">
        <strong className="text-xs text-text-primary">{character.name}</strong>
        <div className="mt-2 grid gap-2 md:grid-cols-3">
          <input className={inputClass} value={String(character.voiceProfile?.provider || '')} placeholder={t('canon.provider')} onChange={event => patchVoice(index, { provider: event.target.value })} />
          <input className={inputClass} value={String(character.voiceProfile?.voiceId || '')} placeholder={t('canon.voiceId')} onChange={event => patchVoice(index, { voiceId: event.target.value })} />
          <input className={inputClass} value={String(character.voiceProfile?.language || '')} placeholder={t('canon.language')} onChange={event => patchVoice(index, { language: event.target.value })} />
          <input className={inputClass} type="number" step="0.05" value={Number(character.voiceProfile?.pace ?? 1)} placeholder={t('canon.pace')} onChange={event => patchVoice(index, { pace: Number(event.target.value) })} />
          <input className={inputClass} type="number" step="0.05" value={Number(character.voiceProfile?.pitch ?? 0)} placeholder={t('canon.pitch')} onChange={event => patchVoice(index, { pitch: Number(event.target.value) })} />
          <input className={inputClass} value={String(character.voiceProfile?.emotionalDefaults || '')} placeholder={t('canon.emotion')} onChange={event => patchVoice(index, { emotionalDefaults: event.target.value })} />
          <textarea className={textareaClass} value={Object.entries(character.voiceProfile?.pronunciationDictionary || {}).map(([word, pronunciation]) => `${word}=${pronunciation}`).join('\n')} placeholder={t('canon.pronunciationPlaceholder')} onChange={event => patchVoice(index, { pronunciationDictionary: Object.fromEntries(event.target.value.split('\n').map(line => line.split('=', 2).map(value => value.trim())).filter(parts => parts.length === 2 && parts[0])) })} />
          <textarea className={textareaClass} value={String(character.voiceProfile?.consentSourceNote || '')} placeholder={t('canon.consent')} onChange={event => patchVoice(index, { consentSourceNote: event.target.value })} />
        </div>
      </div>)}</div>
    </SectionCard>}
  </div>
}
