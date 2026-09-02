import {
  ArrowDown,
  ArrowUp,
  Camera,
  Check,
  ChevronsRight,
  Copy,
  Download,
  Film,
  FolderOpen,
  GripVertical,
  Loader2,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Scissors,
  Trash2,
  Upload,
  Volume2,
  VolumeX,
  WandSparkles,
  X,
} from 'lucide-react'
import { Fragment, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import { ModalShell } from '../../components/common/ModalShell'
import {
  clearVideoEditorReplacementResult,
  clearVideoEditorReplacementTarget,
  outputNameFromEditorClip,
  readVideoEditorReplacementResult,
  writeVideoEditorReplacementTarget,
} from './replacementHandoff'
import { VIDEO_EDITOR_PENDING_SOURCE_KEY, editorSourcePath } from './editorHandoff'
import {
  applyTransitionToGaps,
  editorClipRecoveryMessage,
  normalizeEditorClips,
  splitClipAtTime,
  TIMELINE_TRIM_PX_PER_SEC,
  trimClipFromDelta,
  type ClipFit,
  type EditorClip,
  type Transition,
} from './editorClipNormalization'
import {
  clipId,
  loadEditorDraft,
  persistEditorDraft,
  RESOLUTIONS,
  VIDEO_EDITOR_DRAFT_UPDATED_EVENT,
  type EditorSoundtrack,
  type ResolutionOption,
} from './editorDraft'
import {
  clipIndexAtTime,
  clipTimelineStart,
  effectiveDuration,
  formatPlayheadTime,
  isInterstitialTransition,
  parsePlayheadSeconds,
  sequenceTotalDuration,
  sourceTimeAtSequenceTime,
  transitionDurationAfter,
  transitionTimelineStart,
  type InterstitialTransition,
} from './editorTimeline'

interface SequenceStyle {
  opacity: number
  clipPath: string
  transform: string
  filter: string
}

interface SequenceRuntime {
  activeSlot: 0 | 1
  clipIndex: number
  transitioning: boolean
  interstitial: boolean
  interstitialElapsed: number
  interstitialLastFrame: number | null
  ended: boolean
}

interface SequenceInterstitial {
  transition: InterstitialTransition
  text: string
  textSize: number
  progress: number
}

interface PendingEditorSource {
  name?: string
  url: string
}

interface PendingEditorSequence {
  projectName?: string
  resolution?: ResolutionOption
  clips?: Array<{ name?: string; url?: string }>
}

const VIDEO_ACCEPT = '.mp4,.webm,.mov,.mkv,.avi,.m4v'
const VIDEO_EDITOR_PENDING_SEQUENCE_KEY = 'maestro-video-editor-pending-sequence'
const VIDEO_EDITOR_EXPORT_KEY = 'maestro-video-editor-export-v1'
const MAESTRO_PICKER_PAGE_SIZE = 24
const VIDEO_EDITOR_ACTIVE_STATUSES = new Set<api.VideoEditorExportJob['status']>([
  'queued',
  'waiting_resource',
  'running',
  'cancelling',
])

const isVideoEditorJobActive = (job: api.VideoEditorExportJob | null): boolean => (
  Boolean(job && VIDEO_EDITOR_ACTIVE_STATUSES.has(job.status))
)

function videoEditorExportStorageKey(workspace: string | null | undefined): string {
  return `${VIDEO_EDITOR_EXPORT_KEY}:${encodeURIComponent(workspace || 'default')}`
}

function readVideoEditorExportId(workspace: string | null | undefined): string | null {
  try {
    const value = window.localStorage.getItem(videoEditorExportStorageKey(workspace))
    return value && value.trim() ? value : null
  } catch {
    return null
  }
}

function writeVideoEditorExportId(workspace: string | null | undefined, jobId: string): void {
  try {
    window.localStorage.setItem(videoEditorExportStorageKey(workspace), jobId)
  } catch {
    // A full browser quota must not prevent an export from continuing.
  }
}

function clearVideoEditorExportId(workspace: string | null | undefined): void {
  try {
    window.localStorage.removeItem(videoEditorExportStorageKey(workspace))
  } catch {
    // Ignore storage failures; the server remains the source of truth.
  }
}

function pendingVideoEditorExport(jobId: string): api.VideoEditorExportJob {
  return {
    job_id: jobId,
    status: 'queued',
    progress: 0,
    message: 'Reconnecting to export…',
    filename: null,
    url: null,
    error: null,
  }
}

const TRANSITIONS: Array<{ value: Transition; labelKey: string; descriptionKey: string }> = [
  { value: 'none', labelKey: 'transitions.hardCut', descriptionKey: 'transitions.hardCutHint' },
  { value: 'crossfade', labelKey: 'transitions.crossfade', descriptionKey: 'transitions.crossfadeHint' },
  { value: 'fade-black', labelKey: 'transitions.fadeBlack', descriptionKey: 'transitions.fadeBlackHint' },
  { value: 'wipe-left', labelKey: 'transitions.wipeLeft', descriptionKey: 'transitions.wipeLeftHint' },
  { value: 'slide-left', labelKey: 'transitions.slideLeft', descriptionKey: 'transitions.slideLeftHint' },
  { value: 'slide-right', labelKey: 'transitions.slideRight', descriptionKey: 'transitions.slideRightHint' },
  { value: 'circle-open', labelKey: 'transitions.iris', descriptionKey: 'transitions.irisHint' },
  { value: 'dissolve', labelKey: 'transitions.dissolve', descriptionKey: 'transitions.dissolveHint' },
  { value: 'pixelize', labelKey: 'transitions.pixel', descriptionKey: 'transitions.pixelHint' },
  { value: 'blur', labelKey: 'transitions.blur', descriptionKey: 'transitions.blurHint' },
  { value: 'zoom-in', labelKey: 'transitions.zoom', descriptionKey: 'transitions.zoomHint' },
  { value: 'later-clock', labelKey: 'transitions.laterClock', descriptionKey: 'transitions.laterClockHint' },
  { value: 'later-tropical', labelKey: 'transitions.laterMeme', descriptionKey: 'transitions.laterMemeHint' },
  { value: 'later-cinematic', labelKey: 'transitions.laterCinema', descriptionKey: 'transitions.laterCinemaHint' },
]

const DEFAULT_SEQUENCE_STYLE: SequenceStyle = {
  opacity: 1,
  clipPath: 'inset(0 0 0 0)',
  transform: 'translate3d(0, 0, 0) scale(1)',
  filter: 'none',
}

function sequenceStyle(patch: Partial<SequenceStyle> = {}): SequenceStyle {
  return { ...DEFAULT_SEQUENCE_STYLE, ...patch }
}

function FittedCardText({
  text,
  textSize,
  baseSize,
  boxClassName,
  className,
}: {
  text: string
  textSize: number
  baseSize: number
  boxClassName: string
  className: string
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLParagraphElement>(null)

  useLayoutEffect(() => {
    const box = boxRef.current
    const textElement = textRef.current
    if (!box || !textElement) return

    const fit = () => {
      const availableWidth = box.clientWidth
      const availableHeight = box.clientHeight
      if (!availableWidth || !availableHeight) return

      const scale = Math.max(50, Math.min(160, textSize)) / 100
      const target = Math.max(7, Math.min(availableWidth, availableHeight) * baseSize * scale)
      let low = 6
      let high = target
      let fitted = low

      for (let attempt = 0; attempt < 10; attempt++) {
        const candidate = (low + high) / 2
        textElement.style.fontSize = `${candidate}px`
        const fits = textElement.scrollWidth <= availableWidth + 1
          && textElement.scrollHeight <= availableHeight + 1
        if (fits) {
          fitted = candidate
          low = candidate
        } else {
          high = candidate
        }
      }
      textElement.style.fontSize = `${fitted}px`
    }

    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(box)
    return () => observer.disconnect()
  }, [baseSize, text, textSize])

  return (
    <div ref={boxRef} className={`flex min-h-0 items-center justify-center ${boxClassName}`}>
      <p
        ref={textRef}
        className={`w-full whitespace-pre-line break-words text-center [overflow-wrap:anywhere] ${className}`}
      >
        {text}
      </p>
    </div>
  )
}

function LaterCard({
  transition,
  text,
  textSize = 100,
  progress = 0,
  compact = false,
}: {
  transition: InterstitialTransition
  text: string
  textSize?: number
  progress?: number
  compact?: boolean
}) {
  const { t } = useUiTranslation('videoEditor')
  const safeText = text.trim() || t('timeCard.default')
  if (transition === 'later-clock') {
    return (
      <div
        className="absolute inset-0 z-30 flex items-center justify-center overflow-hidden bg-[#07111f] text-white"
        style={{ backgroundImage: 'radial-gradient(circle at 18% 20%, #224a6b 0, transparent 42%), linear-gradient(145deg, #101f34, #020617 78%)' }}
      >
        <div className={`flex items-center justify-center ${compact ? 'gap-1.5' : 'h-full w-full gap-[clamp(1rem,6vw,5rem)] px-[8%]'}`}>
          <div
            className={`relative shrink-0 rounded-full border-[#fbbf24] shadow-2xl ${compact ? 'h-6 w-6 border-2' : 'h-[clamp(5rem,27vw,17rem)] w-[clamp(5rem,27vw,17rem)] border-[clamp(4px,.8vw,10px)]'}`}
            style={{ backgroundImage: 'radial-gradient(circle, #f8fafc 0 67%, transparent 68%), repeating-conic-gradient(#172554 0deg 1.5deg, #f8fafc 1.5deg 30deg)' }}
          >
            <span
              className={`absolute left-1/2 top-1/2 origin-bottom rounded-full bg-slate-900 ${compact ? 'h-2 w-[2px]' : 'h-[29%] w-[4%]'}`}
              style={{ transform: 'translate(-50%, -100%) rotate(-48deg)' }}
            />
            <span
              className={`absolute left-1/2 top-1/2 origin-bottom rounded-full bg-slate-900 ${compact ? 'h-2.5 w-[1px]' : 'h-[39%] w-[3%]'}`}
              style={{ transform: 'translate(-50%, -100%) rotate(28deg)' }}
            />
            <span
              className={`absolute left-1/2 top-1/2 origin-bottom rounded-full bg-red-500 ${compact ? 'h-2.5 w-px' : 'h-[42%] w-[1.5%]'}`}
              style={{ transform: `translate(-50%, -100%) rotate(${132 + progress * 720}deg)` }}
            />
            <span className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber-400 ${compact ? 'h-1 w-1' : 'h-[8%] w-[8%]'}`} />
          </div>
          {compact ? (
            <p className="max-w-16 whitespace-pre-line break-words text-center text-[6px] font-semibold leading-tight [overflow-wrap:anywhere]">
              {safeText}
            </p>
          ) : (
            <FittedCardText
              text={safeText}
              textSize={textSize}
              baseSize={0.17}
              boxClassName="h-[64%] w-[42%]"
              className="font-semibold leading-tight drop-shadow-lg"
            />
          )}
        </div>
      </div>
    )
  }

  if (transition === 'later-tropical') {
    return (
      <div
        className="absolute inset-0 z-30 flex items-center justify-center overflow-hidden bg-[#087f8c]"
        style={{
          backgroundImage: 'radial-gradient(circle at 12% 18%, #f4d35e 0 5%, transparent 5.5%), radial-gradient(circle at 82% 22%, #f95738 0 7%, transparent 7.5%), radial-gradient(circle at 22% 84%, #74c69d 0 8%, transparent 8.5%), radial-gradient(circle at 91% 78%, #ee964b 0 6%, transparent 6.5%), repeating-linear-gradient(42deg, transparent 0 34px, rgba(7,59,76,.2) 35px 38px)'
        }}
      >
        <div className={`${compact ? 'inset-1 rounded' : 'inset-[9%] rounded-[clamp(1rem,4vw,3rem)] border-[clamp(2px,.5vw,7px)]'} absolute border border-[#f6f7d7]/85 bg-[#043b44]/75 shadow-2xl`} />
        {compact ? (
          <p className="relative max-w-[76%] -rotate-1 whitespace-pre-line break-words text-center text-[6px] font-black uppercase leading-[.95] text-[#f6f7d7] [overflow-wrap:anywhere]" style={{ textShadow: '1px 1px #073b4c' }}>
            {safeText}
          </p>
        ) : (
          <FittedCardText
            text={safeText}
            textSize={textSize}
            baseSize={0.21}
            boxClassName="relative h-[48%] w-[72%]"
            className="-rotate-1 font-black uppercase leading-[.95] text-[#f6f7d7] [text-shadow:clamp(2px,.5vw,8px)_clamp(2px,.5vw,8px)_#073b4c]"
          />
        )}
      </div>
    )
  }

  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center overflow-hidden bg-[#170f0a] text-[#f4e8ce]"
      style={{ backgroundImage: 'radial-gradient(ellipse at center, #382517 0, #170f0a 60%, #090604 100%)' }}
    >
      <div className={`absolute border border-[#c9a96e] ${compact ? 'inset-1' : 'inset-[7%]'}`} />
      <div className={`absolute border border-[#685238] ${compact ? 'inset-1.5' : 'inset-[10%]'}`} />
      {compact ? (
        <p className="relative max-w-[72%] whitespace-pre-line break-words text-center text-[5px] font-serif font-semibold uppercase leading-tight tracking-[.12em] [overflow-wrap:anywhere]">
          {safeText}
        </p>
      ) : (
        <FittedCardText
          text={safeText}
          textSize={textSize}
          baseSize={0.21}
          boxClassName="relative h-[38%] w-[68%]"
          className="font-serif font-semibold uppercase leading-tight tracking-[.12em]"
        />
      )}
    </div>
  )
}

function formatTime(value: number): string {
  return formatPlayheadTime(value)
}

function SequenceScrubber({
  duration,
  time,
  disabled,
  onScrub,
}: {
  duration: number
  time: number
  disabled?: boolean
  onScrub: (nextTime: number, phase: 'start' | 'move' | 'end') => void
}) {
  const trackRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef(false)
  const ratio = duration > 0 ? Math.max(0, Math.min(1, time / duration)) : 0

  const timeAt = (clientX: number) => {
    const track = trackRef.current
    if (!track || duration <= 0) return 0
    const rect = track.getBoundingClientRect()
    return Math.max(0, Math.min(duration, ((clientX - rect.left) / Math.max(1, rect.width)) * duration))
  }

  return (
    <div
      ref={trackRef}
      role="slider"
      tabIndex={disabled ? -1 : 0}
      aria-label="Timeline playhead"
      aria-valuemin={0}
      aria-valuemax={Number(duration.toFixed(2))}
      aria-valuenow={Number(Math.min(duration, Math.max(0, time)).toFixed(2))}
      aria-valuetext={`${time.toFixed(2)} seconds`}
      aria-disabled={disabled || undefined}
      data-testid="timeline-playhead"
      className="relative h-7 min-w-0 flex-1 cursor-pointer rounded-full bg-black/50 touch-none focus:outline-none focus:ring-2 focus:ring-sky-400/60"
      onPointerDown={event => {
        if (disabled) return
        event.preventDefault()
        draggingRef.current = true
        event.currentTarget.setPointerCapture(event.pointerId)
        onScrub(timeAt(event.clientX), 'start')
      }}
      onPointerMove={event => {
        if (!draggingRef.current || disabled) return
        onScrub(timeAt(event.clientX), 'move')
      }}
      onPointerUp={event => {
        if (!draggingRef.current) return
        draggingRef.current = false
        onScrub(timeAt(event.clientX), 'end')
      }}
      onPointerCancel={() => { draggingRef.current = false }}
      onKeyDown={event => {
        if (disabled) return
        const step = event.shiftKey ? 1 : event.altKey ? 0.01 : 0.1
        if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
          event.preventDefault()
          onScrub(Math.max(0, time - step), 'end')
        } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
          event.preventDefault()
          onScrub(Math.min(duration, time + step), 'end')
        } else if (event.key === 'Home') {
          event.preventDefault()
          onScrub(0, 'end')
        } else if (event.key === 'End') {
          event.preventDefault()
          onScrub(duration, 'end')
        }
      }}
    >
      <div
        className="absolute inset-y-0 left-0 rounded-full bg-sky-400/35"
        style={{ width: `${ratio * 100}%` }}
      />
      <div
        className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-400 shadow"
        style={{ left: `${ratio * 100}%` }}
      />
    </div>
  )
}

const MIN_TRIM_DURATION = 0.05

function ClipTrimBar({
  duration,
  start,
  end,
  onChange,
}: {
  duration: number
  start: number
  end: number
  onChange: (next: { trimStart?: number; trimEnd?: number }) => void
}) {
  const trackRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef<'start' | 'end' | null>(null)
  const [dragging, setDragging] = useState<'start' | 'end' | null>(null)
  const safeDuration = Math.max(MIN_TRIM_DURATION, duration)
  const startPercent = Math.max(0, Math.min(100, (start / safeDuration) * 100))
  const endPercent = Math.max(startPercent, Math.min(100, (end / safeDuration) * 100))

  const applyValue = (handle: 'start' | 'end', rawValue: number) => {
    const value = Math.round(Math.max(0, Math.min(safeDuration, rawValue)) * 100) / 100
    if (handle === 'start') {
      onChange({ trimStart: Math.min(value, end - MIN_TRIM_DURATION) })
    } else {
      onChange({ trimEnd: Math.max(value, start + MIN_TRIM_DURATION) })
    }
  }

  const valueAt = (clientX: number) => {
    const bounds = trackRef.current?.getBoundingClientRect()
    if (!bounds?.width) return start
    return Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width)) * safeDuration
  }

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const requested = (event.target as HTMLElement).closest<HTMLElement>('[data-trim-handle]')
      ?.dataset.trimHandle
    const value = valueAt(event.clientX)
    const handle = requested === 'start' || requested === 'end'
      ? requested
      : Math.abs(value - start) <= Math.abs(value - end) ? 'start' : 'end'
    event.currentTarget.setPointerCapture(event.pointerId)
    draggingRef.current = handle
    setDragging(handle)
    applyValue(handle, value)
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (draggingRef.current) applyValue(draggingRef.current, valueAt(event.clientX))
  }

  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    draggingRef.current = null
    setDragging(null)
  }

  const keyboardStep = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    handle: 'start' | 'end',
    current: number,
  ) => {
    const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
    if (!direction) return
    event.preventDefault()
    applyValue(handle, current + direction * (event.shiftKey ? 0.5 : 0.05))
  }

  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/70 p-3">
      <div className="mb-2 flex items-center justify-between gap-3 text-[10px] tabular-nums">
        <span className="text-text-muted">Recorte no destructivo</span>
        <span className="text-text-secondary">
          Conserva {formatTime(Math.max(0, end - start))} · quita {formatTime(start + Math.max(0, duration - end))}
        </span>
      </div>
      <div
        ref={trackRef}
        className="relative h-12 touch-none cursor-pointer select-none"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
      >
        <div
          className="absolute inset-x-0 top-4 h-4 overflow-hidden rounded border border-white/10 bg-black/55"
          style={{ backgroundImage: 'repeating-linear-gradient(90deg, transparent 0 7%, rgba(255,255,255,.08) 7.2% 7.8%)' }}
        />
        <div
          className="absolute top-4 h-4 border-y border-accent-blue/70 bg-accent-blue/35"
          style={{ left: `${startPercent}%`, width: `${endPercent - startPercent}%` }}
        />
        {(['start', 'end'] as const).map(handle => {
          const value = handle === 'start' ? start : end
          const percent = handle === 'start' ? startPercent : endPercent
          return (
            <button
              key={handle}
              type="button"
              role="slider"
              data-trim-handle={handle}
              aria-label={handle === 'start' ? 'Punto de entrada' : 'Punto de salida'}
              aria-valuemin={handle === 'start' ? 0 : start + MIN_TRIM_DURATION}
              aria-valuemax={handle === 'start' ? end - MIN_TRIM_DURATION : safeDuration}
              aria-valuenow={Number(value.toFixed(2))}
              aria-valuetext={formatTime(value)}
              onKeyDown={event => keyboardStep(event, handle, value)}
              className={`absolute top-1 z-10 h-10 w-4 -translate-x-1/2 cursor-ew-resize rounded border shadow-lg focus:outline-none focus:ring-2 focus:ring-accent-blue ${dragging === handle ? 'border-white bg-accent-blue' : 'border-accent-blue bg-bg-secondary'}`}
              style={{ left: `${percent}%` }}
            >
              <span className="mx-auto block h-5 w-px bg-white/70" />
            </button>
          )
        })}
      </div>
      <div className="flex justify-between text-[9px] text-text-muted tabular-nums">
        <span>Entrada {formatTime(start)}</span>
        <span>Salida {formatTime(end)}</span>
      </div>
    </div>
  )
}

function greatestCommonDivisor(left: number, right: number): number {
  let a = Math.abs(Math.round(left))
  let b = Math.abs(Math.round(right))
  while (b) {
    const next = a % b
    a = b
    b = next
  }
  return a || 1
}

function exportAspectLabel(width: number, height: number): string {
  const divisor = greatestCommonDivisor(width, height)
  return `${width / divisor}:${height / divisor}`
}

function ExportPreviewCanvas({
  width,
  height,
  children,
  overlay,
}: {
  width: number
  height: number
  children?: ReactNode
  overlay?: ReactNode
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0)

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return

    const fit = () => {
      const bounds = viewport.getBoundingClientRect()
      // Keep the readout outside the image so every output pixel remains visible.
      const availableHeight = Math.max(1, bounds.height - 24)
      const fitted = Math.min(bounds.width / width, availableHeight / height)
      setScale(Number.isFinite(fitted) && fitted > 0 ? fitted : 0)
    }

    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [height, width])

  const displayWidth = width * scale
  const displayHeight = height * scale
  const aspect = exportAspectLabel(width, height)

  return (
    <div ref={viewportRef} className="absolute inset-4 flex items-center justify-center overflow-hidden">
      {scale > 0 && (
        <div
          className="flex shrink-0 flex-col"
          style={{ width: `${displayWidth}px`, height: `${displayHeight + 24}px` }}
          aria-label={`Export preview ${width} by ${height} pixels, ${aspect}`}
        >
          <div className="flex h-6 shrink-0 items-center justify-between gap-2 px-1 text-[10px] text-text-muted tabular-nums">
            <span className="truncate uppercase tracking-[.12em]">Export preview</span>
            <span className="shrink-0 text-text-secondary">{width}×{height} · {aspect} · {Math.round(scale * 100)}%</span>
          </div>
          <div
            className="relative min-h-0 flex-1 overflow-hidden bg-black shadow-2xl ring-1 ring-white/20"
            data-export-preview-canvas
            data-export-width={width}
            data-export-height={height}
          >
            <div
              className="absolute left-0 top-0 overflow-hidden bg-black"
              style={{
                width: `${width}px`,
                height: `${height}px`,
                transform: `scale(${scale})`,
                transformOrigin: 'top left',
              }}
            >
              {children}
            </div>
            {overlay && <div className="absolute inset-0">{overlay}</div>}
          </div>
        </div>
      )}
    </div>
  )
}

function wait(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

export function VideoEditorPanel() {
  const { t } = useUiTranslation('videoEditor')
  const refreshOutputs = useStore(s => s.refreshOutputs)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const [draft] = useState(() => loadEditorDraft(activeWorkspace))
  const draftWorkspaceRef = useRef(activeWorkspace)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const sequenceRefs = useRef<Array<HTMLVideoElement | null>>([null, null])
  const sequenceFrameRef = useRef<number | null>(null)
  const sequenceRuntimeRef = useRef<SequenceRuntime>({
    activeSlot: 0,
    clipIndex: 0,
    transitioning: false,
    interstitial: false,
    interstitialElapsed: 0,
    interstitialLastFrame: null,
    ended: false,
  })
  const sequencePlayingRef = useRef(false)
  const sequenceSlotSeekRef = useRef<Array<number | null>>([null, null])
  const scrubbingRef = useRef(false)
  const pendingSeekRef = useRef<number | null>(null)
  const pendingSeekAtRef = useRef(0)
  const mountedRef = useRef(true)
  const exportPollingRef = useRef<string | null>(null)
  const exportPollEpochRef = useRef(0)
  const exportSubmittingRef = useRef(false)

  const [clips, setClips] = useState<EditorClip[]>(draft.clips)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)
  const [bulkTransition, setBulkTransition] = useState<Transition>('crossfade')
  const timelineScrollRef = useRef<HTMLDivElement>(null)
  const dragScrollFrameRef = useRef<number | null>(null)
  const dragScrollDirRef = useRef<-1 | 0 | 1>(0)
  const trimmingRef = useRef(false)
  const [projectName, setProjectName] = useState(draft.projectName)
  const [resolution, setResolution] = useState(draft.resolution)
  const [fps, setFps] = useState(draft.fps)
  const [soundtrack, setSoundtrack] = useState<EditorSoundtrack | null>(draft.soundtrack)
  const [previewTime, setPreviewTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [sequenceMode, setSequenceMode] = useState(false)
  const [sequenceTime, setSequenceTime] = useState(0)
  const [playheadDraft, setPlayheadDraft] = useState<string | null>(null)
  const [sequenceSlotIndices, setSequenceSlotIndices] = useState<Array<number | null>>([null, null])
  const [sequenceStyles, setSequenceStyles] = useState([
    sequenceStyle(),
    sequenceStyle({ opacity: 0 }),
  ])
  const [sequenceInterstitial, setSequenceInterstitial] = useState<SequenceInterstitial | null>(null)
  const [selectedTransitionIndex, setSelectedTransitionIndex] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const [addProgress, setAddProgress] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [maestroVideos, setMaestroVideos] = useState<api.ApiOutput[]>([])
  const [maestroVideoTotal, setMaestroVideoTotal] = useState(0)
  const [pickerLoading, setPickerLoading] = useState(false)
  const [pickerSelected, setPickerSelected] = useState<string[]>([])
  const pickerAnchorRef = useRef<number | null>(null)
  const pickerSelectedSet = useMemo(() => new Set(pickerSelected), [pickerSelected])
  const [error, setError] = useState<string | null>(draft.warning)
  const [exportJob, setExportJob] = useState<api.VideoEditorExportJob | null>(() => {
    const jobId = readVideoEditorExportId(activeWorkspace)
    return jobId ? pendingVideoEditorExport(jobId) : null
  })
  const [capturingFrame, setCapturingFrame] = useState(false)
  const [capturedFrame, setCapturedFrame] = useState<api.VideoEditorScreenshot | null>(null)
  const [preparingReplacement, setPreparingReplacement] = useState(false)
  const [pendingHandoff, setPendingHandoff] = useState<'source' | 'sequence' | null>(null)
  const handoffProcessingRef = useRef(false)

  const selected = clips.find(clip => clip.id === selectedId) || clips[0] || null
  const selectedIndex = selected ? clips.findIndex(clip => clip.id === selected.id) : -1
  const totalDuration = useMemo(() => sequenceTotalDuration(clips), [clips])
  const playheadSeconds = sequenceMode
    ? sequenceTime
    : selected && selectedIndex >= 0
      ? clipTimelineStart(clips, selectedIndex) + Math.max(0, previewTime - selected.trimStart)
      : 0

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (sequenceFrameRef.current !== null) cancelAnimationFrame(sequenceFrameRef.current)
    }
  }, [])

  useEffect(() => {
    if (draftWorkspaceRef.current === activeWorkspace) return
    persistEditorDraft(clips, projectName, resolution, fps, draftWorkspaceRef.current)
    const next = loadEditorDraft(activeWorkspace)
    draftWorkspaceRef.current = activeWorkspace
    setClips(next.clips)
    setProjectName(next.projectName)
    setResolution(next.resolution)
    setFps(next.fps)
    setSoundtrack(next.soundtrack)
    setSelectedId(next.clips[0]?.id || null)
    setError(next.warning)
    setPreviewTime(0)
    setPlaying(false)
    setSequenceMode(false)
    // Persist the leaving workspace from the latest in-memory timeline,
    // then replace state. Clips/name/fps are intentionally read from this
    // render rather than listed as deps so a local edit cannot retrigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspace])

  useEffect(() => {
    const handleDraftUpdate = (event: Event) => {
      const detail = (event as CustomEvent<{ workspace?: string }>).detail
      if ((detail?.workspace || 'default') !== (activeWorkspace || 'default')) return
      setSoundtrack(loadEditorDraft(activeWorkspace).soundtrack)
    }
    window.addEventListener(VIDEO_EDITOR_DRAFT_UPDATED_EVENT, handleDraftUpdate)
    return () => window.removeEventListener(VIDEO_EDITOR_DRAFT_UPDATED_EVENT, handleDraftUpdate)
  }, [activeWorkspace])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      persistEditorDraft(clips, projectName, resolution, fps, draftWorkspaceRef.current)
    }, 600)
    return () => window.clearTimeout(timer)
  }, [clips, projectName, resolution, fps])

  useEffect(() => {
    if (!selectedId && clips[0]) setSelectedId(clips[0].id)
    if (selectedId && !clips.some(clip => clip.id === selectedId)) {
      setSelectedId(clips[0]?.id || null)
    }
  }, [clips, selectedId])

  useEffect(() => {
    if (sequenceMode) return
    setPreviewTime(selected?.trimStart || 0)
    setPlaying(false)
  }, [selected?.id, selected?.trimStart, sequenceMode])

  useEffect(() => {
    if (selectedTransitionIndex !== null && selectedTransitionIndex >= clips.length - 1) {
      setSelectedTransitionIndex(clips.length > 1 ? clips.length - 2 : null)
    }
  }, [clips.length, selectedTransitionIndex])

  const patchClip = (id: string, patch: Partial<EditorClip>) => {
    setClips(current => current.map(clip => clip.id === id ? { ...clip, ...patch } : clip))
  }

  const createClipFromSource = useCallback(async (
    source: string,
    previewUrl: string,
    name: string,
    thumbnailUrl?: string | null,
  ): Promise<EditorClip> => {
    const resolvedSource = editorSourcePath(source) || source
    const media = await api.probeVideoEditorClip(resolvedSource, activeWorkspace)
    return {
      ...media,
      id: clipId(),
      name,
      source: resolvedSource,
      previewUrl,
      thumbnailUrl: thumbnailUrl || api.getVideoEditorThumbnailUrl(resolvedSource),
      trimStart: 0,
      trimEnd: media.duration,
      volume: 1,
      muted: false,
      fit: 'fit',
      transition: 'none',
      transitionDuration: 0.5,
      transitionText: t('timeCard.default'),
      transitionTextSize: 100,
    }
  }, [activeWorkspace, t])

  const addSource = useCallback(async (
    source: string,
    previewUrl: string,
    name: string,
    thumbnailUrl?: string | null,
  ) => {
    const clip = await createClipFromSource(source, previewUrl, name, thumbnailUrl)
    setClips(current => [...current, clip])
    setSelectedId(clip.id)
  }, [createClipFromSource])

  const processPendingHandoff = useCallback(async (
    kind: 'source' | 'sequence',
    handoff: PendingEditorSource | PendingEditorSequence,
  ) => {
    if (handoffProcessingRef.current) return
    const rawSources = kind === 'sequence' ? (handoff as PendingEditorSequence).clips || [] : null
    const pendingSources = kind === 'sequence'
      ? rawSources?.every(item => typeof item?.url === 'string' && item.url.trim())
        ? rawSources as Array<{ name?: string; url: string }>
        : []
      : (typeof (handoff as PendingEditorSource).url === 'string'
          && (handoff as PendingEditorSource).url.trim()
        ? [{
            name: (handoff as PendingEditorSource).name || 'comic animatic',
            url: (handoff as PendingEditorSource).url,
          }]
        : [])
    if (!pendingSources.length) {
      setError('The editor hand-off does not contain any valid video sources. It is still available to retry.')
      return
    }

    const sequence = kind === 'sequence' ? handoff as PendingEditorSequence : null
    const requestedResolution = sequence && RESOLUTIONS.find(option =>
      option.width === sequence.resolution?.width && option.height === sequence.resolution?.height)
    const nextProjectName = sequence?.projectName || projectName
    const nextResolution = requestedResolution || resolution
    const nextClips: EditorClip[] = []

    handoffProcessingRef.current = true
    setAdding(true)
    setError(null)
    try {
      for (let index = 0; index < pendingSources.length; index++) {
        const item = pendingSources[index]
        setAddProgress(kind === 'sequence'
          ? `Opening Series shot ${index + 1}/${pendingSources.length}`
          : `Opening ${item.name || 'comic animatic'}`)
        nextClips.push(await createClipFromSource(item.url, item.url, item.name || `Series shot ${index + 1}`))
      }

      if (clips.length && !window.confirm(
        kind === 'sequence'
          ? `The editor already contains ${clips.length} clip${clips.length === 1 ? '' : 's'}. Replace this montage with the hand-off?`
          : `The editor already contains ${clips.length} clip${clips.length === 1 ? '' : 's'}. Add the hand-off to this montage?`,
      )) return

      const committedClips = kind === 'sequence' ? nextClips : [...clips, ...nextClips]
      if (!persistEditorDraft(committedClips, nextProjectName, nextResolution, fps, draftWorkspaceRef.current)) {
        throw new Error('The editor draft could not be saved. The hand-off was kept for Retry.')
      }
      setClips(committedClips)
      setSelectedId((kind === 'sequence' ? committedClips[0] : nextClips[0])?.id || null)
      if (sequence?.projectName) setProjectName(nextProjectName)
      if (requestedResolution) setResolution(nextResolution)
      window.localStorage.removeItem(
        kind === 'sequence' ? VIDEO_EDITOR_PENDING_SEQUENCE_KEY : VIDEO_EDITOR_PENDING_SOURCE_KEY,
      )
      setPendingHandoff(null)
      setError(null)
    } catch (reason) {
      setError(`Could not open the hand-off: ${(reason as Error).message}. The hand-off and current draft were kept; Retry when the source is available.`)
    } finally {
      handoffProcessingRef.current = false
      setAdding(false)
      setAddProgress('')
    }
  }, [clips, createClipFromSource, fps, projectName, resolution])

  useEffect(() => {
    let pending: PendingEditorSource | null = null
    let pendingSequence: PendingEditorSequence | null = null
    try {
      pending = JSON.parse(window.localStorage.getItem(VIDEO_EDITOR_PENDING_SOURCE_KEY) || 'null')
      pendingSequence = JSON.parse(window.localStorage.getItem(VIDEO_EDITOR_PENDING_SEQUENCE_KEY) || 'null')
    } catch {
      pending = null
      pendingSequence = null
    }
    if (pendingSequence?.clips?.length) {
      setPendingHandoff('sequence')
      void processPendingHandoff('sequence', pendingSequence)
      return
    }
    if (pending?.url) {
      setPendingHandoff('source')
      void processPendingHandoff('source', pending)
    }
  }, [processPendingHandoff])

  useEffect(() => {
    const replacement = readVideoEditorReplacementResult()
    if (!replacement) return
    const target = clips.find(clip => clip.id === replacement.clipId)
    if (!target) {
      clearVideoEditorReplacementResult()
      clearVideoEditorReplacementTarget()
      setError(t('remake.slotGone', { n: replacement.clipIndex + 1 }))
      return
    }

    setAdding(true)
    setAddProgress(`Reemplazando clip ${replacement.clipIndex + 1}: ${target.name}`)
    void api.probeVideoEditorClip(replacement.source)
      .then(media => {
        setClips(current => {
          const next = current.map(clip => clip.id === replacement.clipId
            ? {
                ...clip,
                ...media,
                name: replacement.outputName,
                source: replacement.source,
                previewUrl: replacement.source,
                thumbnailUrl: api.getVideoEditorThumbnailUrl(replacement.source),
                trimStart: 0,
                trimEnd: media.duration,
              }
            : clip)
          persistEditorDraft(next, projectName, resolution, fps, draftWorkspaceRef.current)
          return next
        })
        clearVideoEditorReplacementResult()
        clearVideoEditorReplacementTarget()
        setSelectedId(replacement.clipId)
        setError(null)
      })
      .catch(reason => setError(`No se pudo reemplazar el clip ${replacement.clipIndex + 1}: ${(reason as Error).message}`))
      .finally(() => {
        setAdding(false)
        setAddProgress('')
      })
    // Keep a failed result available for another mount; clear it only after
    // the replacement is safely persisted into the editor draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openSelectedInVideoCreation = async () => {
    if (!selected || selectedIndex < 0 || preparingReplacement) return
    setPreparingReplacement(true)
    setError(null)
    setSequencePlaying(false)
    videoRef.current?.pause()

    const outputName = outputNameFromEditorClip(selected.source, selected.name)
    try {
      const metadata = await api.fetchOutputMetadata(outputName, activeWorkspace)
      if (!metadata.params) throw new Error(t('remake.noReusable'))

      const store = useStore.getState()
      store.setSidebarMode('studio')
      store.setGenerationMode('video')
      useStore.setState({ selectedOutputMeta: metadata, metadataLoading: false })
      await useStore.getState().loadSettingsFromOutput()
      useStore.getState().setGenerationMode('video')
      useStore.getState().setSidebarMode('studio')

      persistEditorDraft(clips, projectName, resolution, fps, draftWorkspaceRef.current)
      writeVideoEditorReplacementTarget({
        clipId: selected.id,
        clipIndex: selectedIndex,
        originalName: selected.name,
        outputName,
        requestedAt: Date.now(),
      })
      useStore.getState().setMediaFilter('videos')
    } catch (reason) {
      setError(t('remake.openFailed', { message: (reason as Error).message }))
      setPreparingReplacement(false)
    }
  }

  const addFiles = async (files: File[]) => {
    const videos = files.filter(file => file.type.startsWith('video/') || /\.(mp4|webm|mov|mkv|avi|m4v)$/i.test(file.name))
    if (!videos.length) {
      setError('Choose one or more video files.')
      return
    }
    setAdding(true)
    setError(null)
    const failures: string[] = []
    for (let index = 0; index < videos.length; index++) {
      const file = videos[index]
      setAddProgress(`Importing ${index + 1} of ${videos.length}: ${file.name}`)
      try {
        const uploaded = await api.uploadImage(file)
        await addSource(uploaded.url, uploaded.url, file.name)
      } catch (reason) {
        failures.push(`${file.name}: ${(reason as Error).message}`)
      }
    }
    setAdding(false)
    setAddProgress('')
    if (failures.length) setError(failures.join('\n'))
  }

  const closeMaestroPicker = () => {
    setPickerOpen(false)
    setPickerSelected([])
    pickerAnchorRef.current = null
  }

  const openMaestroPicker = async () => {
    setPickerOpen(true)
    setPickerSelected([])
    pickerAnchorRef.current = null
    setPickerLoading(true)
    setError(null)
    setMaestroVideos([])
    setMaestroVideoTotal(0)
    try {
      const result = await api.fetchOutputs(MAESTRO_PICKER_PAGE_SIZE, 0, { mediaType: 'video', workspace: activeWorkspace })
      setMaestroVideos(result.outputs)
      setMaestroVideoTotal(result.total)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setPickerLoading(false)
    }
  }

  const loadMoreMaestroVideos = async () => {
    if (pickerLoading || maestroVideos.length >= maestroVideoTotal) return
    setPickerLoading(true)
    setError(null)
    try {
      const result = await api.fetchOutputs(
        MAESTRO_PICKER_PAGE_SIZE,
        maestroVideos.length,
        { mediaType: 'video', workspace: activeWorkspace },
      )
      setMaestroVideos(current => {
        const known = new Set(current.map(output => output.name))
        return [...current, ...result.outputs.filter(output => !known.has(output.name))]
      })
      setMaestroVideoTotal(result.total)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setPickerLoading(false)
    }
  }

  const toggleMaestroVideo = (output: api.ApiOutput, event: ReactMouseEvent<HTMLButtonElement>) => {
    const index = maestroVideos.findIndex(item => item.name === output.name)
    if (index < 0) return
    if (event.shiftKey && pickerAnchorRef.current !== null) {
      const start = Math.min(pickerAnchorRef.current, index)
      const end = Math.max(pickerAnchorRef.current, index)
      const range = maestroVideos.slice(start, end + 1).map(item => item.name)
      setPickerSelected(current => {
        const seen = new Set(current)
        const next = [...current]
        for (const name of range) {
          if (!seen.has(name)) {
            seen.add(name)
            next.push(name)
          }
        }
        return next
      })
      return
    }
    pickerAnchorRef.current = index
    setPickerSelected(current => (
      current.includes(output.name)
        ? current.filter(name => name !== output.name)
        : [...current, output.name]
    ))
  }

  const addSelectedMaestroVideos = async () => {
    const selected = pickerSelected
      .map(name => maestroVideos.find(item => item.name === name))
      .filter((item): item is api.ApiOutput => Boolean(item))
    if (!selected.length) {
      setError('Select one or more videos.')
      return
    }
    setAdding(true)
    closeMaestroPicker()
    setError(null)
    const failures: string[] = []
    for (let index = 0; index < selected.length; index++) {
      const output = selected[index]
      setAddProgress(`Adding ${index + 1} of ${selected.length}: ${output.name}`)
      try {
        const source = api.getFileUrl(output.name, activeWorkspace)
        await addSource(
          source,
          source,
          output.name,
          output.thumbnail_url || api.getOutputThumbnailUrl(output.name, activeWorkspace),
        )
      } catch (reason) {
        failures.push(`${output.name}: ${(reason as Error).message}`)
      }
    }
    setAdding(false)
    setAddProgress('')
    if (failures.length) setError(failures.join('\n'))
  }

  const reorder = (id: string, direction: -1 | 1) => {
    setClips(current => {
      const index = current.findIndex(clip => clip.id === id)
      const target = index + direction
      if (index < 0 || target < 0 || target >= current.length) return current
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  const dropAtIndex = (insertionIndex: number, transferId?: string) => {
    const movingId = transferId || draggedId
    if (!movingId) return
    setClips(current => {
      const sourceIndex = current.findIndex(clip => clip.id === movingId)
      if (sourceIndex < 0) return current
      const moving = current[sourceIndex]
      const without = current.filter(clip => clip.id !== movingId)
      const adjustedIndex = insertionIndex > sourceIndex ? insertionIndex - 1 : insertionIndex
      without.splice(Math.max(0, Math.min(without.length, adjustedIndex)), 0, moving)
      return without
    })
    setDraggedId(null)
    setDropIndex(null)
    stopTimelineDragScroll()
  }

  const stopTimelineDragScroll = () => {
    if (dragScrollFrameRef.current !== null) {
      cancelAnimationFrame(dragScrollFrameRef.current)
      dragScrollFrameRef.current = null
    }
    dragScrollDirRef.current = 0
  }

  const tickTimelineDragScroll = () => {
    const scroller = timelineScrollRef.current
    if (!scroller || !dragScrollDirRef.current) {
      dragScrollFrameRef.current = null
      return
    }
    scroller.scrollLeft += dragScrollDirRef.current * 3.2
    dragScrollFrameRef.current = requestAnimationFrame(tickTimelineDragScroll)
  }

  const updateTimelineDragScroll = (clientX: number) => {
    const scroller = timelineScrollRef.current
    if (!scroller) return
    const bounds = scroller.getBoundingClientRect()
    const edge = 56
    let direction: -1 | 0 | 1 = 0
    if (clientX < bounds.left + edge) direction = -1
    else if (clientX > bounds.right - edge) direction = 1
    dragScrollDirRef.current = direction
    if (direction && dragScrollFrameRef.current === null) {
      dragScrollFrameRef.current = requestAnimationFrame(tickTimelineDragScroll)
    }
  }

  const applyAllGapTransitions = () => {
    if (clips.length < 2) return
    setClips(current => applyTransitionToGaps(current, bulkTransition))
    setSelectedTransitionIndex(0)
    setError(null)
  }

  const splitSelected = () => {
    if (!clips.length) return
    let target = selected
    let cut = videoRef.current?.currentTime ?? previewTime
    if (sequenceMode) {
      const clipIndex = clipIndexAtTime(clips, sequenceTime)
      const start = clipTimelineStart(clips, clipIndex)
      const local = Math.max(0, sequenceTime - start)
      target = clips[clipIndex]
      cut = target.trimStart + local
    }
    if (!target) return
    const parts = splitClipAtTime(target, cut, clipId())
    if (!parts) {
      setError('Move the playhead inside the clip, away from the very start and end, then Split.')
      return
    }
    const [left, right] = parts
    setClips(current => {
      const index = current.findIndex(clip => clip.id === target.id)
      if (index < 0) return current
      const next = [...current]
      next[index] = left
      next.splice(index + 1, 0, right)
      return next
    })
    setSequencePlaying(false)
    setSequenceMode(false)
    setSelectedTransitionIndex(null)
    setSelectedId(right.id)
    setPreviewTime(right.trimStart)
    setError(null)
  }

  const beginTimelineTrim = (
    event: ReactPointerEvent<HTMLElement>,
    clipIdValue: string,
    edge: 'start' | 'end',
  ) => {
    event.preventDefault()
    event.stopPropagation()
    trimmingRef.current = true
    let lastX = event.clientX
    const move = (pointer: PointerEvent) => {
      const deltaSeconds = (pointer.clientX - lastX) / TIMELINE_TRIM_PX_PER_SEC
      lastX = pointer.clientX
      if (Math.abs(deltaSeconds) < 0.0005) return
      setClips(current => current.map(clip => (
        clip.id === clipIdValue ? trimClipFromDelta(clip, edge, deltaSeconds) : clip
      )))
    }
    const finish = () => {
      trimmingRef.current = false
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
  }

  const clipVolume = (clip: EditorClip): number => (
    clip.muted ? 0 : Math.max(0, Math.min(1, clip.volume))
  )

  const setSequencePlaying = (value: boolean) => {
    sequencePlayingRef.current = value
    setPlaying(value)
    const runtime = sequenceRuntimeRef.current
    const active = sequenceRefs.current[runtime.activeSlot]
    const inactive = sequenceRefs.current[runtime.activeSlot === 0 ? 1 : 0]
    if (!value) {
      runtime.interstitialLastFrame = null
      active?.pause()
      inactive?.pause()
      return
    }
    if (runtime.interstitial) {
      runtime.interstitialLastFrame = performance.now()
      active?.pause()
      inactive?.pause()
      return
    }
    void active?.play().catch(() => setError('The browser could not start timeline playback.'))
    if (runtime.transitioning) {
      void inactive?.play().catch(() => undefined)
    }
  }

  const removeClip = (id: string) => {
    const index = clips.findIndex(clip => clip.id === id)
    if (index < 0) return

    setSequencePlaying(false)
    videoRef.current?.pause()
    sequenceRuntimeRef.current = {
      activeSlot: 0,
      clipIndex: 0,
      transitioning: false,
      interstitial: false,
      interstitialElapsed: 0,
      interstitialLastFrame: null,
      ended: false,
    }
    sequenceSlotSeekRef.current = [null, null]
    setSequenceMode(false)
    setSequenceTime(0)
    setSequenceSlotIndices([null, null])
    setSequenceStyles([sequenceStyle(), sequenceStyle({ opacity: 0 })])
    setSequenceInterstitial(null)
    setSelectedTransitionIndex(null)
    setDraggedId(current => current === id ? null : current)
    setDropIndex(null)

    const remaining = clips.filter(clip => clip.id !== id)
    // A transition belongs to the exact outgoing→incoming pair. Removing the
    // incoming clip must not silently apply that transition to a different one.
    if (index > 0 && remaining[index - 1]) {
      remaining[index - 1] = { ...remaining[index - 1], transition: 'none' }
    }
    setClips(remaining)
    if (!selectedId || selectedId === id || !remaining.some(clip => clip.id === selectedId)) {
      setSelectedId(remaining[Math.min(index, remaining.length - 1)]?.id || null)
    }
    setError(null)
  }

  const startSequenceAt = (clipIndex: number, sourceTime?: number, autoplay = true) => {
    if (!clips[clipIndex]) return
    const clip = clips[clipIndex]
    const seekTo = sourceTime ?? clip.trimStart
    const previous = sequenceRuntimeRef.current
    const keepMounted = (
      sequenceMode
      && previous.clipIndex === clipIndex
      && previous.activeSlot === 0
      && sequenceSlotIndices[0] === clipIndex
    )
    sequencePlayingRef.current = autoplay
    videoRef.current?.pause()
    const nextIndex = clipIndex + 1 < clips.length ? clipIndex + 1 : null
    sequenceRuntimeRef.current = {
      activeSlot: 0,
      clipIndex,
      transitioning: false,
      interstitial: false,
      interstitialElapsed: 0,
      interstitialLastFrame: null,
      ended: false,
    }
    sequenceSlotSeekRef.current = [
      seekTo,
      nextIndex !== null ? clips[nextIndex].trimStart : null,
    ]
    setPlaying(autoplay)
    setSequenceMode(true)
    setSequenceSlotIndices([clipIndex, nextIndex])
    setSequenceStyles([
      sequenceStyle(),
      sequenceStyle({ opacity: 0 }),
    ])
    setSequenceInterstitial(null)
    setSelectedId(clip.id)
    setSelectedTransitionIndex(null)
    const clock = clipTimelineStart(clips, clipIndex) + Math.max(0, seekTo - clip.trimStart)
    pendingSeekRef.current = clock
    pendingSeekAtRef.current = performance.now()
    setSequenceTime(clock)
    if (!keepMounted) return
    const video = sequenceRefs.current[0]
    if (!video) return
    video.currentTime = seekTo
    if (autoplay) void video.play().catch(() => undefined)
    else video.pause()
  }

  const seekSequence = (value: number, autoplay?: boolean) => {
    if (!clips.length) return
    const clamped = Math.max(0, Math.min(totalDuration, value))
    const play = autoplay ?? sequencePlayingRef.current
    const located = sourceTimeAtSequenceTime(clips, clamped)
    const clip = clips[located.clipIndex]
    if (!clip) return
    pendingSeekRef.current = clamped
    pendingSeekAtRef.current = performance.now()
    setSequenceTime(clamped)

    if (located.interstitial) {
      const alreadyThere = (
        sequenceMode
        && sequenceRuntimeRef.current.clipIndex === located.clipIndex
        && sequenceRuntimeRef.current.interstitial
      )
      if (!alreadyThere) startSequenceAt(located.clipIndex, clip.trimEnd - 0.01, false)
      const runtime = sequenceRuntimeRef.current
      const duration = transitionDurationAfter(clips, located.clipIndex)
      sequencePlayingRef.current = play
      setPlaying(play)
      runtime.interstitial = true
      runtime.transitioning = false
      runtime.ended = false
      runtime.interstitialElapsed = located.interstitialElapsed
      runtime.interstitialLastFrame = play ? performance.now() : null
      sequenceRefs.current[0]?.pause()
      sequenceRefs.current[1]?.pause()
      setSequenceInterstitial({
        transition: clip.transition as InterstitialTransition,
        text: clip.transitionText,
        textSize: clip.transitionTextSize,
        progress: duration > 0 ? located.interstitialElapsed / duration : 1,
      })
      setSequenceTime(clamped)
      return
    }

    const runtime = sequenceRuntimeRef.current
    const overlap = transitionDurationAfter(clips, located.clipIndex)
    const start = clipTimelineStart(clips, located.clipIndex)
    const inOverlap = (
      !isInterstitialTransition(clip.transition)
      && overlap > 0
      && clamped >= start + effectiveDuration(clip) - overlap
    )
    const sameClip = (
      sequenceMode
      && runtime.clipIndex === located.clipIndex
      && !runtime.ended
      && !runtime.interstitial
      && !runtime.transitioning
      && !inOverlap
    )
    if (sameClip) {
      sequencePlayingRef.current = play
      setPlaying(play)
      runtime.ended = false
      const active = sequenceRefs.current[runtime.activeSlot]
      sequenceSlotSeekRef.current[runtime.activeSlot] = located.sourceTime
      if (active) {
        if (Math.abs(active.currentTime - located.sourceTime) <= 0.005) {
          pendingSeekRef.current = null
          pendingSeekAtRef.current = 0
        }
        active.currentTime = located.sourceTime
        if (play) void active.play().catch(() => setError('The browser could not start timeline playback.'))
        else active.pause()
      }
      setSelectedId(clip.id)
      return
    }
    startSequenceAt(located.clipIndex, located.sourceTime, play)
    pendingSeekRef.current = clamped
    pendingSeekAtRef.current = performance.now()
    setSequenceTime(clamped)
  }

  const playbackStartForSelection = () => {
    if (selectedTransitionIndex !== null && clips[selectedTransitionIndex] && clips[selectedTransitionIndex + 1]) {
      return transitionTimelineStart(clips, selectedTransitionIndex)
    }
    if (selectedIndex >= 0) return clipTimelineStart(clips, selectedIndex)
    return 0
  }

  const togglePlayback = () => {
    if (!clips.length) return
    if (sequencePlayingRef.current) {
      setSequencePlaying(false)
      return
    }
    if (sequenceMode && sequenceTime < totalDuration - 0.03) {
      setSequencePlaying(true)
      return
    }
    seekSequence(playbackStartForSelection(), true)
  }

  const selectTimelineClip = (index: number) => {
    if (!clips[index] || trimmingRef.current) return
    setSequencePlaying(false)
    setSelectedTransitionIndex(null)
    setPlayheadDraft(null)
    seekSequence(clipTimelineStart(clips, index), false)
    setSelectedId(clips[index].id)
  }

  const selectTimelineTransition = (index: number) => {
    if (!clips[index] || !clips[index + 1]) return
    setSequencePlaying(false)
    setPlayheadDraft(null)
    seekSequence(transitionTimelineStart(clips, index), false)
    setSelectedTransitionIndex(index)
  }

  const handleSequenceLoaded = (
    slot: 0 | 1,
    clipIndex: number,
    video: HTMLVideoElement,
  ) => {
    const clip = clips[clipIndex]
    if (!clip) return
    const requested = sequenceSlotSeekRef.current[slot]
    video.currentTime = Math.max(
      clip.trimStart,
      Math.min(clip.trimEnd - 0.01, requested ?? clip.trimStart),
    )
    video.volume = clipVolume(clip)
    const runtime = sequenceRuntimeRef.current
    const isActive = runtime.activeSlot === slot && runtime.clipIndex === clipIndex
    const isTransitionTarget = (
      runtime.transitioning
      && runtime.activeSlot !== slot
      && runtime.clipIndex + 1 === clipIndex
    )
    if (sequencePlayingRef.current && !runtime.interstitial && (isActive || isTransitionTarget)) {
      void video.play().catch(() => undefined)
    } else {
      video.pause()
    }
  }

  useEffect(() => {
    if (!sequenceMode) return

    const advanceToNext = (
      runtime: SequenceRuntime,
      nextIndex: number,
      nextClip: EditorClip,
      inactiveSlot: 0 | 1,
      nextVideo: HTMLVideoElement,
    ) => {
      const oldActiveSlot = runtime.activeSlot
      runtime.activeSlot = inactiveSlot
      runtime.clipIndex = nextIndex
      runtime.transitioning = false
      runtime.interstitial = false
      runtime.interstitialElapsed = 0
      runtime.interstitialLastFrame = null
      setSequenceInterstitial(null)
      const followingIndex = nextIndex + 1 < clips.length ? nextIndex + 1 : null
      sequenceSlotSeekRef.current[inactiveSlot] = Math.max(
        nextClip.trimStart,
        nextVideo.currentTime || nextClip.trimStart,
      )
      sequenceSlotSeekRef.current[oldActiveSlot] = (
        followingIndex !== null ? clips[followingIndex].trimStart : null
      )
      setSequenceSlotIndices(previous => {
        const slots = [...previous]
        slots[inactiveSlot] = nextIndex
        slots[oldActiveSlot] = followingIndex
        return slots
      })
      setSequenceStyles(previous => {
        const styles = [...previous]
        styles[inactiveSlot] = sequenceStyle()
        styles[oldActiveSlot] = sequenceStyle({ opacity: 0 })
        return styles
      })
      nextVideo.volume = clipVolume(nextClip)
      if (sequencePlayingRef.current && nextVideo.paused) {
        void nextVideo.play().catch(() => undefined)
      }
      setSelectedId(nextClip.id)
    }

    const renderFrame = () => {
      const runtime = sequenceRuntimeRef.current
      if (runtime.ended) return
      if (scrubbingRef.current) {
        if (pendingSeekRef.current !== null) setSequenceTime(pendingSeekRef.current)
        sequenceFrameRef.current = requestAnimationFrame(renderFrame)
        return
      }
      if (pendingSeekRef.current !== null) {
        const target = sourceTimeAtSequenceTime(clips, pendingSeekRef.current)
        const activeVideo = sequenceRefs.current[runtime.activeSlot]
        const arrived = Boolean(
          activeVideo
          && !target.interstitial
          && Math.abs(activeVideo.currentTime - target.sourceTime) <= 0.08
        )
        const stale = pendingSeekAtRef.current > 0 && performance.now() - pendingSeekAtRef.current > 400
        if (arrived || stale) {
          pendingSeekRef.current = null
          pendingSeekAtRef.current = 0
        } else {
          setSequenceTime(pendingSeekRef.current)
          sequenceFrameRef.current = requestAnimationFrame(renderFrame)
          return
        }
      }
      const currentClip = clips[runtime.clipIndex]
      const activeVideo = sequenceRefs.current[runtime.activeSlot]
      if (!currentClip || !activeVideo) {
        sequenceFrameRef.current = requestAnimationFrame(renderFrame)
        return
      }

      const nextIndex = runtime.clipIndex + 1
      const nextClip = clips[nextIndex]
      const inactiveSlot: 0 | 1 = runtime.activeSlot === 0 ? 1 : 0
      const nextVideo = sequenceRefs.current[inactiveSlot]
      const duration = transitionDurationAfter(clips, runtime.clipIndex)
      const isTimeCard = isInterstitialTransition(currentClip.transition)

      if (runtime.interstitial && isTimeCard) {
        const now = performance.now()
        if (sequencePlayingRef.current) {
          if (runtime.interstitialLastFrame !== null) {
            runtime.interstitialElapsed += Math.max(0, (now - runtime.interstitialLastFrame) / 1000)
          }
          runtime.interstitialLastFrame = now
        } else {
          runtime.interstitialLastFrame = null
        }
        const elapsed = Math.min(duration, runtime.interstitialElapsed)
        const progress = duration > 0 ? elapsed / duration : 1
        setSequenceTime(Math.min(
          totalDuration,
          clipTimelineStart(clips, runtime.clipIndex) + effectiveDuration(currentClip) + elapsed,
        ))
        setSequenceInterstitial({
          transition: currentClip.transition as InterstitialTransition,
          text: currentClip.transitionText,
          textSize: currentClip.transitionTextSize,
          progress,
        })
        if (elapsed >= duration && nextClip && nextVideo) {
          advanceToNext(runtime, nextIndex, nextClip, inactiveSlot, nextVideo)
        }
        sequenceFrameRef.current = requestAnimationFrame(renderFrame)
        return
      }

      const localTime = Math.max(0, activeVideo.currentTime - currentClip.trimStart)
      setSequenceTime(Math.min(
        totalDuration,
        clipTimelineStart(clips, runtime.clipIndex) + localTime,
      ))

      const transitionStart = currentClip.trimEnd - duration
      const inTransition = Boolean(
        nextClip
        && !isTimeCard
        && duration > 0
        && activeVideo.currentTime >= transitionStart
      )

      if (inTransition && nextClip && nextVideo) {
        if (!runtime.transitioning) {
          runtime.transitioning = true
          nextVideo.currentTime = nextClip.trimStart
          nextVideo.volume = 0
          if (sequencePlayingRef.current) void nextVideo.play().catch(() => undefined)
        }
        const progress = Math.max(
          0,
          Math.min(1, (activeVideo.currentTime - transitionStart) / duration),
        )
        activeVideo.volume = clipVolume(currentClip) * (1 - progress)
        nextVideo.volume = clipVolume(nextClip) * progress

        if (currentClip.transition === 'fade-black') {
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle({
              opacity: progress < 0.5 ? 1 - progress * 2 : 0,
            })
            styles[inactiveSlot] = sequenceStyle({
              opacity: progress < 0.5 ? 0 : (progress - 0.5) * 2,
            })
            return styles
          })
        } else if (currentClip.transition === 'wipe-left') {
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle()
            styles[inactiveSlot] = sequenceStyle({
              opacity: 1,
              clipPath: `inset(0 ${(1 - progress) * 100}% 0 0)`,
            })
            return styles
          })
        } else if (currentClip.transition === 'slide-left' || currentClip.transition === 'slide-right') {
          const direction = currentClip.transition === 'slide-left' ? -1 : 1
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle({
              transform: `translate3d(${direction * progress * 100}%, 0, 0) scale(1.015)`,
            })
            styles[inactiveSlot] = sequenceStyle({
              transform: `translate3d(${direction * (progress - 1) * 100}%, 0, 0) scale(1.015)`,
            })
            return styles
          })
        } else if (currentClip.transition === 'circle-open') {
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle()
            styles[inactiveSlot] = sequenceStyle({
              clipPath: `circle(${progress * 75}% at 50% 50%)`,
              transform: `scale(${0.94 + progress * 0.06})`,
            })
            return styles
          })
        } else if (currentClip.transition === 'blur') {
          const blurPeak = Math.sin(progress * Math.PI) * 18
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle({
              opacity: 1 - progress,
              transform: `scale(${1 + progress * 0.05})`,
              filter: `blur(${blurPeak}px)`,
            })
            styles[inactiveSlot] = sequenceStyle({
              opacity: progress,
              transform: `scale(${0.95 + progress * 0.05})`,
              filter: `blur(${blurPeak}px)`,
            })
            return styles
          })
        } else if (currentClip.transition === 'zoom-in') {
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle({
              opacity: 1 - progress,
              transform: `scale(${1 + progress * 0.45})`,
              filter: `blur(${progress * 5}px)`,
            })
            styles[inactiveSlot] = sequenceStyle({
              opacity: Math.min(1, progress * 1.4),
              transform: `scale(${0.72 + progress * 0.28})`,
            })
            return styles
          })
        } else if (currentClip.transition === 'pixelize') {
          const pixelBlur = Math.sin(progress * Math.PI) * 10
          const contrast = 1 + Math.sin(progress * Math.PI)
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle({
              opacity: 1 - progress,
              filter: `blur(${pixelBlur}px) contrast(${contrast})`,
            })
            styles[inactiveSlot] = sequenceStyle({
              opacity: progress,
              filter: `blur(${pixelBlur}px) contrast(${contrast})`,
            })
            return styles
          })
        } else if (currentClip.transition === 'dissolve') {
          const contrast = 1 + Math.sin(progress * Math.PI) * 0.3
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle({
              opacity: 1 - progress,
              filter: `contrast(${contrast}) saturate(${1 - progress * 0.2})`,
            })
            styles[inactiveSlot] = sequenceStyle({
              opacity: progress,
              filter: `contrast(${contrast}) saturate(${0.8 + progress * 0.2})`,
            })
            return styles
          })
        } else {
          setSequenceStyles(previous => {
            const styles = [...previous]
            styles[runtime.activeSlot] = sequenceStyle({ opacity: 1 - progress })
            styles[inactiveSlot] = sequenceStyle({ opacity: progress })
            return styles
          })
        }
      }

      if (activeVideo.currentTime >= currentClip.trimEnd - 0.025) {
        activeVideo.pause()
        if (!nextClip) {
          runtime.ended = true
          sequencePlayingRef.current = false
          setPlaying(false)
          setSequenceTime(totalDuration)
        } else if (isTimeCard) {
          runtime.interstitial = true
          runtime.interstitialElapsed = 0
          runtime.interstitialLastFrame = sequencePlayingRef.current ? performance.now() : null
          runtime.transitioning = false
          nextVideo?.pause()
          if (nextVideo) {
            nextVideo.currentTime = nextClip.trimStart
            nextVideo.volume = clipVolume(nextClip)
          }
          setSequenceInterstitial({
            transition: currentClip.transition as InterstitialTransition,
            text: currentClip.transitionText,
            textSize: currentClip.transitionTextSize,
            progress: 0,
          })
        } else if (nextVideo) {
          advanceToNext(runtime, nextIndex, nextClip, inactiveSlot, nextVideo)
        }
      }

      sequenceFrameRef.current = requestAnimationFrame(renderFrame)
    }

    sequenceFrameRef.current = requestAnimationFrame(renderFrame)
    return () => {
      if (sequenceFrameRef.current !== null) cancelAnimationFrame(sequenceFrameRef.current)
      sequenceFrameRef.current = null
    }
  }, [clips, sequenceMode, totalDuration])

  const pollExport = useCallback(async (jobId: string) => {
    if (!jobId || exportPollingRef.current === jobId) return
    exportPollingRef.current = jobId
    const epoch = ++exportPollEpochRef.current
    try {
      let status = await api.fetchVideoEditorExport(jobId)
      while (mountedRef.current && epoch === exportPollEpochRef.current) {
        if (!mountedRef.current || epoch !== exportPollEpochRef.current) return
        setExportJob(status)
        writeVideoEditorExportId(activeWorkspace, jobId)
        if (status.status === 'completed') {
          await refreshOutputs()
          return
        }
        if (status.status === 'failed' || status.status === 'cancelled') {
          clearVideoEditorExportId(activeWorkspace)
          return
        }
        await wait(1000)
        if (!mountedRef.current || epoch !== exportPollEpochRef.current) return
        status = await api.fetchVideoEditorExport(jobId)
      }
    } catch (reason) {
      if (mountedRef.current && epoch === exportPollEpochRef.current) {
        setError(`Could not reconnect to export ${jobId}: ${(reason as Error).message}`)
      }
    } finally {
      if (exportPollingRef.current === jobId) exportPollingRef.current = null
    }
  }, [activeWorkspace, refreshOutputs])

  useEffect(() => {
    exportPollEpochRef.current += 1
    exportPollingRef.current = null
    const jobId = readVideoEditorExportId(activeWorkspace)
    setExportJob(jobId ? pendingVideoEditorExport(jobId) : null)
    if (jobId) void pollExport(jobId)
    return () => {
      exportPollEpochRef.current += 1
      exportPollingRef.current = null
    }
  }, [activeWorkspace, pollExport])

  const startExport = async () => {
    if (!clips.length || exportSubmittingRef.current || isVideoEditorJobActive(exportJob)) return
    const normalized = normalizeEditorClips(clips, {
      idFactory: clipId,
      thumbnailUrl: api.getVideoEditorThumbnailUrl,
    })
    if (!normalized.clips.length) {
      setClips([])
      setError('No valid clips remain. Restore a source with a finite duration before exporting.')
      return
    }
    const recoveryMessage = editorClipRecoveryMessage(normalized)
    if (recoveryMessage) {
      setClips(normalized.clips)
      persistEditorDraft(normalized.clips, projectName, resolution, fps, draftWorkspaceRef.current)
    }
    setError(recoveryMessage)
    exportSubmittingRef.current = true
    setExportJob({
      job_id: '',
      status: 'queued',
      progress: 0,
      message: 'Submitting export…',
      filename: null,
      url: null,
      error: null,
    })
    try {
      const started = await api.startVideoEditorExport({
        name: projectName,
        width: resolution.width,
        height: resolution.height,
        fps,
        workspace: activeWorkspace,
        soundtrack: soundtrack ? {
          name: soundtrack.name,
          source: soundtrack.source,
          trim_start: soundtrack.trimStart,
          trim_end: soundtrack.trimEnd,
          volume: soundtrack.volume,
          loop: soundtrack.loop,
        } : null,
        clips: normalized.clips.map(clip => ({
          name: clip.name,
          source: clip.source,
          trim_start: clip.trimStart,
          trim_end: clip.trimEnd,
          volume: clip.volume,
          muted: clip.muted,
          fit: clip.fit,
          transition: clip.transition,
          transition_duration: clip.transitionDuration,
          transition_text: clip.transitionText,
          transition_text_size: clip.transitionTextSize,
        })),
      })
      writeVideoEditorExportId(activeWorkspace, started.job_id)
      if (mountedRef.current) setExportJob(started)
      void pollExport(started.job_id)
    } catch (reason) {
      const message = (reason as Error).message
      setError(message)
      clearVideoEditorExportId(activeWorkspace)
      setExportJob(current => current ? { ...current, status: 'failed', error: message, message } : null)
    } finally {
      exportSubmittingRef.current = false
    }
  }

  const cancelExport = async () => {
    if (!exportJob?.job_id || !isVideoEditorJobActive(exportJob) || exportJob.status === 'cancelling') return
    setExportJob(current => current ? {
      ...current,
      status: 'cancelling',
      phase: 'cancelling',
      message: 'Cancelling at the next FFmpeg safe boundary…',
    } : current)
    try {
      const cancelled = await api.cancelVideoEditorExport(exportJob.job_id)
      writeVideoEditorExportId(activeWorkspace, exportJob.job_id)
      setExportJob(cancelled)
      if (isVideoEditorJobActive(cancelled)) void pollExport(cancelled.job_id)
      else if (cancelled.status === 'cancelled') clearVideoEditorExportId(activeWorkspace)
    } catch (reason) {
      const message = (reason as Error).message
      setError(message)
    }
  }

  const takeScreenshot = async () => {
    let clip = selected
    let sourceTime = videoRef.current?.currentTime ?? previewTime
    if (sequenceMode) {
      const runtime = sequenceRuntimeRef.current
      clip = clips[runtime.clipIndex] || null
      sourceTime = sequenceRefs.current[runtime.activeSlot]?.currentTime
        ?? clip?.trimStart
        ?? 0
    }
    if (!clip || capturingFrame) return
    setCapturingFrame(true)
    setCapturedFrame(null)
    setError(null)
    try {
      const result = await api.captureVideoEditorFrame({
        source: clip.source,
        time: sourceTime,
        name: projectName,
        workspace: activeWorkspace,
      })
      setCapturedFrame(result)
      await refreshOutputs()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setCapturingFrame(false)
    }
  }

  return (
    <div
      data-testid="video-editor-panel"
      className="h-full min-h-0 min-w-0 flex flex-col bg-bg-secondary border border-border rounded-xl overflow-hidden"
      onDragOver={event => {
        if (event.dataTransfer.types.includes('Files')) event.preventDefault()
      }}
      onDrop={event => {
        if (!event.dataTransfer.files.length) return
        event.preventDefault()
        void addFiles(Array.from(event.dataTransfer.files))
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={VIDEO_ACCEPT}
        multiple
        className="hidden"
        onChange={event => {
          void addFiles(Array.from(event.target.files || []))
          event.currentTarget.value = ''
        }}
      />

      <div role="toolbar" aria-label="Video editor tools" className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-border bg-bg-tertiary/40">
        <Film size={16} className="shrink-0 text-accent-blue" />
        <input
          value={projectName}
          onChange={event => setProjectName(event.target.value)}
          className="min-w-0 w-32 sm:w-40 md:w-56 bg-transparent text-sm font-medium text-text-primary focus:outline-none border-b border-transparent focus:border-accent-blue"
          aria-label="Project name"
        />
        <div className="hidden flex-1 sm:block" />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={adding}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-bg-secondary hover:bg-bg-hover disabled:opacity-50"
        >
          <Upload size={13} /> Import
        </button>
        <button
          onClick={openMaestroPicker}
          disabled={adding}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg border border-border bg-bg-secondary hover:bg-bg-hover disabled:opacity-50"
        >
          <FolderOpen size={13} /> From HocusPocus
        </button>
        <button
          onClick={startExport}
          disabled={!clips.length || isVideoEditorJobActive(exportJob)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-accent-blue text-white hover:bg-accent-blue/80 disabled:opacity-40"
        >
          {isVideoEditorJobActive(exportJob)
            ? <Loader2 size={13} className="animate-spin" />
            : <Download size={13} />}
          Export MP4
        </button>
        {isVideoEditorJobActive(exportJob) && (
          <button
            onClick={() => void cancelExport()}
            disabled={exportJob?.status === 'cancelling'}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-red-500/40 text-red-300 hover:bg-red-500/10 disabled:opacity-40"
          >
            {exportJob?.status === 'cancelling'
              ? <Loader2 size={13} className="animate-spin" />
              : <X size={13} />}
            {exportJob?.status === 'cancelling' ? 'Cancelling…' : 'Cancel'}
          </button>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto lg:overflow-hidden grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 flex flex-col border-b lg:border-b-0 lg:border-r border-border">
          <div className="flex-1 min-h-[280px] flex items-center justify-center p-4 bg-black/70 relative">
            {sequenceMode ? (
              <ExportPreviewCanvas width={resolution.width} height={resolution.height}>
                {sequenceSlotIndices.map((clipIndex, slot) => {
                  if (clipIndex === null) return null
                  const clip = clips[clipIndex]
                  if (!clip) return null
                  return (
                    <video
                      key={`${slot}-${clip.id}`}
                      ref={element => { sequenceRefs.current[slot] = element }}
                      src={clip.previewUrl}
                      className={`absolute inset-0 w-full h-full ${clip.fit === 'fill' ? 'object-cover' : 'object-contain'}`}
                      style={{
                        opacity: sequenceStyles[slot].opacity,
                        clipPath: sequenceStyles[slot].clipPath,
                        transform: sequenceStyles[slot].transform,
                        filter: sequenceStyles[slot].filter,
                        zIndex: slot === sequenceRuntimeRef.current.activeSlot ? 10 : 20,
                        willChange: 'opacity, clip-path, transform, filter',
                      }}
                      playsInline
                      preload="auto"
                      onLoadedMetadata={event => handleSequenceLoaded(slot as 0 | 1, clipIndex, event.currentTarget)}
                      onSeeked={() => {
                        pendingSeekRef.current = null
                        pendingSeekAtRef.current = 0
                      }}
                    />
                  )
                })}
                {sequenceInterstitial && (
                  <LaterCard
                    transition={sequenceInterstitial.transition}
                    text={sequenceInterstitial.text}
                    textSize={sequenceInterstitial.textSize}
                    progress={sequenceInterstitial.progress}
                  />
                )}
              </ExportPreviewCanvas>
            ) : selected ? (
              <ExportPreviewCanvas width={resolution.width} height={resolution.height}>
                <video
                  key={selected.id}
                  ref={videoRef}
                  src={selected.previewUrl}
                  className={`absolute inset-0 w-full h-full ${selected.fit === 'fill' ? 'object-cover' : 'object-contain'}`}
                  playsInline
                  onLoadedMetadata={event => {
                    event.currentTarget.currentTime = selected.trimStart
                    setPreviewTime(selected.trimStart)
                  }}
                  onPlay={() => {
                    if (!sequencePlayingRef.current) setPlaying(true)
                  }}
                  onPause={() => {
                    if (!sequencePlayingRef.current) setPlaying(false)
                  }}
                  onTimeUpdate={event => {
                    const time = event.currentTarget.currentTime
                    setPreviewTime(time)
                    if (time >= selected.trimEnd - 0.025) {
                      event.currentTarget.pause()
                      event.currentTarget.currentTime = selected.trimStart
                      setPreviewTime(selected.trimStart)
                    }
                  }}
                />
              </ExportPreviewCanvas>
            ) : (
              <ExportPreviewCanvas
                width={resolution.width}
                height={resolution.height}
                overlay={(
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="h-full w-full border-2 border-dashed border-border-light flex flex-col items-center justify-center gap-3 text-text-muted hover:text-text-secondary hover:border-accent-blue/60 transition-colors"
                  >
                    <Upload size={36} />
                    <span className="text-sm">Drop videos here or click to import</span>
                    <span className="text-[10px]">MP4, WebM, MOV, MKV, AVI · up to 500 MB each</span>
                  </button>
                )}
              />
            )}
          </div>

          <div className="px-3 py-3 border-t border-border bg-bg-tertiary/30">
            <div className="flex items-center gap-2">
              <button
                onClick={togglePlayback}
                disabled={!clips.length}
                className="p-1.5 rounded-md hover:bg-bg-hover disabled:opacity-40"
                aria-label={playing ? 'Pause' : 'Play'}
                title="Play from the selected clip, transition, or playhead"
              >
                {playing ? <Pause size={15} /> : <Play size={15} />}
              </button>
              <button
                onClick={() => startSequenceAt(0, undefined, false)}
                disabled={!clips.length}
                className="p-1.5 rounded-md hover:bg-bg-hover disabled:opacity-40"
                title="Return to the beginning"
              >
                <RotateCcw size={13} />
              </button>
              <span className="text-[10px] text-text-muted tabular-nums">
                {formatPlayheadTime(playheadSeconds)} / {formatPlayheadTime(totalDuration)}
              </span>
              <SequenceScrubber
                duration={totalDuration}
                time={Math.min(totalDuration, playheadSeconds)}
                disabled={!clips.length}
                onScrub={(next, phase) => {
                  scrubbingRef.current = phase !== 'end'
                  setPlayheadDraft(null)
                  setSequencePlaying(false)
                  seekSequence(next, false)
                  if (phase === 'end') pendingSeekAtRef.current = performance.now()
                }}
              />
              <label className="flex items-center gap-1 text-[10px] text-text-muted">
                s
                <input
                  type="number"
                  inputMode="decimal"
                  min={0}
                  max={Number(totalDuration.toFixed(2))}
                  step={0.01}
                  aria-label="Playhead seconds"
                  data-testid="playhead-seconds"
                  disabled={!clips.length}
                  value={playheadDraft ?? playheadSeconds.toFixed(2)}
                  onChange={event => setPlayheadDraft(event.target.value)}
                  onBlur={() => {
                    if (playheadDraft === null) return
                    const parsed = parsePlayheadSeconds(playheadDraft)
                    setPlayheadDraft(null)
                    if (parsed === null) return
                    setSequencePlaying(false)
                    seekSequence(parsed, false)
                  }}
                  onKeyDown={event => {
                    if (event.key !== 'Enter') return
                    event.currentTarget.blur()
                  }}
                  className="w-[4.6rem] rounded border border-border bg-bg-secondary px-1.5 py-1 text-[11px] tabular-nums text-text-primary"
                />
              </label>
              <button
                onClick={splitSelected}
                disabled={!clips.length}
                className="flex items-center gap-1 px-2 py-1 text-[10px] rounded border border-border hover:bg-bg-hover disabled:opacity-40"
                title="Split the clip at the current playhead"
              >
                <Scissors size={11} /> Split
              </button>
              <button
                onClick={takeScreenshot}
                disabled={!selected || capturingFrame}
                className="flex items-center gap-1 px-2 py-1 text-[10px] rounded border border-border hover:bg-bg-hover disabled:opacity-40"
                title="Save the exact current source frame as a reusable PNG in HocusPocus Outputs"
              >
                {capturingFrame
                  ? <Loader2 size={11} className="animate-spin" />
                  : <Camera size={11} />}
                Take screenshot
              </button>
            </div>
            {capturedFrame && (
              <div className="mt-1.5 flex items-center gap-2 text-[10px] text-emerald-400">
                <Check size={11} />
                Saved {capturedFrame.filename} at {formatTime(capturedFrame.time)}
                · {capturedFrame.width}×{capturedFrame.height}
              </div>
            )}
          </div>
        </section>

        <aside aria-label="Video editor inspector" className="min-h-0 overflow-y-auto p-3 space-y-4 bg-bg-secondary">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-1.5">Output</label>
            <select
              value={`${resolution.width}x${resolution.height}`}
              onChange={event => {
                const next = RESOLUTIONS.find(option => `${option.width}x${option.height}` === event.target.value)
                if (next) setResolution(next)
              }}
              className="w-full bg-bg-tertiary border border-border rounded px-2 py-1.5 text-xs"
            >
              {RESOLUTIONS.map(option => (
                <option key={option.label} value={`${option.width}x${option.height}`}>
                  {option.label} · {option.width}×{option.height}
                </option>
              ))}
            </select>
            <div className="mt-2">
              <label className="text-[10px] text-text-muted">
                Frame rate
                <select
                  value={fps}
                  onChange={event => setFps(Number(event.target.value))}
                  className="block w-full mt-1 bg-bg-tertiary border border-border rounded px-2 py-1.5 text-xs text-text-primary"
                >
                  {[24, 25, 30, 50, 60].map(value => <option key={value} value={value}>{value} FPS</option>)}
                </select>
              </label>
            </div>
          </div>

          {selectedTransitionIndex !== null && clips[selectedTransitionIndex] && clips[selectedTransitionIndex + 1] && (
            <div className="border-t border-border pt-3">
              <div className="flex items-start gap-2 mb-3">
                <WandSparkles size={14} className="text-purple-400 mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs text-text-primary">Transition {selectedTransitionIndex + 1}</p>
                  <p className="text-[9px] text-text-muted truncate">
                    {clips[selectedTransitionIndex].name} → {clips[selectedTransitionIndex + 1].name}
                  </p>
                </div>
                <button
                  onClick={() => setSelectedTransitionIndex(null)}
                  className="ml-auto p-0.5 text-text-muted hover:text-text-primary"
                >
                  <X size={12} />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-2">
                {TRANSITIONS.map(option => {
                  const active = clips[selectedTransitionIndex].transition === option.value
                  return (
                    <button
                      key={option.value}
                      onClick={() => {
                        const clip = clips[selectedTransitionIndex]
                        patchClip(clip.id, {
                          transition: option.value,
                          ...(isInterstitialTransition(option.value) && !isInterstitialTransition(clip.transition)
                            ? { transitionDuration: 2 }
                            : {}),
                        })
                      }}
                      className={`group rounded-lg border p-2 text-left transition-colors ${
                        active
                          ? 'border-purple-400 bg-purple-500/10'
                          : 'border-border bg-bg-tertiary/40 hover:border-border-light'
                      }`}
                      title={t(option.descriptionKey)}
                    >
                      <div className="h-8 rounded bg-black/60 overflow-hidden relative mb-1.5">
                        <div className="absolute inset-y-0 left-0 w-[58%] bg-gradient-to-br from-cyan-500 to-blue-700" />
                        <div className={`absolute inset-y-0 right-0 w-[58%] bg-gradient-to-br from-fuchsia-500 to-purple-800 ${
                          option.value === 'wipe-left' ? 'border-l-2 border-white/70' : ''
                        }`} />
                        {option.value === 'fade-black' && <div className="absolute inset-0 bg-black/65" />}
                        {option.value === 'none' && <div className="absolute inset-y-0 left-1/2 w-px bg-white" />}
                        {option.value === 'crossfade' && <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent" />}
                        {(option.value === 'slide-left' || option.value === 'slide-right') && (
                          <ChevronsRight
                            size={18}
                            className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-white drop-shadow ${
                              option.value === 'slide-right' ? 'rotate-180' : ''
                            }`}
                          />
                        )}
                        {option.value === 'circle-open' && (
                          <div className="absolute left-1/2 top-1/2 h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white/90 bg-fuchsia-500/25 shadow-[0_0_8px_white]" />
                        )}
                        {option.value === 'dissolve' && (
                          <div
                            className="absolute inset-0 opacity-70"
                            style={{ backgroundImage: 'radial-gradient(circle, white 0 1px, transparent 1.5px)', backgroundSize: '5px 5px' }}
                          />
                        )}
                        {option.value === 'pixelize' && (
                          <div
                            className="absolute inset-0 opacity-70"
                            style={{
                              backgroundImage: 'linear-gradient(90deg, rgba(255,255,255,.75) 1px, transparent 1px), linear-gradient(rgba(255,255,255,.75) 1px, transparent 1px)',
                              backgroundSize: '7px 7px',
                            }}
                          />
                        )}
                        {option.value === 'blur' && <div className="absolute inset-0 backdrop-blur-sm bg-white/10" />}
                        {option.value === 'zoom-in' && (
                          <div className="absolute left-1/2 top-1/2 h-5 w-8 -translate-x-1/2 -translate-y-1/2 border border-white/90 shadow-[0_0_10px_white]" />
                        )}
                        {isInterstitialTransition(option.value) && (
                          <LaterCard
                            transition={option.value}
                            text={t('timeCard.default')}
                            compact
                          />
                        )}
                      </div>
                      <span className={`text-[9px] ${active ? 'text-purple-300' : 'text-text-secondary'}`}>
                        {t(option.labelKey)}
                      </span>
                    </button>
                  )
                })}
              </div>

              {clips[selectedTransitionIndex].transition !== 'none' && (
                <div className="mt-3 space-y-3">
                  {isInterstitialTransition(clips[selectedTransitionIndex].transition) && (
                    <div className="space-y-3">
                      <label className="block text-[10px] text-text-muted">
                        {t('timeCard.label')}
                        <textarea
                          rows={3}
                          maxLength={240}
                          value={clips[selectedTransitionIndex].transitionText}
                          placeholder={t('timeCard.default')}
                          onChange={event => patchClip(clips[selectedTransitionIndex].id, {
                            transitionText: event.target.value,
                          })}
                          className="mt-1 block w-full resize-y rounded border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary"
                        />
                        <span className="mt-1 block text-[9px] text-text-secondary">
                          {t('timeCard.hint')}
                        </span>
                      </label>
                      <label className="block text-[10px] text-text-muted">
                        {t('timeCard.size', { size: Math.round(clips[selectedTransitionIndex].transitionTextSize) })}
                        <input
                          type="range"
                          min={50}
                          max={160}
                          step={5}
                          value={clips[selectedTransitionIndex].transitionTextSize}
                          onChange={event => patchClip(clips[selectedTransitionIndex].id, {
                            transitionTextSize: Number(event.target.value),
                          })}
                          className="mt-1 block w-full"
                        />
                      </label>
                    </div>
                  )}
                  <label className="block text-[10px] text-text-muted">
                    Duration: {clips[selectedTransitionIndex].transitionDuration.toFixed(1)}s
                    <input
                      type="range"
                      min={isInterstitialTransition(clips[selectedTransitionIndex].transition) ? 0.5 : 0.1}
                      max={isInterstitialTransition(clips[selectedTransitionIndex].transition) ? 5 : 2}
                      step={0.1}
                      value={clips[selectedTransitionIndex].transitionDuration}
                      onChange={event => patchClip(clips[selectedTransitionIndex].id, {
                        transitionDuration: Number(event.target.value),
                      })}
                      className="block w-full mt-1"
                    />
                    <span className="block mt-1 text-[9px] text-text-muted/70">
                      {isInterstitialTransition(clips[selectedTransitionIndex].transition)
                        ? 'This card is inserted between clips and adds to the total duration.'
                        : 'The preview and export clamp this automatically for very short clips.'}
                    </span>
                  </label>
                </div>
              )}

              <button
                onClick={() => {
                  const transitionClip = clips[selectedTransitionIndex]
                  const start = clipTimelineStart(clips, selectedTransitionIndex)
                    + effectiveDuration(transitionClip)
                    - (isInterstitialTransition(transitionClip.transition)
                      ? 0.35
                      : transitionDurationAfter(clips, selectedTransitionIndex) + 0.35)
                  seekSequence(Math.max(0, start))
                  window.setTimeout(() => setSequencePlaying(true), 80)
                }}
                className="mt-3 w-full flex items-center justify-center gap-1.5 py-1.5 rounded border border-purple-500/30 bg-purple-500/10 text-[10px] text-purple-300 hover:bg-purple-500/20"
              >
                <Play size={11} /> Preview this transition
              </button>
            </div>
          )}

          {selected && (
            <div className="border-t border-border pt-3">
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="min-w-0">
                  <p className="text-xs text-text-primary truncate">{selected.name}</p>
                  <p className="text-[9px] text-text-muted">
                    {selected.width}×{selected.height} · {selected.fps.toFixed(1)} FPS
                  </p>
                  <p className={`text-[9px] ${selected.has_alpha ? 'text-green-400' : 'text-text-muted'}`}>
                    {selected.has_alpha
                      ? `Alpha channel · ${selected.pixel_format}`
                      : `No alpha · ${selected.pixel_format}`}
                  </p>
                </div>
                <button
                  onClick={() => removeClip(selected.id)}
                  className="flex items-center gap-1 rounded border border-red-500/30 px-2 py-1 text-[10px] text-red-300 transition-colors hover:bg-red-500/15 hover:text-red-200"
                  title="Remove this video from the timeline"
                >
                  <Trash2 size={12} /> Remove
                </button>
              </div>

              <button
                type="button"
                onClick={() => void openSelectedInVideoCreation()}
                disabled={preparingReplacement}
                className="mb-3 flex w-full items-center justify-center gap-1.5 rounded border border-accent-blue/40 bg-accent-blue/10 px-2 py-2 text-[10px] font-medium text-accent-blue transition-colors hover:bg-accent-blue/20 disabled:opacity-50"
                title={t('remake.title')}
              >
                {preparingReplacement
                  ? <Loader2 size={12} className="animate-spin" />
                  : <Film size={12} />}
                {preparingReplacement ? t('remake.loading') : t('remake.action')}
              </button>

              <ClipTrimBar
                duration={selected.duration}
                start={selected.trimStart}
                end={selected.trimEnd}
                onChange={patch => patchClip(selected.id, patch)}
              />
              <p className="mt-2 text-[9px] leading-relaxed text-text-muted">
                {t('trim.hint')}
              </p>

              <div className="mt-2 grid grid-cols-2 gap-2">
                <label className="text-[10px] text-text-muted">
                  {t('trim.exactIn')}
                  <input
                    type="number"
                    min={0}
                    max={selected.trimEnd - 0.05}
                    step={0.05}
                    value={Number(selected.trimStart.toFixed(2))}
                    onChange={event => patchClip(selected.id, {
                      trimStart: Math.max(0, Math.min(Number(event.target.value), selected.trimEnd - 0.05)),
                    })}
                    className="block w-full mt-1 bg-bg-tertiary border border-border rounded px-2 py-1 text-xs text-text-primary"
                  />
                </label>
                <label className="text-[10px] text-text-muted">
                  {t('trim.exactOut')}
                  <input
                    type="number"
                    min={selected.trimStart + 0.05}
                    max={selected.duration}
                    step={0.05}
                    value={Number(selected.trimEnd.toFixed(2))}
                    onChange={event => patchClip(selected.id, {
                      trimEnd: Math.min(selected.duration, Math.max(Number(event.target.value), selected.trimStart + 0.05)),
                    })}
                    className="block w-full mt-1 bg-bg-tertiary border border-border rounded px-2 py-1 text-xs text-text-primary"
                  />
                </label>
              </div>
              {(selected.trimStart > 0.001 || selected.trimEnd < selected.duration - 0.001) && (
                <button
                  type="button"
                  onClick={() => patchClip(selected.id, { trimStart: 0, trimEnd: selected.duration })}
                  className="mt-2 flex w-full items-center justify-center gap-1 rounded border border-border px-2 py-1.5 text-[10px] text-text-muted hover:bg-bg-hover hover:text-text-secondary"
                >
                  <RotateCcw size={11} /> {t('trim.restore')}
                </button>
              )}

              <div className="flex items-center gap-2 mt-3">
                <button
                  onClick={() => patchClip(selected.id, { muted: !selected.muted })}
                  className={`p-1.5 rounded border ${selected.muted ? 'border-red-500/40 text-red-400' : 'border-border text-text-secondary'}`}
                  title={selected.muted ? 'Unmute clip' : 'Mute clip'}
                >
                  {selected.muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
                </button>
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.05}
                  value={selected.volume}
                  disabled={selected.muted}
                  onChange={event => patchClip(selected.id, { volume: Number(event.target.value) })}
                  className="flex-1"
                />
                <span className="text-[9px] text-text-muted tabular-nums w-9 text-right">
                  {Math.round(selected.volume * 100)}%
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 mt-3">
                {(['fit', 'fill'] as ClipFit[]).map(value => (
                  <button
                    key={value}
                    onClick={() => patchClip(selected.id, { fit: value })}
                    className={`px-2 py-1.5 text-[10px] rounded border ${
                      selected.fit === value
                        ? 'border-accent-blue bg-accent-blue/10 text-accent-blue'
                        : 'border-border text-text-muted hover:text-text-secondary'
                    }`}
                  >
                    {value === 'fit' ? 'Fit · no crop' : 'Fill · crop'}
                  </button>
                ))}
              </div>

              <div className="flex gap-1.5 mt-3">
                <button
                  onClick={() => reorder(selected.id, -1)}
                  disabled={selectedIndex <= 0}
                  className="flex-1 flex items-center justify-center gap-1 py-1 text-[10px] border border-border rounded hover:bg-bg-hover disabled:opacity-30"
                >
                  <ArrowUp size={11} /> Earlier
                </button>
                <button
                  onClick={() => reorder(selected.id, 1)}
                  disabled={selectedIndex < 0 || selectedIndex >= clips.length - 1}
                  className="flex-1 flex items-center justify-center gap-1 py-1 text-[10px] border border-border rounded hover:bg-bg-hover disabled:opacity-30"
                >
                  <ArrowDown size={11} /> Later
                </button>
                <button
                  onClick={() => {
                    const duplicate = { ...selected, id: clipId(), name: `${selected.name} (copy)` }
                    setClips(current => {
                      const index = current.findIndex(clip => clip.id === selected.id)
                      const next = [...current]
                      next[index] = { ...selected, transition: 'none' }
                      next.splice(index + 1, 0, duplicate)
                      return next
                    })
                    setSelectedId(duplicate.id)
                  }}
                  className="p-1.5 border border-border rounded hover:bg-bg-hover"
                  title="Duplicate clip"
                >
                  <Copy size={11} />
                </button>
              </div>
            </div>
          )}

          {(adding || exportJob || error) && (
            <div className="border-t border-border pt-3 space-y-2">
              {adding && (
                <div className="flex items-center gap-2 text-[10px] text-accent-blue">
                  <Loader2 size={12} className="animate-spin" /> {addProgress || 'Importing video…'}
                </div>
              )}
              {exportJob && (
                <div className={`rounded border p-2 ${
                  exportJob.status === 'failed'
                    ? 'border-red-500/30 bg-red-500/5'
                    : exportJob.status === 'completed'
                      ? 'border-green-500/30 bg-green-500/5'
                      : exportJob.status === 'cancelled'
                        ? 'border-border bg-bg-secondary'
                      : 'border-accent-blue/30 bg-accent-blue/5'
                }`}>
                  <div className="flex items-center gap-1.5 text-[10px]">
                    {exportJob.status === 'completed'
                      ? <Check size={12} className="text-green-400" />
                      : exportJob.status === 'failed' || exportJob.status === 'cancelled'
                        ? <X size={12} className="text-red-400" />
                        : <Loader2 size={12} className="animate-spin text-accent-blue" />}
                    <span className="truncate">{exportJob.message}</span>
                  </div>
                  {isVideoEditorJobActive(exportJob) && (
                    <div className="h-1 bg-bg-active rounded mt-2 overflow-hidden">
                      <div className="h-full bg-accent-blue" style={{ width: `${exportJob.progress}%` }} />
                    </div>
                  )}
                  {exportJob.status === 'completed' && exportJob.url && (
                    <a
                      href={exportJob.url}
                      download={exportJob.filename || undefined}
                      className="mt-2 flex items-center justify-center gap-1.5 py-1.5 rounded bg-green-500/15 text-green-400 text-[10px] hover:bg-green-500/25"
                    >
                      <Download size={11} /> Download {exportJob.filename}
                    </a>
                  )}
                </div>
              )}
              {error && (
                <div className="space-y-2">
                  <div className="whitespace-pre-wrap text-[10px] text-red-400 bg-red-500/10 border border-red-500/20 rounded p-2">
                    {error}
                  </div>
                  {pendingHandoff && !adding && (
                    <button
                      type="button"
                      onClick={() => {
                        try {
                          const key = pendingHandoff === 'sequence'
                            ? VIDEO_EDITOR_PENDING_SEQUENCE_KEY
                            : VIDEO_EDITOR_PENDING_SOURCE_KEY
                          const handoff = JSON.parse(window.localStorage.getItem(key) || 'null')
                          if (handoff) void processPendingHandoff(pendingHandoff, handoff)
                        } catch (reason) {
                          setError(`Could not retry the hand-off: ${(reason as Error).message}`)
                        }
                      }}
                      className="flex items-center justify-center gap-1.5 w-full py-1.5 rounded border border-red-500/30 text-[10px] text-red-300 hover:bg-red-500/10"
                    >
                      <RotateCcw size={11} /> Retry hand-off
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>

      <div role="region" aria-label="Video editor timeline" className="h-40 shrink-0 border-t border-border bg-bg-tertiary/30 flex flex-col">
        <div className="flex h-9 items-center gap-2 px-3 border-b border-border text-[10px] text-text-muted">
          <span>Timeline · {clips.length} {clips.length === 1 ? 'clip' : 'clips'} · {formatTime(totalDuration)}</span>
          {soundtrack && (
            <span
              className="flex max-w-56 items-center gap-1 truncate rounded border border-purple-500/30 bg-purple-500/10 px-1.5 py-0.5 text-purple-200"
              title={`Soundtrack: ${soundtrack.name}`}
            >
              <Volume2 size={10} /> {soundtrack.name}{soundtrack.loop ? ' · loop' : ''}
            </span>
          )}
          <label className="ml-auto flex items-center gap-1.5">
            <span>All gaps</span>
            <select
              aria-label="Default transition for all gaps"
              value={bulkTransition}
              onChange={event => setBulkTransition(event.target.value as Transition)}
              className="max-w-[11rem] rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-[10px] text-text-secondary"
            >
              {TRANSITIONS.map(option => (
                <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={applyAllGapTransitions}
              disabled={clips.length < 2}
              className="rounded border border-purple-500/40 px-2 py-0.5 text-[10px] text-purple-300 hover:bg-purple-500/10 disabled:opacity-40"
            >
              Apply to all
            </button>
          </label>
        </div>
        <div
          ref={timelineScrollRef}
          className="flex-1 overflow-x-auto p-2"
          onDragOver={event => {
            if (!draggedId && !event.dataTransfer.types.includes('text/x-maestro-video-clip')) return
            event.preventDefault()
            updateTimelineDragScroll(event.clientX)
          }}
          onDrop={() => stopTimelineDragScroll()}
        >
          {clips.length ? (
            <div className="h-full flex items-stretch gap-1 min-w-max">
              {clips.map((clip, index) => {
                const width = Math.max(110, Math.min(360, effectiveDuration(clip) * 24))
                return (
                  <Fragment key={clip.id}>
                    <div className="relative shrink-0" style={{ width }}>
                      <button
                        draggable
                        onDragStart={event => {
                          if (trimmingRef.current) {
                            event.preventDefault()
                            return
                          }
                          event.dataTransfer.effectAllowed = 'move'
                          event.dataTransfer.setData('text/x-maestro-video-clip', clip.id)
                          setDraggedId(clip.id)
                        }}
                        onDragEnd={() => {
                          setDraggedId(null)
                          setDropIndex(null)
                          stopTimelineDragScroll()
                        }}
                        onDragOver={event => {
                          event.preventDefault()
                          event.dataTransfer.dropEffect = 'move'
                          updateTimelineDragScroll(event.clientX)
                          const bounds = event.currentTarget.getBoundingClientRect()
                          setDropIndex(index + (event.clientX > bounds.left + bounds.width / 2 ? 1 : 0))
                        }}
                        onDrop={event => {
                          event.preventDefault()
                          event.stopPropagation()
                          const bounds = event.currentTarget.getBoundingClientRect()
                          const insertionIndex = index + (event.clientX > bounds.left + bounds.width / 2 ? 1 : 0)
                          dropAtIndex(insertionIndex, event.dataTransfer.getData('text/x-maestro-video-clip'))
                        }}
                        onClick={() => {
                          if (trimmingRef.current) return
                          selectTimelineClip(index)
                        }}
                        aria-label={`Select clip ${index + 1}: ${clip.name}`}
                        className={`relative h-full w-full overflow-hidden rounded-lg border text-left transition-colors ${
                          selected?.id === clip.id && selectedTransitionIndex === null
                            ? 'border-accent-blue ring-1 ring-accent-blue/50'
                            : 'border-border hover:border-border-light'
                        }`}
                      >
                        {dropIndex === index && (
                          <span className="absolute inset-y-1 left-0 z-30 w-1 rounded-full bg-accent-blue shadow-[0_0_8px_rgba(59,130,246,0.9)]" />
                        )}
                        {dropIndex === index + 1 && index === clips.length - 1 && (
                          <span className="absolute inset-y-1 right-0 z-30 w-1 rounded-full bg-accent-blue shadow-[0_0_8px_rgba(59,130,246,0.9)]" />
                        )}
                        <img
                          src={clip.thumbnailUrl || api.getVideoEditorThumbnailUrl(clip.source)}
                          alt=""
                          className="absolute inset-0 h-full w-full object-cover opacity-45"
                          loading="lazy"
                          decoding="async"
                        />
                        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-black/40" />
                        <div className="relative flex h-full flex-col p-2">
                          <div className="flex items-center gap-1 text-[9px] text-white/70">
                            <GripVertical size={10} /> {index + 1}
                            {clip.muted && <VolumeX size={9} className="ml-auto" />}
                          </div>
                          <div className="mt-auto">
                            <p className="truncate text-[10px] text-white">{clip.name}</p>
                            <p className="text-[9px] text-white/60">{formatTime(effectiveDuration(clip))}</p>
                          </div>
                        </div>
                        <span
                          role="separator"
                          aria-label={`Trim start of ${clip.name}`}
                          onPointerDown={event => beginTimelineTrim(event, clip.id, 'start')}
                          className="absolute inset-y-0 left-0 z-30 w-2.5 cursor-ew-resize rounded-l-lg bg-accent-blue/0 hover:bg-accent-blue/50"
                        />
                        <span
                          role="separator"
                          aria-label={`Trim end of ${clip.name}`}
                          onPointerDown={event => beginTimelineTrim(event, clip.id, 'end')}
                          className="absolute inset-y-0 right-0 z-30 w-2.5 cursor-ew-resize rounded-r-lg bg-accent-blue/0 hover:bg-accent-blue/50"
                        />
                      </button>
                      <button
                        type="button"
                        onClick={event => {
                          event.stopPropagation()
                          removeClip(clip.id)
                        }}
                        className="absolute right-1 top-1 z-40 flex items-center gap-1 rounded-md border border-red-400/30 bg-black/75 px-1.5 py-1 text-[9px] text-red-200 shadow transition-colors hover:bg-red-500/35 hover:text-white"
                        title={`Remove ${clip.name} from the timeline`}
                        aria-label={`Remove ${clip.name} from the timeline`}
                      >
                        <Trash2 size={10} /> Remove
                      </button>
                    </div>
                    {index < clips.length - 1 && (
                      <button
                        onDragOver={event => {
                          event.preventDefault()
                          event.dataTransfer.dropEffect = 'move'
                          setDropIndex(index + 1)
                        }}
                        onDrop={event => {
                          event.preventDefault()
                          event.stopPropagation()
                          dropAtIndex(index + 1, event.dataTransfer.getData('text/x-maestro-video-clip'))
                        }}
                        onClick={() => {
                          selectTimelineTransition(index)
                        }}
                        aria-label={`Select transition ${index + 1}`}
                        className={`w-14 shrink-0 rounded-lg border flex flex-col items-center justify-center gap-1 transition-colors ${
                          selectedTransitionIndex === index
                            ? 'border-purple-400 bg-purple-500/15 text-purple-300'
                            : clip.transition !== 'none'
                              ? 'border-purple-500/40 bg-purple-500/10 text-purple-400'
                              : 'border-dashed border-border text-text-muted hover:border-purple-500/50 hover:text-purple-300'
                        }`}
                        title={t('transitions.named', { name: t(TRANSITIONS.find(option => option.value === clip.transition)?.labelKey || 'transitions.hardCut') })}
                      >
                        {clip.transition === 'none' ? <Plus size={13} /> : <ChevronsRight size={15} />}
                        <span className="max-w-[48px] truncate text-[8px]">
                          {clip.transition === 'none'
                            ? t('transitions.hardCut')
                            : t(TRANSITIONS.find(option => option.value === clip.transition)?.labelKey || 'transitions.hardCut')}
                        </span>
                      </button>
                    )}
                  </Fragment>
                )
              })}
              <button
                onClick={() => fileInputRef.current?.click()}
                onDragOver={event => {
                  if (!draggedId && !event.dataTransfer.types.includes('text/x-maestro-video-clip')) return
                  event.preventDefault()
                  event.dataTransfer.dropEffect = 'move'
                  setDropIndex(clips.length)
                }}
                onDrop={event => {
                  const movingId = event.dataTransfer.getData('text/x-maestro-video-clip')
                  if (!movingId && !draggedId) return
                  event.preventDefault()
                  event.stopPropagation()
                  dropAtIndex(clips.length, movingId)
                }}
                className={`w-20 rounded-lg border border-dashed flex flex-col items-center justify-center gap-1 transition-colors ${
                  dropIndex === clips.length && draggedId
                    ? 'border-accent-blue bg-accent-blue/10 text-accent-blue'
                    : 'border-border text-text-muted hover:text-accent-blue hover:border-accent-blue'
                }`}
              >
                {draggedId ? <ChevronsRight size={16} /> : <Plus size={16} />}
                <span className="text-[9px]">{draggedId ? 'Move to end' : 'Add clip'}</span>
              </button>
            </div>
          ) : (
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-full h-full rounded-lg border border-dashed border-border flex items-center justify-center gap-2 text-xs text-text-muted hover:text-accent-blue hover:border-accent-blue"
            >
              <Plus size={15} /> Add your first video
            </button>
          )}
        </div>
      </div>

      {pickerOpen && (
        <ModalShell
          open
          title="Add HocusPocus videos"
          onClose={closeMaestroPicker}
          className="fixed inset-0 z-[80] bg-black/65 flex items-center justify-center p-4"
          onMouseDown={event => {
            if (event.currentTarget === event.target) closeMaestroPicker()
          }}
        >
          <div className="w-full max-w-4xl max-h-[78vh] bg-bg-secondary border border-border rounded-xl shadow-2xl overflow-hidden flex flex-col">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
              <FolderOpen size={15} className="text-accent-blue" />
              <span className="text-sm font-medium">Add HocusPocus videos</span>
              {maestroVideoTotal > 0 && (
                <span className="text-[10px] text-text-muted">{maestroVideos.length} / {maestroVideoTotal}</span>
              )}
              <button type="button" onClick={closeMaestroPicker} aria-label="Close HocusPocus video picker" className="ml-auto p-1 rounded hover:bg-bg-hover">
                <X size={15} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {pickerLoading && maestroVideos.length === 0 ? (
                <div className="min-h-48 flex items-center justify-center text-text-muted">
                  <Loader2 size={22} className="animate-spin" />
                </div>
              ) : maestroVideos.length ? (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3" role="listbox" aria-multiselectable="true" aria-label="HocusPocus videos">
                  {maestroVideos.map(output => {
                    const selected = pickerSelectedSet.has(output.name)
                    return (
                      <button
                        key={output.name}
                        type="button"
                        role="option"
                        aria-label={output.name}
                        aria-selected={selected}
                        onClick={event => toggleMaestroVideo(output, event)}
                        className={`relative rounded-lg overflow-hidden border text-left ${
                          selected
                            ? 'border-accent-blue ring-1 ring-accent-blue/50 bg-accent-blue/10'
                            : 'border-border bg-bg-tertiary hover:border-accent-blue'
                        }`}
                      >
                        <span className={`absolute top-2 left-2 z-10 flex h-5 w-5 items-center justify-center rounded border ${
                          selected
                            ? 'border-accent-blue bg-accent-blue text-white'
                            : 'border-white/50 bg-black/50 text-transparent'
                        }`}>
                          <Check size={12} />
                        </span>
                        {output.thumbnail_url ? (
                          <img
                            src={output.thumbnail_url}
                            alt=""
                            className="w-full aspect-video object-cover bg-black"
                            loading="lazy"
                            decoding="async"
                          />
                        ) : (
                          <div className="flex aspect-video items-center justify-center bg-black text-text-muted"><Film size={20} /></div>
                        )}
                        <p className="p-2 text-[10px] text-text-secondary truncate">{output.name}</p>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="min-h-48 flex items-center justify-center text-xs text-text-muted">
                  No videos found in workspace “{activeWorkspace}”.
                </div>
              )}
              {maestroVideos.length < maestroVideoTotal && (
                <div className="flex justify-center py-4">
                  <button
                    type="button"
                    onClick={() => void loadMoreMaestroVideos()}
                    disabled={pickerLoading}
                    className="flex items-center gap-2 rounded-lg border border-border bg-bg-tertiary px-3 py-2 text-xs text-text-secondary hover:border-accent-blue hover:text-text-primary disabled:opacity-60"
                  >
                    {pickerLoading && <Loader2 size={13} className="animate-spin" />}
                    Load {Math.min(MAESTRO_PICKER_PAGE_SIZE, maestroVideoTotal - maestroVideos.length)} more
                  </button>
                </div>
              )}
            </div>
            {maestroVideos.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-t border-border bg-bg-tertiary/40">
                <button
                  type="button"
                  onClick={() => setPickerSelected(maestroVideos.map(item => item.name))}
                  className="px-2.5 py-1.5 text-xs rounded-lg border border-border bg-bg-secondary hover:bg-bg-hover"
                >
                  Select all shown
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPickerSelected([])
                    pickerAnchorRef.current = null
                  }}
                  disabled={!pickerSelected.length}
                  className="px-2.5 py-1.5 text-xs rounded-lg border border-border bg-bg-secondary hover:bg-bg-hover disabled:opacity-40"
                >
                  Clear
                </button>
                <span className="text-[10px] text-text-muted">
                  {pickerSelected.length} selected · click to toggle, Shift-click for a range
                </span>
                <button
                  type="button"
                  onClick={() => void addSelectedMaestroVideos()}
                  disabled={!pickerSelected.length || adding}
                  className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-accent-blue text-white hover:bg-accent-blue/80 disabled:opacity-40"
                >
                  {pickerSelected.length
                    ? `Add ${pickerSelected.length} ${pickerSelected.length === 1 ? 'video' : 'videos'}`
                    : 'Add videos'}
                </button>
              </div>
            )}
          </div>
        </ModalShell>
      )}
    </div>
  )
}
