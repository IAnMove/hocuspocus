import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { fetchCharacterKitLibrary } from '../../api/characters'
import type { CharacterKitLibrary } from '../../lib/characterKit'
import { useUiTranslation } from '../../i18n'
import { characterKitPoseOptions } from '../characters/characterKitGuide'
import { SeriesField } from './components'
import { inputClass, secondaryButton, selectClass, textareaClass } from './styles'
import type { SeriesProject, SeriesShot, SeriesShotCastEntry, SeriesShotLayout2D } from './types'

const FRAMINGS = ['wide', 'two', 'medium', 'close', 'insert', 'title'] as const
const PLAN_KEYS = new Set(['framing', 'camera', 'cast', 'timing'])

/** The rest of the 2D plan (effects, sounds, props, set layers, card, music...) as JSON. */
function advancedLayout(layout: SeriesShotLayout2D | undefined) {
  return JSON.stringify(Object.fromEntries(Object.entries(layout || {}).filter(([key]) => !PLAN_KEYS.has(key))), null, 2)
}

function useKitLibrary(workspace: string) {
  const [library, setLibrary] = useState<CharacterKitLibrary | null>(null)
  useEffect(() => {
    let alive = true
    fetchCharacterKitLibrary(workspace).then(value => { if (alive) setLibrary(value) }).catch(() => {})
    return () => { alive = false }
  }, [workspace])
  return library
}

function JsonField({ label, value, onApply }: { label: string; value: string; onApply: (parsed: Record<string, unknown> | undefined) => void }) {
  const { t } = useUiTranslation('seriesLab')
  const [text, setText] = useState(value)
  const [error, setError] = useState('')
  useEffect(() => { setText(value); setError('') }, [value])
  const apply = () => {
    try {
      const parsed = text.trim() ? JSON.parse(text) : undefined
      if (parsed !== undefined && (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null)) throw new Error(t('approval.edit.jsonObject'))
      setError(''); onApply(parsed)
    } catch (reason) { setError((reason as Error).message) }
  }
  return <SeriesField label={label}>
    <textarea className={`${textareaClass} font-mono text-[11px]`} spellCheck={false} value={text} onChange={event => setText(event.target.value)} />
    <div className="mt-1 flex items-center gap-2">
      <button type="button" className={secondaryButton} disabled={text === value} onClick={apply}>{t('approval.edit.applyJson')}</button>
      {error && <span role="alert" className="text-[10px] text-red-300">{error}</span>}
    </div>
  </SeriesField>
}

function CastRow({ series, library, entry, onChange, onRemove }: {
  series: SeriesProject; library: CharacterKitLibrary | null; entry: SeriesShotCastEntry
  onChange: (entry: SeriesShotCastEntry) => void; onRemove: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const ref = series.characters.find(item => item.id === entry.characterId)?.voiceProfile?.characterKitRef
  const kit = ref ? library?.kits[ref.id] : undefined
  const poses = kit ? characterKitPoseOptions(kit) : []
  return <div className="grid grid-cols-[1fr_1fr_72px_40px] items-center gap-2">
    <select aria-label={t('approval.edit.castCharacter')} className={selectClass} value={entry.characterId}
      onChange={event => onChange({ ...entry, characterId: event.target.value, poseId: undefined })}>
      {series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select>
    <select aria-label={t('approval.edit.castPose')} className={selectClass} value={entry.poseId ?? ''}
      onChange={event => onChange({ ...entry, poseId: event.target.value || undefined })}>
      <option value="">{t('approval.edit.poseDefault')}</option>
      {entry.poseId && !poses.some(pose => pose.id === entry.poseId) && <option value={entry.poseId}>{entry.poseId}</option>}
      {poses.map(pose => <option key={pose.id} value={pose.id}>{pose.label}</option>)}
    </select>
    <input aria-label={t('approval.edit.castX')} className={inputClass} type="number" min={0} max={100} step={1} value={entry.x ?? ''}
      onChange={event => onChange({ ...entry, x: event.target.value === '' ? undefined : Math.max(0, Math.min(100, Number(event.target.value))) })} />
    <button type="button" className={secondaryButton} aria-label={t('approval.edit.castRemove')} onClick={onRemove}><Trash2 size={13} /></button>
  </div>
}

/** A shot's 2D plan in place: framing, camera, cast (character, pose, x), timing; the rest and a 3D shot's scene as JSON. */
export function SeriesShotPlanEditor({ workspace, series, shot, onChange }: {
  workspace: string; series: SeriesProject; shot: SeriesShot; onChange: (shot: SeriesShot) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const library = useKitLibrary(workspace)
  const layout = shot.layout2d || {}
  const cast = Array.isArray(layout.cast) ? layout.cast : []
  const setLayout = (patch: Partial<SeriesShotLayout2D>) => {
    const next = Object.fromEntries(Object.entries({ ...layout, ...patch }).filter(([, value]) => value !== undefined && value !== ''))
    onChange({ ...shot, layout2d: Object.keys(next).length ? next as SeriesShotLayout2D : undefined })
  }
  const setCast = (next: SeriesShotCastEntry[]) => setLayout({ cast: next.length ? next : undefined })
  const timing = layout.timing || {}
  const setTiming = (key: 'intro' | 'tail', value: string) => {
    const next = { ...timing, [key]: value === '' ? undefined : Math.max(0, Math.min(6, Number(value))) }
    const kept = Object.fromEntries(Object.entries(next).filter(([, item]) => item !== undefined))
    setLayout({ timing: Object.keys(kept).length ? kept : undefined })
  }
  return <div className="space-y-3 rounded-lg border border-border p-3">
    <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">{t('approval.edit.planTitle')}</p>
    <div className="grid gap-2 sm:grid-cols-4">
      <SeriesField label={t('approval.edit.framing')}>
        <select className={selectClass} value={layout.framing ?? ''} onChange={event => setLayout({ framing: (event.target.value || undefined) as SeriesShotLayout2D['framing'] })}>
          <option value="">{t('approval.edit.auto')}</option>
          {FRAMINGS.map(value => <option key={value} value={value}>{t(`approval.framings.${value}`)}</option>)}
        </select>
      </SeriesField>
      <SeriesField label={t('approval.edit.camera')}>
        <select className={selectClass} value={layout.camera ?? ''} onChange={event => setLayout({ camera: (event.target.value || undefined) as SeriesShotLayout2D['camera'] })}>
          <option value="">{t('approval.edit.auto')}</option>
          <option value="static">{t('approval.cameras.static')}</option>
          <option value="push">{t('approval.cameras.push')}</option>
        </select>
      </SeriesField>
      <SeriesField label={t('approval.edit.intro')}>
        <input className={inputClass} type="number" min={0} max={6} step={0.05} value={timing.intro ?? ''} onChange={event => setTiming('intro', event.target.value)} />
      </SeriesField>
      <SeriesField label={t('approval.edit.tail')}>
        <input className={inputClass} type="number" min={0} max={6} step={0.05} value={timing.tail ?? ''} onChange={event => setTiming('tail', event.target.value)} />
      </SeriesField>
    </div>
    <div className="space-y-2">
      <p className="text-[10px] text-text-muted">{t('approval.edit.castHint')}</p>
      {cast.map((entry, index) => <CastRow key={`${index}-${entry.characterId}`} series={series} library={library} entry={entry}
        onChange={next => setCast(cast.map((item, position) => position === index ? next : item))}
        onRemove={() => setCast(cast.filter((_item, position) => position !== index))} />)}
      <button type="button" className={secondaryButton} disabled={!series.characters.length || cast.length >= 8}
        onClick={() => setCast([...cast, { characterId: series.characters[0]!.id, x: 50 }])}><Plus size={13} />{t('approval.edit.castAdd')}</button>
    </div>
    <JsonField label={t('approval.edit.advanced')} value={advancedLayout(shot.layout2d)}
      onApply={parsed => setLayout({ ...Object.fromEntries(Object.keys(layout).filter(key => !PLAN_KEYS.has(key)).map(key => [key, undefined])), ...parsed })} />
    {shot.productionMethod === 'animation_3d' && <JsonField label={t('approval.edit.scene3d')} value={JSON.stringify(shot.scene3d || {}, null, 2)}
      onApply={parsed => onChange({ ...shot, scene3d: parsed && Object.keys(parsed).length ? parsed : undefined })} />}
  </div>
}
