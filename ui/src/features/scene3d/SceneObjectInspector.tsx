import { useEffect, useState, type ReactNode } from 'react'
import { useUiTranslation } from '../../i18n'
import { parseSceneFx } from '../sceneFx/types'
import { createWorldSfx, parseWorldSfx } from '../sceneFx/world'
import { defaultMediaScreen } from './mediaScreen'
import { defaultSpeech, type FacePlacement, type Scene3DSpeech } from './speech/types'
import { patchScene3DSlot } from './templates.ts'
import type { Scene3DCameraFamily, Scene3DDocument, Scene3DSlot, Vec3 } from './types.ts'
import type { Scene3DSaveState } from './documentHistory.ts'

const FAMILIES = ['establishment', 'orbit', 'follow', 'pursuit', 'side', 'front', 'chase', 'hood', 'wing', 'product', 'reveal', 'encounter', 'musical'] as const satisfies readonly Scene3DCameraFamily[]

const DEFAULT_FACE: FacePlacement = {
  meshIndex: 0,
  center: [0, 1.5, 0.1],
  size: [0.1, 0.08],
  skin: [0.5, 0.3, 0.2],
  eyes: {
    left: [-0.04, 1.55, 0.1],
    right: [0.04, 1.55, 0.1],
    size: [0.04, 0.02],
    skinLeft: [0.5, 0.3, 0.2],
    skinRight: [0.5, 0.3, 0.2],
  },
}

export type InspectorMode = 'object' | 'scene'

export type SceneObjectInspectorProps = {
  document: Scene3DDocument
  selectedId?: string
  locked: boolean
  saveState: Scene3DSaveState
  canUndo: boolean
  canRedo: boolean
  conflict: Scene3DDocument | null
  preview?: ReactNode
  onChange: (document: Scene3DDocument, group?: string) => void
  onUndo: () => void
  onRedo: () => void
  onCheckpoint: () => void
  onResolveConflict: (choice: 'mine' | 'theirs') => void
}

export function SceneObjectInspector({
  document, selectedId, locked, saveState, canUndo, canRedo, conflict, preview,
  onChange, onUndo, onRedo, onCheckpoint, onResolveConflict,
}: SceneObjectInspectorProps) {
  const { t } = useUiTranslation('scene3d')
  const [mode, setMode] = useState<InspectorMode>('object')
  const [previewOpen, setPreviewOpen] = useState(true)
  const selected = document.slots.find(slot => slot.id === selectedId) ?? document.slots[0]
  useInspectorHistoryKeys(locked, onUndo, onRedo)
  const commit = (next: Scene3DDocument, group?: string) => {
    if (locked) return
    onChange(next, group)
  }
  return (
    <section className="flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-bg-secondary p-3" data-testid="scene3d-inspector">
      <HistoryBar
        saveState={saveState}
        canUndo={canUndo}
        canRedo={canRedo}
        locked={locked}
        onUndo={onUndo}
        onRedo={onRedo}
        onCheckpoint={onCheckpoint}
      />
      {conflict && <ConflictBanner onKeep={() => onResolveConflict('mine')} onLoad={() => onResolveConflict('theirs')} />}
      <div className="flex flex-wrap gap-2">
        <ModeButton id="object" mode={mode} onMode={setMode} label={t('inspector.object')} />
        <ModeButton id="scene" mode={mode} onMode={setMode} label={t('inspector.scene')} />
        <button type="button" className="min-h-11 rounded-lg border border-border px-3 text-xs lg:hidden" data-testid="scene3d-inspector-preview-toggle"
          onClick={() => setPreviewOpen(open => !open)}>
          {previewOpen ? t('inspector.hidePreview') : t('inspector.showPreview')}
        </button>
      </div>
      {previewOpen && (
        <div data-testid="scene3d-inspector-preview" className="min-h-16 overflow-hidden rounded-lg border border-border bg-black/40 lg:hidden">
          {preview ?? <p className="p-3 text-xs text-text-muted">{t('inspector.previewHint')}</p>}
        </div>
      )}
      {mode === 'object'
        ? <ObjectPanel slot={selected} document={document} locked={locked} onChange={commit} />
        : <ScenePanel document={document} locked={locked} onChange={commit} />}
    </section>
  )
}

function HistoryBar({ saveState, canUndo, canRedo, locked, onUndo, onRedo, onCheckpoint }: {
  saveState: Scene3DSaveState; canUndo: boolean; canRedo: boolean; locked: boolean
  onUndo: () => void; onRedo: () => void; onCheckpoint: () => void
}) {
  const { t } = useUiTranslation('scene3d')
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" data-testid="scene3d-history-undo" className="min-h-11 rounded-lg border border-border px-3 text-xs" disabled={locked || !canUndo} onClick={onUndo}>{t('history.undo')}</button>
      <button type="button" data-testid="scene3d-history-redo" className="min-h-11 rounded-lg border border-border px-3 text-xs" disabled={locked || !canRedo} onClick={onRedo}>{t('history.redo')}</button>
      <button type="button" data-testid="scene3d-history-checkpoint" className="min-h-11 rounded-lg border border-border px-3 text-xs" disabled={locked} onClick={onCheckpoint}>{t('history.checkpoint')}</button>
      <p role="status" data-testid="scene3d-save-state" className="text-xs text-text-muted">{t(`history.${saveState}`)}</p>
    </div>
  )
}

function ConflictBanner({ onKeep, onLoad }: { onKeep: () => void; onLoad: () => void }) {
  const { t } = useUiTranslation('scene3d')
  return (
    <div role="alert" data-testid="scene3d-tab-conflict" className="space-y-2 rounded-lg border border-amber-300/50 p-3 text-xs">
      <p>{t('history.conflict')}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="min-h-11 rounded-lg border border-border px-3" onClick={onKeep}>{t('history.keepMine')}</button>
        <button type="button" className="min-h-11 rounded-lg border border-border px-3" onClick={onLoad}>{t('history.takeTheirs')}</button>
      </div>
    </div>
  )
}

function ModeButton({ id, mode, onMode, label }: { id: InspectorMode; mode: InspectorMode; onMode: (mode: InspectorMode) => void; label: string }) {
  return (
    <button type="button" data-testid={`scene3d-inspector-${id}`} aria-pressed={mode === id}
      className={`min-h-11 rounded-lg border px-3 text-xs ${mode === id ? 'border-cyan-300 bg-cyan-300/15' : 'border-border'}`}
      onClick={() => onMode(id)}>{label}</button>
  )
}

function ObjectPanel({ slot, document, locked, onChange }: {
  slot: Scene3DSlot | undefined; document: Scene3DDocument; locked: boolean
  onChange: (document: Scene3DDocument, group?: string) => void
}) {
  const { t } = useUiTranslation('scene3d')
  if (!slot) return <p className="text-xs text-text-muted">{t('inspector.empty')}</p>
  const face = slot.speech?.face
  return (
    <fieldset disabled={locked} className="space-y-3 text-xs disabled:opacity-50" data-testid="scene3d-inspector-object-fields">
      <p className="font-semibold text-text-primary">{slot.id}</p>
      <AxisFields label={t('inspector.position')} values={slot.position} onChange={(position, group) => onChange(patchScene3DSlot(document, slot.id, { position }), group)} group={`pos:${slot.id}`} />
      <label className="flex items-center gap-2">{t('inspector.yaw')}
        <input type="number" step="1" aria-label={t('inspector.yaw')} className={fieldClass} value={Number((slot.rotationY * 180 / Math.PI).toFixed(1))}
          onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) onChange(patchScene3DSlot(document, slot.id, { rotationY: value * Math.PI / 180 }), `yaw:${slot.id}`) }} />
      </label>
      <label className="flex items-center gap-2">{t('inspector.scale')}
        <input type="number" min="0.05" step="0.05" aria-label={t('inspector.scale')} className={fieldClass} value={Number(slot.scale.toFixed(3))}
          onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= 0.05) onChange(patchScene3DSlot(document, slot.id, { scale: Math.min(100, value) }), `scale:${slot.id}`) }} />
      </label>
      <label className="block">{t('inspector.source')}
        <input data-testid="scene3d-inspector-source" aria-label={t('inspector.source')} className={`${fieldClass} mt-1 w-full`} value={slot.sourceUrl}
          onChange={event => onChange(patchScene3DSlot(document, slot.id, { sourceUrl: event.target.value }))} />
      </label>
      <MouthFields slot={slot} face={face} document={document} onChange={onChange} />
      <div className="flex flex-wrap gap-2">
        <button type="button" data-testid="scene3d-inspector-add-screen" className="min-h-11 rounded-lg border border-border px-3" onClick={() => onChange(addScreenToDocument(document, slot))}>{t('inspector.addScreen')}</button>
        <button type="button" data-testid="scene3d-inspector-add-sfx" className="min-h-11 rounded-lg border border-border px-3" onClick={() => onChange(addSfxToDocument(document))}>{t('inspector.addSfx')}</button>
      </div>
      <details data-testid="scene3d-inspector-advanced" className="rounded-lg border border-border p-2">
        <summary className="cursor-pointer font-semibold">{t('inspector.advanced')}</summary>
        <p className="mt-2 text-text-muted">{t('inspector.advancedHint')}</p>
        {slot.screen && <p data-testid="scene3d-inspector-screen-url">{slot.screen.sourceUrl || t('inspector.screenEmpty')}</p>}
      </details>
    </fieldset>
  )
}

function MouthFields({ slot, face, document, onChange }: {
  slot: Scene3DSlot; face: FacePlacement | undefined; document: Scene3DDocument
  onChange: (document: Scene3DDocument, group?: string) => void
}) {
  const { t } = useUiTranslation('scene3d')
  if (!face) {
    return <button type="button" data-testid="scene3d-inspector-add-lips" className="min-h-11 rounded-lg border border-border px-3"
      onClick={() => onChange(patchScene3DSlot(document, slot.id, { speech: withFace(slot.speech, DEFAULT_FACE) }))}>{t('inspector.addLips')}</button>
  }
  return (
    <div className="space-y-2" data-testid="scene3d-inspector-mouth">
      <p className="font-semibold">{t('inspector.mouth')}</p>
      {(['X', 'Y', 'Z'] as const).map((axis, index) => (
        <label key={axis} className="flex items-center gap-2">{t('inspector.mouth')} {axis}
          <input type="number" step="0.001" data-testid={`scene3d-inspector-mouth-${axis.toLowerCase()}`} aria-label={`${t('inspector.mouth')} ${axis}`}
            className={fieldClass} value={Number(face.center[index].toFixed(5))}
            onChange={event => {
              const value = Number(event.target.value)
              if (!Number.isFinite(value)) return
              const center = [...face.center] as [number, number, number]
              center[index] = value
              onChange(patchScene3DSlot(document, slot.id, { speech: withFace(slot.speech, { ...face, center }) }), `mouth:${slot.id}`)
            }} />
        </label>
      ))}
    </div>
  )
}

function ScenePanel({ document, locked, onChange }: {
  document: Scene3DDocument; locked: boolean
  onChange: (document: Scene3DDocument, group?: string) => void
}) {
  const { t } = useUiTranslation('scene3d')
  const environment = document.environment
  return (
    <fieldset disabled={locked} className="space-y-3 text-xs disabled:opacity-50" data-testid="scene3d-inspector-scene-fields">
      <label className="flex items-center gap-2">{t('inspector.camera')}
        <select aria-label={t('inspector.camera')} className={fieldClass} value={document.camera.family}
          onChange={event => onChange({ ...document, camera: { ...document.camera, family: event.target.value as Scene3DCameraFamily, framing: undefined } })}>
          {FAMILIES.map(family => <option key={family} value={family}>{family}</option>)}
        </select>
      </label>
      <AxisFields label={t('inspector.cameraEye')} values={document.camera.eye} onChange={(eye, group) => onChange({ ...document, camera: { ...document.camera, eye } }, group)} group="camera-eye" />
      <AxisFields label={t('inspector.cameraLook')} values={document.camera.look} onChange={(look, group) => onChange({ ...document, camera: { ...document.camera, look } }, group)} group="camera-look" />
      <label className="flex items-center gap-2">{t('inspector.fov')}
        <input type="number" min="10" max="120" step="1" aria-label={t('inspector.fov')} className={fieldClass} value={document.camera.fov}
          onChange={event => { const fov = Number(event.target.value); if (Number.isFinite(fov) && fov > 0 && fov < 180) onChange({ ...document, camera: { ...document.camera, fov } }) }} />
      </label>
      <label className="flex min-h-11 items-center gap-2">
        <input type="checkbox" checked={Boolean(environment)} onChange={event => onChange({ ...document, environment: event.target.checked ? { reflectiveFloor: true, platform: false, bloom: 0.48 } : undefined })} />
        {t('inspector.environment')}
      </label>
      <details data-testid="scene3d-inspector-scene-advanced" className="rounded-lg border border-border p-2">
        <summary className="cursor-pointer font-semibold">{t('inspector.advanced')}</summary>
        {environment && (
          <div className="mt-2 space-y-2">
            <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={environment.reflectiveFloor} onChange={event => onChange({ ...document, environment: { ...environment, reflectiveFloor: event.target.checked } })} />{t('inspector.floor')}</label>
            <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={environment.platform} onChange={event => onChange({ ...document, environment: { ...environment, platform: event.target.checked } })} />{t('inspector.platform')}</label>
            <label className="flex items-center gap-2">{t('inspector.bloom')}
              <input type="number" min="0" max="1.5" step="0.05" aria-label={t('inspector.bloom')} className={fieldClass} value={environment.bloom}
                onChange={event => { const bloom = Number(event.target.value); if (Number.isFinite(bloom)) onChange({ ...document, environment: { ...environment, bloom: Math.max(0, Math.min(1.5, bloom)) } }) }} />
            </label>
          </div>
        )}
        <label className="mt-2 flex items-center gap-2">{t('inspector.light')}
          <input type="color" aria-label={t('inspector.light')} value={document.light.color} onChange={event => onChange({ ...document, light: { ...document.light, color: event.target.value } })} />
        </label>
      </details>
    </fieldset>
  )
}

function AxisFields({ label, values, onChange, group }: {
  label: string; values: Vec3; onChange: (values: Vec3, group?: string) => void; group: string
}) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {(['X', 'Y', 'Z'] as const).map((axis, index) => (
        <label key={axis} className="text-xs">{label} {axis}
          <input type="number" step="0.05" aria-label={`${label} ${axis}`} className={`${fieldClass} mt-1 w-full`} value={Number(values[index].toFixed(3))}
            onChange={event => {
              const value = Number(event.target.value)
              if (!Number.isFinite(value)) return
              const next = [...values] as [number, number, number]
              next[index] = value
              onChange(next, group)
            }} />
        </label>
      ))}
    </div>
  )
}

function useInspectorHistoryKeys(locked: boolean, onUndo: () => void, onRedo: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (locked || !(event.ctrlKey || event.metaKey) || event.altKey) return
      const target = event.target
      if (target instanceof HTMLElement && target.closest('input, textarea, select')) return
      if (event.key === 'z' || event.key === 'Z') {
        event.preventDefault()
        if (event.shiftKey) onRedo()
        else onUndo()
      }
      if (event.key === 'y' || event.key === 'Y') {
        event.preventDefault()
        onRedo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [locked, onUndo, onRedo])
}

function withFace(speech: Scene3DSpeech | undefined, face: FacePlacement): Scene3DSpeech {
  return { ...defaultSpeech(), ...speech, enabled: true, face }
}

function addScreenToDocument(document: Scene3DDocument, slot: Scene3DSlot): Scene3DDocument {
  if (slot.media === 'model3d' || slot.media === 'screen') {
    return patchScene3DSlot(document, slot.id, { media: slot.media === 'model3d' ? slot.media : 'screen', screen: slot.screen ?? defaultMediaScreen() })
  }
  if (document.slots.length >= 64) return document
  const id = `screen_${Date.now().toString(36)}`
  return {
    ...document,
    slots: [...document.slots, {
      id, slot: 'prop', media: 'screen', sourceUrl: '', clip: null,
      position: [0, 0, -2], rotationY: 0, scale: 1, screen: defaultMediaScreen(),
    }],
  }
}

function addSfxToDocument(document: Scene3DDocument): Scene3DDocument {
  const world = createWorldSfx('sparks', document.duration, (document.worldSfx ?? []).map(cue => cue.id))
  const overlay = parseSceneFx([...(document.sfx ?? []), { id: `fx-${Date.now().toString(36)}`, kind: 'sparks', start: 0, end: Math.min(3, document.duration) }])
  return { ...document, worldSfx: parseWorldSfx([...(document.worldSfx ?? []), world]), sfx: overlay }
}

const fieldClass = 'min-h-11 rounded-lg border border-border bg-bg-primary px-2 text-xs text-text-primary'
