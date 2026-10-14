import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { CANCELLED, INTERRUPTED } from './characterCreatorSession'
import type { KeyedCandidate } from './characterCandidates'

const checker = 'bg-[conic-gradient(#e5e7eb_25%,#f9fafb_0_50%,#e5e7eb_0_75%,#f9fafb_0)] bg-[length:16px_16px]'
const HOVER_MS = 120, LONG_PRESS_MS = 450, PRESS_SLOP = 10

/**
 * Shows a picture large while the pointer rests on it (mouse), while it is pressed and held (touch) or while it has the
 * keyboard focus. The press that opened it does not also pick it.
 */
function usePeek() {
  const [peeking, setPeeking] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const press = useRef<{ x: number; y: number } | null>(null)
  const held = useRef(false)
  const clear = () => { window.clearTimeout(timer.current); timer.current = undefined }
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const release = (event: PointerEvent) => {
    if (event.pointerType === 'mouse') return
    clear(); press.current = null; setPeeking(false)
  }
  const handlers = {
    onPointerEnter: (event: PointerEvent) => {
      if (event.pointerType === 'mouse') { clear(); timer.current = window.setTimeout(() => setPeeking(true), HOVER_MS) }
    },
    onPointerLeave: (event: PointerEvent) => {
      if (event.pointerType === 'mouse') { clear(); setPeeking(false) }
    },
    onPointerDown: (event: PointerEvent) => {
      if (event.pointerType === 'mouse') return
      held.current = false; press.current = { x: event.clientX, y: event.clientY }; clear()
      timer.current = window.setTimeout(() => { held.current = true; setPeeking(true) }, LONG_PRESS_MS)
    },
    onPointerMove: (event: PointerEvent) => {
      if (press.current && !held.current && Math.hypot(event.clientX - press.current.x, event.clientY - press.current.y) > PRESS_SLOP) { clear(); press.current = null }
    },
    onPointerUp: release,
    onPointerCancel: release,
    onContextMenu: (event: MouseEvent) => { if (held.current || peeking) event.preventDefault() },
    onClickCapture: (event: MouseEvent) => {
      if (held.current) { held.current = false; event.preventDefault(); event.stopPropagation() }
    },
    onFocus: (event: { currentTarget: Element }) => {
      try { if (event.currentTarget.matches(':focus-visible')) setPeeking(true) } catch { /* no :focus-visible: only hover and press peek */ }
    },
    onBlur: () => setPeeking(false),
  }
  return { peeking, handlers }
}

/** The enlarged picture, over everything: the panels around the tiles clip anything drawn inside them. */
function PeekLayer({ source }: { source: string }) {
  return createPortal(
    <div data-testid="candidate-peek" className="pointer-events-none fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4">
      <div className={`overflow-hidden rounded-xl border border-border shadow-2xl ${checker}`}>
        <img src={source} alt="" className="max-h-[88vh] max-w-[92vw] object-contain" />
      </div>
    </div>, document.body)
}

function Tile({ candidate, index, picked, locked, onPick }: {
  candidate: KeyedCandidate; index: number; picked: boolean; locked: boolean; onPick: (candidate: KeyedCandidate) => void
}) {
  const { t } = useUiTranslation('characters')
  const { peeking, handlers } = usePeek()
  const source = candidate.keyed || candidate.raw
  const rigReasons: Record<string, string> = {
    eyes_small: t('styleCreator.rigReasons.eyes_small'),
    eyes_not_found: t('styleCreator.rigReasons.eyes_not_found'),
    sclera_dark: t('styleCreator.rigReasons.sclera_dark'),
    mouth_not_found: t('styleCreator.rigReasons.mouth_not_found'),
    face_low_confidence: t('styleCreator.rigReasons.face_low_confidence'),
    not_keyed: t('styleCreator.rigReasons.not_keyed'),
    face_too_light: t('styleCreator.rigReasons.face_too_light'),
    face_keyed_out: t('styleCreator.rigReasons.face_keyed_out'),
  }
  const failure = candidate.error === INTERRUPTED ? t('styleCreator.interrupted') : candidate.error === CANCELLED ? t('styleCreator.cancelledOption') : candidate.error
  const pickable = !locked && (candidate.status === 'drawn' || candidate.status === 'keying' || candidate.status === 'ready')
  return <>
    <button type="button" disabled={!pickable} onClick={() => onPick(candidate)} aria-pressed={picked} aria-label={t('styleCreator.option', { number: index + 1 })}
      {...handlers} className={`relative aspect-[3/4] w-full select-none overflow-hidden rounded-lg border-2 [-webkit-touch-callout:none] ${picked ? 'border-cyan-300' : 'border-border'} ${checker}`}>
      {source ? <img src={source} alt="" draggable={false} className="pointer-events-none h-full w-full object-contain" /> : null}
      {candidate.status === 'generating' || candidate.status === 'keying'
        ? <span className="absolute inset-0 flex items-center justify-center bg-black/30 text-xs text-white">
          <Loader2 size={16} className="mr-1 animate-spin" />{t(candidate.status === 'keying' ? 'styleCreator.keying' : 'styleCreator.generating')}</span>
        : null}
      {candidate.status === 'drawn' && <span className="absolute inset-x-1 bottom-1 rounded bg-slate-950/80 p-1 text-[11px] text-white">{t('styleCreator.drawn')}</span>}
      {candidate.status === 'failed' && <span role="alert" className="absolute inset-x-1 bottom-1 rounded bg-red-950/80 p-1 text-[11px] text-red-100">
        {t('styleCreator.failed', { error: failure })}</span>}
      {candidate.status === 'ready' && candidate.rig && <span className="absolute inset-x-1 top-1 rounded bg-slate-950/80 p-1 text-[11px] text-white">
        {candidate.rig.ready ? t('styleCreator.rigReady') : candidate.rig.reasons.map(code => rigReasons[code] ?? code).join(', ')}</span>}
      {candidate.status === 'ready' && candidate.haze !== undefined && <span className="absolute inset-x-1 bottom-1 rounded bg-amber-950/80 p-1 text-[11px] text-amber-100">
        {t('styleCreator.haze', { percent: Math.round(candidate.haze * 100) })}</span>}
    </button>
    {peeking && source ? <PeekLayer source={source} /> : null}
  </>
}

/** The options side by side, as large as the page allows; each opens large on hover, long press or focus. */
export function CandidateGrid({ candidates, picked, onPick, locked }: {
  candidates: KeyedCandidate[]; picked?: string; onPick: (candidate: KeyedCandidate) => void; locked: boolean
}) {
  const { t } = useUiTranslation('characters')
  return <div className="space-y-1" data-testid="character-candidates">
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${candidates.length}, minmax(0, 15rem))` }}>
      {candidates.map((candidate, index) => <Tile key={candidate.id} candidate={candidate} index={index} picked={picked === candidate.id} locked={locked} onPick={onPick} />)}
    </div>
    <p className="text-[11px] text-text-muted">{t('styleCreator.peekHint')}</p>
  </div>
}
