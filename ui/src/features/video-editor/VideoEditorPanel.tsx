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
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'

type ClipFit = 'fit' | 'fill'
type Transition =
  | 'none'
  | 'crossfade'
  | 'fade-black'
  | 'wipe-left'
  | 'slide-left'
  | 'slide-right'
  | 'circle-open'
  | 'dissolve'
  | 'pixelize'
  | 'blur'
  | 'zoom-in'
  | 'later-clock'
  | 'later-tropical'
  | 'later-cinematic'

type InterstitialTransition = 'later-clock' | 'later-tropical' | 'later-cinematic'

interface SequenceStyle {
  opacity: number
  clipPath: string
  transform: string
  filter: string
}

interface EditorClip extends api.VideoEditorProbe {
  id: string
  name: string
  source: string
  previewUrl: string
  thumbnailUrl: string
  trimStart: number
  trimEnd: number
  volume: number
  muted: boolean
  fit: ClipFit
  transition: Transition
  transitionDuration: number
  transitionText: string
  transitionTextSize: number
}

interface ResolutionOption {
  label: string
  width: number
  height: number
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

const RESOLUTIONS: ResolutionOption[] = [
  { label: 'Landscape 720p', width: 1280, height: 720 },
  { label: 'Landscape 1080p', width: 1920, height: 1080 },
  { label: 'Portrait 720p', width: 720, height: 1280 },
  { label: 'Portrait 1080p', width: 1080, height: 1920 },
  { label: 'Square 1080p', width: 1080, height: 1080 },
  { label: 'Classic 4:3', width: 1440, height: 1080 },
]

const VIDEO_ACCEPT = '.mp4,.webm,.mov,.mkv,.avi,.m4v'
const VIDEO_EDITOR_DRAFT_KEY = 'maestro-video-editor-draft-v1'
const MAESTRO_PICKER_PAGE_SIZE = 24
const TRANSITIONS: Array<{ value: Transition; label: string; description: string }> = [
  { value: 'none', label: 'Hard cut', description: 'Immediate cut with no overlap.' },
  { value: 'crossfade', label: 'Crossfade', description: 'One shot dissolves smoothly into the next.' },
  { value: 'fade-black', label: 'Fade black', description: 'Fade out through black, then reveal the next shot.' },
  { value: 'wipe-left', label: 'Wipe left', description: 'The next shot pushes in from the left.' },
  { value: 'slide-left', label: 'Slide left', description: 'Both shots travel together in a fast lateral camera move.' },
  { value: 'slide-right', label: 'Slide right', description: 'A reverse lateral slide reveals the next shot.' },
  { value: 'circle-open', label: 'Iris reveal', description: 'The next shot opens from the centre like a cinematic iris.' },
  { value: 'dissolve', label: 'Film dissolve', description: 'A textured, organic hand-off between shots.' },
  { value: 'pixelize', label: 'Digital pixel', description: 'The image breaks into pixels while changing shots.' },
  { value: 'blur', label: 'Motion blur', description: 'A fast horizontal blur hides the cut between moving shots.' },
  { value: 'zoom-in', label: 'Zoom portal', description: 'Push through the outgoing image and land inside the next shot.' },
  { value: 'later-clock', label: 'Momentos después · Reloj', description: 'Inserts an original time card with a moving analogue clock.' },
  { value: 'later-tropical', label: 'Momentos después · Meme', description: 'Inserts an original tropical time-card inspired by the classic meme format.' },
  { value: 'later-cinematic', label: 'Momentos después · Cine', description: 'Inserts an elegant cinematic intertitle between the two clips.' },
]

const TRANSITION_VALUES = new Set<Transition>(TRANSITIONS.map(option => option.value))
const INTERSTITIAL_TRANSITIONS = new Set<Transition>([
  'later-clock',
  'later-tropical',
  'later-cinematic',
])

const DEFAULT_SEQUENCE_STYLE: SequenceStyle = {
  opacity: 1,
  clipPath: 'inset(0 0 0 0)',
  transform: 'translate3d(0, 0, 0) scale(1)',
  filter: 'none',
}

function sequenceStyle(patch: Partial<SequenceStyle> = {}): SequenceStyle {
  return { ...DEFAULT_SEQUENCE_STYLE, ...patch }
}

function isInterstitialTransition(value: Transition): value is InterstitialTransition {
  return INTERSTITIAL_TRANSITIONS.has(value)
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
  const safeText = text.trim() || 'Momentos después…'
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

function clipId(): string {
  return `clip-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function formatTime(value: number): string {
  if (!Number.isFinite(value)) return '0:00.0'
  const minutes = Math.floor(value / 60)
  const seconds = value - minutes * 60
  return `${minutes}:${seconds.toFixed(1).padStart(4, '0')}`
}

function effectiveDuration(clip: EditorClip): number {
  return Math.max(0, clip.trimEnd - clip.trimStart)
}

function transitionDurationAfter(clips: EditorClip[], index: number): number {
  const current = clips[index]
  const next = clips[index + 1]
  if (!current || !next || current.transition === 'none') return 0
  if (isInterstitialTransition(current.transition)) {
    return Math.max(0.5, Math.min(current.transitionDuration, 5))
  }
  return Math.max(
    0.05,
    Math.min(current.transitionDuration, effectiveDuration(current) * 0.45, effectiveDuration(next) * 0.45),
  )
}

function clipTimelineStart(clips: EditorClip[], index: number): number {
  let start = 0
  for (let cursor = 0; cursor < index; cursor++) {
    const transitionDuration = transitionDurationAfter(clips, cursor)
    start += effectiveDuration(clips[cursor]) + (
      isInterstitialTransition(clips[cursor].transition) ? transitionDuration : -transitionDuration
    )
  }
  return start
}

function wait(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function loadEditorDraft(): {
  clips: EditorClip[]
  projectName: string
  resolution: ResolutionOption
  fps: number
} {
  const fallback = { clips: [], projectName: 'my_video', resolution: RESOLUTIONS[0], fps: 30 }
  try {
    const saved = JSON.parse(window.localStorage.getItem(VIDEO_EDITOR_DRAFT_KEY) || 'null')
    if (!saved || !Array.isArray(saved.clips)) return fallback
    const resolution = RESOLUTIONS.find(option =>
      option.width === saved.resolution?.width && option.height === saved.resolution?.height,
    ) || RESOLUTIONS[0]
    return {
      clips: saved.clips
        .filter((clip: EditorClip) => typeof clip?.source === 'string')
        .map((clip: EditorClip) => ({
          ...clip,
          thumbnailUrl: typeof clip.thumbnailUrl === 'string' && clip.thumbnailUrl
            ? clip.thumbnailUrl
            : api.getVideoEditorThumbnailUrl(clip.source),
          transition: TRANSITION_VALUES.has(clip.transition) ? clip.transition : 'none',
          transitionDuration: Number.isFinite(clip.transitionDuration) ? clip.transitionDuration : 0.5,
          transitionText: typeof clip.transitionText === 'string' ? clip.transitionText : 'Momentos después…',
          transitionTextSize: Number.isFinite(clip.transitionTextSize)
            ? Math.max(50, Math.min(160, clip.transitionTextSize))
            : 100,
        })),
      projectName: typeof saved.projectName === 'string' ? saved.projectName : fallback.projectName,
      resolution,
      fps: [24, 25, 30, 50, 60].includes(saved.fps) ? saved.fps : 30,
    }
  } catch {
    return fallback
  }
}

export function VideoEditorPanel() {
  const [draft] = useState(loadEditorDraft)
  const refreshOutputs = useStore(s => s.refreshOutputs)
  const activeWorkspace = useStore(s => s.activeWorkspace)
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
  const mountedRef = useRef(true)

  const [clips, setClips] = useState<EditorClip[]>(draft.clips)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)
  const [projectName, setProjectName] = useState(draft.projectName)
  const [resolution, setResolution] = useState(draft.resolution)
  const [fps, setFps] = useState(draft.fps)
  const [previewTime, setPreviewTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [sequenceMode, setSequenceMode] = useState(false)
  const [sequenceTime, setSequenceTime] = useState(0)
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
  const [error, setError] = useState<string | null>(null)
  const [exportJob, setExportJob] = useState<api.VideoEditorExportJob | null>(null)
  const [capturingFrame, setCapturingFrame] = useState(false)
  const [capturedFrame, setCapturedFrame] = useState<api.VideoEditorScreenshot | null>(null)

  const selected = clips.find(clip => clip.id === selectedId) || clips[0] || null
  const selectedIndex = selected ? clips.findIndex(clip => clip.id === selected.id) : -1
  const totalDuration = useMemo(() => {
    const raw = clips.reduce((total, clip) => total + effectiveDuration(clip), 0)
    const transitionDelta = clips.reduce(
      (total, clip, index) => {
        const duration = transitionDurationAfter(clips, index)
        return total + (isInterstitialTransition(clip.transition) ? duration : -duration)
      },
      0,
    )
    return Math.max(0, raw + transitionDelta)
  }, [clips])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (sequenceFrameRef.current !== null) cancelAnimationFrame(sequenceFrameRef.current)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        window.localStorage.setItem(VIDEO_EDITOR_DRAFT_KEY, JSON.stringify({
          clips, projectName, resolution, fps, savedAt: new Date().toISOString(),
        }))
      } catch {
        // A full browser quota must not interrupt editing.
      }
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

  const addSource = async (source: string, previewUrl: string, name: string, thumbnailUrl?: string | null) => {
    const media = await api.probeVideoEditorClip(source)
    const clip: EditorClip = {
      ...media,
      id: clipId(),
      name,
      source,
      previewUrl,
      thumbnailUrl: thumbnailUrl || api.getVideoEditorThumbnailUrl(source),
      trimStart: 0,
      trimEnd: media.duration,
      volume: 1,
      muted: false,
      fit: 'fit',
      transition: 'none',
      transitionDuration: 0.5,
      transitionText: 'Momentos después…',
      transitionTextSize: 100,
    }
    setClips(current => [...current, clip])
    setSelectedId(clip.id)
  }

  useEffect(() => {
    let pending: { name?: string; url?: string } | null = null
    try {
      pending = JSON.parse(window.localStorage.getItem('maestro-video-editor-pending-source') || 'null')
      if (pending?.url) window.localStorage.removeItem('maestro-video-editor-pending-source')
    } catch {
      pending = null
    }
    if (!pending?.url) return
    setAdding(true)
    setAddProgress(`Opening ${pending.name || 'comic animatic'}`)
    void addSource(pending.url, pending.url, pending.name || 'Comic animatic')
      .catch(reason => setError((reason as Error).message))
      .finally(() => {
        setAdding(false)
        setAddProgress('')
      })
    // The hand-off is intentionally consumed once when the editor mounts.
  }, [])

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

  const openMaestroPicker = async () => {
    setPickerOpen(true)
    setPickerLoading(true)
    setError(null)
    setMaestroVideos([])
    setMaestroVideoTotal(0)
    try {
      const result = await api.fetchOutputs(MAESTRO_PICKER_PAGE_SIZE, 0, { mediaType: 'video' })
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
        { mediaType: 'video' },
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

  const chooseMaestroVideo = async (output: api.ApiOutput) => {
    setAdding(true)
    setPickerOpen(false)
    setError(null)
    setAddProgress(`Adding ${output.name}`)
    try {
      const source = api.getFileUrl(output.name)
      await addSource(source, source, output.name, output.thumbnail_url || api.getOutputThumbnailUrl(output.name))
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setAdding(false)
      setAddProgress('')
    }
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
  }

  const splitSelected = () => {
    if (!selected) return
    const cut = videoRef.current?.currentTime ?? previewTime
    if (cut <= selected.trimStart + 0.05 || cut >= selected.trimEnd - 0.05) {
      setError('Move the preview playhead inside the clip before splitting.')
      return
    }
    const second: EditorClip = {
      ...selected,
      id: clipId(),
      name: `${selected.name} (part 2)`,
      trimStart: cut,
    }
    setClips(current => {
      const index = current.findIndex(clip => clip.id === selected.id)
      const next = [...current]
      next[index] = {
        ...selected,
        name: `${selected.name} (part 1)`,
        trimEnd: cut,
        transition: 'none',
      }
      next.splice(index + 1, 0, second)
      return next
    })
    setSelectedId(second.id)
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
      sourceTime ?? clips[clipIndex].trimStart,
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
    setSelectedId(clips[clipIndex].id)
    setSelectedTransitionIndex(null)
    const local = (sourceTime ?? clips[clipIndex].trimStart) - clips[clipIndex].trimStart
    setSequenceTime(clipTimelineStart(clips, clipIndex) + Math.max(0, local))
  }

  const seekSequence = (value: number) => {
    if (!clips.length) return
    const clamped = Math.max(0, Math.min(totalDuration, value))
    let clipIndex = 0
    for (let index = clips.length - 1; index >= 0; index--) {
      if (clamped >= clipTimelineStart(clips, index)) {
        clipIndex = index
        break
      }
    }
    const cardStart = clipTimelineStart(clips, clipIndex) + effectiveDuration(clips[clipIndex])
    if (
      isInterstitialTransition(clips[clipIndex].transition)
      && clips[clipIndex + 1]
      && clamped >= cardStart
    ) {
      const autoplay = sequencePlayingRef.current
      startSequenceAt(clipIndex, clips[clipIndex].trimEnd - 0.01, autoplay)
      const runtime = sequenceRuntimeRef.current
      runtime.interstitial = true
      runtime.interstitialElapsed = Math.min(
        transitionDurationAfter(clips, clipIndex),
        Math.max(0, clamped - cardStart),
      )
      runtime.interstitialLastFrame = autoplay ? performance.now() : null
      setSequenceInterstitial({
        transition: clips[clipIndex].transition as InterstitialTransition,
        text: clips[clipIndex].transitionText,
        textSize: clips[clipIndex].transitionTextSize,
        progress: runtime.interstitialElapsed / transitionDurationAfter(clips, clipIndex),
      })
      setSequenceTime(clamped)
      return
    }
    const local = clamped - clipTimelineStart(clips, clipIndex)
    const sourceTime = Math.min(
      clips[clipIndex].trimEnd - 0.01,
      clips[clipIndex].trimStart + Math.max(0, local),
    )
    startSequenceAt(clipIndex, sourceTime, sequencePlayingRef.current)
    setSequenceTime(clamped)
  }

  const togglePlayback = () => {
    if (!clips.length) return
    if (!sequenceMode || sequenceTime >= totalDuration - 0.03) {
      startSequenceAt(0)
      return
    }
    setSequencePlaying(!sequencePlayingRef.current)
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

  const startExport = async () => {
    if (!clips.length || exportJob?.status === 'queued' || exportJob?.status === 'running') return
    setError(null)
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
        clips: clips.map(clip => ({
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
      while (mountedRef.current) {
        const status = await api.fetchVideoEditorExport(started.job_id)
        setExportJob(status)
        if (status.status === 'completed') {
          await refreshOutputs()
          break
        }
        if (status.status === 'failed') break
        await wait(1000)
      }
    } catch (reason) {
      const message = (reason as Error).message
      setError(message)
      setExportJob(current => current ? { ...current, status: 'failed', error: message, message } : null)
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
      className="h-full min-h-[620px] flex flex-col bg-bg-secondary border border-border rounded-xl overflow-hidden"
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

      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-bg-tertiary/40">
        <Film size={16} className="text-accent-blue" />
        <input
          value={projectName}
          onChange={event => setProjectName(event.target.value)}
          className="w-40 md:w-56 bg-transparent text-sm font-medium text-text-primary focus:outline-none border-b border-transparent focus:border-accent-blue"
          aria-label="Project name"
        />
        <div className="flex-1" />
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
          <FolderOpen size={13} /> From Maestro
        </button>
        <button
          onClick={startExport}
          disabled={!clips.length || exportJob?.status === 'queued' || exportJob?.status === 'running'}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-accent-blue text-white hover:bg-accent-blue/80 disabled:opacity-40"
        >
          {exportJob?.status === 'queued' || exportJob?.status === 'running'
            ? <Loader2 size={13} className="animate-spin" />
            : <Download size={13} />}
          Export MP4
        </button>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 flex flex-col border-b lg:border-b-0 lg:border-r border-border">
          <div className="flex-1 min-h-[280px] flex items-center justify-center p-4 bg-black/70 relative">
            {sequenceMode ? (
              <div
                className={`relative max-w-full max-h-full bg-black shadow-2xl ${
                  resolution.width >= resolution.height ? 'w-full' : 'h-full'
                }`}
                style={{ aspectRatio: `${resolution.width}/${resolution.height}` }}
              >
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
              </div>
            ) : selected ? (
              <div
                className={`relative max-w-full max-h-full bg-black shadow-2xl ${
                  resolution.width >= resolution.height ? 'w-full' : 'h-full'
                }`}
                style={{ aspectRatio: `${resolution.width}/${resolution.height}` }}
              >
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
              </div>
            ) : (
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full max-w-xl aspect-video rounded-xl border-2 border-dashed border-border-light flex flex-col items-center justify-center gap-3 text-text-muted hover:text-text-secondary hover:border-accent-blue/60 transition-colors"
              >
                <Upload size={36} />
                <span className="text-sm">Drop videos here or click to import</span>
                <span className="text-[10px]">MP4, WebM, MOV, MKV, AVI · up to 500 MB each</span>
              </button>
            )}
          </div>

          <div className="px-3 py-2 border-t border-border bg-bg-tertiary/30">
            <div className="flex items-center gap-2">
              <button
                onClick={togglePlayback}
                disabled={!clips.length}
                className="p-1.5 rounded-md hover:bg-bg-hover disabled:opacity-40"
                title="Play the complete timeline from beginning to end"
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
              <span className="text-[10px] text-text-muted tabular-nums w-[98px]">
                {formatTime(sequenceMode ? sequenceTime : 0)} / {formatTime(totalDuration)}
              </span>
              <input
                type="range"
                min={0}
                max={totalDuration || 1}
                step={0.01}
                value={sequenceMode ? Math.min(totalDuration, sequenceTime) : 0}
                onChange={event => seekSequence(Number(event.target.value))}
                disabled={!clips.length}
                className="flex-1"
              />
              <button
                onClick={splitSelected}
                disabled={!selected || sequenceMode}
                className="flex items-center gap-1 px-2 py-1 text-[10px] rounded border border-border hover:bg-bg-hover disabled:opacity-40"
                title="Split selected clip at the preview playhead"
              >
                <Scissors size={11} /> Split
              </button>
              <button
                onClick={takeScreenshot}
                disabled={!selected || capturingFrame}
                className="flex items-center gap-1 px-2 py-1 text-[10px] rounded border border-border hover:bg-bg-hover disabled:opacity-40"
                title="Save the exact current source frame as a reusable PNG in Maestro Outputs"
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

        <aside className="min-h-0 overflow-y-auto p-3 space-y-4 bg-bg-secondary">
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
                      title={option.description}
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
                            text="Momentos después…"
                            compact
                          />
                        )}
                      </div>
                      <span className={`text-[9px] ${active ? 'text-purple-300' : 'text-text-secondary'}`}>
                        {option.label}
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
                        Card text
                        <textarea
                          rows={3}
                          maxLength={240}
                          value={clips[selectedTransitionIndex].transitionText}
                          placeholder="Momentos después…"
                          onChange={event => patchClip(clips[selectedTransitionIndex].id, {
                            transitionText: event.target.value,
                          })}
                          className="mt-1 block w-full resize-y rounded border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary"
                        />
                        <span className="mt-1 block text-[9px] text-text-secondary">
                          Enter adds a manual line break. The text also wraps automatically to fit the card.
                        </span>
                      </label>
                      <label className="block text-[10px] text-text-muted">
                        Text size: {Math.round(clips[selectedTransitionIndex].transitionTextSize)}%
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

              <div className="grid grid-cols-2 gap-2">
                <label className="text-[10px] text-text-muted">
                  Trim start
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
                  Trim end
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
                      : 'border-accent-blue/30 bg-accent-blue/5'
                }`}>
                  <div className="flex items-center gap-1.5 text-[10px]">
                    {exportJob.status === 'completed'
                      ? <Check size={12} className="text-green-400" />
                      : exportJob.status === 'failed'
                        ? <X size={12} className="text-red-400" />
                        : <Loader2 size={12} className="animate-spin text-accent-blue" />}
                    <span className="truncate">{exportJob.message}</span>
                  </div>
                  {(exportJob.status === 'queued' || exportJob.status === 'running') && (
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
                <div className="whitespace-pre-wrap text-[10px] text-red-400 bg-red-500/10 border border-red-500/20 rounded p-2">
                  {error}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>

      <div className="h-32 shrink-0 border-t border-border bg-bg-tertiary/30 flex flex-col">
        <div className="h-7 flex items-center px-3 border-b border-border text-[10px] text-text-muted">
          <span>Timeline · {clips.length} {clips.length === 1 ? 'clip' : 'clips'} · {formatTime(totalDuration)}</span>
          <span className="ml-auto">Drag clips to reorder</span>
        </div>
        <div className="flex-1 overflow-x-auto p-2">
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
                          event.dataTransfer.effectAllowed = 'move'
                          event.dataTransfer.setData('text/x-maestro-video-clip', clip.id)
                          setDraggedId(clip.id)
                        }}
                        onDragEnd={() => {
                          setDraggedId(null)
                          setDropIndex(null)
                        }}
                        onDragOver={event => {
                          event.preventDefault()
                          event.dataTransfer.dropEffect = 'move'
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
                          setSequencePlaying(false)
                          setSequenceMode(false)
                          setSelectedTransitionIndex(null)
                          setSelectedId(clip.id)
                        }}
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
                          setSequencePlaying(false)
                          setSequenceMode(false)
                          setSelectedTransitionIndex(index)
                        }}
                        className={`w-14 shrink-0 rounded-lg border flex flex-col items-center justify-center gap-1 transition-colors ${
                          selectedTransitionIndex === index
                            ? 'border-purple-400 bg-purple-500/15 text-purple-300'
                            : clip.transition !== 'none'
                              ? 'border-purple-500/40 bg-purple-500/10 text-purple-400'
                              : 'border-dashed border-border text-text-muted hover:border-purple-500/50 hover:text-purple-300'
                        }`}
                        title={`Transition: ${TRANSITIONS.find(option => option.value === clip.transition)?.label || 'Hard cut'}`}
                      >
                        {clip.transition === 'none' ? <Plus size={13} /> : <ChevronsRight size={15} />}
                        <span className="max-w-[48px] truncate text-[8px]">
                          {clip.transition === 'none'
                            ? 'Transition'
                            : TRANSITIONS.find(option => option.value === clip.transition)?.label}
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
        <div
          className="fixed inset-0 z-[80] bg-black/65 flex items-center justify-center p-4"
          onMouseDown={event => {
            if (event.currentTarget === event.target) setPickerOpen(false)
          }}
        >
          <div className="w-full max-w-4xl max-h-[78vh] bg-bg-secondary border border-border rounded-xl shadow-2xl overflow-hidden flex flex-col">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
              <FolderOpen size={15} className="text-accent-blue" />
              <span className="text-sm font-medium">Add a Maestro video</span>
              {maestroVideoTotal > 0 && (
                <span className="text-[10px] text-text-muted">{maestroVideos.length} / {maestroVideoTotal}</span>
              )}
              <button onClick={() => setPickerOpen(false)} className="ml-auto p-1 rounded hover:bg-bg-hover">
                <X size={15} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {pickerLoading && maestroVideos.length === 0 ? (
                <div className="min-h-48 flex items-center justify-center text-text-muted">
                  <Loader2 size={22} className="animate-spin" />
                </div>
              ) : maestroVideos.length ? (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                  {maestroVideos.map(output => (
                    <button
                      key={output.name}
                      onClick={() => void chooseMaestroVideo(output)}
                      className="rounded-lg overflow-hidden border border-border bg-bg-tertiary hover:border-accent-blue text-left"
                    >
                      {output.thumbnail_url ? (
                        <img
                          src={output.thumbnail_url}
                          alt={output.name}
                          className="w-full aspect-video object-cover bg-black"
                          loading="lazy"
                          decoding="async"
                        />
                      ) : (
                        <div className="flex aspect-video items-center justify-center bg-black text-text-muted"><Film size={20} /></div>
                      )}
                      <p className="p-2 text-[10px] text-text-secondary truncate">{output.name}</p>
                    </button>
                  ))}
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
          </div>
        </div>
      )}
    </div>
  )
}
