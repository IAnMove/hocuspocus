import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { createUploadSession } from '../asset-picker/upload'
import { WORLD_BEAM_KINDS, WORLD_SFX_KINDS, createWorldSfx, parseWorldSfx, type WorldSfx, type WorldSfxKind } from './world'
import type { WorldSfxDemoId } from './worldDemo'

export function WorldSfxControls({ cues = [], duration, selectedId, disabled, onChange, onSelect, onDemo }: {
  cues?: WorldSfx[]
  duration: number
  selectedId?: string
  disabled?: boolean
  onChange: (cues: WorldSfx[]) => void
  onSelect: (id: string) => void
  onDemo: (id: WorldSfxDemoId) => void
}) {
  const { t } = useUiTranslation('sceneFx')
  const cuesRef = useRef(cues)
  const upload = useRef(createUploadSession())
  const [mediaError, setMediaError] = useState('')
  useEffect(() => {
    cuesRef.current = cues
  }, [cues])
  useEffect(() => () => upload.current.abort(), [])
  const update = (id: string, patch: Partial<WorldSfx>) => onChange(parseWorldSfx(cues.map(cue => cue.id === id ? { ...cue, ...patch } : cue)))
  const assignPortalMedia = (id: string, file?: File) => {
    if (!file) return
    setMediaError('')
    void upload.current.run(file).then(uploaded => {
      onChange(parseWorldSfx(cuesRef.current.map(cue => cue.id === id ? { ...cue, sourceUrl: uploaded.url } : cue)))
    }).catch(error => {
      if (error instanceof DOMException && error.name === 'AbortError') return
      setMediaError(t('worldMediaFailed'))
    })
  }
  const setAxis = (id: string, field: 'position' | 'rotation', axis: 'x' | 'y' | 'z', value: number) => {
    const cue = cues.find(item => item.id === id)
    if (!cue || !Number.isFinite(value)) return
    update(id, { [field]: { ...cue[field], [axis]: value } })
  }
  return <div className="space-y-2 rounded-lg border border-violet-400/30 bg-bg-primary p-3" data-testid="world-sfx-controls">
    <div className="flex flex-wrap gap-2">
      {(['depth', 'duel', 'mixed'] as const).map(id => <button key={id} type="button" data-testid={`world-sfx-demo-${id}`} disabled={disabled} onClick={() => onDemo(id)} className="min-h-10 rounded border border-cyan-400/40 px-3 text-xs disabled:opacity-50">{t(`worldDemo.${id}`)}</button>)}
    </div>
  <details>
    <summary className="cursor-pointer text-sm font-semibold">{t('worldTitle')} ({cues.length})</summary>
    <p className="my-2 text-xs text-text-muted">{t('worldHelp')}</p>
    <fieldset disabled={disabled} className="space-y-3 disabled:opacity-50">
      {cues.map(cue => <div key={cue.id} className={`space-y-2 rounded border p-2 ${selectedId === cue.id ? 'border-violet-300 bg-violet-400/5' : 'border-border'}`}>
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="min-h-9 rounded border border-border px-2 text-xs" onClick={() => onSelect(cue.id)}>{t('select')}</button>
          <label>{t('effect')}<select value={cue.kind} onChange={e => update(cue.id, { kind: e.target.value as WorldSfxKind, color: undefined })} className="ml-2 rounded border border-border bg-bg-tertiary p-2">
            {WORLD_SFX_KINDS.map(kind => <option key={kind} value={kind}>{t(`presets.${kind}`)}</option>)}
          </select></label>
          <label>{t('color')}<input type="color" value={cue.color} onChange={e => update(cue.id, { color: e.target.value })} /></label>
          <label><input type="checkbox" checked={cue.sound} onChange={e => update(cue.id, { sound: e.target.checked })} /> {t('sound')}</label>
        {cue.kind === 'media_portal' && <>
          <label className="text-xs">{t('worldMedia')}<input value={cue.sourceUrl ?? ''} placeholder={t('worldMediaHelp')}
            onChange={e => update(cue.id, { sourceUrl: e.target.value.trim() || undefined })}
            className="ml-2 min-h-9 min-w-[12rem] rounded border border-border bg-bg-tertiary px-2" /></label>
          <input type="file" accept="image/*,video/*" aria-label={t('worldMedia')} disabled={disabled}
            onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; assignPortalMedia(cue.id, file) }} />
          {mediaError && <p role="alert" className="text-xs text-red-300">{mediaError}</p>}
        </>}
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {(['start', 'end', 'scale', 'intensity', 'volume', 'seed'] as const).map(key => <label key={key} className="text-xs">{t(key === 'scale' ? 'worldScale' : key)}<input type="number" value={cue[key]} min={key === 'end' ? cue.start + 0.1 : key === 'scale' ? 0.05 : 0} step={key === 'seed' ? 1 : 0.1} onChange={e => {
            const value = e.target.valueAsNumber
            if (Number.isFinite(value) && (key !== 'start' || value < cue.end) && (key !== 'end' || value > cue.start)) update(cue.id, { [key]: value })
          }} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>)}
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(['x', 'y', 'z'] as const).map(axis => <label key={axis} className="text-xs">{t('worldPosition')} {axis.toUpperCase()}<input type="number" step="0.05" value={cue.position[axis]} onChange={e => setAxis(cue.id, 'position', axis, e.target.valueAsNumber)} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>)}
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(['x', 'y', 'z'] as const).map(axis => <label key={axis} className="text-xs">{t('worldRotation')} {axis.toUpperCase()}<input type="number" step="5" value={cue.rotation[axis]} onChange={e => setAxis(cue.id, 'rotation', axis, e.target.valueAsNumber)} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>)}
        </div>
        <label className="text-xs">{t('anchor')}<input value={cue.anchor?.slotId ?? ''} placeholder={t('anchorNone')} onChange={e => update(cue.id, { anchor: e.target.value.trim() ? { slotId: e.target.value.trim(), offset: cue.anchor?.offset } : undefined })} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>
        {WORLD_BEAM_KINDS.has(cue.kind) && <>
          <label className="text-xs">{t('worldTarget')}<input value={cue.target?.slotId ?? ''} placeholder={t('anchorNone')} onChange={e => update(cue.id, { target: e.target.value.trim() ? { slotId: e.target.value.trim(), offset: cue.target?.offset } : undefined })} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>
          <div className="grid grid-cols-3 gap-2">
            {(['x', 'y', 'z'] as const).map(axis => <label key={axis} className="text-xs">{t('worldTargetPosition')} {axis.toUpperCase()}<input type="number" step="0.05" value={cue.targetPosition?.[axis] ?? 0} onChange={e => {
              const value = e.target.valueAsNumber
              if (!Number.isFinite(value)) return
              update(cue.id, { targetPosition: { x: cue.targetPosition?.x ?? 0, y: cue.targetPosition?.y ?? 0, z: cue.targetPosition?.z ?? 0, [axis]: value } })
            }} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>)}
          </div>
        </>}
        <button type="button" onClick={() => onChange(cues.filter(item => item.id !== cue.id))} className="min-h-9 text-xs text-red-300">{t('remove')}</button>
      </div>)}
      <div className="flex flex-wrap gap-2">
        {WORLD_SFX_KINDS.map(kind => <button key={kind} type="button" disabled={cues.length >= 64} onClick={() => onChange([...cues, createWorldSfx(kind, duration, cues.map(cue => cue.id))])} className="min-h-10 rounded border border-violet-400/40 px-3 text-xs">{t('addWorld')} · {t(`presets.${kind}`)}</button>)}
      </div>
    </fieldset>
  </details>
  </div>
}
