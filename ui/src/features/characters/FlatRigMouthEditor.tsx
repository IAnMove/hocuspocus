import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { fetchCharacterKitLibrary, previewFlatRigMouth, rigFlatCharacter, type FlatRigMouthPreview, type FlatRigResult } from '../../api/characters'
import { useUiTranslation } from '../../i18n'
import { characterKitPoseHasOwnMouths, type CharacterKit } from '../../lib/characterKit'
import {
  MOUTH_LINE_PREVIEW_STATES, cleanMouthLine, flatRigPoseSource, imageToZoom, isFlatRigged, isWarpRigged, mouthLineRigRequest,
  mouthZoom, sameMouthLine, savedMouthLine, zoomImageStyle, zoomToImage, type MouthLineDraft, type MouthZoom,
} from '../../lib/flatRigMouth'
import { characterKitPoseLabel } from './characterKitGuide'

type Props = {
  kit: CharacterKit
  poseId: string
  workspace: string
  disabled?: boolean
  /** Saving re-rigs the saved kit on the server; the parent takes the result (reloads its library). Without it the
   * editor only previews. */
  onRigged?: (result: FlatRigResult) => void | Promise<void>
  onBusyChange?: (busy: boolean) => void
}

type Drag = { pointerId: number; mode: 'move' | 'left' | 'right' }
const NUDGE = 0.1
const handle = 'absolute flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 touch-none items-center justify-center rounded-full'
const button = 'min-h-9 rounded border border-border px-2 py-1 text-xs text-text-secondary disabled:opacity-40'

/** The mouth line of one pose, placed by hand on its face, with its warp mouths previewed live (flat rig). */
export function FlatRigMouthEditor(props: Props) {
  const { t } = useUiTranslation('characters')
  const warp = isWarpRigged(props.kit)
  const [open, setOpen] = useState(warp)
  if (!isFlatRigged(props.kit)) return null
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} className="rounded border border-amber-300/30 bg-black/15 p-2">
    <summary className="cursor-pointer text-sm font-medium text-amber-100">{t('mouthLine.title', { pose: characterKitPoseLabel(props.poseId) })}</summary>
    {open && <MouthLineWorkbench key={`${props.kit.id}:${props.poseId}`} {...props} />}
  </details>
}

function MouthLineWorkbench({ kit, poseId, workspace, disabled = false, onRigged, onBusyChange }: Props) {
  const { t } = useUiTranslation('characters')
  const source = flatRigPoseSource(kit, poseId)
  const saved = useMemo(() => savedMouthLine(kit, poseId), [kit, poseId])
  const savedKey = JSON.stringify(saved ?? null)
  const [baseline, setBaseline] = useState<MouthLineDraft | undefined>(saved)
  const [draft, setDraft] = useState<MouthLineDraft | undefined>(saved)
  const [preview, setPreview] = useState<FlatRigMouthPreview | null>(null)
  const [aspect, setAspect] = useState<number | null>(null)
  const [spread, setSpread] = useState(false)
  const [zoom, setZoom] = useState<MouthZoom | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<Drag | null>(null)
  const requestRef = useRef<{ busy: boolean; queued?: MouthLineDraft | null; controller?: AbortController }>({ busy: false })
  const draftRef = useRef(draft)
  draftRef.current = draft
  const locked = disabled || saving
  const pose = characterKitPoseLabel(poseId)

  useEffect(() => { onBusyChange?.(saving) }, [saving, onBusyChange])
  useEffect(() => () => { requestRef.current.controller?.abort(); onBusyChange?.(false) }, [onBusyChange])
  // A save (or another tab) moves the saved line: start again from it.
  useEffect(() => {
    const line = savedKey === 'null' ? undefined : JSON.parse(savedKey) as MouthLineDraft
    setBaseline(line); setDraft(line); setZoom(null)
  }, [savedKey])

  const run = async (value: MouthLineDraft | undefined) => {
    const state = requestRef.current
    if (state.busy) { state.queued = value ?? null; return }
    state.busy = true; state.controller = new AbortController(); setLoading(true)
    try {
      const result = await previewFlatRigMouth({ workspace, kitId: kit.id, pose: poseId, signal: state.controller.signal,
        ...(value ? { mouth: value.mouth, mouthWidth: value.mouthWidth } : {}) })
      setPreview(result); setError(null)
      if (!draftRef.current) {
        // Nothing saved: start from where the rig places the line.
        const start = cleanMouthLine({ mouth: result.mouth, mouthWidth: result.mouthWidth })
        setBaseline(start); setDraft(start)
      }
    } catch (cause) {
      if (!state.controller.signal.aborted) setError(cause instanceof Error ? cause.message : t('mouthLine.errors.preview'))
    } finally {
      state.busy = false
      if (!state.controller.signal.aborted) setLoading(false)
      if (state.queued !== undefined) {
        const next = state.queued ?? undefined
        state.queued = undefined
        void run(next)
      }
    }
  }
  const draftKey = JSON.stringify(draft ?? null)
  useEffect(() => {
    const timer = window.setTimeout(() => { void run(draftRef.current) }, 120)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one preview per change of the line
  }, [draftKey, kit.id, poseId, workspace])
  useEffect(() => {
    if (draft && aspect && !zoom) setZoom(mouthZoom(draft, aspect, spread ? 9 : 4.5))
  }, [draft, aspect, zoom, spread])

  const pointAt = (event: ReactPointerEvent): [number, number] | null => {
    const box = boxRef.current?.getBoundingClientRect()
    if (!box || !zoom) return null
    return zoomToImage(zoom, (event.clientX - box.left) / Math.max(1, box.width), (event.clientY - box.top) / Math.max(1, box.height))
  }
  const update = (next: MouthLineDraft) => { setNote(null); setDraft(cleanMouthLine(next)) }
  const startDrag = (event: ReactPointerEvent<HTMLElement>, mode: Drag['mode']) => {
    if (locked || !draft) return
    event.preventDefault(); event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, mode }
    if (mode === 'move') { const point = pointAt(event); if (point) update({ ...draft, mouth: point }) }
  }
  const moveDrag = (event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current, current = draftRef.current
    if (!drag || drag.pointerId !== event.pointerId || !current) return
    const point = pointAt(event)
    if (!point) return
    update(drag.mode === 'move' ? { ...current, mouth: point } : { ...current, mouthWidth: Math.abs(point[0] - current.mouth[0]) * 2 })
  }
  const endDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null
  }
  const nudge = (dx: number, dy: number, dw = 0) => {
    if (!draft || locked) return
    update({ mouth: [draft.mouth[0] + dx, draft.mouth[1] + dy], mouthWidth: draft.mouthWidth + dw })
  }
  const reframe = (wide: boolean) => {
    setSpread(wide)
    if (draft && aspect) setZoom(mouthZoom(draft, aspect, wide ? 9 : 4.5))
  }

  const save = async () => {
    if (!onRigged || !draft || locked) return
    setSaving(true); setError(null); setNote(null)
    try {
      const library = await fetchCharacterKitLibrary(workspace)
      const stored = library.kits[kit.id]
      if (!stored || JSON.stringify(stored) !== JSON.stringify(kit)) throw new Error(t('mouthLine.errors.unsaved'))
      const result = await rigFlatCharacter({ workspace, kitId: kit.id, baseRevision: library.revision, ...mouthLineRigRequest(kit, poseId, draft) })
      setNote(t('mouthLine.saved', { pose }))
      await onRigged(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('mouthLine.errors.save'))
    } finally { setSaving(false) }
  }

  const dot = draft && zoom ? imageToZoom(zoom, draft.mouth[0], draft.mouth[1]) : null
  const ends = draft && zoom ? [imageToZoom(zoom, draft.mouth[0] - draft.mouthWidth / 2, draft.mouth[1]),
    imageToZoom(zoom, draft.mouth[0] + draft.mouthWidth / 2, draft.mouth[1])] : null
  const line = preview && zoom ? preview.line.map(([x, y]) => imageToZoom(zoom, x, y).join(',')).join(' ') : ''
  const dirty = Boolean(draft && !sameMouthLine(draft, baseline))
  const warp = isWarpRigged(kit)

  return <div className="mt-2 space-y-2">
    <p className="text-xs leading-relaxed text-text-secondary">{t('mouthLine.intro')}</p>
    {!warp && <p className="text-xs text-amber-200">{t('mouthLine.notWarp')}</p>}
    {warp && poseId !== 'base' && !characterKitPoseHasOwnMouths(kit, poseId) && <p className="text-xs text-amber-200">{t('mouthLine.noOwn')}</p>}
    <div className="grid gap-3 @3xl:grid-cols-2">
      <div className="space-y-2">
        <div ref={boxRef} data-testid="mouth-line-zoom" className="relative aspect-square touch-none overflow-hidden rounded border border-border bg-bg-primary"
          onPointerDown={event => startDrag(event, 'move')} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
          {source && <img src={source} alt={t('mouthLine.zoomAlt', { name: kit.name })} draggable={false}
            onLoad={event => setAspect(event.currentTarget.naturalWidth / Math.max(1, event.currentTarget.naturalHeight))}
            className={`pointer-events-none absolute max-w-none select-none ${zoom ? '' : 'invisible'}`} style={zoom ? zoomImageStyle(zoom) : undefined} />}
          {line && <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
            <polyline points={line} fill="none" stroke={preview?.found ? '#6ee7b7' : '#fcd34d'} strokeWidth={0.6} strokeDasharray={preview?.found ? undefined : '2 1.5'} />
          </svg>}
          {ends?.map(([x, y], index) => <span key={index} role="button" tabIndex={-1} aria-label={t(index ? 'mouthLine.right' : 'mouthLine.left')}
            className={`${handle} cursor-ew-resize`} style={{ left: `${x}%`, top: `${y}%` }}
            onPointerDown={event => startDrag(event, index ? 'right' : 'left')} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
            <span className="h-4 w-1.5 rounded-sm border border-black/60 bg-amber-300" />
          </span>)}
          {dot && <span role="button" tabIndex={-1} aria-label={t('mouthLine.dot')} data-testid="mouth-line-dot"
            className={`${handle} cursor-move`} style={{ left: `${dot[0]}%`, top: `${dot[1]}%` }}
            onPointerDown={event => startDrag(event, 'move')} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
            <span className="h-3.5 w-3.5 rounded-full border-2 border-black/70 bg-emerald-300" />
          </span>}
        </div>
        <div className="grid grid-cols-4 gap-1">
          <button type="button" className={button} disabled={locked || !draft} onClick={() => nudge(0, -NUDGE)}>{t('mouthLine.nudge.up')}</button>
          <button type="button" className={button} disabled={locked || !draft} onClick={() => nudge(0, NUDGE)}>{t('mouthLine.nudge.down')}</button>
          <button type="button" className={button} disabled={locked || !draft} onClick={() => nudge(-NUDGE, 0)}>{t('mouthLine.nudge.left')}</button>
          <button type="button" className={button} disabled={locked || !draft} onClick={() => nudge(NUDGE, 0)}>{t('mouthLine.nudge.right')}</button>
          <button type="button" className={button} disabled={locked || !draft} onClick={() => nudge(0, 0, -2 * NUDGE)}>{t('mouthLine.nudge.narrower')}</button>
          <button type="button" className={button} disabled={locked || !draft} onClick={() => nudge(0, 0, 2 * NUDGE)}>{t('mouthLine.nudge.wider')}</button>
          <button type="button" className={`${button} col-span-2`} disabled={!draft} onClick={() => reframe(!spread)}>{t(spread ? 'mouthLine.zoomIn' : 'mouthLine.zoomOut')}</button>
        </div>
      </div>
      <div className="space-y-2">
        <p aria-live="polite" className="text-xs text-text-secondary">{loading ? t('mouthLine.loading') : preview ? t(preview.found ? 'mouthLine.snapped' : 'mouthLine.free') : ''}</p>
        {preview?.warnings?.includes('mouth_line_unsure') && !dirty && <p className="text-xs text-amber-200">{t('mouthLine.unsure')}</p>}
        <div className="grid grid-cols-3 gap-1">
          {MOUTH_LINE_PREVIEW_STATES.map(({ state, sound }) => <figure key={state} className="overflow-hidden rounded border border-border bg-black/30">
            {preview?.states[state]
              ? <img src={preview.states[state]} alt={t('mouthLine.stateAlt', { name: kit.name, sound: t(`mouthLine.sounds.${sound}`) })} className={`aspect-square w-full object-cover ${loading ? 'opacity-70' : ''}`} />
              : <div className="aspect-square w-full animate-pulse bg-bg-active" />}
            <figcaption className="py-0.5 text-center text-xs text-text-secondary">{t(`mouthLine.sounds.${sound}`)}</figcaption>
          </figure>)}
        </div>
        <div className="grid grid-cols-2 gap-1">
          <button type="button" className={button} disabled={locked || !dirty} onClick={() => { setNote(null); setDraft(baseline) }}>{t('mouthLine.undo')}</button>
          <button type="button" disabled={locked || !onRigged || !draft || (!dirty && warp && characterKitPoseHasOwnMouths(kit, poseId))} onClick={() => void save()}
            className="min-h-9 rounded border border-emerald-300/50 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-100 disabled:opacity-40">
            {saving ? t('mouthLine.saving') : t('mouthLine.save')}</button>
        </div>
        {!onRigged && <p className="text-xs text-text-muted">{t('mouthLine.previewOnly')}</p>}
        {note && <p role="status" className="text-xs text-emerald-200">{note}</p>}
        {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
      </div>
    </div>
  </div>
}
