import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Redo2, Undo2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { RenderQualityPicker } from '../render/RenderQualityPicker'
import { deskBarOverflow } from './deskBar'
import { Scene3DDocumentControls } from './Scene3DDocumentControls'
import type { Scene3DDeskModel } from './scene3dDeskModel'

export function Scene3DDeskTopBar({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3d')
  const { t: desk } = useUiTranslation('scene3dEditor')
  const bar = useRef<HTMLDivElement>(null)
  const width = useBarWidth(bar)
  const hidden = deskBarOverflow(width)
  const history = <DeskHistory model={model} />
  return (
    <div ref={bar} className="flex min-h-8 w-full min-w-0 flex-nowrap items-center gap-1 overflow-hidden">
      <span className="shrink-0 text-xs font-medium text-text-secondary">{t('stage.editorTitle')}</span>
      <Scene3DDocumentControls
        section="library"
        document={model.sceneDoc}
        disabled={model.editingLocked}
        workspace={model.workspace}
        preview={model.preview}
        identity={model.session.identity}
        onChange={next => { model.applyScene(next); model.setFrame(0) }}
        onLoad={model.loadDocument}
        onSaved={model.acknowledgeSave}
        onCheckpoint={model.session.checkpoint}
        checkpointLabel={t('history.checkpoint')}
      />
      {!hidden.includes('history') && <>
        <BarRule />
        {history}
      </>}
      <BarRule />
      <RenderQualityPicker
        width={model.sceneDoc.width}
        height={model.sceneDoc.height}
        fps={model.fps}
        duration={model.sceneDoc.duration}
        disabled={model.exporting}
        capabilitiesUrl="/api/v1/scenes/world3d/export/capabilities"
        onChange={model.setRenderChoice}
      />
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <button
          type="button"
          data-testid="world3d-export"
          disabled={model.editingLocked || Boolean(model.clipIssue)}
          onClick={() => void model.exportScene()}
          className="inline-flex h-8 items-center rounded-lg border border-cyan-400/50 bg-cyan-400/10 px-3 text-xs font-semibold text-cyan-100 disabled:opacity-40"
        >
          {model.exporting ? t('stage.exporting') : t('stage.export')}
        </button>
        {model.exporting && <button
          type="button"
          data-testid="world3d-export-cancel"
          onClick={model.abortExport}
          className="inline-flex h-8 items-center rounded-lg border border-amber-400/50 bg-amber-400/10 px-2 text-xs font-semibold text-amber-100"
        >{t('stage.exportCancel')}</button>}
        {!hidden.includes('expand') && model.topBarExtra}
        {hidden.length > 0 && <MoreMenu label={desk('desk.more')}>
          {hidden.includes('history') && history}
          {hidden.includes('expand') && model.topBarExtra}
        </MoreMenu>}
      </div>
      <p role="status" data-testid="scene3d-save-state" className="sr-only">{t(`history.${model.session.saveState}`)}</p>
    </div>
  )
}

function DeskHistory({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3d')
  const locked = model.editingLocked
  return (
    <div className="flex shrink-0 items-center gap-1">
      <button type="button" data-testid="scene3d-history-undo" aria-label={t('history.undo')} title={t('history.undoHint')} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-text-primary disabled:opacity-40" disabled={locked || !model.session.canUndo} onClick={model.session.undo}><Undo2 size={15} aria-hidden="true" /></button>
      <button type="button" data-testid="scene3d-history-redo" aria-label={t('history.redo')} title={t('history.redoHint')} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-text-primary disabled:opacity-40" disabled={locked || !model.session.canRedo} onClick={model.session.redo}><Redo2 size={15} aria-hidden="true" /></button>
    </div>
  )
}

function BarRule() {
  return <span aria-hidden="true" className="mx-0.5 h-5 w-px shrink-0 bg-border" />
}

function MoreMenu({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return undefined
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  return (
    <div ref={root} className="relative">
      <button type="button" data-testid="scene3d-desk-more" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(value => !value)} className="inline-flex h-8 items-center rounded-lg border border-border px-2 text-xs text-text-primary">{label}</button>
      {open && <div role="menu" className="absolute right-0 top-full z-30 mt-1 flex min-w-44 flex-col gap-1 rounded-lg border border-border bg-bg-primary p-1 shadow-lg">{children}</div>}
    </div>
  )
}

function useBarWidth(bar: RefObject<HTMLDivElement | null>) {
  const [width, setWidth] = useState(1600)
  useEffect(() => {
    const element = bar.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(entries => {
      const next = entries[0]?.contentRect.width
      if (next) setWidth(next)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [bar])
  return width
}
