import { useUiTranslation } from '../../i18n'
import { parseClipCues } from './clipCues.ts'
import { fitClipPlayback, parseClipPlayback } from './performance.ts'
import { Scene3DClipSequenceControls } from './Scene3DClipSequenceControls.tsx'
import type { Scene3DClipCatalogEntry, Scene3DSlot } from './types.ts'

export function Scene3DAnimationControls({ slot, clips, duration, disabled, onChange }: {
  slot: Scene3DSlot
  clips: Scene3DClipCatalogEntry[] | undefined
  duration: number
  disabled: boolean
  onChange: (patch: Partial<Scene3DSlot>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: stageT } = useUiTranslation('scene3d')
  if (slot.media !== 'model3d' || !slot.sourceUrl) return null
  if (clips == null) return <p role="status" className="mt-2 text-xs text-text-muted">{t('animationsLoading')}</p>
  if (!clips.length) return <p className="mt-2 text-xs text-text-muted">{t('animationsEmpty')}</p>
  const playback = parseClipPlayback(slot.clipPlayback) ?? { speed: 1, start: 0, loop: true }
  const selected = clips.find(clip => clip.index === slot.clip?.index && clip.name === slot.clip.name)
  const fitted = fitClipPlayback(selected?.durationSeconds, duration, playback)
  const sequence = parseClipCues(slot.clips)
  if (sequence) return <div className="mt-3 space-y-2">
    <Scene3DClipSequenceControls slot={slot} clips={clips} duration={duration} disabled={disabled} onChange={onChange} />
  </div>
  return <div className="mt-3 space-y-2">
    <label className="block text-xs font-medium">{t('animation')}
      <select aria-label={`${t('animation')} ${slot.id}`} disabled={disabled}
        className="mt-1 min-h-10 w-full rounded-lg border border-border bg-bg-tertiary px-2 text-xs disabled:opacity-40"
        value={slot.clip ? String(slot.clip.index) : ''}
        onChange={event => {
          const clip = clips.find(item => String(item.index) === event.target.value)
          onChange({ clip: clip ? { index: clip.index, name: clip.name } : null })
        }}>
        <option value="">{stageT('stage.noClip')}</option>
        {clips.map(clip => <option key={clip.index} value={clip.index} disabled={clip.durationSeconds == null}>
          {clip.index}: {clip.name} · {clip.durationSeconds == null ? '?' : clip.durationSeconds.toFixed(2)} s
        </option>)}
      </select>
    </label>
    {slot.clip && <div className="flex flex-wrap items-center gap-3">
      <label className="text-xs">{t('animationSpeed')}
        <input aria-label={`${t('animationSpeed')} ${slot.id}`} type="number" min="0.1" max="4" step="0.1" disabled={disabled} value={playback.speed}
          className="ml-2 min-h-10 w-20 rounded border border-border bg-bg-tertiary px-2"
          onChange={event => onChange({ clipPlayback: parseClipPlayback({ ...playback, speed: event.target.valueAsNumber }) })} />
      </label>
      <label className="text-xs">{t('animationStart')}
        <input aria-label={`${t('animationStart')} ${slot.id}`} type="number" min="0" step="0.1" disabled={disabled} value={playback.start}
          className="ml-2 min-h-10 w-20 rounded border border-border bg-bg-tertiary px-2"
          onChange={event => onChange({ clipPlayback: parseClipPlayback({ ...playback, start: event.target.valueAsNumber }) })} />
      </label>
      <label className="flex min-h-10 items-center gap-2 text-xs"><input type="checkbox" disabled={disabled} checked={playback.loop}
        onChange={event => onChange({ clipPlayback: { ...playback, loop: event.target.checked } })} />{t('animationLoop')}</label>
      <button type="button" disabled={disabled || !fitted} title={t('animationFitHint')}
        className="min-h-10 rounded border border-border px-3 text-xs disabled:opacity-40"
        onClick={() => { if (fitted) onChange({ clipPlayback: fitted }) }}>{t('animationFit')}</button>
    </div>}
    <Scene3DClipSequenceControls slot={slot} clips={clips} duration={duration} disabled={disabled} onChange={onChange} />
  </div>
}
