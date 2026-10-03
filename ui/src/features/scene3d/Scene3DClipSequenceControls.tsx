import { useUiTranslation } from '../../i18n'
import { DEFAULT_CUE_FADE, MAX_CLIP_CUES, parseClipCues, type Scene3DClipCue } from './clipCues.ts'
import { appendClipCue, removeClipCue, replaceClipCue, singleClipFromSequence, startClipSequence } from './clipSequenceEdit.ts'
import type { Scene3DClipCatalogEntry, Scene3DSlot } from './types.ts'

const fieldClass = 'ml-2 min-h-10 w-20 rounded border border-border bg-bg-tertiary px-2'

export function Scene3DClipSequenceControls({ slot, clips, duration, disabled, onChange }: {
  slot: Scene3DSlot
  clips: Scene3DClipCatalogEntry[]
  duration: number
  disabled: boolean
  onChange: (patch: Partial<Scene3DSlot>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const cues = parseClipCues(slot.clips)
  if (!cues) return <SequenceStart slot={slot} disabled={disabled || !clips.length} onChange={onChange} />
  const catalog = catalogWithCueClips(clips, cues)
  return <div className="space-y-2">
    <p className="text-xs font-medium">{t('sequence')}</p>
    <p className="text-xs text-text-muted">{t('sequenceHelp')}</p>
    <ol className="space-y-2">
      {cues.map((cue, index) => <CueRow key={`${cue.clip.index}:${cue.start}:${index}`} cue={cue} index={index} slotId={slot.id}
        clips={catalog} disabled={disabled}
        onChange={patch => onChange({ clips: replaceClipCue(cues, index, patch) })}
        onRemove={() => onChange(cues.length === 1 ? singleClipFromSequence(cues) : { clips: removeClipCue(cues, index) })} />)}
    </ol>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={disabled || cues.length >= MAX_CLIP_CUES || !clips.length}
        className="min-h-10 rounded border border-border px-3 text-xs disabled:opacity-40"
        onClick={() => {
          const previous = cues.at(-1)?.clip
          const clip = clips.find(item => item.index === previous?.index) ?? clips[0]
          onChange({ clips: appendClipCue(cues, { index: clip.index, name: clip.name }, duration) })
        }}>{t('sequenceAdd')}</button>
      <button type="button" disabled={disabled} className="min-h-10 rounded border border-border px-3 text-xs disabled:opacity-40"
        onClick={() => onChange(singleClipFromSequence(cues))}>{t('sequenceSingle')}</button>
    </div>
  </div>
}

function SequenceStart({ slot, disabled, onChange }: {
  slot: Scene3DSlot
  disabled: boolean
  onChange: (patch: Partial<Scene3DSlot>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const ready = Boolean(slot.clip)
  return <button type="button" disabled={disabled || !ready} title={ready ? undefined : t('sequenceNeedClip')}
    className="min-h-10 rounded border border-border px-3 text-xs disabled:opacity-40"
    onClick={() => { const cues = startClipSequence(slot); if (cues) onChange({ clips: cues }) }}>{t('sequenceStart')}</button>
}

function CueRow({ cue, index, slotId, clips, disabled, onChange, onRemove }: {
  cue: Scene3DClipCue
  index: number
  slotId: string
  clips: Scene3DClipCatalogEntry[]
  disabled: boolean
  onChange: (patch: Parameters<typeof replaceClipCue>[2]) => void
  onRemove: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: stageT } = useUiTranslation('scene3d')
  const label = t('sequenceCue', { n: index + 1 })
  return <li className="space-y-2 rounded-lg border border-border p-2">
    <label className="block text-xs font-medium">{label}
      <select aria-label={`${label} ${slotId}`} disabled={disabled} value={String(cue.clip.index)}
        className="mt-1 min-h-10 w-full rounded-lg border border-border bg-bg-tertiary px-2 text-xs disabled:opacity-40"
        onChange={event => {
          const clip = clips.find(item => String(item.index) === event.target.value)
          if (clip) onChange({ clip: { index: clip.index, name: clip.name } })
        }}>
        <option value="">{stageT('stage.noClip')}</option>
        {clips.map(clip => <option key={clip.index} value={clip.index}>{clip.index}: {clip.name}</option>)}
      </select>
    </label>
    <div className="flex flex-wrap items-center gap-3">
      <NumberField label={t('sequenceStartTime')} slotId={slotId} disabled={disabled} min={0} max={600} step={0.1} value={cue.start}
        onChange={start => onChange({ start })} />
      <NumberField label={t('sequenceFade')} slotId={slotId} disabled={disabled} min={0} max={10} step={0.1} value={cue.fade ?? (index === 0 ? 0 : DEFAULT_CUE_FADE)}
        onChange={fade => onChange({ fade })} />
      <NumberField label={t('sequenceHold')} slotId={slotId} disabled={disabled} min={0} max={600} step={0.1} value={cue.duration}
        onChange={duration => onChange({ duration: duration ?? null })} />
      <NumberField label={t('sequenceOffset')} slotId={slotId} disabled={disabled} min={0} max={600} step={0.1} value={cue.offset ?? 0}
        onChange={offset => onChange({ offset })} />
      <NumberField label={t('animationSpeed')} slotId={slotId} disabled={disabled} min={0.1} max={4} step={0.1} value={cue.speed ?? 1}
        onChange={speed => onChange({ speed })} />
      <label className="flex min-h-10 items-center gap-2 text-xs">
        <input type="checkbox" disabled={disabled} checked={cue.loop !== false} aria-label={`${t('animationLoop')} ${label} ${slotId}`}
          onChange={event => onChange({ loop: event.target.checked })} />{t('animationLoop')}
      </label>
      <button type="button" disabled={disabled} className="min-h-10 rounded border border-border px-3 text-xs disabled:opacity-40"
        onClick={onRemove}>{t('sequenceRemove')}</button>
    </div>
  </li>
}

function NumberField({ label, slotId, disabled, min, max, step, value, onChange }: {
  label: string
  slotId: string
  disabled: boolean
  min: number
  max: number
  step: number
  value: number | undefined
  onChange: (value: number | undefined) => void
}) {
  return <label className="text-xs">{label}
    <input aria-label={`${label} ${slotId}`} type="number" min={min} max={max} step={step} disabled={disabled} value={value ?? ''}
      className={fieldClass}
      onChange={event => onChange(event.target.value === '' ? undefined : event.target.valueAsNumber)} />
  </label>
}

function catalogWithCueClips(clips: Scene3DClipCatalogEntry[], cues: readonly Scene3DClipCue[]): Scene3DClipCatalogEntry[] {
  const known = new Set(clips.map(clip => clip.index))
  const missing = cues.filter(cue => !known.has(cue.clip.index)).map(cue => ({ index: cue.clip.index, name: cue.clip.name, durationSeconds: null }))
  return missing.length ? [...clips, ...missing] : clips
}
