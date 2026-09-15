import { CinematicControls, AppearanceControls } from './CinematicControls'
import { useSceneDocumentHandoff } from '../sceneFx/handoff'
import { SceneFxControls } from '../sceneFx/SceneFxControls'
import { SceneFxOverlay } from '../sceneFx/SceneFxOverlay'
import { adoptPreparedSceneDocument, withFxShowcase } from '../sceneFx/showcase'
import { WorldSfxControls } from '../sceneFx/WorldSfxControls'
import { worldSfxAudioCues } from '../sceneFx/world'
import { worldSfxDemoDocument } from '../sceneFx/worldDemo'
import { WORLD_SFX_SELECT_PREFIX } from './transformGizmo'
import { Scene3DMotionControls } from './Scene3DMotionControls'
import { Scene3DSpeakerControls } from './speech/Scene3DSpeakerControls'
import { Scene3DSpeechStatus } from './speech/Scene3DSpeechStatus'
import { Scene3DSpeechSelector } from './speech/Scene3DSpeechSelector'
import { LipsPickOverlay } from './speech/LipsPickOverlay'
import { defaultSpeech } from './speech/types'
import { speechEnd } from './speech/timeline'
import { useSpeechProfiles } from './speech/useSpeechProfiles'
import { SPEECH_HANDOFF_EVENT, takeSpeechProduction, preserveSpeechDraft } from './speech/production'
import { Scene3DSoundtrackControls } from './speech/Scene3DSoundtrackControls'
import { SceneSpeechAudio } from './speech/preview'
import { Scene3DScreenControls } from './Scene3DScreenControls'
import { defaultMediaScreen } from './mediaScreen'
import { Scene3DFramingControls } from './Scene3DFramingControls'
import { KineticTextControls } from '../../components/common/KineticTextControls'
import { KineticTextOverlay } from '../../components/common/KineticTextOverlay'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchOutputs, type ApiOutput } from '../../api/client'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { Scene3DTemplateBrowser } from './Scene3DTemplateBrowser'
import { Scene3DUserTemplates } from './Scene3DUserTemplates'
import { remountUserTemplate, type World3DUserTemplate } from './userTemplates.ts'
import { Scene3DAnimationControls } from './Scene3DAnimationControls'
import { Scene3DDocumentControls } from './Scene3DDocumentControls'
import { Scene3DTransport } from './Scene3DTransport'
import { Scene3DTransformPanel } from './Scene3DTransformPanel'
import { Scene3DInteraction } from './Scene3DInteraction'
import type { TransformMode } from './transformGizmo'
import { clipBindingError, resolveScene3DClip, retainSlotClipCatalogs } from './clips.ts'
import { scene3dFrameCount, scene3dFrameTime, scene3dPlaybackSpeed } from './clock.ts'
import { parseScene3DDocument } from './document.ts'
import { applyScene3DGizmoPatch, createDocumentId, useScene3DHistory } from './documentHistory.ts'
import { SceneObjectInspector } from './SceneObjectInspector.tsx'
import { canMutateWorld3DScene } from './exportLock.ts'
import { exportWorld3DDocument } from './exportFlow.ts'
import { Scene3DStage, type Scene3DStageHandle } from './Scene3DStage.tsx'
import { applyScene3DTemplate, patchScene3DSlot, remountScene3DTemplate, type Scene3DTemplateId } from './templates.ts'
import { commitSlotSourceChoice, pickerOutputFromSlot, type SlotSourceCapture } from './slotSource.ts'
import type { Scene3DCameraFamily, Scene3DClipCatalogEntry, Scene3DDocument, Scene3DLoop, Scene3DSlot } from './types.ts'
import { documentFromWorld3DRequest, listenForWorld3DWorkflow } from './world3dAgent.ts'

const FAMILIES = ['establishment', 'orbit', 'follow', 'pursuit', 'side', 'front', 'chase', 'hood', 'wing', 'product', 'reveal', 'encounter', 'musical'] as const satisfies readonly Scene3DCameraFamily[]

type Props = {
  width: number
  height: number
  initialDocument?: Scene3DDocument
}

function revokeIfBlob(url: string) {
  if (url.startsWith('blob:')) URL.revokeObjectURL(url)
}

function numberField(label: string, value: number, onChange: (value: number) => void, step = 0.05, disabled = false) {
  return (
    <label className="flex items-center gap-1 text-[8px] text-text-muted">
      {label}
      <input
        type="number"
        step={step}
        disabled={disabled}
        value={Number.isFinite(value) ? value : 0}
        onChange={event => {
          const next = Number(event.target.value)
          if (Number.isFinite(next)) onChange(next)
        }}
        className="w-16 rounded border border-border bg-bg-tertiary px-1 py-0.5 text-[9px] text-text-primary disabled:opacity-40"
      />
    </label>
  )
}

export function Scene3DWorkspace({ width, height, initialDocument }: Props) {
  const { t } = useUiTranslation('scene3d')
  const { t: editorT } = useUiTranslation('scene3dEditor')
  const workspace = useStore(s => s.activeWorkspace)
  const [transformMode, setTransformMode] = useState<TransformMode>('translate')
  const [keepAssets, setKeepAssets] = useState(true)
  const [selectedUserTemplateId, setSelectedUserTemplateId] = useState<string>()
  const [speechOpen, setSpeechOpen] = useState(Boolean(initialDocument?.slots.some(slot => slot.speech)))
  const [pickTarget, setPickTarget] = useState<string>()
  const [playing, setPlaying] = useState(false)
  const [frame, setFrame] = useState(0)
  const [selectedId, setSelectedId] = useState('subject_1')
  const [selectedWorldSfxId, setSelectedWorldSfxId] = useState<string | undefined>()
  const [exporting, setExporting] = useState(false)
  const exportingRef = useRef(false)
  const session = useScene3DHistory(
    initialDocument ? structuredClone(initialDocument) : ({ ...applyScene3DTemplate('two-shot'), width, height }),
    workspace || 'default',
    exporting,
  )
  const sceneDoc = session.document
  const applyHistory = session.apply
  const applyScene = useCallback((updater: Scene3DDocument | ((current: Scene3DDocument) => Scene3DDocument), group?: string) => {
    if (!canMutateWorld3DScene(exportingRef.current)) return
    applyHistory(updater, group)
  }, [applyHistory])
  const selectSlot = (id: string) => {
    setPickTarget(undefined)
    setSelectedWorldSfxId(undefined)
    setSelectedId(id)
  }
  const frameRef = useRef(0)
  const sceneDocRef = useRef(sceneDoc)
  const [catalogs, setCatalogs] = useState<Record<string, Scene3DClipCatalogEntry[]>>({})
  const [modelItems, setModelItems] = useState<ApiOutput[]>([])
  const [imageItems, setImageItems] = useState<ApiOutput[]>([])
  const [videoItems, setVideoItems] = useState<ApiOutput[]>([])
  const [screenTargets, setScreenTargets] = useState<Record<string, { meshes: string[]; nodes: string[] }>>({})
  const [exportNote, setExportNote] = useState<string | null>(null)
  const generationRef = useRef(0)
  const workspaceRef = useRef('')
  const stageRef = useRef<Scene3DStageHandle>(null)
  const exportAbortRef = useRef<AbortController | null>(null)
  const fps = sceneDoc.fps
  const speed = scene3dPlaybackSpeed(sceneDoc.playbackSpeed)
  const count = scene3dFrameCount(sceneDoc.duration, fps)
  const seconds = scene3dFrameTime(frame, sceneDoc.duration, fps)
  const selected = sceneDoc.slots.find(slot => slot.id === selectedId) ?? sceneDoc.slots[0]
  const editingLocked = exporting || playing
  useSceneDocumentHandoff('3d', raw => {
    if (exportingRef.current || playing) throw new Error('Stop playback/export before replacing the scene.')
    const next = parseScene3DDocument(raw)
    if (!next) throw new Error('Invalid prepared 3D document.')
    const adopted = adoptPreparedSceneDocument(sceneDocRef.current, next)
    if (adopted.mode === 'retain') {
      applyScene(adopted.document)
      return
    }
    sessionStorage.setItem('hocuspocus:scene-before-command:' + Date.now(), JSON.stringify(sceneDocRef.current))
    generationRef.current += 1; applyScene(adopted.document); setFrame(0)
    selectSlot(adopted.document.slots[0]?.id ?? 'subject_1'); setSpeechOpen(adopted.document.slots.some(slot => Boolean(slot.speech)))
  })
  const speechVisible = speechOpen && selected?.media === 'model3d'

  useEffect(() => {
    frameRef.current = frame
  }, [frame])

  useEffect(() => {
    sceneDocRef.current = sceneDoc
  }, [sceneDoc])

  const setExportingFlag = (value: boolean) => {
    exportingRef.current = value
    setExporting(value)
  }

  useEffect(() => {
    const host = window as Window & { __world3dStage?: Scene3DStageHandle | null }
    host.__world3dStage = stageRef.current
    return () => { host.__world3dStage = null }
  })

  useEffect(() => () => {
    for (const slot of sceneDocRef.current.slots) revokeIfBlob(slot.sourceUrl)
  }, [])

  useEffect(() => listenForWorld3DWorkflow(async request => {
    if (!canMutateWorld3DScene(exportingRef.current)) {
      throw new Error('world3d-export-in-progress')
    }
    const next = documentFromWorld3DRequest(request)
    setSpeechOpen(request.templateId.startsWith('speech-'))
    generationRef.current += 1
    applyScene(next)
    setFrame(0)
    return { message: next.templateId, templateId: request.templateId, slotIds: next.slots.map(slot => slot.id) }
  }), [applyScene])

  const clipIssue = useMemo(() => {
    for (const slot of sceneDoc.slots) {
      const entries = catalogs[slot.id]
      if (!slot.clip || entries == null) continue
      const error = clipBindingError(resolveScene3DClip(entries, slot.clip))
      if (error) return `${slot.slot}: ${error.message}`
    }
    return null
  }, [catalogs, sceneDoc.slots])

  useEffect(() => {
    if (!playing) return
    let raf = 0
    const origin = performance.now()
    const originFrame = frameRef.current
    const tick = () => {
      const elapsed = scene3dFrameTime(originFrame, sceneDoc.duration, fps) + (performance.now() - origin) / 1000 * speed
      const wrapped = elapsed % Math.max(sceneDoc.duration, 0.001)
      const next = Math.min(count - 1, Math.round(wrapped * fps))
      setFrame(current => (current === next ? current : next))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, sceneDoc.duration, fps, count, speed])

  useEffect(() => {
    if (workspaceRef.current && workspaceRef.current !== workspace) generationRef.current += 1
    workspaceRef.current = workspace
  }, [workspace])

  useEffect(() => {
    let alive = true
    Promise.all([
      fetchOutputs(200, 0, { mediaType: 'model3d', workspace }),
      fetchOutputs(200, 0, { mediaType: 'image', workspace }),
      fetchOutputs(200, 0, { mediaType: 'video', workspace }),
    ]).then(([models, images, videos]) => {
      if (!alive) return
      setModelItems(models.outputs.filter(item => item.type === 'model3d' && /\.glb$/i.test(item.name)))
      setImageItems(images.outputs.filter(item => item.type === 'image'))
      setVideoItems(videos.outputs.filter(item => item.type === 'video'))
    }).catch(() => {
      if (!alive) return
      setModelItems([])
      setImageItems([])
      setVideoItems([])
    })
    return () => { alive = false }
  }, [workspace])

  const assignChoice = (slot: Scene3DSlot, capture: SlotSourceCapture, item: ApiOutput | null) => {
    const commit = commitSlotSourceChoice({
      generation: generationRef.current,
      slotId: slot.id,
      templateId: sceneDocRef.current.templateId,
      workspaceId: workspaceRef.current || workspace,
      exporting: exportingRef.current,
    }, capture, item)
    if (commit.action === 'ignore') return
    if (!canMutateWorld3DScene(exportingRef.current)) return
    if (commit.action === 'clear') {
      revokeIfBlob(slot.sourceUrl)
      applyScene(current => patchScene3DSlot(current, slot.id, { sourceUrl: '', sourceRef: undefined, clip: null, speech: undefined }))
      setCatalogs(current => {
        const next = { ...current }
        delete next[slot.id]
        return next
      })
      return
    }
    revokeIfBlob(slot.sourceUrl)
    applyScene(current => patchScene3DSlot(current, slot.id, {
      sourceUrl: commit.sourceUrl,
      sourceRef: commit.sourceRef,
      speech: slot.speech ? { ...slot.speech, face: undefined, atlas: undefined } : undefined,
      media: commit.media,
      clip: commit.clip,
    }))
    setCatalogs(current => {
      const next = { ...current }
      delete next[slot.id]
      return next
    })
  }

  useSpeechProfiles(sceneDoc, workspace, catalogs, stageRef, applyScene, editingLocked)
  useEffect(() => {
    const receive = () => {
      if (exportingRef.current) return
      try {
        const next = takeSpeechProduction(workspace, sessionStorage, () => preserveSpeechDraft(workspace, sceneDocRef.current))
        if (!next) return
        generationRef.current++
        setPlaying(false); setFrame(0)
        setCatalogs(current => retainSlotClipCatalogs(sceneDocRef.current.slots, next.slots, current))
        setSpeechOpen(true)
        selectSlot(next.slots[0]?.id ?? 'subject_1'); applyScene(next)
      } catch (error) { setExportNote(error instanceof Error ? error.message : String(error)) }
    }
    window.addEventListener(SPEECH_HANDOFF_EVENT, receive); receive()
    return () => window.removeEventListener(SPEECH_HANDOFF_EVENT, receive)
  }, [workspace, exporting, applyScene])

  const adoptMountedScene = (next: Scene3DDocument, userTemplateId?: string) => {
    if (!canMutateWorld3DScene(exportingRef.current)) return
    generationRef.current += 1
    const keptUrls = new Set(next.slots.map(slot => slot.sourceUrl))
    for (const slot of sceneDoc.slots) if (!keptUrls.has(slot.sourceUrl)) revokeIfBlob(slot.sourceUrl)
    if (next.templateId.startsWith('speech-') || next.slots.some(slot => Boolean(slot.speech))) setSpeechOpen(true)
    setPlaying(false)
    applyScene(next)
    setCatalogs(current => retainSlotClipCatalogs(sceneDoc.slots, next.slots, current))
    setFrame(0)
    selectSlot(next.slots.find(slot => slot.media === 'model3d')?.id ?? next.slots[0]?.id ?? 'subject_1')
    setSelectedUserTemplateId(userTemplateId)
  }

  const mountTemplate = (id: Scene3DTemplateId) => {
    adoptMountedScene(remountScene3DTemplate(id, sceneDoc, keepAssets))
  }

  const mountUserTemplate = (pack: World3DUserTemplate) => {
    adoptMountedScene(remountUserTemplate(pack, sceneDoc, keepAssets), pack.id)
  }

  const roundtrip = Boolean(parseScene3DDocument(JSON.parse(JSON.stringify(sceneDoc))))

  const exportScene = async () => {
    const stage = stageRef.current
    if (!stage || exportingRef.current || playing) return
    const target = session.captureForSave()
    const abort = new AbortController()
    exportAbortRef.current = abort
    setExportingFlag(true)
    setExportNote(t('stage.exporting'))
    try {
      const result = await exportWorld3DDocument(stage, target.document, target.identity.workspace, (index, total) => {
        setExportNote(t('stage.exportProgress', { index, total }))
      }, abort.signal)
      ;(window as Window & { __world3dLastMp4?: Blob }).__world3dLastMp4 = result.blob
      if (result.saved) setExportNote(t('stage.exported', { name: result.saved.name }))
      else setExportNote(result.error?.message ?? t('stage.exportFailed'))
    } catch (error) {
      const aborted = abort.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')
      setExportNote(aborted ? t('stage.exportCancelled') : error instanceof Error ? error.message : t('stage.exportFailed'))
    } finally {
      exportAbortRef.current = null
      setExportingFlag(false)
    }
  }

  return (
    <div className="flex w-full flex-col gap-2" data-testid="scene3d-workspace">
      <SceneSpeechAudio document={sceneDoc} seconds={seconds} playing={playing && !exporting} />
      {sceneDoc.production && <p className="rounded-lg border border-border bg-bg-secondary p-3 text-sm" data-testid="speech-production-origin">
        {editorT(`speech.kind.${sceneDoc.production.kind}`)} · {sceneDoc.production.title}
        <span className="mt-1 block text-xs text-text-muted">{editorT('speech.productionReady')}</span>
        <button className="mt-2 underline" disabled={editingLocked} onClick={() => {
          try {
            const raw = sessionStorage.getItem('hocuspocus:world3d-before-speech:' + workspace)
            const previous = raw && parseScene3DDocument(JSON.parse(raw))
            if (!previous) return
            preserveSpeechDraft(workspace, sceneDoc)
            generationRef.current++
            setCatalogs(current => retainSlotClipCatalogs(sceneDoc.slots, previous.slots, current))
            setFrame(0); applyScene(previous)
          } catch (error) { setExportNote(error instanceof Error ? error.message : String(error)) }
        }}>{editorT('speech.previousShot')}</button>
      </p>}
      <Scene3DSpeechStatus document={sceneDoc} seconds={seconds} />
      <Scene3DSoundtrackControls tracks={sceneDoc.soundtrack} disabled={editingLocked}
        onChange={soundtrack => applyScene(current => ({ ...current, soundtrack }))} />
      <details className="rounded-xl border border-border bg-bg-secondary">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-text-primary">{editorT('templates')} · {editorT(`template.${sceneDoc.templateId}.title`)}</summary>
      <Scene3DTemplateBrowser selected={selectedUserTemplateId ? undefined : sceneDoc.templateId} disabled={exporting} onSelect={mountTemplate} />
      <Scene3DUserTemplates document={sceneDoc} disabled={editingLocked} selectedId={selectedUserTemplateId} onApply={mountUserTemplate} />
      <label className="flex min-h-10 items-center gap-2 px-1 text-xs text-text-secondary"><input type="checkbox" checked={keepAssets} disabled={exporting} onChange={event => setKeepAssets(event.target.checked)} />{editorT('keepAssets')}</label>
      </details>
      <Scene3DDocumentControls document={sceneDoc} disabled={editingLocked}
        workspace={workspace} identity={session.identity} preview={() => stageRef.current?.paint(seconds, sceneDoc)?.toDataURL('image/png')}
        onChange={next => { applyScene(next); setFrame(0) }}
        onSaved={(output, document, identity) => session.acknowledgeSave(document, identity, Math.max(identity.revision + 1, Math.trunc(output.created_at) || 0))}
        onLoad={(next, source) => {
          if (!canMutateWorld3DScene(exportingRef.current)) return
          generationRef.current += 1
          const keptUrls = new Set(next.slots.map(slot => slot.sourceUrl))
          for (const slot of sceneDoc.slots) if (!keptUrls.has(slot.sourceUrl)) revokeIfBlob(slot.sourceUrl)
          setCatalogs(current => retainSlotClipCatalogs(sceneDoc.slots, next.slots, current))
          setPlaying(false); setFrame(0)
          session.open(next, source ?? { workspace: workspace || 'default', documentId: createDocumentId(), revision: 0 })
          selectSlot(next.slots[0]?.id ?? 'subject_1')
          setSpeechOpen(next.slots.some(slot => Boolean(slot.speech)))
          setSelectedUserTemplateId(undefined)
        }} />
      <Scene3DSpeechSelector slots={sceneDoc.slots} selected={selected} open={speechOpen}
        onToggle={() => { setPickTarget(undefined); setSpeechOpen(open => !open) }} onSelect={selectSlot} />
      <CinematicControls environment={sceneDoc.environment} disabled={editingLocked} onChange={environment => applyScene(current => ({ ...current, environment }))} />
      <SceneFxControls cues={sceneDoc.sfx} duration={sceneDoc.duration} disabled={editingLocked} onChange={sfx => applyScene(current => ({ ...current, sfx }))} onShowcase={collection => applyScene(current => withFxShowcase(current, collection))} />
      <WorldSfxControls cues={sceneDoc.worldSfx} duration={sceneDoc.duration} selectedId={selectedWorldSfxId} disabled={editingLocked}
        onSelect={id => { setPickTarget(undefined); setSelectedWorldSfxId(id) }}
        onChange={worldSfx => applyScene(current => ({ ...current, worldSfx }))}
        onDemo={id => {
          if (!canMutateWorld3DScene(exportingRef.current)) return
          const demo = worldSfxDemoDocument(id)
          const keptUrls = new Set(demo.slots.map(slot => slot.sourceUrl))
          for (const slot of sceneDoc.slots) if (!keptUrls.has(slot.sourceUrl)) revokeIfBlob(slot.sourceUrl)
          setCatalogs(current => retainSlotClipCatalogs(sceneDoc.slots, demo.slots, current))
          generationRef.current += 1
          setPlaying(false); setFrame(0); applyScene(demo)
          setSelectedId(demo.slots[0]?.id ?? 'subject_1')
          setSelectedWorldSfxId(demo.worldSfx?.[0]?.id)
        }} />
      <KineticTextControls cues={sceneDoc.texts} duration={sceneDoc.duration} disabled={editingLocked} onChange={texts => applyScene(current => ({ ...current, texts }))} />
      <Scene3DTransport playing={playing} disabled={exporting} seconds={seconds} duration={sceneDoc.duration} speed={speed}
        onToggle={() => { if (canMutateWorld3DScene(exportingRef.current)) { setPickTarget(undefined); setPlaying(current => !current) } }}
        onSeek={time => { if (exportingRef.current) return; setPlaying(false); setFrame(Math.min(count - 1, Math.max(0, Math.round(time * fps)))) }}
        onSpeed={playbackSpeed => applyScene(current => ({ ...current, playbackSpeed }))} />
      <div className={`grid items-start gap-3 ${speechVisible ? 'xl:grid-cols-[minmax(0,1fr)_21rem]' : ''}`}>
      <Scene3DInteraction enabled={!playing && !exporting && (Boolean(selectedWorldSfxId) || (Boolean(selected) && selected.media !== 'image'))}
        width={sceneDoc.width} height={sceneDoc.height} onMode={setTransformMode}>
        <Scene3DStage
          ref={stageRef}
          document={sceneDoc}
          sceneSeconds={seconds}
          selectedId={selectedId}
          selectedWorldSfxId={selectedWorldSfxId}
          transformMode={transformMode}
          editing={!playing && !exporting}
          onSelect={id => {
            setPickTarget(undefined)
            if (id.startsWith(WORLD_SFX_SELECT_PREFIX)) { setSelectedWorldSfxId(id.slice(WORLD_SFX_SELECT_PREFIX.length)); return }
            setSelectedWorldSfxId(undefined)
            setSelectedId(id)
          }}
          onTransform={(id, patch) => applyScene(current => applyScene3DGizmoPatch(current, id, patch, seconds), `drag:${id}`)}
          onSlotClips={(slotId, clips) => setCatalogs(current => ({ ...current, [slotId]: clips }))}
          onSlotMeshes={(slotId, meshes, nodes) => setScreenTargets(current => ({ ...current, [slotId]: { meshes, nodes } }))}
        />
        <SceneFxOverlay cues={sceneDoc.sfx} soundCues={[...(sceneDoc.sfx ?? []), ...worldSfxAudioCues(sceneDoc.worldSfx)]} seconds={seconds} width={sceneDoc.width} height={sceneDoc.height} duration={sceneDoc.duration} playing={playing} speed={speed} getSource={() => stageRef.current?.canvas() ?? null} />
        <KineticTextOverlay cues={sceneDoc.texts} seconds={seconds} width={sceneDoc.width} height={sceneDoc.height} />
        {speechVisible && !playing && !exporting && selected && pickTarget === `${generationRef.current}/${selected.id}/${selected.sourceUrl}` &&
          <LipsPickOverlay onCancel={() => setPickTarget(undefined)} onPick={(x, y) => {
            const face = stageRef.current?.pickFace?.(selected.id, x, y, selected.speech?.face)
            if (!face) return false
            applyScene(current => patchScene3DSlot(current, selected.id, {
              speech: { ...defaultSpeech(), ...selected.speech, face, enabled: true, eyes: selected.speech?.face ? selected.speech.eyes : false, clean: selected.speech?.face ? selected.speech.clean : false },
            }))
            setPickTarget(undefined); return true
          }} />}
        {sceneDoc.clipNumber && <div className="pointer-events-none absolute right-3 top-3 z-[901] rounded bg-black/80 px-3 py-2 font-mono text-sm text-cyan-50">CLIP {String(sceneDoc.clipNumber).padStart(2, '0')}</div>}
        <div className="pointer-events-none absolute left-3 top-3 rounded-lg bg-black/75 px-3 py-2 text-xs text-cyan-200">
          {t('stage.badge')} · {editorT(`template.${sceneDoc.templateId}.title`)}
          <span className="mt-1 block text-[10px] text-amber-100/90">{t('stage.previewQuality')}</span>
        </div>
      </Scene3DInteraction>
      <SceneObjectInspector
        document={sceneDoc}
        selectedId={selectedId}
        locked={editingLocked}
        saveState={session.saveState}
        canUndo={session.canUndo}
        canRedo={session.canRedo}
        conflict={session.conflict}
        preview={<p className="p-3 text-xs text-cyan-100">{t('inspector.previewHint')}</p>}
        onChange={(next, group) => applyScene(next, group)}
        onUndo={session.undo}
        onRedo={session.redo}
        onCheckpoint={session.checkpoint}
        onResolveConflict={session.resolveConflict}
      />
      {speechVisible && <div id="world3d-speech-inspector" className="min-w-0 xl:max-h-[38rem] xl:overflow-y-auto">
        <Scene3DSpeakerControls
          key={`${workspace}/${generationRef.current}/${selected.id}/${selected.sourceUrl}`}
          slot={selected} workspace={workspace} disabled={editingLocked}
          onPick={() => { setPlaying(false); setPickTarget(`${generationRef.current}/${selected.id}/${selected.sourceUrl}`) }}
          calibrate={profile => stageRef.current?.facePlacement?.(selected.id, profile)}
          onChange={speech => applyScene(current => current.slots.find(slot => slot.id === selected.id)?.sourceUrl === selected.sourceUrl
            ? patchScene3DSlot(current, selected.id, { speech }) : current)}
          onImport={patch => applyScene(current => current.slots.find(slot => slot.id === selected.id)?.sourceUrl === selected.sourceUrl
            ? patchScene3DSlot(current, selected.id, patch) : current)}
          onFit={duration => applyScene(current => ({ ...current, duration: Math.min(600, Math.max(duration, ...current.slots.map(slot =>
            slot.speech?.enabled ? speechEnd(slot.speech) : 0), ...(current.soundtrack ?? []).map(track => track.end ?? 0))) }))} />
      </div>}
      </div>
      {sceneDoc.dressing === 'workshop' && <label className="flex items-center gap-2 text-xs">{editorT('travel.screen')}<select disabled={exporting} value={sceneDoc.workshopScreen ?? 'code'} onChange={event => applyScene(current => ({ ...current, workshopScreen: event.target.value as 'code' | 'error' | 'success' }))} className="min-h-10 rounded border border-border bg-bg-tertiary px-2">{(['code', 'error', 'success'] as const).map(state => <option key={state} value={state}>{editorT(`travel.${state}`)}</option>)}</select></label>}
      <Scene3DFramingControls framing={sceneDoc.camera.framing} slots={sceneDoc.slots} disabled={editingLocked} onChange={framing => applyScene(current => ({ ...current, camera: { ...current.camera, framing } }))} />
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-text-primary">{editorT('camera')}
          <select disabled={exporting} value={sceneDoc.camera.family} onChange={event => applyScene(current => ({ ...current, camera: { ...current.camera, family: event.target.value as Scene3DCameraFamily, framing: undefined } }))}
            className="min-h-11 rounded-lg border border-border bg-bg-primary px-3 text-xs disabled:opacity-40">
            {FAMILIES.map(family => <option key={family} value={family}>{t(`stage.family.${family}`)}</option>)}
          </select>
        </label>
        <button
          type="button"
          data-testid="world3d-export"
          disabled={editingLocked || Boolean(clipIssue)}
          onClick={() => void exportScene()}
          className="ml-auto min-h-11 rounded-lg border border-cyan-400/50 bg-cyan-400/10 px-4 text-xs font-semibold text-cyan-100 disabled:opacity-40"
        >
          {exporting ? t('stage.exporting') : t('stage.export')}
        </button>
        {exporting && <button
          type="button"
          data-testid="world3d-export-cancel"
          onClick={() => exportAbortRef.current?.abort()}
          className="min-h-11 rounded-lg border border-amber-400/50 bg-amber-400/10 px-4 text-xs font-semibold text-amber-100"
        >{t('stage.exportCancel')}</button>}
      </div>
      <p className="text-xs text-text-muted">{t('stage.exportQualityHint')}</p>
      {selected && !selectedWorldSfxId && <Scene3DTransformPanel slot={selected} mode={transformMode} disabled={editingLocked} onMode={setTransformMode}
        onChange={patch => applyScene(current => patchScene3DSlot(current, selected.id, patch))}
        onReset={() => {
          const pose = applyScene3DTemplate(sceneDoc.templateId).slots.find(slot => slot.id === selected.id)
          if (pose) applyScene(current => patchScene3DSlot(current, selected.id, { position: pose.position, scale: pose.scale, rotationY: pose.rotationY }))
        }} />}
      {selected && selected.media !== 'image' && <Scene3DMotionControls slot={selected} duration={sceneDoc.duration / speed} disabled={editingLocked} onChange={patch => applyScene(current => patchScene3DSlot(current, selected.id, patch))} />}
      <button type="button" disabled={editingLocked || sceneDoc.slots.length >= 64} className="min-h-11 self-start rounded-lg border border-cyan-400/50 px-4 text-sm text-text-primary" onClick={() => {
        if (!canMutateWorld3DScene(exportingRef.current)) return
        const id = `screen_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
        applyScene(current => ({ ...current, slots: [...current.slots, { id, slot: 'prop', media: 'screen', sourceUrl: '', clip: null, position: [0, 0, -2], rotationY: 0, scale: 1, screen: defaultMediaScreen() }] }))
        selectSlot(id)
      }}>{editorT('screens.add')}</button>
      <div className="grid gap-1.5 md:grid-cols-2">
        {sceneDoc.slots.map(slot => {
          const capture: SlotSourceCapture = {
            generation: generationRef.current,
            slotId: slot.id,
            templateId: sceneDoc.templateId,
            workspaceId: workspace,
          }
          return (
            <div key={slot.id} className={`rounded-xl border p-3 text-xs text-text-secondary ${selectedId === slot.id ? 'border-cyan-300 bg-cyan-400/5' : 'border-border bg-bg-primary'}`}>
              <button type="button" className="block min-h-10 font-semibold text-text-primary" onClick={() => selectSlot(slot.id)}>{t(`stage.slot.${slot.slot}`)}</button>
              {slot.media === 'model3d' && <button type="button" className="mb-2 min-h-9 rounded-lg border border-border px-3 text-xs hover:bg-bg-hover"
                onClick={() => {
                  selectSlot(slot.id); setSpeechOpen(true)
                  window.requestAnimationFrame(() => window.document.getElementById('world3d-speech-inspector')?.scrollIntoView({ block: 'nearest' }))
                }}>{editorT('speech.option')}{slot.speech?.enabled ? ' · ✓' : ''}</button>}
              {slot.media !== 'screen' && <div className="mt-1">
                <AssetInput
                  label={t(`stage.slot.${slot.slot}`)}
                  placeholder={t('stage.fromApp')}
                  items={slot.slot === 'background' ? imageItems : modelItems}
                  value={pickerOutputFromSlot(slot.sourceUrl, slot.media, slot.sourceRef)}
                  accept={slot.slot === 'background' ? 'image/*' : '.glb,model/gltf-binary'}
                  optional
                  disabled={exporting}
                  constraints={{
                    kinds: slot.slot === 'background' ? ['image'] : ['model3d'],
                    maxCount: 1,
                    optional: true,
                  }}
                  onChoose={item => assignChoice(slot, capture, item)}
                />
              </div>}
              <Scene3DScreenControls slot={slot} meshes={screenTargets[slot.id]?.meshes ?? []} nodes={screenTargets[slot.id]?.nodes ?? []} items={[...imageItems, ...videoItems]} disabled={editingLocked}
                onChange={screen => applyScene(current => patchScene3DSlot(current, slot.id, { screen }))}
                onChoose={item => {
                  if (item && item.type !== 'image' && item.type !== 'video') return
                  const commit = commitSlotSourceChoice({ generation: generationRef.current, slotId: slot.id, templateId: sceneDocRef.current.templateId, workspaceId: workspaceRef.current || workspace, exporting: exportingRef.current }, capture, item)
                  if (commit.action === 'ignore') return
                  applyScene(current => {
                    const live = current.slots.find(value => value.id === slot.id)
                    if (!live?.screen) return current
                    return patchScene3DSlot(current, slot.id, { screen: { ...live.screen, sourceUrl: commit.action === 'clear' ? '' : commit.sourceUrl,
                      sourceRef: commit.action === 'clear' ? undefined : commit.sourceRef, media: item?.type === 'video' ? 'video' : 'image' } })
                  })
                }}
                onRemove={() => { generationRef.current += 1; applyScene(current => ({ ...current, slots: current.slots.filter(value => value.id !== slot.id), camera: current.camera.framing?.targetSlot === slot.id ? { ...current.camera, framing: undefined } : current.camera })) }} />
              <AppearanceControls slot={slot} disabled={editingLocked} onChange={patch => applyScene(current => patchScene3DSlot(current, slot.id, patch))} />
              <Scene3DAnimationControls slot={slot} clips={catalogs[slot.id]} duration={sceneDoc.duration} disabled={editingLocked}
                onChange={patch => applyScene(current => patchScene3DSlot(current, slot.id, patch))} />
              {slot.slot === 'background' && <label className="my-2 flex min-h-9 items-center gap-2 text-xs"><span>{editorT('travel.surface')}</span><select disabled={exporting} value={slot.surface ?? 'backdrop'} onChange={event => applyScene(current => patchScene3DSlot(current, slot.id, { surface: event.target.value === 'backdrop' ? undefined : event.target.value as 'floor' | 'wall' | 'environment', loop: undefined }))} className="rounded border border-border bg-bg-tertiary p-2"><option value="backdrop">{editorT('travel.backdrop')}</option><option value="environment">{editorT('cinematic.background')}</option><option value="wall">{editorT('travel.wall')}</option><option value="floor">{editorT('travel.floor')}</option></select></label>}
              {slot.slot === 'background' && slot.surface && slot.surface !== 'environment' && numberField(editorT('travel.repeat'), slot.textureRepeat ?? (slot.surface === 'floor' ? 4 : 2), value => applyScene(current => patchScene3DSlot(current, slot.id, { textureRepeat: Math.max(1, Math.min(16, value)) })), 1, exporting)}
              {slot.slot === 'background' && !slot.surface && (
                <InfiniteBackdropControls
                  loop={slot.loop}
                  disabled={exporting}
                  infiniteLabel={t('stage.infinite')}
                  speedLabel={t('stage.loopSpeed')}
                  onChange={loop => applyScene(current => patchScene3DSlot(current, slot.id, {
                    media: 'image',
                    loop,
                    ...(loop.cylinder && slot.scale > 2 ? { scale: 1 } : {}),
                  }))}
                />
              )}
            </div>
          )
        })}
      </div>
      {clipIssue && <p className="text-xs text-red-300">{clipIssue}</p>}
      {exportNote && <p className="text-xs text-cyan-100" data-testid="world3d-export-note">{exportNote}</p>}
      <p className="text-xs text-text-muted">{sceneDoc.templateId === 'run-loop' ? t('stage.runHelp') : t('stage.help')}</p>
      <span data-testid="scene3d-roundtrip" className="hidden">{roundtrip ? 'ok' : 'bad'}</span>
    </div>
  )
}

function InfiniteBackdropControls({
  loop,
  infiniteLabel,
  speedLabel,
  onChange,
  disabled = false,
}: {
  loop: Scene3DLoop | undefined
  infiniteLabel: string
  speedLabel: string
  onChange: (loop: Scene3DLoop) => void
  disabled?: boolean
}) {
  const speed = loop?.speed ?? 0.18
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      <label className="flex items-center gap-1 text-[8px] text-text-muted">
        <input
          type="checkbox"
          data-testid="scene3d-infinite"
          disabled={disabled}
          checked={loop?.cylinder === true}
          onChange={event => onChange({ cylinder: event.target.checked, speed })}
        />
        {infiniteLabel}
      </label>
      {loop?.cylinder === true && numberField(speedLabel, speed, value => onChange({ cylinder: true, speed: value }), 0.01, disabled)}
    </div>
  )
}
