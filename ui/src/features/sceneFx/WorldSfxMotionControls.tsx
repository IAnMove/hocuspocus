import { useUiTranslation } from '../../i18n'
import type { WorldSfx } from './world'
import type { WorldSfxKeyframe } from './worldMotion'

const inputClass = 'mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2'
type Props = { cue: WorldSfx; onChange: (patch: Partial<WorldSfx>) => void }

export function WorldSfxMotionControls({ cue, onChange }: Props) {
  const { t } = useUiTranslation('sceneFx')
  const frames = cue.motion ?? []
  const patchFrame = (index: number, patch: Partial<WorldSfxKeyframe>) => onChange({ motion: frames.map((frame, i) => i === index ? { ...frame, ...patch } : frame) })
  const addFrame = () => {
    const last = frames.at(-1)
    onChange({ motion: [...frames, { time: Math.min(600, (last?.time ?? cue.start) + 0.5), position: last?.position ?? cue.position, rotation: last?.rotation ?? cue.rotation, scale: last?.scale ?? cue.scale, easing: 'smooth' }] })
  }
  return <details className="rounded border border-border p-2">
    <summary className="cursor-pointer text-xs font-semibold">{t('motion.title')} ({frames.length})</summary>
    <p className="my-2 text-xs text-text-muted">{t('motion.help')}</p>
    {cue.anchor && <p className="text-xs text-amber-300">{t('motion.detach')}</p>}
    <fieldset disabled={Boolean(cue.anchor)} className="space-y-2 disabled:opacity-50">
      {frames.map((frame, index) => <div key={index} className="space-y-2 rounded border border-border p-2">
        <div className="grid grid-cols-2 gap-2">
          {(['time', 'scale'] as const).map(field => <label key={field} className="text-xs">{t(`motion.${field}`)}<input className={inputClass} type="number" min="0" max={field === 'time' ? 600 : 64} step="0.05" value={frame[field]} onChange={e => { if (Number.isFinite(e.target.valueAsNumber)) patchFrame(index, { [field]: e.target.valueAsNumber }) }} /></label>)}
        </div>
        {(['position', 'rotation'] as const).map(field => <div key={field} className="grid grid-cols-3 gap-2">
          {(['x', 'y', 'z'] as const).map(axis => <label key={axis} className="text-xs">{t(field === 'position' ? 'worldPosition' : 'worldRotation')} {axis.toUpperCase()}<input type="number" className={inputClass} step={field === 'position' ? '.05' : '15'} value={frame[field][axis]} onChange={e => { if (Number.isFinite(e.target.valueAsNumber)) patchFrame(index, { [field]: { ...frame[field], [axis]: e.target.valueAsNumber } }) }} /></label>)}
        </div>)}
        <label className="text-xs">{t('motion.easing')}<select className={inputClass} value={frame.easing ?? 'smooth'} onChange={e => patchFrame(index, { easing: e.target.value as 'smooth' | 'linear' })}><option value="smooth">{t('motion.smooth')}</option><option value="linear">{t('motion.linear')}</option></select></label>
        <button type="button" className="min-h-9 text-xs text-red-300" onClick={() => onChange({ motion: frames.filter((_, i) => i !== index) })}>{t('remove')}</button>
      </div>)}
      <button type="button" className="min-h-9 rounded border border-violet-400/40 px-3 text-xs" disabled={frames.length >= 32 || frames.at(-1)?.time === 600} onClick={addFrame}>{t('motion.add')}</button>
    </fieldset>
    {frames.length > 0 && <button type="button" className="ml-3 min-h-9 text-xs" onClick={() => onChange({ motion: undefined })}>{t('motion.clear')}</button>}
  </details>
}

export function PortalPlaybackControls({ cue, onChange }: Props) {
  const { t } = useUiTranslation('sceneFx')
  const playback = cue.mediaPlayback ?? { start: 0, speed: 1, loop: true }
  return <details className="rounded border border-border p-2">
    <summary className="cursor-pointer text-xs font-semibold">{t('portalPlayback.title')}</summary>
    <label className="my-2 block text-xs"><input type="checkbox" checked={cue.mediaProjection === 'screen'} onChange={e => onChange({ mediaProjection: e.target.checked ? 'screen' : undefined })} /> {t('portalPlayback.screen')}</label>
    <p className="mb-2 text-xs text-text-muted">{t('portalPlayback.help')}</p>
    <div className="grid grid-cols-2 gap-2">
      {(['start', 'speed'] as const).map(field => <label key={field} className="text-xs">{t(`portalPlayback.${field}`)}<input className={inputClass} type="number" min={field === 'start' ? 0 : .05} step="0.05" value={playback[field]} onChange={e => { if (Number.isFinite(e.target.valueAsNumber)) onChange({ mediaPlayback: { ...playback, [field]: e.target.valueAsNumber } }) }} /></label>)}
    </div>
    <label className="mt-2 block text-xs"><input type="checkbox" checked={playback.loop} onChange={e => onChange({ mediaPlayback: { ...playback, loop: e.target.checked } })} /> {t('portalPlayback.loop')}</label>
  </details>
}
