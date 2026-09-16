import { useState, type KeyboardEvent } from 'react'
import { Loader2, Play, Sparkles, TriangleAlert, Wrench } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { VIDEOJS_LIMITS } from './document.ts'
import { VIDEOJS_TRANSITIONS, type VideoJsScene, type VideoJsSceneError } from './types.ts'

interface SceneEditorProps {
  scene: VideoJsScene
  isFirst: boolean
  error: VideoJsSceneError | null
  locked: boolean
  llmBusy: boolean
  onPatch: (patch: Partial<VideoJsScene>) => void
  onAdjust: (instruction: string) => void
  onFix: (error: VideoJsSceneError) => void
}

const field = 'min-h-9 rounded-lg border border-border bg-bg-primary px-2 text-sm text-text-primary disabled:opacity-50'

function insertIndent(event: KeyboardEvent<HTMLTextAreaElement>, update: (value: string) => void) {
  const target = event.currentTarget
  const { selectionStart, selectionEnd, value } = target
  event.preventDefault()
  update(`${value.slice(0, selectionStart)}  ${value.slice(selectionEnd)}`)
  window.requestAnimationFrame(() => target.setSelectionRange(selectionStart + 2, selectionStart + 2))
}

function SceneErrorBox({ error, disabled, busy, onFix }: { error: VideoJsSceneError; disabled: boolean; busy: boolean; onFix: () => void }) {
  const { t } = useUiTranslation('videojs')
  return (
    <div role="alert" className="flex flex-wrap items-start gap-3 rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-xs text-red-100" data-testid="videojs-scene-error">
      <TriangleAlert size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{t(`errors.${error.phase}`)}{error.line ? ` · ${t('editor.line', { line: error.line })}` : ''}</p>
        <p className="mt-1 break-words font-mono">{error.message}</p>
      </div>
      <button type="button" disabled={disabled} onClick={onFix} className="inline-flex min-h-9 items-center gap-2 rounded-md bg-red-200 px-3 font-semibold text-red-950 disabled:opacity-50">
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Wrench size={14} />}{t('editor.fix')}
      </button>
    </div>
  )
}

export function VideoJsSceneEditor({ scene, isFirst, error, locked, llmBusy, onPatch, onAdjust, onFix }: SceneEditorProps) {
  const { t } = useUiTranslation('videojs')
  const [draft, setDraft] = useState(scene.code)
  const [source, setSource] = useState(scene.code)
  const [instruction, setInstruction] = useState('')
  // Code replaced from outside (LLM, undo, import) resets the local draft.
  if (scene.code !== source) {
    setSource(scene.code)
    setDraft(scene.code)
  }
  const dirty = draft !== scene.code
  const run = () => { if (dirty) onPatch({ code: draft }) }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); run() }
    else if (event.key === 'Tab' && !event.shiftKey) insertIndent(event, setDraft)
  }
  const adjust = () => {
    if (!instruction.trim()) return
    onAdjust(instruction.trim())
    setInstruction('')
  }
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-bg-secondary p-3" aria-label={t('editor.region')} data-testid="videojs-scene-editor">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-[1fr_auto_auto_auto_auto]">
        <label className="col-span-2 flex flex-col gap-1 text-xs text-text-muted md:col-span-1">{t('editor.sceneTitle')}
          <input className={field} value={scene.title} disabled={locked} maxLength={120} onChange={event => onPatch({ title: event.target.value })} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-muted">{t('editor.kind')}
          <select className={field} value={scene.kind} disabled={locked} onChange={event => onPatch({ kind: event.target.value as VideoJsScene['kind'] })}>
            <option value="2d">2D</option><option value="3d">3D</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-muted">{t('editor.duration')}
          <input className={`${field} w-24`} type="number" min={VIDEOJS_LIMITS.minSceneSeconds} max={VIDEOJS_LIMITS.maxSceneSeconds} step={0.5} value={scene.duration} disabled={locked}
            onChange={event => onPatch({ duration: Number(event.target.value) })} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-muted">{t('editor.transition')}
          <select className={field} value={scene.transition} disabled={locked || isFirst} onChange={event => onPatch({ transition: event.target.value as VideoJsScene['transition'] })}>
            {VIDEOJS_TRANSITIONS.map(name => <option key={name} value={name}>{t(`transitions.${name}`)}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-muted">{t('editor.transitionDuration')}
          <input className={`${field} w-24`} type="number" min={0} max={VIDEOJS_LIMITS.maxTransitionSeconds} step={0.1} value={scene.transitionDuration} disabled={locked || isFirst || scene.transition === 'none'}
            onChange={event => onPatch({ transitionDuration: Number(event.target.value) })} />
        </label>
      </div>
      {error && <SceneErrorBox error={error} disabled={locked || llmBusy} busy={llmBusy} onFix={() => onFix(error)} />}
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
          <span>{t('editor.code')}</span>
          {dirty && <span className="text-amber-300">{t('editor.unsaved')}</span>}
          <button type="button" disabled={locked || !dirty} onClick={run} className="ml-auto inline-flex min-h-8 items-center gap-1 rounded-md bg-accent-blue px-3 font-semibold text-white disabled:opacity-40">
            <Play size={13} />{t('editor.run')}
          </button>
        </div>
        <textarea value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={onKeyDown} disabled={locked} spellCheck={false} wrap="off"
          aria-label={t('editor.code')} maxLength={VIDEOJS_LIMITS.codeChars} rows={18} data-testid="videojs-code"
          className="w-full resize-y rounded-lg border border-border bg-[#0b0f19] p-3 font-mono text-xs leading-5 text-slate-100 disabled:opacity-60" />
      </div>
      <div className="flex flex-wrap gap-2">
        <input value={instruction} onChange={event => setInstruction(event.target.value)} disabled={locked || llmBusy} placeholder={t('editor.adjustPlaceholder')}
          aria-label={t('editor.adjustLabel')} onKeyDown={event => { if (event.key === 'Enter') adjust() }} className={`${field} min-w-60 flex-1`} />
        <button type="button" disabled={locked || llmBusy || !instruction.trim()} onClick={adjust} className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-accent-blue/60 px-3 text-xs font-semibold text-text-primary hover:bg-accent-blue/10 disabled:opacity-40">
          {llmBusy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}{t('editor.adjust')}
        </button>
      </div>
    </section>
  )
}
