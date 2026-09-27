import { useState } from 'react'
import { Layers, Loader2, Save, Trash2 } from 'lucide-react'
import { listMontages, saveMontage, type MontageSummary } from '../../api/montages'
import { loadMontageIntoEditor } from './montageLoader'
import { useUiTranslation } from '../../i18n'
import type { EditorSoundtrack, ResolutionOption } from './editorDraft'
import type { EditorClip } from './editorClipNormalization'
import { montageFromEditor, type MontageLayers, type MontageRef } from './montage'

export interface MontageEditorState {
  projectName: string
  resolution: ResolutionOption
  fps: number
  clips: EditorClip[]
  soundtrack: EditorSoundtrack | null
}

interface ToolbarProps {
  workspace: string
  disabled: boolean
  current: () => MontageEditorState
  layers: MontageLayers
  montageRef: MontageRef | null
  onOpen: (state: MontageEditorState, layers: MontageLayers, ref: MontageRef) => void
  onSaved: (ref: MontageRef) => void
  onError: (message: string | null) => void
}

const button = 'flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-bg-secondary hover:bg-bg-hover disabled:opacity-50'

/** Open and save editable montages (<name>.montage.json) stored in the workspace. */
export function MontageToolbar({ workspace, disabled, current, layers, montageRef, onOpen, onSaved, onError }: ToolbarProps) {
  const { t } = useUiTranslation('videoEditor')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [items, setItems] = useState<MontageSummary[] | null>(null)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (!next) return
    try { setItems(await listMontages(workspace)) } catch (error) { onError((error as Error).message) }
  }
  const openMontage = async (file: string) => {
    setBusy(true)
    onError(null)
    try {
      const loaded = await loadMontageIntoEditor(workspace, file)
      onOpen(loaded.state, loaded.layers, loaded.ref)
      setOpen(false)
    } catch (error) { onError((error as Error).message) } finally { setBusy(false) }
  }
  const save = async () => {
    const state = current()
    if (!state.clips.length) return
    setBusy(true)
    onError(null)
    try {
      const montage = montageFromEditor({ ...state, layers, origins: montageRef?.origins, extras: montageRef?.extras, notes: montageRef?.notes })
      const saved = await saveMontage({ workspace, montage, ...(montageRef ? { file: montageRef.file, expected_revision: montageRef.revision } : {}) })
      onSaved({ ...montageRef, file: saved.file, revision: saved.revision, origins: montageRef?.origins ?? {} })
    } catch (error) { onError((error as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="relative flex items-center gap-2">
      <button onClick={() => void toggle()} disabled={disabled || busy} className={button} title={t('montage.openTitle')}>
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Layers size={13} />} {t('montage.open')}
      </button>
      <button onClick={() => void save()} disabled={disabled || busy} className={button} title={montageRef ? t('montage.saveAs', { file: montageRef.file }) : t('montage.saveTitle')}>
        <Save size={13} /> {t('montage.save')}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-80 max-h-80 overflow-y-auto rounded-lg border border-border bg-bg-secondary p-1 shadow-xl">
          {items === null ? <div className="p-2 text-xs text-text-muted">{t('montage.loading')}</div>
            : !items.length ? <div className="p-2 text-xs text-text-muted">{t('montage.none')}</div>
              : items.map(item => (
                <button key={item.file} onClick={() => void openMontage(item.file)} className="block w-full rounded px-2 py-1.5 text-left text-xs hover:bg-bg-hover">
                  <span className="block font-medium text-text-primary">{item.name}</span>
                  <span className="block text-text-muted">{t('montage.summary', { clips: item.clips, overlays: item.overlays, cues: item.audioCues, revision: item.revision })}</span>
                </button>
              ))}
        </div>
      )}
    </div>
  )
}

interface LayersProps {
  layers: MontageLayers
  disabled: boolean
  onChange: (layers: MontageLayers) => void
}

const numberInput = 'w-16 rounded border border-border bg-bg-tertiary px-1 py-0.5 text-right text-xs'
const round = (value: number) => Math.round(value * 100) / 100

/** Timed overlays (captions/titles) and audio cues (narration) of the open montage. */
export function MontageLayersPanel({ layers, disabled, onChange }: LayersProps) {
  const { t } = useUiTranslation('videoEditor')
  if (!layers.overlays.length && !layers.audioCues.length) return null
  const setOverlay = (id: string, patch: Partial<MontageLayers['overlays'][number]>) =>
    onChange({ ...layers, overlays: layers.overlays.map(item => item.id === id ? { ...item, ...patch } : item) })
  const setCue = (id: string, patch: Partial<MontageLayers['audioCues'][number]>) =>
    onChange({ ...layers, audioCues: layers.audioCues.map(item => item.id === id ? { ...item, ...patch } : item) })
  return (
    <details className="border-b border-border bg-bg-tertiary/30 px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none text-text-secondary">
        {t('montage.layers', { overlays: layers.overlays.length, cues: layers.audioCues.length })}
      </summary>
      <div className="mt-2 grid gap-3 lg:grid-cols-2">
        <div>
          <div className="mb-1 font-medium text-text-primary">{t('montage.overlays')}</div>
          {layers.overlays.map(item => (
            <div key={item.id} className="flex items-center gap-2 py-0.5">
              <span className="min-w-0 flex-1 truncate" title={item.source}>{item.name || item.id}</span>
              <input type="number" step={0.1} min={0} aria-label={t('montage.start')} className={numberInput} disabled={disabled} value={round(item.start)} onChange={event => setOverlay(item.id, { start: Math.max(0, Number(event.target.value)) })} />
              <input type="number" step={0.1} min={0} aria-label={t('montage.end')} className={numberInput} disabled={disabled} value={round(item.end)} onChange={event => setOverlay(item.id, { end: Math.max(item.start + .1, Number(event.target.value)) })} />
              <button aria-label={t('montage.remove')} disabled={disabled} onClick={() => onChange({ ...layers, overlays: layers.overlays.filter(other => other.id !== item.id) })} className="text-text-muted hover:text-red-300"><Trash2 size={12} /></button>
            </div>
          ))}
        </div>
        <div>
          <div className="mb-1 flex items-center gap-2 font-medium text-text-primary">
            {t('montage.audioCues')}
            <label className="ml-auto flex items-center gap-1 font-normal text-text-muted">{t('montage.duck')}
              <input type="range" min={0} max={1} step={0.05} disabled={disabled} value={layers.duck} onChange={event => onChange({ ...layers, duck: Number(event.target.value) })} />
            </label>
          </div>
          {layers.audioCues.map(item => (
            <div key={item.id} className="flex items-center gap-2 py-0.5">
              <span className="min-w-0 flex-1 truncate" title={item.source}>{item.name || item.id}</span>
              <input type="number" step={0.1} min={0} aria-label={t('montage.start')} className={numberInput} disabled={disabled} value={round(item.start)} onChange={event => setCue(item.id, { start: Math.max(0, Number(event.target.value)) })} />
              <input type="number" step={0.05} min={0} max={2} aria-label={t('montage.volume')} className={numberInput} disabled={disabled} value={round(item.volume)} onChange={event => setCue(item.id, { volume: Math.min(2, Math.max(0, Number(event.target.value))) })} />
              <button aria-label={t('montage.remove')} disabled={disabled} onClick={() => onChange({ ...layers, audioCues: layers.audioCues.filter(other => other.id !== item.id) })} className="text-text-muted hover:text-red-300"><Trash2 size={12} /></button>
            </div>
          ))}
        </div>
      </div>
    </details>
  )
}
