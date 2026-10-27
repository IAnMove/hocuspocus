import { propSlot, type LibraryProp } from './propLibrary'
import { useDocumentRoundtrip } from './documentRoundtrip'
import { safeSessionStorage, safeStorageGet, safeStorageSet } from '../../lib/safeStorage'
import { isBuiltinScene3DTemplate } from './templateCatalog'
import { useSceneDocumentHandoff } from '../sceneFx/handoff'
import { adoptPreparedSceneDocument, withFxShowcase } from '../sceneFx/showcase'
import { applyWorldSfxDemo } from '../sceneFx/worldDemo'
import { WORLD_SFX_SELECT_PREFIX, type TransformMode } from './transformGizmo'
import { useWalkBake } from './useWalkBake'
import { useSpeechProfiles } from './speech/useSpeechProfiles'
import { SPEECH_HANDOFF_EVENT, takeSpeechProduction, preserveSpeechDraft } from './speech/production'
import { defaultMediaScreen } from './mediaScreen'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { fetchOutputs, type ApiOutput } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { remountUserTemplate, type World3DUserTemplate } from './userTemplates.ts'
import type { ExportReviewInput } from '../render/exportReview.ts'
import type { RenderChoice } from '../render/renderEstimate.ts'
import { clipBindingError, resolveScene3DClip, retainSlotClipCatalogs } from './clips.ts'
import { scene3dFrameCount, scene3dFrameTime, scene3dPlaybackSpeed } from './clock.ts'
import { parseScene3DDocument } from './document.ts'
import { createDocumentId, useScene3DHistory, type Scene3DDocumentRef } from './documentHistory.ts'
import { canMutateWorld3DScene } from './exportLock.ts'
import { applyAssignedSlotSource, exportWorkspaceDocument } from './workspaceMutations.ts'
import type { Scene3DStageHandle } from './Scene3DStage.tsx'
import { applyScene3DTemplate, patchScene3DSlot, remountScene3DTemplate, type Scene3DTemplateId } from './templates.ts'
import type { SlotSourceCapture, SlotSourceLive } from './slotSource.ts'
import type { Scene3DClipCatalogEntry, Scene3DDocument, Scene3DSlot } from './types.ts'
import { documentFromWorld3DRequest, listenForWorld3DDocument, listenForWorld3DWorkflow } from './world3dAgent.ts'
import { Scene3DDesk } from './Scene3DDesk'
import { dispatchAddPicker } from './pickerApply'
import type { AddPickerCategory } from './addPickerCatalog'

type Props = {
  width: number
  height: number
  initialDocument?: Scene3DDocument
  fill?: boolean
  topBarExtra?: ReactNode
}

function revokeIfBlob(url: string) {
  if (url.startsWith('blob:')) URL.revokeObjectURL(url)
}

function seekWorkspaceTime(
  time: number,
  exporting: boolean,
  fps: number,
  count: number,
  setPlaying: (value: boolean) => void,
  setFrame: (value: number) => void,
) {
  if (exporting) return
  setPlaying(false)
  setFrame(Math.min(count - 1, Math.max(0, Math.round(time * fps))))
}

export function Scene3DWorkspace({ width, height, initialDocument, fill = false, topBarExtra }: Props) {
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
  const [picker, setPicker] = useState<{ open: boolean; category: AddPickerCategory }>({ open: false, category: 'all' })
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
  const [receiptReview, setReceiptReview] = useState<ExportReviewInput | null>(null)
  const generationRef = useRef(0)
  const [generation, setGeneration] = useState(0)
  const bumpGeneration = useCallback(() => {
    generationRef.current += 1
    setGeneration(generationRef.current)
  }, [])
  const workspaceRef = useRef('')
  const stageRef = useRef<Scene3DStageHandle>(null)
  const walkBake = useWalkBake(stageRef, sceneDoc, applyScene, { needsSaved: editorT('travel.walkNeedsSaved'), failed: editorT('travel.walkFailed'), timed: editorT('travel.walkTimed') })
  const exportAbortRef = useRef<AbortController | null>(null)
  const renderChoiceRef = useRef<RenderChoice>({ level: 'draft', shutter: 0 })
  const fps = sceneDoc.fps
  const speed = scene3dPlaybackSpeed(sceneDoc.playbackSpeed)
  const count = scene3dFrameCount(sceneDoc.duration, fps)
  const seconds = scene3dFrameTime(frame, sceneDoc.duration, fps)
  const selected = selectedId ? (sceneDoc.slots.find(slot => slot.id === selectedId) ?? sceneDoc.slots[0]) : undefined
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
    safeStorageSet('session', 'hocuspocus:scene-before-command:' + Date.now(), JSON.stringify(sceneDocRef.current))
    bumpGeneration(); applyScene(adopted.document); setFrame(0)
    selectSlot(adopted.document.slots[0]?.id ?? 'subject_1'); setSpeechOpen(adopted.document.slots.some(slot => Boolean(slot.speech)))
  })
  const speechVisible = speechOpen && selected?.media === 'model3d'

  useEffect(() => {
    frameRef.current = frame
  }, [frame])

  useEffect(() => {
    sceneDocRef.current = sceneDoc
    const host = window as Window & { __world3dDocument?: Scene3DDocument }
    host.__world3dDocument = sceneDoc
    return () => { if (host.__world3dDocument === sceneDoc) delete host.__world3dDocument }
  }, [sceneDoc])

  useEffect(() => {
    const host = window as Window & { __world3dApplyDocument?: (raw: unknown) => boolean }
    host.__world3dApplyDocument = raw => {
      const next = parseScene3DDocument(raw)
      if (!next) return false
      applyScene(next)
      return true
    }
    return () => { delete host.__world3dApplyDocument }
  }, [applyScene])

  const setExportingFlag = (value: boolean) => {
    exportingRef.current = value
    setExporting(value)
  }

  useEffect(() => {
    const host = window as Window & { __world3dStage?: Scene3DStageHandle | null }
    host.__world3dStage = stageRef.current
  })
  useEffect(() => () => {
    const host = window as Window & { __world3dStage?: Scene3DStageHandle | null }
    host.__world3dStage = null
  }, [])

  useEffect(() => () => {
    for (const slot of sceneDocRef.current.slots) revokeIfBlob(slot.sourceUrl)
  }, [])

  useEffect(() => listenForWorld3DWorkflow(async request => {
    if (!canMutateWorld3DScene(exportingRef.current)) {
      throw new Error('world3d-export-in-progress')
    }
    const next = documentFromWorld3DRequest(request)
    setSpeechOpen(request.templateId.startsWith('speech-'))
    bumpGeneration()
    applyScene(next)
    setFrame(0)
    return { message: next.templateId, templateId: request.templateId, slotIds: next.slots.map(slot => slot.id) }
  }), [applyScene, bumpGeneration])

  useEffect(() => listenForWorld3DDocument(async request => {
    if (!canMutateWorld3DScene(exportingRef.current)) throw new Error('world3d-export-in-progress')
    const next = parseScene3DDocument(request.document)
    if (!next) throw new Error('invalid_world3d_document')
    bumpGeneration()
    applyScene(next)
    setFrame(0)
    return { message: next.templateId, templateId: next.templateId, slotIds: next.slots.map(slot => slot.id) }
  }), [applyScene, bumpGeneration])

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
    if (workspaceRef.current && workspaceRef.current !== workspace) bumpGeneration()
    workspaceRef.current = workspace
  }, [workspace, bumpGeneration])

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
    applyAssignedSlotSource(
      slot,
      {
        generation: generationRef.current,
        slotId: slot.id,
        templateId: sceneDocRef.current.templateId,
        workspaceId: workspaceRef.current || workspace,
        exporting: exportingRef.current,
      },
      capture,
      item,
      revokeIfBlob,
      updater => applyScene(updater),
      setCatalogs,
    )
  }

  useSpeechProfiles(sceneDoc, workspace, catalogs, stageRef, applyScene, editingLocked)
  useEffect(() => {
    const receive = () => {
      if (exportingRef.current) return
      try {
        const next = takeSpeechProduction(workspace, safeSessionStorage, () => preserveSpeechDraft(workspace, sceneDocRef.current))
        if (!next) return
        bumpGeneration()
        setPlaying(false); setFrame(0)
        setCatalogs(current => retainSlotClipCatalogs(sceneDocRef.current.slots, next.slots, current))
        setSpeechOpen(true)
        selectSlot(next.slots[0]?.id ?? 'subject_1'); applyScene(next)
      } catch (error) { setExportNote(error instanceof Error ? error.message : String(error)) }
    }
    window.addEventListener(SPEECH_HANDOFF_EVENT, receive); receive()
    return () => window.removeEventListener(SPEECH_HANDOFF_EVENT, receive)
  }, [workspace, exporting, applyScene, bumpGeneration])

  const adoptMountedScene = (next: Scene3DDocument, userTemplateId?: string) => {
    if (!canMutateWorld3DScene(exportingRef.current)) return
    bumpGeneration()
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

  const roundtrip = useDocumentRoundtrip(sceneDoc)

  const exportScene = async () => {
    const target = session.captureForSave()
    setReceiptReview(null)
    await exportWorkspaceDocument(
      stageRef.current,
      target.document,
      target.identity.workspace,
      playing,
      exportingRef.current,
      t,
      setExportNote,
      setExportingFlag,
      abort => { exportAbortRef.current = abort },
      renderChoiceRef.current,
      setReceiptReview,
    )
  }

  const loadDocument = (next: Scene3DDocument, source?: Scene3DDocumentRef) => {
    if (!canMutateWorld3DScene(exportingRef.current)) return
    bumpGeneration()
    const keptUrls = new Set(next.slots.map(slot => slot.sourceUrl))
    for (const slot of sceneDoc.slots) if (!keptUrls.has(slot.sourceUrl)) revokeIfBlob(slot.sourceUrl)
    setCatalogs(current => retainSlotClipCatalogs(sceneDoc.slots, next.slots, current))
    setPlaying(false)
    setFrame(0)
    session.open(next, source ?? { workspace: workspace || 'default', documentId: createDocumentId(), revision: 0 })
    selectSlot(next.slots[0]?.id ?? 'subject_1')
    setSpeechOpen(next.slots.some(slot => Boolean(slot.speech)))
    setSelectedUserTemplateId(undefined)
  }
  const acknowledgeSave = (output: ApiOutput, document: Scene3DDocument, identity: Scene3DDocumentRef) => {
    session.acknowledgeSave(document, identity, Math.max(identity.revision + 1, Math.trunc(output.created_at) || 0))
  }
  const onDemo = (id: 'depth' | 'duel' | 'mixed') => {
    if (!canMutateWorld3DScene(exportingRef.current)) return
    const adopted = applyWorldSfxDemo(sceneDoc, id)
    if (adopted.mode === 'replace') adoptMountedScene(adopted.document)
    else applyScene(adopted.document)
    setPlaying(false)
    setFrame(0)
    setSelectedWorldSfxId(adopted.document.worldSfx?.[adopted.mode === 'replace' ? 0 : (sceneDoc.worldSfx?.length ?? 0)]?.id)
  }
  const onShowcase = (collection?: 'all' | 'anime' | 'retro') => {
    applyScene(current => withFxShowcase(current, collection))
  }
  const onPick = (item: Parameters<typeof dispatchAddPicker>[0]) => {
    dispatchAddPicker(item, { applyScene, onDemo, onShowcase })
  }
  const openPicker = (category: AddPickerCategory) => setPicker({ open: true, category })
  const closePicker = () => setPicker(current => ({ ...current, open: false }))
  const addProp = (prop: LibraryProp) => {
    applyScene(current => ({ ...current, slots: [...current.slots, propSlot(prop, workspace, `${prop.id}-${Date.now()}`)] }))
  }
  const addScreen = () => {
    if (!canMutateWorld3DScene(exportingRef.current) || sceneDoc.slots.length >= 64) return
    const id = `screen_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
    applyScene(current => ({
      ...current,
      slots: [...current.slots, { id, slot: 'prop', media: 'screen', sourceUrl: '', clip: null, position: [0, 0, -2] as Scene3DSlot['position'], rotationY: 0, scale: 1, screen: defaultMediaScreen() }],
    }))
    selectSlot(id)
  }
  const removeSelected = () => {
    if (!selected || selected.slot !== 'prop') return
    applyScene(current => ({ ...current, slots: current.slots.filter(slot => slot.id !== selected.id) }))
  }
  const resetSelectedPose = () => {
    if (!selected) return
    const pose = isBuiltinScene3DTemplate(sceneDoc.templateId)
      ? applyScene3DTemplate(sceneDoc.templateId).slots.find(item => item.id === selected.id)
      : undefined
    if (!pose) return
    applyScene(current => patchScene3DSlot(current, selected.id, { position: pose.position, scale: pose.scale, rotationY: pose.rotationY }))
  }
  const onStageSelect = (id: string) => {
    setPickTarget(undefined)
    if (id.startsWith(WORLD_SFX_SELECT_PREFIX)) {
      setSelectedWorldSfxId(id.slice(WORLD_SFX_SELECT_PREFIX.length))
      return
    }
    setSelectedWorldSfxId(undefined)
    setSelectedId(id)
  }
  const seek = (time: number) => seekWorkspaceTime(time, exportingRef.current, fps, count, setPlaying, setFrame)
  const togglePlay = () => {
    if (!canMutateWorld3DScene(exportingRef.current)) return
    setPickTarget(undefined)
    setPlaying(current => !current)
  }
  const onSpeed = (playbackSpeed: number) => applyScene(current => ({ ...current, playbackSpeed }))
  const restorePreviousShot = () => {
    try {
      const raw = safeStorageGet('session', 'hocuspocus:world3d-before-speech:' + workspace)
      const previous = raw && parseScene3DDocument(JSON.parse(raw))
      if (!previous) return
      preserveSpeechDraft(workspace, sceneDoc)
      bumpGeneration()
      setCatalogs(current => retainSlotClipCatalogs(sceneDoc.slots, previous.slots, current))
      setFrame(0)
      applyScene(previous)
    } catch (error) { setExportNote(error instanceof Error ? error.message : String(error)) }
  }
  const liveSource = (): SlotSourceLive => ({
    generation: generationRef.current,
    slotId: selected?.id ?? '',
    templateId: sceneDocRef.current.templateId,
    workspaceId: workspaceRef.current || workspace,
    exporting: exportingRef.current,
  })
  const preview = () => stageRef.current?.paint(seconds, sceneDoc)?.toDataURL('image/png')

  return (
    <Scene3DDesk model={{
      fill, topBarExtra, sceneDoc, editingLocked, exporting, playing, selected, selectedId, selectedWorldSfxId,
      speechVisible, speechOpen, pickTarget, generation, transformMode, seconds, speed, fps, count, workspace,
      session, stageRef, catalogs, modelItems, imageItems, videoItems, screenTargets, keepAssets, selectedUserTemplateId,
      clipIssue, exportNote, receiptReview, roundtrip, pickerOpen: picker.open, pickerCategory: picker.category,
      setKeepAssets, mountTemplate, mountUserTemplate, applyScene, loadDocument, acknowledgeSave, selectSlot,
      setTransformMode, setPlaying, setFrame, setPickTarget, setSelectedWorldSfxId, setCatalogs, setScreenTargets,
      setSpeechOpen, exportScene, abortExport: () => exportAbortRef.current?.abort(), assignChoice, bumpGeneration,
      onExamplesInstalled: () => { if (!exportingRef.current) bumpGeneration() },
      liveSource, walkFor: walkBake.control, onPick, openPicker, closePicker, addProp, addScreen, removeSelected,
      resetSelectedPose, onStageSelect, onDemo, onShowcase, seek, setRenderChoice: choice => { renderChoiceRef.current = choice },
      onSpeed, togglePlay, restorePreviousShot, preview,
    }} />
  )
}
