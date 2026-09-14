import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { uploadImage } from '../../api/client'
import { LabsLibraryPick } from '../../lib/LabsLibraryPick'
import { useUiTranslation } from '../../i18n'
import { characterFacePatchPrompt, registerCharacterFacePatch, type FacePatchMetadata } from '../../lib/characterFacePatch'
import { prepareCharacterFacePatch } from '../../lib/prepareCharacterFacePatch'
import { faceRigOverlayPreviewStyle, type CharacterKitFaceRigState } from '../../lib/characterKitFaceRig'
import type { CharacterFaceAnchor, CharacterKit, CharacterKitAsset, CharacterMouthState } from '../../lib/characterKit'
import { CHARACTER_MOUTH_STATES } from '../../lib/characterMouthStates'

const MOUTH_STATES = CHARACTER_MOUTH_STATES
const ACCEPTED_MIME = new Set(['image/png', 'image/jpeg', 'image/webp'])
type PreparedPatch = Awaited<ReturnType<typeof prepareCharacterFacePatch>>
type PrepareService = (poseSource: string, variant: File, anchor: CharacterFaceAnchor) => Promise<PreparedPatch>
type UploadResult = Awaited<ReturnType<typeof uploadImage>>
type UploadService = (file: File) => Promise<UploadResult>

export type CharacterFacePatchPanelProps = {
  kit: CharacterKit
  poseId: string
  state: CharacterKitFaceRigState
  anchor: CharacterFaceAnchor
  workspace: string
  disabled?: boolean
  onChange: (kit: CharacterKit) => void
  onStatus?: (message: string) => void
  /** Test seams; production defaults to local preparation and the existing upload API. */
  prepare?: PrepareService
  upload?: UploadService
}

type InputSnapshot = {
  epoch: object
  kit: CharacterKit
  kitVersion: string
  poseId: string
  poseSource: string
  state: CharacterKitFaceRigState
  anchor: CharacterFaceAnchor
  workspace: string
}
type PreparedRecord = PreparedPatch & { input: InputSnapshot; variant: File }
type OperationSnapshot = InputSnapshot & { token: number; prepared?: PreparedRecord; variant: File }
type Controller = {
  labels: Record<CharacterKitFaceRigState, string>
  prompt: string
  poseSource: string
  disabledReason: string | null
  prepared: PreparedRecord | null
  previewUrl: string | null
  busy: 'prepare' | 'save' | null
  error: string | null
  status: string | null
  onVariantChange: (event: ChangeEvent<HTMLInputElement>) => void
  applyVariant: (variant: File | undefined) => void
  onSave: () => void
}

function normalizedPoseId(value: string) { return value.trim() || 'base' }
function poseFor(kit: CharacterKit, poseId: string) { const id = normalizedPoseId(poseId); return id === 'base' ? kit.base : kit.poses[id] }
function isMouthState(state: CharacterKitFaceRigState): state is CharacterMouthState { return (MOUTH_STATES as readonly string[]).includes(state) }
function sameAnchor(a: CharacterFaceAnchor, b: CharacterFaceAnchor) { return a.offsetX === b.offsetX && a.offsetY === b.offsetY && a.scale === b.scale && a.rotation === b.rotation }
function sameInput(a: InputSnapshot | null, b: InputSnapshot) { return Boolean(a) && a!.epoch === b.epoch && a!.kit === b.kit && a!.kitVersion === b.kitVersion && a!.poseId === b.poseId && a!.poseSource === b.poseSource && a!.state === b.state && a!.workspace === b.workspace && sameAnchor(a!.anchor, b.anchor) }
function objectUrlFor(blob: Blob) { return typeof globalThis.URL?.createObjectURL === 'function' ? globalThis.URL.createObjectURL(blob) : null }
function revokeObjectUrl(url: string | null) { if (url && typeof globalThis.URL?.revokeObjectURL === 'function') globalThis.URL.revokeObjectURL(url) }
function localAssetId() { const uuid = globalThis.crypto?.randomUUID?.(); return `face-patch-${uuid || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}` }
function uploadedUrl(result: UploadResult) {
  if (typeof result.url === 'string' && result.url.trim()) return result.url
  if (typeof result.filename === 'string' && result.filename.trim()) return `/api/v1/uploads/${encodeURIComponent(result.filename)}`
  throw new Error('The upload did not return a saved file URL.')
}
function inputFor(
  kit: CharacterKit,
  poseId: string,
  state: CharacterKitFaceRigState,
  anchor: CharacterFaceAnchor,
  workspace: string,
): InputSnapshot {
  const id = normalizedPoseId(poseId)
  const pose = poseFor(kit, id)
  return {
    epoch: {},
    kit,
    kitVersion: kit.updatedAt ?? '',
    poseId: id,
    poseSource: pose?.source ?? '',
    state,
    anchor: { ...anchor },
    workspace,
  }
}

function patchInputAllowed(props: CharacterFacePatchPanelProps) {
  const id = normalizedPoseId(props.poseId)
  const pose = poseFor(props.kit, id)
  return !props.disabled
    && isMouthState(props.state)
    && Boolean(pose?.source)
    && pose?.reviewState === 'approved'
    && Number.isFinite(props.anchor.rotation)
    && props.anchor.rotation === 0
}

function useCharacterFacePatchController(props: CharacterFacePatchPanelProps): Controller {
  const { t } = useUiTranslation('characters')
  const {
    kit,
    poseId,
    state,
    anchor,
    workspace,
    disabled = false,
    prepare,
    upload,
  } = props
  const id = normalizedPoseId(poseId)
  const pose = poseFor(kit, id)
  const poseSource = pose?.source ?? ''
  const currentInput = useMemo(
    () => inputFor(kit, poseId, state, anchor, workspace),
    [anchor, kit, poseId, state, workspace],
  )
  const latestPropsRef = useRef(props)
  const lastInputRef = useRef(currentInput)
  const mountedRef = useRef(true)
  const tokenRef = useRef(0)
  const activeRef = useRef<OperationSnapshot | null>(null)
  const preparedRef = useRef<PreparedRecord | null>(null)
  const previewRef = useRef<string | null>(null)
  const [prepared, setPrepared] = useState<PreparedRecord | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [active, setActive] = useState<OperationSnapshot | null>(null)
  const [busy, setBusy] = useState<'prepare' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  useLayoutEffect(() => {
    latestPropsRef.current = props
    if (!sameInput(lastInputRef.current, currentInput)) {
      tokenRef.current += 1
      activeRef.current = null
      preparedRef.current = null
      revokeObjectUrl(previewRef.current)
      previewRef.current = null
    }
    lastInputRef.current = currentInput
  }, [currentInput, props])
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      tokenRef.current += 1
      activeRef.current = null
      preparedRef.current = null
      revokeObjectUrl(previewRef.current)
      previewRef.current = null
    }
  }, [])

  const announce = (message: string) => {
    if (mountedRef.current) {
      setStatus(message)
      latestPropsRef.current.onStatus?.(message)
    }
  }
  const replacePreview = (next: string | null) => {
    revokeObjectUrl(previewRef.current)
    previewRef.current = next
    setPreviewUrl(next)
  }
  const clearPrepared = () => {
    preparedRef.current = null
    setPrepared(null)
    replacePreview(null)
  }
  const cancelStale = (snapshot: OperationSnapshot) => {
    if (!mountedRef.current || tokenRef.current !== snapshot.token || activeRef.current !== snapshot) return
    tokenRef.current += 1
    activeRef.current = null
    setActive(null)
    clearPrepared()
    setBusy(null)
    setError(null)
    announce(t('facePatch.status.cancelled'))
  }
  const isCurrent = (snapshot: OperationSnapshot) => {
    if (!mountedRef.current || tokenRef.current !== snapshot.token || activeRef.current !== snapshot) return false
    const latest = latestPropsRef.current
    const latestId = normalizedPoseId(latest.poseId)
    return patchInputAllowed(latest)
      && latest.kit === snapshot.kit
      && (latest.kit.updatedAt ?? '') === snapshot.kitVersion
      && latestId === snapshot.poseId
      && (poseFor(latest.kit, latestId)?.source ?? '') === snapshot.poseSource
      && latest.state === snapshot.state
      && latest.workspace === snapshot.workspace
      && sameAnchor(latest.anchor, snapshot.anchor)
      && (!snapshot.prepared || preparedRef.current === snapshot.prepared)
  }
  const labels: Record<CharacterKitFaceRigState, string> = {
    closed: t('faceRig.states.closed'),
    small: t('faceRig.states.small'),
    wide: t('faceRig.states.wide'),
    round: t('faceRig.states.round'),
    pressed: t('faceRig.states.pressed'), medium: t('faceRig.states.medium'), pucker: t('faceRig.states.pucker'),
    bite: t('faceRig.states.bite'), tongue: t('faceRig.states.tongue'),
    'open-eyes': t('faceRig.states.open-eyes'),
    blink: t('faceRig.states.blink'),
  }
  const mouthState = isMouthState(state)
  const prompt = mouthState ? characterFacePatchPrompt(kit.name, state) : ''
  const disabledReason = disabled
    ? t('facePatch.disabled.external')
    : !mouthState
      ? t('facePatch.disabled.eyes')
      : !pose?.source || pose.reviewState !== 'approved'
        ? t('facePatch.disabled.pose')
        : !Number.isFinite(anchor.rotation) || anchor.rotation !== 0
          ? t('facePatch.disabled.rotation')
          : null
  const activeIsCurrent = Boolean(active && sameInput(active, currentInput))
  const preparedIsCurrent = Boolean(prepared && sameInput(prepared.input, currentInput))
  const staleVisible = Boolean((active && !activeIsCurrent) || (prepared && !preparedIsCurrent))
  const currentPrepared = preparedIsCurrent ? prepared : null
  const visibleBusy = activeIsCurrent ? busy : null

  const beginRequest = () => {
    tokenRef.current += 1
    activeRef.current = null
    setActive(null)
    clearPrepared()
    setError(null)
    setStatus(null)
    return tokenRef.current
  }
  const applyVariant = (variant: File | undefined) => {
    if (!patchInputAllowed(latestPropsRef.current)) {
      setError(disabledReason ?? t('facePatch.disabled.external'))
      return
    }
    const token = beginRequest()
    if (!variant) return
    if (!ACCEPTED_MIME.has(variant.type) && !/\.(?:png|jpe?g|webp)$/i.test(variant.name)) {
      setError(t('facePatch.errors.fileType'))
      return
    }
    const snapshot: OperationSnapshot = { ...currentInput, token, variant }
    activeRef.current = snapshot
    setActive(snapshot)
    setBusy('prepare')
    const service = prepare ?? (async (...args: Parameters<typeof prepareCharacterFacePatch>) => prepareCharacterFacePatch(...args))
    void (async () => {
      try {
        const result = await service(snapshot.poseSource, variant, snapshot.anchor)
        const nextUrl = objectUrlFor(result.blob)
        if (!isCurrent(snapshot)) { revokeObjectUrl(nextUrl); cancelStale(snapshot); return }
        const record: PreparedRecord = { ...result, input: snapshot, variant }
        preparedRef.current = record
        setPrepared(record)
        replacePreview(nextUrl)
        activeRef.current = null
        setActive(null)
        setBusy(null)
        setError(null)
        announce(t('facePatch.status.prepared'))
      } catch (cause) {
        if (!isCurrent(snapshot)) { cancelStale(snapshot); return }
        activeRef.current = null
        setActive(null)
        setBusy(null)
        setError(cause instanceof Error ? cause.message : t('facePatch.errors.prepare'))
      }
    })()
  }
  const onSave = () => {
    if (!patchInputAllowed(latestPropsRef.current)) {
      setError(disabledReason ?? t('facePatch.disabled.external'))
      return
    }
    if (!currentPrepared) {
      setError(t('facePatch.errors.noPrepared'))
      return
    }
    const snapshot: OperationSnapshot = {
      ...currentPrepared.input,
      token: tokenRef.current,
      prepared: currentPrepared,
      variant: currentPrepared.variant,
    }
    activeRef.current = snapshot
    setActive(snapshot)
    setBusy('save')
    setError(null)
    setStatus(null)
    const service = upload ?? uploadImage
    void (async () => {
      try {
        const variantSource = uploadedUrl(await service(snapshot.variant))
        if (!isCurrent(snapshot)) { cancelStale(snapshot); return }
        const assetId = localAssetId()
        const patchFile = new File([snapshot.prepared!.blob], `${assetId}.png`, { type: 'image/png' })
        const patchSource = uploadedUrl(await service(patchFile))
        if (!isCurrent(snapshot)) { cancelStale(snapshot); return }
        const asset: CharacterKitAsset = {
          id: assetId,
          name: `${snapshot.kit.name} · ${labels[snapshot.state]} raster patch`,
          source: patchSource,
          kind: 'overlay',
          alphaStatus: snapshot.prepared!.metadata.feather === 0 ? 'opaque' : 'transparent',
          reviewState: 'pending',
          workspace: snapshot.workspace,
        }
        const metadata: FacePatchMetadata = {
          ...snapshot.prepared!.metadata,
          poseId: snapshot.poseId,
          variantSource,
        }
        const next = registerCharacterFacePatch(
          snapshot.kit,
          snapshot.poseId,
          snapshot.state as CharacterMouthState,
          asset,
          metadata,
        )
        if (!isCurrent(snapshot)) { cancelStale(snapshot); return }
        activeRef.current = null
        setActive(null)
        clearPrepared()
        setBusy(null)
        setError(null)
        announce(t('facePatch.status.savedPending'))
        latestPropsRef.current.onChange(next)
      } catch (cause) {
        if (!isCurrent(snapshot)) { cancelStale(snapshot); return }
        activeRef.current = null
        setActive(null)
        setBusy(null)
        setError(cause instanceof Error ? cause.message : t('facePatch.errors.upload'))
      }
    })()
  }
  return {
    labels,
    prompt,
    poseSource,
    disabledReason,
    prepared: currentPrepared,
    previewUrl: currentPrepared ? previewUrl : null,
    busy: visibleBusy,
    error: staleVisible ? null : error,
    status: staleVisible ? t('facePatch.status.cancelled') : status,
    onVariantChange: (event: ChangeEvent<HTMLInputElement>) => {
      const variant = event.target.files?.[0]
      event.target.value = ''
      applyVariant(variant)
    },
    applyVariant,
    onSave,
  }
}

export function CharacterFacePatchPanel(props: CharacterFacePatchPanelProps) {
  const { t } = useUiTranslation('characters')
  const controller = useCharacterFacePatchController(props)
  const { kit, anchor } = props
  const fileDisabled = Boolean(controller.disabledReason) || Boolean(controller.busy)
  const saveDisabled = fileDisabled || !controller.prepared

  return (
    <section data-testid="character-face-patch-panel" className="space-y-1.5 rounded border border-violet-300/30 bg-violet-400/[.04] p-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-medium text-violet-100">{t('facePatch.title')}</h3>
        <span className="text-[8px] text-violet-200/75">{controller.labels[props.state]}</span>
      </div>
      <p className="text-[9px] leading-relaxed text-text-secondary">{t('facePatch.experimental')}</p>
      <p className="text-[9px] leading-relaxed text-amber-100">{t('facePatch.keepTexture')}</p>
      <p className="text-[9px] leading-relaxed text-text-muted">{t('facePatch.alignment')}</p>
      <label className="block text-[8px] text-text-muted" htmlFor="character-face-patch-prompt">
        {t('facePatch.promptLabel')}
        <textarea id="character-face-patch-prompt" readOnly rows={5} value={controller.prompt} className="mt-0.5 w-full resize-y rounded border border-border bg-bg-primary px-1.5 py-1 text-[8px] leading-relaxed text-text-secondary" />
      </label>
      {controller.disabledReason && <p role="alert" className="rounded border border-amber-300/30 bg-amber-400/10 p-1 text-[9px] text-amber-100">{controller.disabledReason}</p>}
      <div className="space-y-1 rounded border border-border/70 bg-black/20 p-1">
        {controller.poseSource && (
          <div className="relative aspect-square overflow-hidden rounded border border-border bg-bg-primary">
            <img src={controller.poseSource} alt={t('facePatch.poseAlt', { name: kit.name })} className="absolute inset-0 h-full w-full object-contain" draggable={false} />
            {controller.previewUrl && <img src={controller.previewUrl} alt={t('facePatch.previewAlt', { state: controller.labels[props.state] })} className="absolute object-contain" style={faceRigOverlayPreviewStyle(anchor)} draggable={false} />}
          </div>
        )}
        <p className="text-[8px] text-text-secondary">{t('facePatch.variantHint')}</p>
        <label className="block text-[9px] text-text-secondary">
          {t('facePatch.variantLabel')}
          <input type="file" accept="image/png,image/jpeg,image/webp" disabled={fileDisabled} onChange={controller.onVariantChange} className="mt-0.5 block w-full text-[8px] text-text-muted file:mr-1 file:rounded file:border-0 file:bg-violet-400/20 file:px-1 file:py-0.5 file:text-[8px] file:text-violet-100" />
        </label>
        <LabsLibraryPick workspace={props.workspace} disabled={fileDisabled} onFile={file => controller.applyVariant(file)} />
        <button type="button" disabled={saveDisabled} onClick={controller.onSave} className="w-full rounded border border-violet-300/50 bg-violet-400/10 px-1 py-1.5 text-[9px] text-violet-100 disabled:opacity-40">
          {controller.busy === 'prepare' ? t('facePatch.status.preparing') : controller.busy === 'save' ? t('facePatch.status.saving') : t('facePatch.savePending')}
        </button>
      </div>
      {controller.error && <p role="alert" className="text-[9px] text-red-200">{controller.error}</p>}
      {controller.status && <p role="status" className="text-[9px] text-emerald-100">{controller.status}</p>}
    </section>
  )
}
