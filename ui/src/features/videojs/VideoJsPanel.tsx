import { useCallback, useRef, useState } from 'react'
import { Download, FilePlus, FlaskConical, Presentation, Undo2, Upload } from 'lucide-react'
import { generateLlmText } from '../../api/llm'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import {
  VIDEOJS_LIMITS,
  createVideoJsDocument,
  createVideoJsScene,
  duplicateVideoJsScene,
  moveVideoJsScene,
  touchVideoJsDocument,
  updateVideoJsScene,
  videoJsDuration,
  videoJsSceneFocusTime,
  videoJsTimeline,
} from './document.ts'
import { videoJsExampleDocument } from './examples.ts'
import { runVideoJsLlm, type VideoJsLlmRequest } from './llm.ts'
import { downloadVideoJsDocument, readVideoJsFile } from './storage.ts'
import { useVideoJsDocument } from './useVideoJsDocument.ts'
import { useVideoJsSandbox, videoJsExportBlocker } from './useVideoJsSandbox.ts'
import { VideoJsExportBar } from './VideoJsExportBar.tsx'
import { isVideoJsExporting, useVideoJsExport } from './useVideoJsExport.ts'
import { VideoJsPromptCard } from './VideoJsPromptCard.tsx'
import { VideoJsSceneEditor } from './VideoJsSceneEditor.tsx'
import { VideoJsSceneList } from './VideoJsSceneList.tsx'
import { VideoJsStage, type VideoJsStageHandle } from './VideoJsStage.tsx'
import type { VideoJsDocument, VideoJsScene, VideoJsSceneKind } from './types.ts'

const toolButton = 'inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-text-primary hover:bg-bg-hover disabled:opacity-40'

function useLlmActions(document: VideoJsDocument, commit: (next: VideoJsDocument) => void, onCreated: (next: VideoJsDocument) => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async (request: VideoJsLlmRequest) => {
    setBusy(true)
    setError(null)
    try {
      const next = await runVideoJsLlm(document, request, generateLlmText)
      commit(next)
      if (request.mode === 'create') onCreated(next)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally {
      setBusy(false)
    }
  }, [document, commit, onCreated])
  return { busy, error, run }
}

function VideoJsToolbar({ document, locked, canUndo, onUndo, onReplace, onTitle }: {
  document: VideoJsDocument
  locked: boolean
  canUndo: boolean
  onUndo: () => void
  onReplace: (next: VideoJsDocument) => void
  onTitle: (title: string) => void
}) {
  const { t } = useUiTranslation('videojs')
  const fileInput = useRef<HTMLInputElement>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const importFile = async (file: File | undefined) => {
    if (!file) return
    try {
      onReplace(await readVideoJsFile(file))
      setImportError(null)
    } catch (error) {
      setImportError(error instanceof Error ? error.message : String(error))
    }
  }
  return (
    <header className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-xl font-semibold text-text-primary">
            {t('title')}
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/50 bg-amber-400/10 px-2 py-0.5 text-[11px] font-semibold text-amber-200"><FlaskConical size={12} />{t('experimental')}</span>
          </h1>
          <p className="text-sm leading-relaxed text-text-muted">{t('subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={toolButton} disabled={locked || !canUndo} onClick={onUndo}><Undo2 size={14} />{t('toolbar.undo')}</button>
          <button type="button" className={toolButton} disabled={locked} onClick={() => onReplace(createVideoJsDocument({ width: document.width, height: document.height, fps: document.fps }))}><FilePlus size={14} />{t('toolbar.new')}</button>
          <button type="button" className={toolButton} disabled={locked} onClick={() => onReplace(videoJsExampleDocument())}><Presentation size={14} />{t('toolbar.demo')}</button>
          <button type="button" className={toolButton} disabled={locked} onClick={() => fileInput.current?.click()}><Upload size={14} />{t('toolbar.import')}</button>
          <button type="button" className={toolButton} onClick={() => downloadVideoJsDocument(document)}><Download size={14} />{t('toolbar.export')}</button>
          <input ref={fileInput} type="file" accept=".json,application/json" className="hidden" onChange={event => { void importFile(event.target.files?.[0]); event.target.value = '' }} />
        </div>
      </div>
      <label className="flex max-w-xl flex-col gap-1 text-xs text-text-muted">{t('toolbar.videoTitle')}
        <input value={document.title} maxLength={160} disabled={locked} onChange={event => onTitle(event.target.value)}
          className="min-h-9 rounded-lg border border-border bg-bg-primary px-2 text-sm text-text-primary disabled:opacity-50" />
      </label>
      {importError && <p role="alert" className="text-xs text-red-300">{t('toolbar.importFailed', { message: importError })}</p>}
    </header>
  )
}

export function VideoJsPanel() {
  const { t } = useUiTranslation('videojs')
  const workspace = useStore(s => s.activeWorkspace) || 'default'
  const { document, commit, undo, canUndo } = useVideoJsDocument(workspace)
  const { attachHost, sandbox, status, errors, revision, reportFrameErrors, fail, reload } = useVideoJsSandbox(document)
  const exporter = useVideoJsExport(sandbox, document, workspace)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const stage = useRef<VideoJsStageHandle>(null)
  const seekTo = useCallback((seconds: number) => stage.current?.seek(seconds), [])
  const onCreated = useCallback((next: VideoJsDocument) => { setSelectedId(next.scenes[0]?.id ?? null); seekTo(0) }, [seekTo])
  const llm = useLlmActions(document, commit, onCreated)
  const exporting = isVideoJsExporting(exporter.state)
  const locked = exporting || llm.busy
  const selected = document.scenes.find(scene => scene.id === selectedId) ?? document.scenes[0] ?? null
  const selectedError = selected ? errors.find(error => error.sceneId === selected.id) ?? null : null
  const duration = videoJsDuration(document)

  const replace = (next: VideoJsDocument) => { commit(next); setSelectedId(next.scenes[0]?.id ?? null); seekTo(0) }
  const patchScene = (sceneId: string, patch: Partial<VideoJsScene>) => {
    const key = Object.keys(patch).length === 1 && 'title' in patch ? `title:${sceneId}` : null
    commit(current => updateVideoJsScene(current, sceneId, patch), key)
  }
  const addScene = (kind: VideoJsSceneKind) => {
    if (document.scenes.length >= VIDEOJS_LIMITS.scenes) return
    const scene = createVideoJsScene(kind)
    commit(current => touchVideoJsDocument({ ...current, scenes: [...current.scenes, scene] }))
    setSelectedId(scene.id)
    seekTo(duration)
  }
  const selectScene = (sceneId: string) => {
    setSelectedId(sceneId)
    seekTo(videoJsSceneFocusTime(document, sceneId))
  }
  const deleteScene = (sceneId: string) => {
    commit(current => current.scenes.length > 1 ? touchVideoJsDocument({ ...current, scenes: current.scenes.filter(scene => scene.id !== sceneId) }) : current)
  }
  const blocker = videoJsExportBlocker(errors.length, status)
  const blockedReason = blocker ? t(`export.${blocker}`) : null

  return (
    <div className="flex w-full flex-col gap-4" data-testid="videojs-workspace">
      <VideoJsToolbar document={document} locked={locked} canUndo={canUndo} onUndo={undo} onReplace={replace}
        onTitle={title => commit(current => touchVideoJsDocument({ ...current, title }), 'video-title')} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
        <div className="flex min-w-0 flex-col gap-3">
          <VideoJsStage sandbox={sandbox} status={status} revision={revision} width={document.width} height={document.height}
            duration={duration} handle={stage} locked={exporting} onFrameErrors={reportFrameErrors} onCrash={fail} onReload={reload} />
          <VideoJsExportBar state={exporter.state} canExport={!locked && !blockedReason && duration > 0} blockedReason={blockedReason}
            onStart={() => void exporter.start()} onCancel={exporter.cancel} />
        </div>
        <VideoJsPromptCard document={document} locked={exporting} busy={llm.busy} error={llm.error}
          onCreate={request => void llm.run({ mode: 'create', request })}
          onAdjustVideo={instruction => void llm.run({ mode: 'adjust-video', instruction })}
          onFormat={patch => commit(current => touchVideoJsDocument({ ...current, ...patch }))} />
      </div>
      <VideoJsSceneList document={document} selectedId={selected?.id ?? null} errors={errors} locked={locked}
        onSelect={selectScene}
        onAdd={addScene}
        onMove={(sceneId, offset) => commit(current => moveVideoJsScene(current, sceneId, offset))}
        onDuplicate={sceneId => commit(current => duplicateVideoJsScene(current, sceneId))}
        onDelete={deleteScene} />
      {selected && (
        <VideoJsSceneEditor scene={selected} isFirst={selected.id === document.scenes[0]?.id} error={selectedError} locked={locked} llmBusy={llm.busy}
          onPatch={patch => patchScene(selected.id, patch)}
          onAdjust={instruction => void llm.run({ mode: 'adjust-scene', sceneId: selected.id, instruction })}
          onFix={error => void llm.run({ mode: 'fix-scene', sceneId: selected.id, error })} />
      )}
      <p className="text-xs text-text-muted">{t('footer', { scenes: videoJsTimeline(document).length, seconds: duration.toFixed(1) })}</p>
      <div ref={attachHost} className="relative h-0 overflow-hidden" aria-hidden="true" />
    </div>
  )
}
