import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { ParseKeys } from 'i18next'
import { analyzeAudio, cleanCharacterKitFaceOverlay, getFileUrl, uploadImage } from '../../api/client'
import { generateImageAsset } from '../../lib/imageGeneration'
import { generateSceneSpeechClip } from '../../lib/sceneSpeech'
import {
  CHARACTER_FACE_RIG_STATES,
  FACE_RIG_PRESET_ROOT,
  FACE_RIG_STYLE_PRESETS,
  FACE_RIG_TRAIT_CHIPS,
  applyFaceRigMouthPreset,
  assessFaceRigPlacement,
  characterKitPosePrompt,
  classifyCharacterKitAlpha,
  composeCharacterKitLook,
  faceRigAnchorFor,
  faceRigAnchorFromRegion,
  faceRigRegionFromAnchor,
  previewPercentToImagePixel,
  wipeMouthRegion,
  faceRigGenerationRequests,
  faceRigOverlayPreviewStyle,
  faceRigVisemeAt,
  isFaceRigEyeState,
  lockFaceRigEyePlacement,
  lockFaceRigMouthPlacement,
  previewFaceRigDialogue,
  previewFaceRigDialogueFromAudio,
  registerCleanedFaceRigAsset,
  registerGeneratedFaceRigAsset,
  setFaceRigReviewState,
  type FaceRigMouthPresetPack,
  type CharacterKitFaceRigState,
  type FaceRigDialoguePreview,
  type FaceRigDialogueViseme,
} from '../../lib/characterKitFaceRig'
import { registerGeneratedKitPose, registerWipedKitPose, type CharacterFaceAnchor, type CharacterKit, type CharacterKitAsset, type CharacterMouthState } from '../../lib/characterKit'
import { characterKitNextStep, characterKitPoseLabel } from './characterKitGuide'
import { useStore } from '../../stores/useStore'
import i18n, { useUiTranslation } from '../../i18n'

type Props = {
  kit: CharacterKit
  poseId: string
  disabled?: boolean
  onChange: (kit: CharacterKit) => void
  onCommit?: (kit: CharacterKit) => void
  onStatus?: (message: string) => void
}

const PLACEMENT_WARNING_KEYS: Record<string, ParseKeys<'characters'>> = {
  'This overlay sits far from the pose center and may miss the face.': 'faceRig.warnings.farFromCenter',
  'This overlay is unusually small compared with the pose.': 'faceRig.warnings.tooSmall',
  'This eye overlay is larger than a typical eye mask. Scale it down until it only covers the eyes.': 'faceRig.warnings.eyeTooLarge',
  'This mouth overlay is larger than a typical viseme. Scale it down until it sits on the lips.': 'faceRig.warnings.mouthTooLarge',
  'Mouths on a full-body cutout usually sit above the chest. Nudge Down/Up until the overlay covers the lips, then lock all mouths.': 'faceRig.warnings.mouthTooLow',
}

function tCharacters(key: ParseKeys<'characters'>, options?: Record<string, unknown>): string {
  return i18n.t(key, { ns: 'characters', ...options })
}

function assetFor(kit: CharacterKit, state: CharacterKitFaceRigState): CharacterKitAsset | undefined {
  if (state === 'open-eyes') return kit.eyes.open
  if (state === 'blink') return kit.eyes.blink
  return kit.mouth[state as CharacterMouthState]
}

function withAlphaStatus(kit: CharacterKit, state: CharacterKitFaceRigState, alphaStatus: CharacterKitAsset['alphaStatus']): CharacterKit {
  if (state === 'open-eyes') {
    return kit.eyes.open ? { ...kit, eyes: { ...kit.eyes, open: { ...kit.eyes.open, alphaStatus } } } : kit
  }
  if (state === 'blink') {
    return kit.eyes.blink ? { ...kit, eyes: { ...kit.eyes, blink: { ...kit.eyes.blink, alphaStatus } } } : kit
  }
  const current = kit.mouth[state]
  return current ? { ...kit, mouth: { ...kit.mouth, [state]: { ...current, alphaStatus } } } : kit
}

async function inspectSourceAlpha(source: string) {
  const response = await fetch(source)
  if (!response.ok) throw new Error(tCharacters('faceRig.errors.inspectAlpha'))
  const bitmap = await createImageBitmap(await response.blob())
  try {
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width; canvas.height = bitmap.height
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) throw new Error(tCharacters('faceRig.errors.inspectBrowser'))
    context.drawImage(bitmap, 0, 0)
    return classifyCharacterKitAlpha(context.getImageData(0, 0, bitmap.width, bitmap.height).data)
  } finally { bitmap.close() }
}

export function CharacterKitFaceRigPanel({ kit, poseId, disabled = false, onChange, onCommit, onStatus }: Props) {
  const { t } = useUiTranslation('characters')
  const stateLabel = (state: CharacterKitFaceRigState) => t(`faceRig.states.${state}`)
  const imageModel = useStore(state => state.selectedModelPerMode.image || '')
  const speechModel = useStore(state => state.selectedModelPerAudioSubMode.speech ?? 'kugelaudio_0_open')
  const workspace = useStore(state => state.activeWorkspace)
  const [selectedState, setSelectedState] = useState<CharacterKitFaceRigState>('wide')
  const [styleId, setStyleId] = useState<typeof FACE_RIG_STYLE_PRESETS[number]['id']>(FACE_RIG_STYLE_PRESETS[0].id)
  const [traits, setTraits] = useState<string[]>([])
  const [extraNotes, setExtraNotes] = useState(kit.lookNotes ?? '')
  const [busyState, setBusyState] = useState<CharacterKitFaceRigState | 'pack' | 'cleanup' | 'dialogue' | 'pose' | 'wipe' | null>(null)
  const [holdBlink, setHoldBlink] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showOverlay, setShowOverlay] = useState(true)
  const [checkerboard, setCheckerboard] = useState(true)
  const [draftAnchor, setDraftAnchor] = useState<CharacterFaceAnchor>(() => faceRigAnchorFor(kit, poseId, selectedState))
  const [dialogueText, setDialogueText] = useState(() => t('faceRig.tryLine.sample'))
  const [dialoguePreview, setDialoguePreview] = useState<FaceRigDialoguePreview | null>(null)
  const [liveViseme, setLiveViseme] = useState<FaceRigDialogueViseme | undefined>(undefined)
  const [dialogueAudio, setDialogueAudio] = useState<string | null>(null)
  const [presetPacks, setPresetPacks] = useState<FaceRigMouthPresetPack[]>([])
  const [presetId, setPresetId] = useState('')
  const previewRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; origin: CharacterFaceAnchor; mode: 'move' | 'resize' } | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const playTokenRef = useRef(0)
  const dialoguePreviewRef = useRef<FaceRigDialoguePreview | null>(null)
  const savedAnchor = useMemo(() => faceRigAnchorFor(kit, poseId, selectedState), [kit, poseId, selectedState])
  const poseSource = poseId === 'base' ? kit.base?.source : kit.poses[poseId]?.source
  const selectedAsset = assetFor(kit, selectedState)
  const stylePrompt = FACE_RIG_STYLE_PRESETS.find(item => item.id === styleId)?.prompt ?? ''
  const description = composeCharacterKitLook({
    name: kit.name,
    traits: traits.join(', '),
    stylePrompt,
    extra: extraNotes,
  })
  const playbackState: CharacterKitFaceRigState = holdBlink ? 'blink' : (liveViseme?.sourceState ?? selectedState)
  const playbackAsset = playbackState === 'open-eyes'
    ? kit.eyes.open ?? selectedAsset
    : playbackState === 'blink'
      ? kit.eyes.blink ?? selectedAsset
      : kit.mouth[playbackState] ?? selectedAsset
  const playbackAnchor = holdBlink || liveViseme ? faceRigAnchorFor(kit, poseId, playbackState) : draftAnchor
  const draftAnchorRef = useRef(draftAnchor)
  draftAnchorRef.current = draftAnchor
  const poseApproved = Boolean((poseId === 'base' ? kit.base : kit.poses[poseId])?.reviewState === 'approved')
  const placement = useMemo(() => assessFaceRigPlacement(draftAnchor, selectedState), [draftAnchor, selectedState])
  const overlayStyle = useMemo(() => faceRigOverlayPreviewStyle(playbackAnchor), [playbackAnchor])
  const mouthRegion = useMemo(() => faceRigRegionFromAnchor(draftAnchor), [draftAnchor])
  const nextStep = characterKitNextStep(kit, poseId)
  const poseName = characterKitPoseLabel(poseId)
  const dirtyAnchor = JSON.stringify(draftAnchor) !== JSON.stringify(savedAnchor)
  dialoguePreviewRef.current = dialoguePreview

  useEffect(() => {
    setDraftAnchor(savedAnchor)
  }, [savedAnchor, selectedState, poseId, kit.id])
  useEffect(() => {
    let cancelled = false
    void fetch(`${FACE_RIG_PRESET_ROOT}/manifest.json`).then(async response => {
      if (!response.ok) throw new Error('Could not load mouth style packs.')
      const data = await response.json() as { packs?: FaceRigMouthPresetPack[] }
      if (!cancelled) {
        setPresetPacks(Array.isArray(data.packs) ? data.packs : [])
        setPresetId(current => current || data.packs?.[0]?.id || '')
      }
    }).catch(() => { if (!cancelled) setPresetPacks([]) })
    return () => { cancelled = true }
  }, [])

  const requests = useMemo(() => {
    try { return faceRigGenerationRequests(kit, poseId, description) }
    catch { return [] }
  }, [kit, poseId, description])
  const selectedRequest = requests.find(request => request.state === selectedState)

  const generateState = async (current: CharacterKit, state: CharacterKitFaceRigState): Promise<CharacterKit> => {
    const request = faceRigGenerationRequests(current, poseId, description).find(item => item.state === state)!
    const generated = await generateImageAsset(
      'maestro',
      request.prompt,
      imageModel || undefined,
      request.reference,
      'full character, head, body, skin rectangle, opaque background, checkerboard, text, glow, halo, shadow, extra objects',
      { strictReference: true, referenceMode: 'identity', resolution: '1024x1024', aspectRatio: '1:1' },
    )
    const alpha = await inspectSourceAlpha(generated.source).catch(() => ({
      pixelCount: 0, transparentRatio: 0, translucentRatio: 0, opaqueRatio: 0, status: 'unknown' as const,
    }))
    return registerGeneratedFaceRigAsset(current, state, {
      id: generated.id,
      name: `${kit.name} · ${state}`,
      source: generated.source,
      kind: 'overlay',
      alphaStatus: alpha.status,
      reviewState: 'pending',
      prompt: request.prompt,
      model: generated.model || imageModel || undefined,
      workspace,
    }, {
      poseId: request.poseId,
      reference: request.reference,
      prompt: request.prompt,
      provider: generated.provider || 'maestro',
      model: generated.model || imageModel || '',
      jobId: generated.metadata?.jobId,
      taskId: generated.metadata?.taskId,
      rootTaskId: generated.metadata?.rootTaskId,
      alphaMetrics: alpha,
    })
  }

  const persistLook = (next: CharacterKit): CharacterKit => ({ ...next, lookNotes: description })

  const toggleTrait = (trait: string) => {
    setTraits(current => current.includes(trait) ? current.filter(item => item !== trait) : [...current, trait])
  }

  const generatePose = async () => {
    setBusyState('pose'); setError(null)
    try {
      const generated = await generateImageAsset(
        'maestro',
        characterKitPosePrompt(kit, description),
        imageModel || undefined,
        poseSource,
        'background, ground shadow, extra characters, collage, turnaround sheet, text, watermark, frame, border',
        { strictReference: Boolean(poseSource), referenceMode: 'identity', aspectRatio: '2:3' },
      )
      const next = registerGeneratedKitPose(persistLook(kit), poseId || 'base', {
        id: generated.id,
        name: `${kit.name} · pose`,
        source: generated.source,
        kind: 'image',
        alphaStatus: 'unknown',
        reviewState: 'pending',
        prompt: characterKitPosePrompt(kit, description),
        model: generated.model || imageModel || undefined,
        workspace,
      })
      onChange(next)
      onStatus?.(t('faceRig.status.bodyGenerated', { pose: poseName }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.poseFailed'))
    } finally { setBusyState(null) }
  }

  const generateSelected = async () => {
    setBusyState(selectedState); setError(null)
    try {
      const next = await generateState(persistLook(kit), selectedState)
      onChange(next); onStatus?.(t('faceRig.status.statePending', { name: stateLabel(selectedState) }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.generateFailed'))
    } finally { setBusyState(null) }
  }

  const generateMissingPack = async () => {
    setBusyState('pack'); setError(null)
    try {
      let next = persistLook(kit)
      const missing = CHARACTER_FACE_RIG_STATES.filter(state => !assetFor(next, state) || assetFor(next, state)?.reviewState === 'rejected')
      if (!missing.length) throw new Error(t('faceRig.errors.packComplete'))
      for (const state of missing) {
        onStatus?.(t('faceRig.status.generatingState', { name: stateLabel(state) }))
        next = await generateState(next, state)
        onChange(next)
      }
      onStatus?.(t('faceRig.status.packGenerated', { count: missing.length }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.packFailed'))
    } finally { setBusyState(null) }
  }

  const cleanSelected = async () => {
    const asset = assetFor(kit, selectedState)
    if (!asset) throw new Error(t('faceRig.errors.cleanBeforeGenerate', { name: stateLabel(selectedState) }))
    setBusyState('cleanup'); setError(null)
    try {
      const cleaned = await cleanCharacterKitFaceOverlay({ workspace, source: asset.source })
      const alpha = await inspectSourceAlpha(cleaned.source).catch(() => cleaned.alpha)
      const next = registerCleanedFaceRigAsset(kit, selectedState, { ...cleaned, alpha })
      onChange(next)
      onStatus?.(t('faceRig.status.cleaned', { name: stateLabel(selectedState), status: t(`alpha.${alpha.status}`) }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.cleanupFailed'))
    } finally { setBusyState(null) }
  }

  const updateAnchorField = (field: keyof CharacterFaceAnchor, value: number) => {
    if (!Number.isFinite(value)) return
    setDraftAnchor(current => {
      const next = { ...current, [field]: value }
      draftAnchorRef.current = next
      return next
    })
  }

  const planDialogue = () => {
    try {
      const preview = previewFaceRigDialogue(kit, dialogueText)
      setDialoguePreview(preview)
      setLiveViseme(undefined)
      setError(null)
      onStatus?.(t('faceRig.status.planned', { count: preview.visemes.length, duration: preview.end.toFixed(1) }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.planFailed'))
    }
  }

  const playDialogue = () => {
    let preview = dialoguePreviewRef.current
    if (!preview) {
      try {
        preview = previewFaceRigDialogue(kit, dialogueText)
        setDialoguePreview(preview)
        dialoguePreviewRef.current = preview
        setError(null)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : t('faceRig.errors.planFailed'))
        return
      }
    }
    const token = ++playTokenRef.current
    const started = performance.now()
    const audio = audioRef.current
    if (audio && dialogueAudio) {
      audio.currentTime = 0
      void audio.play().catch(() => undefined)
    }
    const tick = () => {
      if (playTokenRef.current !== token) return
      const current = dialoguePreviewRef.current
      if (!current) return
      const elapsed = audio && dialogueAudio && !audio.paused ? audio.currentTime : (performance.now() - started) / 1000
      setLiveViseme(faceRigVisemeAt(current, elapsed))
      if (elapsed >= current.end) {
        setLiveViseme(undefined)
        return
      }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }

  const speakDialogue = async () => {
    const line = dialogueText.trim()
    if (!line) throw new Error(t('faceRig.errors.writeLine'))
    setBusyState('dialogue'); setError(null)
    try {
      const clip = await generateSceneSpeechClip({ prompt: line, model: speechModel, durationSeconds: 3 })
      setDialogueAudio(clip.filename)
      let preview = previewFaceRigDialogue(kit, line, 3)
      try {
        const analysis = await analyzeAudio({ audio_path: clip.filename, transcribe: true, extract_vocals: true, lyrics_hint: line })
        const units = (analysis.lyrics ?? []).flatMap(segment => segment.words?.length
          ? segment.words.map(word => ({ text: word.text, start: word.start, end: word.end }))
          : [{ text: segment.text, start: segment.start, end: segment.end }])
        preview = previewFaceRigDialogueFromAudio(kit, line, units)
      } catch {
        preview = previewFaceRigDialogue(kit, line, 3)
      }
      setDialoguePreview(preview)
      onStatus?.(t('faceRig.status.speechReady', { count: preview.visemes.length }))
      requestAnimationFrame(() => playDialogue())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.speechFailed'))
    } finally { setBusyState(null) }
  }

  const onOverlayPointerDown = (event: ReactPointerEvent<HTMLImageElement>) => {
    if (disabled || Boolean(busyState) || !showOverlay || liveViseme) return
    const box = previewRef.current
    if (!box) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, origin: draftAnchor, mode: 'move' }
  }

  const onRegionPointerDown = (event: ReactPointerEvent<HTMLElement>, mode: 'move' | 'resize') => {
    if (disabled || Boolean(busyState) || liveViseme) return
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, origin: draftAnchor, mode }
  }

  const onOverlayPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current
    const box = previewRef.current
    if (!drag || drag.pointerId !== event.pointerId || !box) return
    const dx = ((event.clientX - drag.startX) / Math.max(1, box.clientWidth)) * 100
    const dy = ((event.clientY - drag.startY) / Math.max(1, box.clientHeight)) * 100
    if (drag.mode === 'resize') {
      const region = faceRigRegionFromAnchor(drag.origin)
      const next = faceRigAnchorFromRegion({
        ...region,
        width: Math.max(1, region.width + dx),
        height: Math.max(1, region.height + dy),
      })
      draftAnchorRef.current = next
      setDraftAnchor(next)
      return
    }
    const next = {
      ...drag.origin,
      offsetX: drag.origin.offsetX + dx,
      offsetY: drag.origin.offsetY + dy,
    }
    draftAnchorRef.current = next
    setDraftAnchor(next)
  }

  const onOverlayPointerUp = (event: ReactPointerEvent<HTMLImageElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null
      commitPlacement()
    }
  }

  const applyPreset = () => {
    const pack = presetPacks.find(item => item.id === presetId)
    if (!pack) throw new Error(t('faceRig.errors.choosePack'))
    try {
      const next = applyFaceRigMouthPreset(kit, pack, workspace)
      onChange(next)
      onStatus?.(t('faceRig.status.presetApplied', { name: pack.label }))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.applyPackFailed'))
    }
  }

  const commitPlacement = (source = kit, record = false) => {
    try {
      const anchor = draftAnchorRef.current
      const next = isFaceRigEyeState(selectedState)
        ? lockFaceRigEyePlacement(persistLook(source), poseId, anchor, record)
        : lockFaceRigMouthPlacement(persistLook(source), poseId, anchor, record)
      onChange(next)
      onCommit?.(next)
      onStatus?.(isFaceRigEyeState(selectedState)
        ? t('faceRig.status.eyesSaved', { pose: poseName })
        : t('faceRig.status.mouthSaved', { pose: poseName }))
      setError(null)
      return next
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.savePlacementFailed'))
      return source
    }
  }

  const savePlacement = () => {
    commitPlacement(kit, true)
  }

  const lockMouths = () => {
    commitPlacement(kit, true)
  }

  const nudge = (field: keyof CharacterFaceAnchor, delta: number) => {
    if (disabled || Boolean(busyState)) return
    setDraftAnchor(current => {
      const next = { ...current, [field]: current[field] + delta }
      draftAnchorRef.current = next
      return next
    })
    window.setTimeout(() => commitPlacement(), 0)
  }

  const wipeMouthZone = async () => {
    if (!poseSource) throw new Error(t('faceRig.errors.approvePoseBeforeWipe'))
    setBusyState('wipe'); setError(null)
    try {
      const response = await fetch(poseSource)
      if (!response.ok) throw new Error(t('faceRig.errors.loadPose'))
      const bitmap = await createImageBitmap(await response.blob())
      try {
        const canvas = document.createElement('canvas')
        canvas.width = bitmap.width
        canvas.height = bitmap.height
        const context = canvas.getContext('2d', { willReadFrequently: true })
        if (!context) throw new Error(t('faceRig.errors.editPose'))
        context.drawImage(bitmap, 0, 0)
        const region = faceRigRegionFromAnchor(draftAnchor)
        const topLeft = previewPercentToImagePixel(region.x, region.y, bitmap.width, bitmap.height)
        const bottomRight = previewPercentToImagePixel(region.x + region.width, region.y + region.height, bitmap.width, bitmap.height)
        const pixels = wipeMouthRegion(
          context.getImageData(0, 0, bitmap.width, bitmap.height).data,
          bitmap.width,
          bitmap.height,
          {
            cx: (topLeft.x + bottomRight.x) / 2,
            cy: (topLeft.y + bottomRight.y) / 2,
            rx: Math.max(2, Math.abs(bottomRight.x - topLeft.x) / 2),
            ry: Math.max(2, Math.abs(bottomRight.y - topLeft.y) / 2),
          },
        )
        const painted = new ImageData(bitmap.width, bitmap.height)
        painted.data.set(pixels)
        context.putImageData(painted, 0, 0)
        const blob = await new Promise<Blob>((resolve, reject) => {
          canvas.toBlob(value => value ? resolve(value) : reject(new Error(t('faceRig.errors.encodeWiped'))), 'image/png')
        })
        const uploaded = await uploadImage(new File([blob], `${kit.id}-${poseId || 'base'}-mouthless.png`, { type: 'image/png' }))
        const current = poseId === 'base' ? kit.base : kit.poses[poseId]
        const next = registerWipedKitPose(persistLook(kit), poseId || 'base', {
          id: current?.id || `${kit.id}-${poseId || 'base'}`,
          name: `${kit.name} · ${poseId || 'base'} mouthless`,
          source: uploaded.url || `/api/v1/file/${uploaded.filename}`,
          kind: 'image',
          alphaStatus: current?.alphaStatus ?? 'unknown',
          reviewState: current?.reviewState ?? 'pending',
          workspace,
        })
        const locked = lockFaceRigMouthPlacement(next, poseId || 'base', draftAnchorRef.current, false)
        onChange(locked)
        onCommit?.(locked)
        onStatus?.(t('faceRig.status.wiped', { pose: poseName }))
      } finally { bitmap.close() }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('faceRig.errors.wipeFailed'))
    } finally { setBusyState(null) }
  }

  const flashBlink = () => {
    if (!kit.eyes.blink?.source) {
      setError(t('faceRig.errors.blinkFirst'))
      return
    }
    setHoldBlink(true)
    window.setTimeout(() => setHoldBlink(false), 450)
  }

  const review = (state: CharacterKitFaceRigState, approved: boolean) => {
    try {
      if (approved && assetFor(kit, state)?.alphaStatus !== 'transparent') {
        throw new Error(t('faceRig.errors.approvalBlocked'))
      }
      let next = setFaceRigReviewState(kit, state, approved ? 'approved' : 'rejected')
      next = withAlphaStatus(next, state, approved ? 'transparent' : 'unknown')
      onChange(next)
      onStatus?.(t('faceRig.status.reviewed', {
        name: stateLabel(state),
        result: t(approved ? 'faceRig.status.approved' : 'faceRig.status.rejected'),
      }))
      setError(null)
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('faceRig.errors.reviewFailed')) }
  }

  return <div className="space-y-1.5">
    <p className="text-[10px] font-medium text-emerald-100">{t('faceRig.mouthsOnPose', { pose: poseName })}</p>
    <ol className="list-decimal space-y-0.5 pl-4 text-[9px] leading-relaxed text-text-secondary">
      <li>{t('faceRig.steps.box')}</li>
      <li>{t('faceRig.steps.wipe')}</li>
      <li>{t('faceRig.steps.eyes')}</li>
      <li>{t('faceRig.steps.scene')}</li>
    </ol>
    <p className="text-[9px] text-amber-100">{nextStep.title}</p>
    <details className="rounded border border-border/70 bg-black/10 px-1.5 py-1">
      <summary className="cursor-pointer text-[9px] text-text-muted">{t('faceRig.createNew.summary')}</summary>
      <div className="mt-1 space-y-1">
        <p className="text-[8px] text-text-muted">{t('faceRig.createNew.hint')}</p>
        <div className="flex flex-wrap gap-1">{FACE_RIG_STYLE_PRESETS.map(preset => (
          <button key={preset.id} type="button" disabled={disabled || Boolean(busyState)} onClick={() => setStyleId(preset.id)} className={`rounded border px-1 py-0.5 text-[8px] ${styleId === preset.id ? 'border-emerald-300 bg-emerald-400/15 text-emerald-100' : 'border-border text-text-muted'}`}>{t(`faceRig.styles.${preset.id}`)}</button>
        ))}</div>
        <div className="flex flex-wrap gap-1">{FACE_RIG_TRAIT_CHIPS.map(trait => (
          <button key={trait} type="button" disabled={disabled || Boolean(busyState)} onClick={() => toggleTrait(trait)} className={`rounded border px-1 py-0.5 text-[8px] ${traits.includes(trait) ? 'border-amber-300 bg-amber-400/15 text-amber-100' : 'border-border text-text-muted'}`}>{t(`faceRig.traits.${trait}`)}</button>
        ))}</div>
        <label className="block text-[8px] text-text-muted">{t('faceRig.extraNotes')}<textarea value={extraNotes} disabled={disabled || Boolean(busyState)} onChange={event => setExtraNotes(event.target.value)} rows={2} placeholder={t('faceRig.extraNotesPlaceholder')} className="mt-0.5 w-full resize-y rounded border border-border bg-bg-primary px-1.5 py-1 text-[8px]" /></label>
        <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => void generatePose()} className="w-full rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1 text-[9px] text-emerald-100 disabled:opacity-40">{busyState === 'pose' ? t('faceRig.generatingBody') : poseApproved ? t('faceRig.regenerateBody') : t('faceRig.generateBody')}</button>
        {presetPacks.length > 0 && <div className="grid grid-cols-[1fr_auto] gap-1">
          <select aria-label={t('faceRig.mouthPackAria')} value={presetId} disabled={disabled || Boolean(busyState)} onChange={event => setPresetId(event.target.value)} className="rounded border border-border bg-bg-primary px-1 py-1 text-[8px]">
            {presetPacks.map(pack => <option key={pack.id} value={pack.id}>{pack.label}</option>)}
          </select>
          <button type="button" disabled={disabled || Boolean(busyState) || !presetId} onClick={applyPreset} className="rounded border border-violet-300/40 bg-violet-400/10 px-1 py-1 text-[8px] text-violet-100 disabled:opacity-40">{t('faceRig.usePack')}</button>
        </div>}
      </div>
    </details>
    {poseSource && <div className="space-y-1 rounded border border-amber-300/25 bg-black/20 p-1">
      <div
        ref={previewRef}
        className={`relative aspect-square overflow-hidden rounded border border-border ${checkerboard ? 'bg-[linear-gradient(45deg,#1c2330_25%,transparent_25%),linear-gradient(-45deg,#1c2330_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1c2330_75%),linear-gradient(-45deg,transparent_75%,#1c2330_75%)] bg-[length:12px_12px]' : 'bg-bg-primary'}`}
      >
        <img src={poseSource} alt={t('faceRig.poseAlt', { name: kit.name })} className="absolute inset-0 h-full w-full object-contain" draggable={false} />
        {showOverlay && playbackAsset && <img
          src={playbackAsset.source}
          alt={t('faceRig.overlayAlt', { name: kit.name, state: stateLabel(playbackState) })}
          className={`absolute object-contain ${liveViseme || holdBlink ? '' : 'cursor-grab active:cursor-grabbing'}`}
          style={overlayStyle}
          draggable={false}
          onPointerDown={onOverlayPointerDown}
          onPointerMove={onOverlayPointerMove}
          onPointerUp={onOverlayPointerUp}
          onPointerCancel={onOverlayPointerUp}
        />}
        <div
          className="absolute cursor-move rounded border-2 border-amber-300/80 bg-amber-400/10"
          style={{ left: `${mouthRegion.x}%`, top: `${mouthRegion.y}%`, width: `${mouthRegion.width}%`, height: `${mouthRegion.height}%` }}
          onPointerDown={event => onRegionPointerDown(event, 'move')}
          onPointerMove={onOverlayPointerMove}
          onPointerUp={onOverlayPointerUp}
          onPointerCancel={onOverlayPointerUp}
        >
          <span
            className="absolute right-0 bottom-0 h-2.5 w-2.5 translate-x-1/2 translate-y-1/2 cursor-nwse-resize rounded-sm border border-amber-100 bg-amber-300"
            onPointerDown={event => onRegionPointerDown(event, 'resize')}
          />
        </div>
      </div>
      <p className="text-[8px] text-text-secondary">{t('faceRig.dragBoxHint')}</p>
      <div className="grid grid-cols-2 gap-1">
        <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => void wipeMouthZone()} className="rounded border border-amber-300/50 bg-amber-400/10 px-1 py-1.5 text-[10px] text-amber-100 disabled:opacity-40">{busyState === 'wipe' ? t('faceRig.wiping') : t('faceRig.wipeMouth')}</button>
        <button type="button" disabled={disabled || Boolean(busyState)} onClick={lockMouths} className="rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1.5 text-[10px] text-emerald-100 disabled:opacity-40">{t('faceRig.lockMouths')}</button>
      </div>
    </div>}
    <div className="grid grid-cols-3 gap-1">{CHARACTER_FACE_RIG_STATES.map(state => {
      const asset = assetFor(kit, state)
      return <button key={state} type="button" disabled={disabled || Boolean(busyState)} onClick={() => setSelectedState(state)} className={`rounded border px-1 py-1 text-[7px] ${selectedState === state ? 'border-emerald-300 bg-emerald-400/15 text-emerald-100' : 'border-border text-text-muted'}`}>{stateLabel(state)}<span className="block text-[6px]">{t(`review.${asset?.reviewState ?? 'missing'}`)}</span></button>
    })}</div>
    {selectedRequest && <details className="rounded border border-border/70 bg-black/10 px-1.5 py-1"><summary className="cursor-pointer text-[7px] text-text-muted">{t('faceRig.promptUsed', { name: stateLabel(selectedState) })}</summary><p className="mt-1 select-text text-[7px] leading-relaxed text-text-secondary">{selectedRequest.prompt}</p></details>}
    {assetFor(kit, selectedState) && <div className="space-y-1 rounded border border-emerald-300/20 bg-[linear-gradient(45deg,#1c2330_25%,transparent_25%),linear-gradient(-45deg,#1c2330_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1c2330_75%),linear-gradient(-45deg,transparent_75%,#1c2330_75%)] bg-[length:12px_12px] p-1.5">
      <img src={assetFor(kit, selectedState)!.source} alt={`${kit.name} ${stateLabel(selectedState)}`} className="mx-auto h-28 w-full object-contain" />
      <div className="flex items-center justify-between text-[7px]"><span className="truncate text-text-secondary">{assetFor(kit, selectedState)!.name}</span><span className="text-emerald-100">{t(`alpha.${assetFor(kit, selectedState)!.alphaStatus}`)} · {t(`review.${assetFor(kit, selectedState)!.reviewState}`)}</span></div>
      <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => void cleanSelected()} className="w-full rounded border border-cyan-300/40 bg-cyan-400/10 px-1 py-1 text-[8px] text-cyan-100 disabled:opacity-40">{busyState === 'cleanup' ? t('faceRig.cleaningCutout') : t('faceRig.cleanMouthBackground')}</button>
      <div className="flex gap-1 text-[7px] text-text-muted">
        <button type="button" onClick={() => setShowOverlay(value => !value)} className="rounded border border-border px-1 py-0.5">{showOverlay ? t('faceRig.hideMouth') : t('faceRig.showMouth')}</button>
        <button type="button" onClick={() => setCheckerboard(value => !value)} className="rounded border border-border px-1 py-0.5">{checkerboard ? t('faceRig.solidBackground') : t('faceRig.checkerboard')}</button>
      </div>
      <div className="space-y-1 rounded border border-border/70 bg-black/20 p-1">
        <div className="grid grid-cols-4 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetY', -1)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">{t('faceRig.nudge.up')}</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetY', 1)} className="rounded border border-amber-300/40 bg-amber-400/10 px-1 py-1 text-[8px] text-amber-100">{t('faceRig.nudge.down')}</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetX', -1)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">{t('faceRig.nudge.left')}</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetX', 1)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">{t('faceRig.nudge.right')}</button>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('scale', -0.005)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">{t('faceRig.nudge.smaller')}</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('scale', 0.005)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">{t('faceRig.nudge.bigger')}</button>
        </div>
        <div className="grid grid-cols-2 gap-1 text-[7px] text-text-muted">
          <label>{t('faceRig.fields.x')}<input type="range" min={-40} max={40} step={0.5} value={draftAnchor.offsetX} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('offsetX', Number(event.target.value))} onPointerUp={() => commitPlacement()} className="w-full" /></label>
          <label>{t('faceRig.fields.y')}<input type="range" min={-50} max={20} step={0.5} value={draftAnchor.offsetY} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('offsetY', Number(event.target.value))} onPointerUp={() => commitPlacement()} className="w-full" /></label>
          <label>{t('faceRig.fields.scale')}<input type="range" min={0.01} max={0.45} step={0.001} value={draftAnchor.scale} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('scale', Number(event.target.value))} onPointerUp={() => commitPlacement()} className="w-full" /></label>
          <label>{t('faceRig.fields.rotate')}<input type="range" min={-45} max={45} step={0.5} value={draftAnchor.rotation} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('rotation', Number(event.target.value))} onPointerUp={() => commitPlacement()} className="w-full" /></label>
        </div>
        <p className="text-[7px] text-text-secondary">{t('faceRig.readout', { x: draftAnchor.offsetX.toFixed(2), y: draftAnchor.offsetY.toFixed(2), scale: draftAnchor.scale.toFixed(4), rot: draftAnchor.rotation.toFixed(1) })}</p>
        {placement.warnings.map(warning => <p key={warning} className="text-[7px] text-amber-200">{PLACEMENT_WARNING_KEYS[warning] ? t(PLACEMENT_WARNING_KEYS[warning]) : warning}</p>)}
        <div className="grid grid-cols-2 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState) || !dirtyAnchor} onClick={savePlacement} className="rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{t('faceRig.saveMouth')}</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={lockMouths} className="rounded border border-amber-300/50 bg-amber-400/10 px-1 py-1 text-[8px] text-amber-100 disabled:opacity-40">{t('faceRig.lockMouths')}</button>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState) || !dirtyAnchor} onClick={() => setDraftAnchor(savedAnchor)} className="rounded border border-border px-1 py-1 text-[8px] text-text-muted disabled:opacity-40">{t('faceRig.reset')}</button>
          <button type="button" disabled={disabled || Boolean(busyState) || !kit.eyes.blink?.source} onClick={flashBlink} className="rounded border border-cyan-300/40 px-1 py-1 text-[8px] text-cyan-100 disabled:opacity-40">{holdBlink ? t('faceRig.blinking') : t('faceRig.flashBlink')}</button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-1"><button type="button" disabled={disabled || Boolean(busyState) || assetFor(kit, selectedState)!.alphaStatus !== 'transparent'} onClick={() => review(selectedState, true)} className="rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{t('faceRig.approveTransparent')}</button><button type="button" disabled={disabled || Boolean(busyState)} onClick={() => review(selectedState, false)} className="rounded border border-red-300/30 px-1 py-1 text-[8px] text-red-200">{t('faceRig.reject')}</button></div>
    </div>}
    <div className="grid grid-cols-2 gap-1"><button type="button" disabled={disabled || Boolean(busyState) || !selectedRequest} onClick={() => void generateSelected()} className="rounded border border-emerald-300/50 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{busyState === selectedState ? t('faceRig.generatingNamed', { name: stateLabel(selectedState) }) : t('faceRig.generateNamed', { name: stateLabel(selectedState) })}</button><button type="button" disabled={disabled || Boolean(busyState) || !requests.length} onClick={() => void generateMissingPack()} className="rounded border border-emerald-300/30 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{busyState === 'pack' ? t('faceRig.generatingPack') : t('faceRig.generateMissing')}</button></div>
    <details className="space-y-1 rounded border border-amber-300/20 bg-black/15 p-1.5">
      <summary className="cursor-pointer text-[9px] text-text-muted">{t('faceRig.tryLine.summary')}</summary>
      <textarea value={dialogueText} disabled={disabled || Boolean(busyState)} onChange={event => setDialogueText(event.target.value)} rows={2} className="mt-1 w-full resize-y rounded border border-border bg-bg-primary px-1.5 py-1 text-[8px]" />
      <div className="grid grid-cols-2 gap-1">
        <button type="button" disabled={disabled || Boolean(busyState) || !dialogueText.trim()} onClick={planDialogue} className="rounded border border-amber-300/40 px-1 py-1 text-[8px] text-amber-100 disabled:opacity-40">{t('faceRig.tryLine.planMouths')}</button>
        <button type="button" disabled={disabled || Boolean(busyState) || !dialogueText.trim()} onClick={() => void speakDialogue()} className="rounded border border-amber-300/50 bg-amber-400/10 px-1 py-1 text-[8px] text-amber-100 disabled:opacity-40">{busyState === 'dialogue' ? t('faceRig.tryLine.generatingVoice') : t('faceRig.tryLine.speak')}</button>
      </div>
      {dialoguePreview && <div className="space-y-1">
        <p className="text-[7px] text-text-secondary">{t('faceRig.tryLine.beats', { count: dialoguePreview.visemes.length, duration: dialoguePreview.end.toFixed(1), available: dialoguePreview.available.join(', ') || t('faceRig.tryLine.none') })}</p>
        {dialoguePreview.missing.length > 0 && <p className="text-[7px] text-amber-200">{t('faceRig.tryLine.missing', { missing: dialoguePreview.missing.join(', '), fallback: dialoguePreview.visemes.find(beat => beat.fallback)?.sourceState ?? t('faceRig.tryLine.remainingMouth') })}</p>}
        <div className="flex flex-wrap gap-1">{dialoguePreview.visemes.map((beat, index) => <span key={`${beat.start}-${index}`} className={`rounded border px-1 py-0.5 text-[6px] ${liveViseme && liveViseme.start === beat.start && liveViseme.state === beat.state ? 'border-amber-300 text-amber-100' : 'border-border text-text-muted'}`}>{beat.state}{beat.fallback ? `→${beat.sourceState}` : ''}</span>)}</div>
        <button type="button" disabled={disabled || Boolean(busyState)} onClick={playDialogue} className="w-full rounded border border-border px-1 py-1 text-[8px] text-text-secondary">{t('faceRig.tryLine.playMouths')}</button>
      </div>}
      {dialogueAudio && <audio ref={audioRef} src={getFileUrl(dialogueAudio, workspace)} preload="auto" className="hidden" />}
    </details>
    <p className="text-[8px] text-text-muted">{t('faceRig.unsavedHint')}</p>
    {error && <p className="text-[9px] text-red-300">{error}</p>}
  </div>
}
