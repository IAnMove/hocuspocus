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
  /** Other Face Rig work is running: the editor waits. */
  busy?: boolean
  /** Saving re-rigs the saved kit on the server; the parent takes the result (reloads its library). Without it the
   * editor only previews. */
  onRigged?: (result: FlatRigResult) => void | Promise<void>
  onBusyChange?: (busy: boolean) => void
}

type Drag = { pointerId: number; mode: 'move' | 'left' | 'right' }
const NUDGE = 0.1
const handle = 'absolute flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 touch-none items-center justify-center rounded-full'
const button = 'min-h-9 rounded border border-border px-2 py-1 text-xs text-text-secondary disabled:opacity-40'
const message = (cause: unknown, fallback: string) => cause instanceof Error ? cause.message : fallback

/** The mouth line of one pose, placed by hand on its face, with its warp mouths previewed live (flat rig). */
export function FlatRigMouthEditor(props: Props) {
  const { t } = useUiTranslation('characters')
  const [open, setOpen] = useState(() => isWarpRigged(props.kit))
  if (!isFlatRigged(props.kit)) return null
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)} data-testid="flat-rig-mouth-line" className="rounded border border-amber-300/30 bg-black/15 p-2">
    <summary className="cursor-pointer text-sm font-medium text-amber-100">{t('mouthLine.title', { pose: characterKitPoseLabel(props.poseId) })}</summary>
    {open && <MouthLineWorkbench key={`${props.kit.id}:${props.poseId}`} {...props} />}
  </details>
}

/** One preview in flight at a time; a line moved meanwhile is previewed next (the latest only). */
function useMouthLinePreview(kit: CharacterKit, poseId: string, workspace: string, draft: MouthLineDraft | undefined,
  onFirst: (line: MouthLineDraft) => void) {
  const { t } = useUiTranslation('characters')
  const [preview, setPreview] = useState<FlatRigMouthPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const state = useRef<{ busy: boolean; queued?: MouthLineDraft | null; controller?: AbortController }>({ busy: false })
  const latest = useRef({ draft, onFirst })
  useEffect(() => { latest.current = { draft, onFirst } })
  const run = async (value: MouthLineDraft | undefined) => {
    const current = state.current
    if (current.busy) { current.queued = value ?? null; return }
    const controller = new AbortController()
    Object.assign(current, { busy: true, controller }); setLoading(true)
    try {
      const result = await previewFlatRigMouth({ workspace, kitId: kit.id, pose: poseId, signal: controller.signal,
        ...(value ? { mouth: value.mouth, mouthWidth: value.mouthWidth } : {}) })
      setPreview(result); setError(null)
      // Nothing saved: start from where the rig places the line.
      if (!latest.current.draft) latest.current.onFirst(cleanMouthLine({ mouth: result.mouth, mouthWidth: result.mouthWidth }))
    } catch (cause) {
      if (!controller.signal.aborted) setError(message(cause, t('mouthLine.errors.preview')))
    } finally {
      current.busy = false
      if (!controller.signal.aborted) setLoading(false)
      const next = current.queued
      current.queued = undefined
      if (next !== undefined) void run(next ?? undefined)
    }
  }
  const key = JSON.stringify(draft ?? null)
  useEffect(() => {
    const timer = window.setTimeout(() => { void run(latest.current.draft) }, 120)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one preview per change of the line
  }, [key, kit.id, poseId, workspace])
  useEffect(() => () => state.current.controller?.abort(), [])
  return { preview, loading, error }
}

function MouthLineWorkbench({ kit, poseId, workspace, disabled = false, busy = false, onRigged, onBusyChange }: Props) {
  const { t } = useUiTranslation('characters')
  const saved = useMemo(() => savedMouthLine(kit, poseId), [kit, poseId])
  const savedKey = JSON.stringify(saved ?? null)
  const [baseline, setBaseline] = useState<MouthLineDraft | undefined>(saved)
  const [draft, setDraft] = useState<MouthLineDraft | undefined>(saved)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const start = (line: MouthLineDraft | undefined) => { setBaseline(line); setDraft(line) }
  const { preview, loading, error } = useMouthLinePreview(kit, poseId, workspace, draft, start)
  const locked = disabled || busy || saving
  const warp = isWarpRigged(kit)
  const own = characterKitPoseHasOwnMouths(kit, poseId)
  const dirty = Boolean(draft && !sameMouthLine(draft, baseline))

  useEffect(() => { onBusyChange?.(saving) }, [saving, onBusyChange])
  useEffect(() => () => onBusyChange?.(false), [onBusyChange])
  // A save (or another tab) moves the saved line: start again from it.
  useEffect(() => { start(savedKey === 'null' ? undefined : JSON.parse(savedKey) as MouthLineDraft) }, [savedKey])

  const change = (next: MouthLineDraft) => { setNote(null); setDraft(cleanMouthLine(next)) }
  const save = async () => {
    if (!onRigged || !draft || locked) return
    setSaving(true); setFailure(null); setNote(null)
    try {
      const library = await fetchCharacterKitLibrary(workspace)
      const stored = library.kits[kit.id]
      if (!stored || JSON.stringify(stored) !== JSON.stringify(kit)) throw new Error(t('mouthLine.errors.unsaved'))
      const result = await rigFlatCharacter({ workspace, kitId: kit.id, baseRevision: library.revision, ...mouthLineRigRequest(kit, poseId, draft) })
      setNote(t('mouthLine.saved', { pose: characterKitPoseLabel(poseId) }))
      await onRigged(result)
    } catch (cause) {
      setFailure(message(cause, t('mouthLine.errors.save')))
    } finally { setSaving(false) }
  }

  return <div className="mt-2 space-y-2">
    <p className="text-xs leading-relaxed text-text-secondary">{t('mouthLine.intro')}</p>
    {!warp && <p className="text-xs text-amber-200">{t('mouthLine.notWarp')}</p>}
    {warp && !own && <p className="text-xs text-amber-200">{t('mouthLine.noOwn')}</p>}
    <div className="grid gap-3 @3xl:grid-cols-2">
      <MouthLineZoom kit={kit} poseId={poseId} draft={draft} preview={preview} locked={locked} onChange={change} />
      <div className="space-y-2">
        <MouthLineStates name={kit.name} preview={preview} loading={loading} dirty={dirty} />
        <div className="grid grid-cols-2 gap-1">
          <button type="button" className={button} disabled={locked || !dirty} onClick={() => { setNote(null); setDraft(baseline) }}>{t('mouthLine.undo')}</button>
          <button type="button" disabled={locked || !onRigged || !draft || (!dirty && warp && own)} onClick={() => void save()}
            className="min-h-9 rounded border border-emerald-300/50 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-100 disabled:opacity-40">
            {t(saving ? 'mouthLine.saving' : 'mouthLine.save')}</button>
        </div>
        {!onRigged && <p className="text-xs text-text-muted">{t('mouthLine.previewOnly')}</p>}
        {note && <p role="status" className="text-xs text-emerald-200">{note}</p>}
        {(failure || error) && <p role="alert" className="text-xs text-red-300">{failure || error}</p>}
      </div>
    </div>
  </div>
}

/** The face zoomed in round the mouth: a point on the line and the two corners, dragged or nudged. */
function MouthLineZoom({ kit, poseId, draft, preview, locked, onChange }: { kit: CharacterKit; poseId: string
  draft?: MouthLineDraft; preview: FlatRigMouthPreview | null; locked: boolean; onChange: (draft: MouthLineDraft) => void }) {
  const { t } = useUiTranslation('characters')
  const source = flatRigPoseSource(kit, poseId)
  const [aspect, setAspect] = useState<number | null>(null)
  const [spread, setSpread] = useState(false)
  const [frame, setFrame] = useState<MouthZoom | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<Drag | null>(null)
  // The window stays put while the line moves; it is placed once the line and the image size are known.
  const zoom = frame ?? (draft && aspect ? mouthZoom(draft, aspect, 4.5) : null)
  const reframe = (wide: boolean) => { setSpread(wide); if (draft && aspect) setFrame(mouthZoom(draft, aspect, wide ? 9 : 4.5)) }

  const pointAt = (event: ReactPointerEvent): [number, number] | null => {
    const box = boxRef.current?.getBoundingClientRect()
    if (!box || !zoom) return null
    return zoomToImage(zoom, (event.clientX - box.left) / Math.max(1, box.width), (event.clientY - box.top) / Math.max(1, box.height))
  }
  // A drag moves the point or one corner: what it does not move is the same in the line of any render.
  const follow = (event: ReactPointerEvent, mode: Drag['mode']) => {
    const point = pointAt(event)
    if (!point || !draft) return
    if (zoom && !frame) setFrame(zoom)
    onChange(mode === 'move' ? { ...draft, mouth: point } : { ...draft, mouthWidth: Math.abs(point[0] - draft.mouth[0]) * 2 })
  }
  const startDrag = (event: ReactPointerEvent<HTMLElement>, mode: Drag['mode']) => {
    if (locked || !draft) return
    event.preventDefault(); event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, mode }
    if (mode === 'move') follow(event, mode)
  }
  const moveDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) follow(event, dragRef.current.mode)
  }
  const endDrag = (event: ReactPointerEvent<HTMLElement>) => { if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null }
  const nudge = (dx: number, dy: number, dw = 0) => {
    if (!draft || locked) return
    if (zoom && !frame) setFrame(zoom)
    onChange({ mouth: [draft.mouth[0] + dx, draft.mouth[1] + dy], mouthWidth: draft.mouthWidth + dw })
  }
  const drag = (mode: Drag['mode']) => ({ onPointerDown: (event: ReactPointerEvent<HTMLElement>) => startDrag(event, mode),
    onPointerMove: moveDrag, onPointerUp: endDrag, onPointerCancel: endDrag })

  const at = (x: number, y: number) => {
    const [left, top] = imageToZoom(zoom!, x, y)
    return { left: `${left}%`, top: `${top}%` }
  }
  const line = preview && zoom ? preview.line.map(([x, y]) => imageToZoom(zoom, x, y).join(',')).join(' ') : ''
  const nudges = [['up', 0, -NUDGE, 0], ['down', 0, NUDGE, 0], ['left', -NUDGE, 0, 0], ['right', NUDGE, 0, 0],
    ['narrower', 0, 0, -2 * NUDGE], ['wider', 0, 0, 2 * NUDGE]] as const
  return <div className="space-y-2">
    <div ref={boxRef} data-testid="mouth-line-zoom" className="relative aspect-square touch-none overflow-hidden rounded border border-border bg-bg-primary" {...drag('move')}>
      {source && <img src={source} alt={t('mouthLine.zoomAlt', { name: kit.name })} draggable={false}
        onLoad={event => setAspect(event.currentTarget.naturalWidth / Math.max(1, event.currentTarget.naturalHeight))}
        className={`pointer-events-none absolute max-w-none select-none ${zoom ? '' : 'invisible'}`} style={zoom ? zoomImageStyle(zoom) : undefined} />}
      {line && <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
        <polyline points={line} fill="none" stroke={preview?.found ? '#6ee7b7' : '#fcd34d'} strokeWidth={0.6} strokeDasharray={preview?.found ? undefined : '2 1.5'} />
      </svg>}
      {zoom && draft && <>
        {(['left', 'right'] as const).map(side => <span key={side} role="button" tabIndex={-1} aria-label={t(`mouthLine.${side}`)}
          className={`${handle} cursor-ew-resize`} style={at(draft.mouth[0] + (side === 'left' ? -1 : 1) * draft.mouthWidth / 2, draft.mouth[1])} {...drag(side)}>
          <span className="h-4 w-1.5 rounded-sm border border-black/60 bg-amber-300" />
        </span>)}
        <span role="button" tabIndex={-1} aria-label={t('mouthLine.dot')} data-testid="mouth-line-dot" className={`${handle} cursor-move`}
          style={at(draft.mouth[0], draft.mouth[1])} {...drag('move')}>
          <span className="h-3.5 w-3.5 rounded-full border-2 border-black/70 bg-emerald-300" />
        </span>
      </>}
    </div>
    <div className="grid grid-cols-4 gap-1">
      {nudges.map(([name, dx, dy, dw]) => <button key={name} type="button" className={button} disabled={locked || !draft} onClick={() => nudge(dx, dy, dw)}>{t(`mouthLine.nudge.${name}`)}</button>)}
      <button type="button" className={`${button} col-span-2`} disabled={!draft} onClick={() => reframe(!spread)}>{t(spread ? 'mouthLine.zoomIn' : 'mouthLine.zoomOut')}</button>
    </div>
  </div>
}

/** The warped rest, i, e, a, o, u at the line, as the rig would make them. */
function MouthLineStates({ name, preview, loading, dirty }: { name: string; preview: FlatRigMouthPreview | null; loading: boolean; dirty: boolean }) {
  const { t } = useUiTranslation('characters')
  const status = loading ? 'mouthLine.loading' : preview?.found ? 'mouthLine.snapped' : 'mouthLine.free'
  return <>
    <p aria-live="polite" className="text-xs text-text-secondary">{preview || loading ? t(status) : ''}</p>
    {preview?.warnings?.includes('mouth_line_unsure') && !dirty && <p className="text-xs text-amber-200">{t('mouthLine.unsure')}</p>}
    <div className="grid grid-cols-3 gap-1">
      {MOUTH_LINE_PREVIEW_STATES.map(({ state, sound }) => <figure key={state} className="overflow-hidden rounded border border-border bg-black/30">
        {preview?.states[state]
          ? <img src={preview.states[state]} alt={t('mouthLine.stateAlt', { name, sound: t(`mouthLine.sounds.${sound}`) })} className={`aspect-square w-full object-cover ${loading ? 'opacity-70' : ''}`} />
          : <div className="aspect-square w-full animate-pulse bg-bg-active" />}
        <figcaption className="py-0.5 text-center text-xs text-text-secondary">{t(`mouthLine.sounds.${sound}`)}</figcaption>
      </figure>)}
    </div>
  </>
}
