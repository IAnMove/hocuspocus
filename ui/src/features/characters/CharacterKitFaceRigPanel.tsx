import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { analyzeAudio, cleanCharacterKitFaceOverlay, getFileUrl } from '../../api/client'
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
  faceRigGenerationRequests,
  faceRigOverlayPreviewStyle,
  faceRigVisemeAt,
  lockFaceRigMouthPlacement,
  previewFaceRigDialogue,
  previewFaceRigDialogueFromAudio,
  registerCleanedFaceRigAsset,
  registerGeneratedFaceRigAsset,
  setFaceRigAnchor,
  setFaceRigReviewState,
  type FaceRigMouthPresetPack,
  type CharacterKitFaceRigState,
  type FaceRigDialoguePreview,
  type FaceRigDialogueViseme,
} from '../../lib/characterKitFaceRig'
import { registerGeneratedKitPose, type CharacterFaceAnchor, type CharacterKit, type CharacterKitAsset, type CharacterMouthState } from '../../lib/characterKit'
import { useStore } from '../../stores/useStore'

type Props = {
  kit: CharacterKit
  poseId: string
  disabled?: boolean
  onChange: (kit: CharacterKit) => void
  onStatus?: (message: string) => void
}

const LABELS: Record<CharacterKitFaceRigState, string> = {
  closed: 'Closed',
  small: 'Small',
  wide: 'Wide',
  round: 'Round / O',
  blink: 'Blink',
}

function assetFor(kit: CharacterKit, state: CharacterKitFaceRigState): CharacterKitAsset | undefined {
  return state === 'blink' ? kit.eyes.blink : kit.mouth[state as CharacterMouthState]
}

function withAlphaStatus(kit: CharacterKit, state: CharacterKitFaceRigState, alphaStatus: CharacterKitAsset['alphaStatus']): CharacterKit {
  if (state === 'blink') {
    return kit.eyes.blink ? { ...kit, eyes: { ...kit.eyes, blink: { ...kit.eyes.blink, alphaStatus } } } : kit
  }
  const current = kit.mouth[state]
  return current ? { ...kit, mouth: { ...kit.mouth, [state]: { ...current, alphaStatus } } } : kit
}

async function inspectSourceAlpha(source: string) {
  const response = await fetch(source)
  if (!response.ok) throw new Error('Could not inspect the generated image alpha channel.')
  const bitmap = await createImageBitmap(await response.blob())
  try {
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width; canvas.height = bitmap.height
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) throw new Error('This browser cannot inspect image transparency.')
    context.drawImage(bitmap, 0, 0)
    return classifyCharacterKitAlpha(context.getImageData(0, 0, bitmap.width, bitmap.height).data)
  } finally { bitmap.close() }
}

export function CharacterKitFaceRigPanel({ kit, poseId, disabled = false, onChange, onStatus }: Props) {
  const imageModel = useStore(state => state.selectedModelPerMode.image || '')
  const speechModel = useStore(state => state.selectedModelPerAudioSubMode.speech ?? 'kugelaudio_0_open')
  const workspace = useStore(state => state.activeWorkspace)
  const [selectedState, setSelectedState] = useState<CharacterKitFaceRigState>('wide')
  const [styleId, setStyleId] = useState<typeof FACE_RIG_STYLE_PRESETS[number]['id']>(FACE_RIG_STYLE_PRESETS[0].id)
  const [traits, setTraits] = useState<string[]>([])
  const [extraNotes, setExtraNotes] = useState(kit.lookNotes ?? '')
  const [busyState, setBusyState] = useState<CharacterKitFaceRigState | 'pack' | 'cleanup' | 'dialogue' | 'pose' | null>(null)
  const [holdBlink, setHoldBlink] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showOverlay, setShowOverlay] = useState(true)
  const [checkerboard, setCheckerboard] = useState(true)
  const [draftAnchor, setDraftAnchor] = useState<CharacterFaceAnchor>(() => faceRigAnchorFor(kit, poseId, selectedState))
  const [dialogueText, setDialogueText] = useState('The square is frozen and the bell is too loud.')
  const [dialoguePreview, setDialoguePreview] = useState<FaceRigDialoguePreview | null>(null)
  const [liveViseme, setLiveViseme] = useState<FaceRigDialogueViseme | undefined>(undefined)
  const [dialogueAudio, setDialogueAudio] = useState<string | null>(null)
  const [presetPacks, setPresetPacks] = useState<FaceRigMouthPresetPack[]>([])
  const [presetId, setPresetId] = useState('')
  const previewRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; origin: CharacterFaceAnchor } | null>(null)
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
  const playbackAsset = playbackState === 'blink' ? kit.eyes.blink ?? selectedAsset : kit.mouth[playbackState] ?? selectedAsset
  const playbackAnchor = holdBlink || liveViseme ? faceRigAnchorFor(kit, poseId, playbackState) : draftAnchor
  const poseApproved = Boolean((poseId === 'base' ? kit.base : kit.poses[poseId])?.reviewState === 'approved')
  const placement = useMemo(() => assessFaceRigPlacement(draftAnchor, selectedState), [draftAnchor, selectedState])
  const overlayStyle = useMemo(() => faceRigOverlayPreviewStyle(playbackAnchor), [playbackAnchor])
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
      name: `${kit.name} · ${LABELS[state]}`,
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
      onStatus?.('Paso 1: pose generated as pending. Approve it in Kit & poses, then generate mouths.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Character pose generation failed.')
    } finally { setBusyState(null) }
  }

  const generateSelected = async () => {
    setBusyState(selectedState); setError(null)
    try {
      const next = await generateState(persistLook(kit), selectedState)
      onChange(next); onStatus?.(`${LABELS[selectedState]} generated as pending review. Drag it onto the lips, then lock all mouths.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Face Rig generation failed.')
    } finally { setBusyState(null) }
  }

  const generateMissingPack = async () => {
    setBusyState('pack'); setError(null)
    try {
      let next = persistLook(kit)
      const missing = CHARACTER_FACE_RIG_STATES.filter(state => !assetFor(next, state) || assetFor(next, state)?.reviewState === 'rejected')
      if (!missing.length) throw new Error('The five Face Rig states already exist. Generate one selected state to replace it.')
      for (const state of missing) {
        onStatus?.(`Generating Face Rig ${LABELS[state]}…`)
        next = await generateState(next, state)
        onChange(next)
      }
      onStatus?.(`Generated ${missing.length} Face Rig states. Review transparency and placement before approval.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Face Rig pack generation failed.')
    } finally { setBusyState(null) }
  }

  const cleanSelected = async () => {
    const asset = assetFor(kit, selectedState)
    if (!asset) throw new Error(`Generate ${LABELS[selectedState]} before cleaning it.`)
    setBusyState('cleanup'); setError(null)
    try {
      const cleaned = await cleanCharacterKitFaceOverlay({ workspace, source: asset.source })
      const alpha = await inspectSourceAlpha(cleaned.source).catch(() => cleaned.alpha)
      const next = registerCleanedFaceRigAsset(kit, selectedState, { ...cleaned, alpha })
      onChange(next)
      onStatus?.(`${LABELS[selectedState]} cleaned as ${alpha.status}. It stays pending until you approve the placement.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Face Rig cleanup failed.')
    } finally { setBusyState(null) }
  }

  const updateAnchorField = (field: keyof CharacterFaceAnchor, value: number) => {
    if (!Number.isFinite(value)) return
    setDraftAnchor(current => ({ ...current, [field]: value }))
  }

  const planDialogue = () => {
    try {
      const preview = previewFaceRigDialogue(kit, dialogueText)
      setDialoguePreview(preview)
      setLiveViseme(undefined)
      setError(null)
      onStatus?.(`Planned ${preview.visemes.length} visemes over ${preview.end.toFixed(1)}s. Missing mouths stay as fallbacks and are not saved.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not plan this Face Rig line.')
    }
  }

  const playDialogue = () => {
    const preview = dialoguePreviewRef.current
    if (!preview) { planDialogue(); return }
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
    if (!line) throw new Error('Write a short test line first.')
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
      onStatus?.(`Preview speech ready with ${preview.visemes.length} visemes. Nothing was saved to the kit.`)
      requestAnimationFrame(() => playDialogue())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Face Rig speech preview failed.')
    } finally { setBusyState(null) }
  }

  const onOverlayPointerDown = (event: ReactPointerEvent<HTMLImageElement>) => {
    if (disabled || Boolean(busyState) || !showOverlay || liveViseme) return
    const box = previewRef.current
    if (!box) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, origin: draftAnchor }
  }

  const onOverlayPointerMove = (event: ReactPointerEvent<HTMLImageElement>) => {
    const drag = dragRef.current
    const box = previewRef.current
    if (!drag || drag.pointerId !== event.pointerId || !box) return
    const dx = ((event.clientX - drag.startX) / Math.max(1, box.clientWidth)) * 100
    const dy = ((event.clientY - drag.startY) / Math.max(1, box.clientHeight)) * 100
    setDraftAnchor({
      ...drag.origin,
      offsetX: drag.origin.offsetX + dx,
      offsetY: drag.origin.offsetY + dy,
    })
  }

  const onOverlayPointerUp = (event: ReactPointerEvent<HTMLImageElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null
  }

  const applyPreset = () => {
    const pack = presetPacks.find(item => item.id === presetId)
    if (!pack) throw new Error('Choose a mouth style pack first.')
    try {
      const next = applyFaceRigMouthPreset(kit, pack, workspace)
      onChange(next)
      onStatus?.(`Applied ${pack.label} as pending Face Rig mouths. Check placement before approval.`)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not apply this mouth pack.')
    }
  }

  const savePlacement = () => {
    try {
      const next = setFaceRigAnchor(persistLook(kit), poseId, selectedState, draftAnchor)
      onChange(next)
      onStatus?.(`${LABELS[selectedState]} placement saved for ${poseId || 'base'}. It stays pending until you approve.`)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this Face Rig placement.')
    }
  }

  const lockMouths = () => {
    try {
      const next = lockFaceRigMouthPlacement(persistLook(kit), poseId, draftAnchor)
      onChange(next)
      onStatus?.(`Locked this height and size on closed, small, wide and round for ${poseId || 'base'}.`)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not lock this mouth placement.')
    }
  }

  const nudge = (field: keyof CharacterFaceAnchor, delta: number) => {
    if (disabled || Boolean(busyState)) return
    setDraftAnchor(current => ({ ...current, [field]: current[field] + delta }))
  }

  const flashBlink = () => {
    if (!kit.eyes.blink?.source) {
      setError('Generate a blink overlay first, then flash it to check the eyes.')
      return
    }
    setHoldBlink(true)
    window.setTimeout(() => setHoldBlink(false), 450)
  }

  const review = (state: CharacterKitFaceRigState, approved: boolean) => {
    try {
      if (approved && assetFor(kit, state)?.alphaStatus !== 'transparent') {
        throw new Error('Approval is blocked: this output does not contain a verified transparent alpha channel.')
      }
      let next = setFaceRigReviewState(kit, state, approved ? 'approved' : 'rejected')
      next = withAlphaStatus(next, state, approved ? 'transparent' : 'unknown')
      onChange(next)
      onStatus?.(`${LABELS[state]} ${approved ? 'approved as transparent' : 'rejected'}. Save the kit to publish this review.`)
      setError(null)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not review this Face Rig state.') }
  }

  return <div className="space-y-1.5">
    <p className="text-[8px] leading-relaxed text-text-muted">Two steps: first the puppet body, then lips and blinks you drag onto the face. Pick a style and a couple of traits; the prompts are already written. Recipes never see pending pieces.</p>
    <div className="space-y-1 rounded border border-emerald-300/20 bg-black/15 p-1.5">
      <p className="text-[8px] font-medium text-emerald-100">Paso 1 · Personaje</p>
      <p className="text-[7px] text-text-muted">Style + traits only. Generate a full-body cutout, then approve it in Kit & poses.</p>
      <div className="flex flex-wrap gap-1">{FACE_RIG_STYLE_PRESETS.map(preset => (
        <button key={preset.id} type="button" disabled={disabled || Boolean(busyState)} onClick={() => setStyleId(preset.id)} className={`rounded border px-1 py-0.5 text-[7px] ${styleId === preset.id ? 'border-emerald-300 bg-emerald-400/15 text-emerald-100' : 'border-border text-text-muted'}`}>{preset.label}</button>
      ))}</div>
      <div className="flex flex-wrap gap-1">{FACE_RIG_TRAIT_CHIPS.map(trait => (
        <button key={trait} type="button" disabled={disabled || Boolean(busyState)} onClick={() => toggleTrait(trait)} className={`rounded border px-1 py-0.5 text-[7px] ${traits.includes(trait) ? 'border-amber-300 bg-amber-400/15 text-amber-100' : 'border-border text-text-muted'}`}>{trait}</button>
      ))}</div>
      <label className="block text-[8px] text-text-muted">Extra notes (optional)<textarea value={extraNotes} disabled={disabled || Boolean(busyState)} onChange={event => setExtraNotes(event.target.value)} rows={2} placeholder="Only what the chips do not cover…" className="mt-0.5 w-full resize-y rounded border border-border bg-bg-primary px-1.5 py-1 text-[8px]" /></label>
      <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => void generatePose()} className="w-full rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{busyState === 'pose' ? 'Generating character…' : poseApproved ? 'Regenerate pose (stays pending)' : 'Generate full-body cutout'}</button>
      <p className="text-[7px] text-text-secondary">{poseApproved ? `Approved pose: ${poseId || 'base'}. Continue with mouths.` : 'Approve the pose in Kit & poses before generating Face Rig overlays.'}</p>
    </div>
    {presetPacks.length > 0 && <div className="grid grid-cols-[1fr_auto] gap-1">
      <select aria-label="Mouth style pack" value={presetId} disabled={disabled || Boolean(busyState)} onChange={event => setPresetId(event.target.value)} className="rounded border border-border bg-bg-primary px-1 py-1 text-[8px]">
        {presetPacks.map(pack => <option key={pack.id} value={pack.id}>{pack.label}</option>)}
      </select>
      <button type="button" disabled={disabled || Boolean(busyState) || !presetId} onClick={applyPreset} className="rounded border border-violet-300/40 bg-violet-400/10 px-1 py-1 text-[8px] text-violet-100 disabled:opacity-40">Apply pack</button>
    </div>}
    <p className="text-[8px] font-medium text-emerald-100">Paso 2 · Labios y parpadeo</p>
    <div className="grid grid-cols-5 gap-1">{CHARACTER_FACE_RIG_STATES.map(state => {
      const asset = assetFor(kit, state)
      return <button key={state} type="button" disabled={disabled || Boolean(busyState)} onClick={() => setSelectedState(state)} className={`rounded border px-1 py-1 text-[7px] ${selectedState === state ? 'border-emerald-300 bg-emerald-400/15 text-emerald-100' : 'border-border text-text-muted'}`}>{LABELS[state]}<span className="block text-[6px]">{asset?.reviewState ?? 'missing'}</span></button>
    })}</div>
    {selectedRequest && <details className="rounded border border-border/70 bg-black/10 px-1.5 py-1"><summary className="cursor-pointer text-[7px] text-text-muted">Prompt used for {LABELS[selectedState]}</summary><p className="mt-1 select-text text-[7px] leading-relaxed text-text-secondary">{selectedRequest.prompt}</p></details>}
    {assetFor(kit, selectedState) && <div className="space-y-1 rounded border border-emerald-300/20 bg-[linear-gradient(45deg,#1c2330_25%,transparent_25%),linear-gradient(-45deg,#1c2330_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1c2330_75%),linear-gradient(-45deg,transparent_75%,#1c2330_75%)] bg-[length:12px_12px] p-1.5">
      <img src={assetFor(kit, selectedState)!.source} alt={`${kit.name} ${LABELS[selectedState]}`} className="mx-auto h-28 w-full object-contain" />
      <div className="flex items-center justify-between text-[7px]"><span className="truncate text-text-secondary">{assetFor(kit, selectedState)!.name}</span><span className="text-emerald-100">{assetFor(kit, selectedState)!.alphaStatus} · {assetFor(kit, selectedState)!.reviewState}</span></div>
      <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => void cleanSelected()} className="w-full rounded border border-cyan-300/40 bg-cyan-400/10 px-1 py-1 text-[8px] text-cyan-100 disabled:opacity-40">{busyState === 'cleanup' ? 'Cleaning overlay…' : 'Clean background / halo'}</button>
      {poseSource && selectedAsset && <div className="space-y-1 rounded border border-border/70 bg-black/20 p-1">
        <div className="flex items-center justify-between gap-1 text-[7px] text-text-muted">
          <span>Placement on {poseId || 'base'}</span>
          <span className="flex gap-1">
            <button type="button" onClick={() => setShowOverlay(value => !value)} className="rounded border border-border px-1 py-0.5">{showOverlay ? 'Hide overlay' : 'Show overlay'}</button>
            <button type="button" onClick={() => setCheckerboard(value => !value)} className="rounded border border-border px-1 py-0.5">{checkerboard ? 'Solid' : 'Checker'}</button>
          </span>
        </div>
        <div
          ref={previewRef}
          className={`relative aspect-square overflow-hidden rounded border border-border ${checkerboard ? 'bg-[linear-gradient(45deg,#1c2330_25%,transparent_25%),linear-gradient(-45deg,#1c2330_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1c2330_75%),linear-gradient(-45deg,transparent_75%,#1c2330_75%)] bg-[length:12px_12px]' : 'bg-bg-primary'}`}
        >
          <img src={poseSource} alt={`${kit.name} pose`} className="absolute inset-0 h-full w-full object-contain" draggable={false} />
          {showOverlay && playbackAsset && <img
            src={playbackAsset.source}
            alt={`${kit.name} ${LABELS[playbackState]} overlay`}
            className={`absolute object-contain ${liveViseme || holdBlink ? '' : 'cursor-grab active:cursor-grabbing'}`}
            style={overlayStyle}
            draggable={false}
            onPointerDown={onOverlayPointerDown}
            onPointerMove={onOverlayPointerMove}
            onPointerUp={onOverlayPointerUp}
            onPointerCancel={onOverlayPointerUp}
          />}
          <div className="pointer-events-none absolute inset-x-0 top-[32%] border-t border-dashed border-amber-200/40" title="Typical mouth line" />
        </div>
        <p className="text-[7px] text-text-muted">Paso 2 · Arrastra la boca hasta los labios. Abajo = Down. Luego lock all mouths.</p>
        <div className="grid grid-cols-4 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetY', -1)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">Up</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetY', 1)} className="rounded border border-amber-300/40 bg-amber-400/10 px-1 py-1 text-[8px] text-amber-100">Down</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetX', -1)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">Left</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('offsetX', 1)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">Right</button>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('scale', -0.005)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">Smaller</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={() => nudge('scale', 0.005)} className="rounded border border-border px-1 py-1 text-[8px] text-text-secondary">Bigger</button>
        </div>
        <div className="grid grid-cols-2 gap-1 text-[7px] text-text-muted">
          <label>X<input type="range" min={-40} max={40} step={0.5} value={draftAnchor.offsetX} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('offsetX', Number(event.target.value))} className="w-full" /></label>
          <label>Y (down →)<input type="range" min={-50} max={20} step={0.5} value={draftAnchor.offsetY} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('offsetY', Number(event.target.value))} className="w-full" /></label>
          <label>Scale<input type="range" min={0.01} max={0.45} step={0.001} value={draftAnchor.scale} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('scale', Number(event.target.value))} className="w-full" /></label>
          <label>Rotate<input type="range" min={-45} max={45} step={0.5} value={draftAnchor.rotation} disabled={disabled || Boolean(busyState)} onChange={event => updateAnchorField('rotation', Number(event.target.value))} className="w-full" /></label>
        </div>
        <p className="text-[7px] text-text-secondary">x {draftAnchor.offsetX.toFixed(2)} · y {draftAnchor.offsetY.toFixed(2)} · scale {draftAnchor.scale.toFixed(4)} · rot {draftAnchor.rotation.toFixed(1)}°</p>
        {placement.warnings.map(warning => <p key={warning} className="text-[7px] text-amber-200">{warning}</p>)}
        <div className="grid grid-cols-2 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState) || !dirtyAnchor} onClick={savePlacement} className="rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">Save this state</button>
          <button type="button" disabled={disabled || Boolean(busyState)} onClick={lockMouths} className="rounded border border-amber-300/50 bg-amber-400/10 px-1 py-1 text-[8px] text-amber-100 disabled:opacity-40">Lock all mouths</button>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <button type="button" disabled={disabled || Boolean(busyState) || !dirtyAnchor} onClick={() => setDraftAnchor(savedAnchor)} className="rounded border border-border px-1 py-1 text-[8px] text-text-muted disabled:opacity-40">Reset</button>
          <button type="button" disabled={disabled || Boolean(busyState) || !kit.eyes.blink?.source} onClick={flashBlink} className="rounded border border-cyan-300/40 px-1 py-1 text-[8px] text-cyan-100 disabled:opacity-40">{holdBlink ? 'Blinking…' : 'Flash blink 0.4s'}</button>
        </div>
      </div>}
      <div className="grid grid-cols-2 gap-1"><button type="button" disabled={disabled || Boolean(busyState) || assetFor(kit, selectedState)!.alphaStatus !== 'transparent'} onClick={() => review(selectedState, true)} className="rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">Approve transparent</button><button type="button" disabled={disabled || Boolean(busyState)} onClick={() => review(selectedState, false)} className="rounded border border-red-300/30 px-1 py-1 text-[8px] text-red-200">Reject</button></div>
    </div>}
    <div className="grid grid-cols-2 gap-1"><button type="button" disabled={disabled || Boolean(busyState) || !selectedRequest} onClick={() => void generateSelected()} className="rounded border border-emerald-300/50 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{busyState === selectedState ? `Generating ${LABELS[selectedState]}…` : `Generate / replace ${LABELS[selectedState]}`}</button><button type="button" disabled={disabled || Boolean(busyState) || !requests.length} onClick={() => void generateMissingPack()} className="rounded border border-emerald-300/30 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{busyState === 'pack' ? 'Generating pack…' : 'Generate missing pack'}</button></div>
    <div className="space-y-1 rounded border border-amber-300/20 bg-black/15 p-1.5">
      <p className="text-[8px] text-text-muted">Short dialogue preview. This does not save visemes or audio into the kit.</p>
      <textarea value={dialogueText} disabled={disabled || Boolean(busyState)} onChange={event => setDialogueText(event.target.value)} rows={2} className="w-full resize-y rounded border border-border bg-bg-primary px-1.5 py-1 text-[8px]" />
      <div className="grid grid-cols-2 gap-1">
        <button type="button" disabled={disabled || Boolean(busyState) || !dialogueText.trim()} onClick={planDialogue} className="rounded border border-amber-300/40 px-1 py-1 text-[8px] text-amber-100 disabled:opacity-40">Plan visemes</button>
        <button type="button" disabled={disabled || Boolean(busyState) || !dialogueText.trim()} onClick={() => void speakDialogue()} className="rounded border border-amber-300/50 bg-amber-400/10 px-1 py-1 text-[8px] text-amber-100 disabled:opacity-40">{busyState === 'dialogue' ? 'Generating speech…' : `Speak 3s · ${speechModel}`}</button>
      </div>
      {dialoguePreview && <div className="space-y-1">
        <p className="text-[7px] text-text-secondary">{dialoguePreview.visemes.length} beats · {dialoguePreview.end.toFixed(1)}s · available {dialoguePreview.available.join(', ') || 'none'}</p>
        {dialoguePreview.missing.length > 0 && <p className="text-[7px] text-amber-200">Missing {dialoguePreview.missing.join(', ')}; those beats use {dialoguePreview.visemes.find(beat => beat.fallback)?.sourceState ?? 'the remaining mouth'} as fallback.</p>}
        <div className="flex flex-wrap gap-1">{dialoguePreview.visemes.map((beat, index) => <span key={`${beat.start}-${index}`} className={`rounded border px-1 py-0.5 text-[6px] ${liveViseme && liveViseme.start === beat.start && liveViseme.state === beat.state ? 'border-amber-300 text-amber-100' : 'border-border text-text-muted'}`}>{beat.state}{beat.fallback ? `→${beat.sourceState}` : ''}</span>)}</div>
        <button type="button" disabled={disabled || Boolean(busyState)} onClick={playDialogue} className="w-full rounded border border-border px-1 py-1 text-[8px] text-text-secondary">Play visemes</button>
      </div>}
      {dialogueAudio && <audio ref={audioRef} src={getFileUrl(dialogueAudio, workspace)} preload="auto" className="hidden" />}
    </div>
    <p className="text-[7px] text-text-muted">Model: {imageModel || 'current HocusPocus image model'} · reference: {poseId || 'base'}. Drag the overlay or use the sliders, save placement, then approve. Recipes never see pending pieces.</p>
    {error && <p className="text-[8px] text-red-300">{error}</p>}
  </div>
}
