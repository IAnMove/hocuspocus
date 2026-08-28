import { useMemo, useState } from 'react'
import { generateImageAsset } from '../../lib/imageGeneration'
import {
  CHARACTER_FACE_RIG_STATES,
  classifyCharacterKitAlpha,
  faceRigGenerationRequests,
  registerGeneratedFaceRigAsset,
  setFaceRigReviewState,
  type CharacterKitFaceRigState,
} from '../../lib/characterKitFaceRig'
import type { CharacterKit, CharacterKitAsset, CharacterMouthState } from '../../lib/characterKit'
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
  const workspace = useStore(state => state.activeWorkspace)
  const [selectedState, setSelectedState] = useState<CharacterKitFaceRigState>('wide')
  const [description, setDescription] = useState('')
  const [busyState, setBusyState] = useState<CharacterKitFaceRigState | 'pack' | null>(null)
  const [error, setError] = useState<string | null>(null)

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

  const generateSelected = async () => {
    setBusyState(selectedState); setError(null)
    try {
      const next = await generateState(kit, selectedState)
      onChange(next); onStatus?.(`${LABELS[selectedState]} generated as pending review.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Face Rig generation failed.')
    } finally { setBusyState(null) }
  }

  const generateMissingPack = async () => {
    setBusyState('pack'); setError(null)
    try {
      let next = kit
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
    <p className="text-[8px] leading-relaxed text-text-muted">Generate reusable mouth and blink overlays from the approved pose. Outputs stay pending until you verify transparency and placement; recipes never see pending pieces.</p>
    <label className="block text-[8px] text-text-muted">Identity / art notes (optional)<textarea value={description} disabled={disabled || Boolean(busyState)} onChange={event => setDescription(event.target.value)} rows={2} placeholder="Flat paper-cut texture, thick uneven black outline…" className="mt-0.5 w-full resize-y rounded border border-border bg-bg-primary px-1.5 py-1 text-[8px]" /></label>
    <div className="grid grid-cols-5 gap-1">{CHARACTER_FACE_RIG_STATES.map(state => {
      const asset = assetFor(kit, state)
      return <button key={state} type="button" disabled={disabled || Boolean(busyState)} onClick={() => setSelectedState(state)} className={`rounded border px-1 py-1 text-[7px] ${selectedState === state ? 'border-emerald-300 bg-emerald-400/15 text-emerald-100' : 'border-border text-text-muted'}`}>{LABELS[state]}<span className="block text-[6px]">{asset?.reviewState ?? 'missing'}</span></button>
    })}</div>
    {selectedRequest && <details className="rounded border border-border/70 bg-black/10 px-1.5 py-1"><summary className="cursor-pointer text-[7px] text-text-muted">Prompt used for {LABELS[selectedState]}</summary><p className="mt-1 select-text text-[7px] leading-relaxed text-text-secondary">{selectedRequest.prompt}</p></details>}
    {assetFor(kit, selectedState) && <div className="space-y-1 rounded border border-emerald-300/20 bg-[linear-gradient(45deg,#1c2330_25%,transparent_25%),linear-gradient(-45deg,#1c2330_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1c2330_75%),linear-gradient(-45deg,transparent_75%,#1c2330_75%)] bg-[length:12px_12px] p-1.5">
      <img src={assetFor(kit, selectedState)!.source} alt={`${kit.name} ${LABELS[selectedState]}`} className="mx-auto h-28 w-full object-contain" />
      <div className="flex items-center justify-between text-[7px]"><span className="truncate text-text-secondary">{assetFor(kit, selectedState)!.name}</span><span className="text-emerald-100">{assetFor(kit, selectedState)!.alphaStatus} · {assetFor(kit, selectedState)!.reviewState}</span></div>
      <div className="grid grid-cols-2 gap-1"><button type="button" disabled={disabled || Boolean(busyState) || assetFor(kit, selectedState)!.alphaStatus !== 'transparent'} onClick={() => review(selectedState, true)} className="rounded border border-emerald-300/40 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">Approve transparent</button><button type="button" disabled={disabled || Boolean(busyState)} onClick={() => review(selectedState, false)} className="rounded border border-red-300/30 px-1 py-1 text-[8px] text-red-200">Reject</button></div>
    </div>}
    <div className="grid grid-cols-2 gap-1"><button type="button" disabled={disabled || Boolean(busyState) || !selectedRequest} onClick={() => void generateSelected()} className="rounded border border-emerald-300/50 bg-emerald-400/10 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{busyState === selectedState ? `Generating ${LABELS[selectedState]}…` : `Generate / replace ${LABELS[selectedState]}`}</button><button type="button" disabled={disabled || Boolean(busyState) || !requests.length} onClick={() => void generateMissingPack()} className="rounded border border-emerald-300/30 px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{busyState === 'pack' ? 'Generating pack…' : 'Generate missing pack'}</button></div>
    <p className="text-[7px] text-text-muted">Model: {imageModel || 'current HocusPocus image model'} · reference: {poseId || 'base'}. After approval, mount the pose and capture each state anchor in the scene.</p>
    {error && <p className="text-[8px] text-red-300">{error}</p>}
  </div>
}
