import {
  ArrowDown,
  ArrowUp,
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
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
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
  trimStart: number
  trimEnd: number
  volume: number
  muted: boolean
  fit: ClipFit
  transition: Transition
  transitionDuration: number
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
  ended: boolean
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
  return Math.max(
    0.05,
    Math.min(current.transitionDuration, effectiveDuration(current) * 0.45, effectiveDuration(next) * 0.45),
  )
}

function clipTimelineStart(clips: EditorClip[], index: number): number {
  let start = 0
  for (let cursor = 0; cursor < index; cursor++) {
    start += effectiveDuration(clips[cursor]) - transitionDurationAfter(clips, cursor)
  }
  return start
}

function wait(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

export function VideoEditorPanel() {
  const refreshOutputs = useStore(s => s.refreshOutputs)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const sequenceRefs = useRef<Array<HTMLVideoElement | null>>([null, null])
  const sequenceFrameRef = useRef<number | null>(null)
  const sequenceRuntimeRef = useRef<SequenceRuntime>({ activeSlot: 0, clipIndex: 0, transitioning: false, ended: false })
  const sequencePlayingRef = useRef(false)
  const sequenceSlotSeekRef = useRef<Array<number | null>>([null, null])
  const mountedRef = useRef(true)

  const [clips, setClips] = useState<EditorClip[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)
  const [projectName, setProjectName] = useState('my_video')
  const [resolution, setResolution] = useState(RESOLUTIONS[0])
  const [fps, setFps] = useState(30)
  const [previewTime, setPreviewTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [sequenceMode, setSequenceMode] = useState(false)
  const [sequenceTime, setSequenceTime] = useState(0)
  const [sequenceSlotIndices, setSequenceSlotIndices] = useState<Array<number | null>>([null, null])
  const [sequenceStyles, setSequenceStyles] = useState([
    sequenceStyle(),
    sequenceStyle({ opacity: 0 }),
  ])
  const [selectedTransitionIndex, setSelectedTransitionIndex] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const [addProgress, setAddProgress] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [maestroVideos, setMaestroVideos] = useState<api.ApiOutput[]>([])
  const [pickerLoading, setPickerLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exportJob, setExportJob] = useState<api.VideoEditorExportJob | null>(null)

  const selected = clips.find(clip => clip.id === selectedId) || clips[0] || null
  const selectedIndex = selected ? clips.findIndex(clip => clip.id === selected.id) : -1
  const totalDuration = useMemo(() => {
    const raw = clips.reduce((total, clip) => total + effectiveDuration(clip), 0)
    const overlap = clips.reduce(
      (total, _clip, index) => total + transitionDurationAfter(clips, index),
      0,
    )
    return Math.max(0, raw - overlap)
  }, [clips])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (sequenceFrameRef.current !== null) cancelAnimationFrame(sequenceFrameRef.current)
    }
  }, [])

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

  const addSource = async (source: string, previewUrl: string, name: string) => {
    const media = await api.probeVideoEditorClip(source)
    const clip: EditorClip = {
      ...media,
      id: clipId(),
      name,
      source,
      previewUrl,
      trimStart: 0,
      trimEnd: media.duration,
      volume: 1,
      muted: false,
      fit: 'fit',
      transition: 'none',
      transitionDuration: 0.5,
    }
    setClips(current => [...current, clip])
    setSelectedId(clip.id)
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

  const openMaestroPicker = async () => {
    setPickerOpen(true)
    setPickerLoading(true)
    setError(null)
    try {
      const result = await api.fetchOutputs(0, 0)
      setMaestroVideos(result.outputs.filter(output => output.type === 'video'))
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
      await addSource(source, source, output.name)
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
      active?.pause()
      inactive?.pause()
      return
    }
    void active?.play().catch(() => setError('The browser could not start timeline playback.'))
    if (runtime.transitioning) {
      void inactive?.play().catch(() => undefined)
    }
  }

  const startSequenceAt = (clipIndex: number, sourceTime?: number, autoplay = true) => {
    if (!clips[clipIndex]) return
    sequencePlayingRef.current = autoplay
    videoRef.current?.pause()
    const nextIndex = clipIndex + 1 < clips.length ? clipIndex + 1 : null
    sequenceRuntimeRef.current = { activeSlot: 0, clipIndex, transitioning: false, ended: false }
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
    if (sequencePlayingRef.current && (isActive || isTransitionTarget)) {
      void video.play().catch(() => undefined)
    } else {
      video.pause()
    }
  }

  useEffect(() => {
    if (!sequenceMode) return

    const renderFrame = () => {
      const runtime = sequenceRuntimeRef.current
      if (runtime.ended) return
      const currentClip = clips[runtime.clipIndex]
      const activeVideo = sequenceRefs.current[runtime.activeSlot]
      if (!currentClip || !activeVideo) {
        sequenceFrameRef.current = requestAnimationFrame(renderFrame)
        return
      }

      const localTime = Math.max(0, activeVideo.currentTime - currentClip.trimStart)
      setSequenceTime(Math.min(
        totalDuration,
        clipTimelineStart(clips, runtime.clipIndex) + localTime,
      ))

      const nextIndex = runtime.clipIndex + 1
      const nextClip = clips[nextIndex]
      const inactiveSlot = runtime.activeSlot === 0 ? 1 : 0
      const nextVideo = sequenceRefs.current[inactiveSlot]
      const duration = transitionDurationAfter(clips, runtime.clipIndex)
      const transitionStart = currentClip.trimEnd - duration
      const inTransition = Boolean(
        nextClip
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
        } else {
          const oldActiveSlot = runtime.activeSlot
          runtime.activeSlot = inactiveSlot
          runtime.clipIndex = nextIndex
          runtime.transitioning = false
          const followingIndex = nextIndex + 1 < clips.length ? nextIndex + 1 : null
          sequenceSlotSeekRef.current[inactiveSlot] = Math.max(
            nextClip.trimStart,
            nextVideo?.currentTime || nextClip.trimStart,
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
          if (nextVideo) {
            nextVideo.volume = clipVolume(nextClip)
            if (sequencePlayingRef.current && nextVideo.paused) {
              void nextVideo.play().catch(() => undefined)
            }
          }
          setSelectedId(nextClip.id)
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
            </div>
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
                      onClick={() => patchClip(clips[selectedTransitionIndex].id, { transition: option.value })}
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
                      </div>
                      <span className={`text-[9px] ${active ? 'text-purple-300' : 'text-text-secondary'}`}>
                        {option.label}
                      </span>
                    </button>
                  )
                })}
              </div>

              {clips[selectedTransitionIndex].transition !== 'none' && (
                <label className="block text-[10px] text-text-muted mt-3">
                  Duration: {clips[selectedTransitionIndex].transitionDuration.toFixed(1)}s
                  <input
                    type="range"
                    min={0.1}
                    max={2}
                    step={0.1}
                    value={clips[selectedTransitionIndex].transitionDuration}
                    onChange={event => patchClip(clips[selectedTransitionIndex].id, {
                      transitionDuration: Number(event.target.value),
                    })}
                    className="block w-full mt-1"
                  />
                  <span className="block mt-1 text-[9px] text-text-muted/70">
                    The preview and export clamp this automatically for very short clips.
                  </span>
                </label>
              )}

              <button
                onClick={() => {
                  const start = clipTimelineStart(clips, selectedTransitionIndex)
                    + effectiveDuration(clips[selectedTransitionIndex])
                    - transitionDurationAfter(clips, selectedTransitionIndex)
                    - 0.35
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
                  onClick={() => setClips(current => current.filter(clip => clip.id !== selected.id))}
                  className="p-1 text-text-muted hover:text-red-400"
                  title="Delete clip"
                >
                  <Trash2 size={13} />
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
                      className={`relative overflow-hidden rounded-lg border text-left transition-colors ${
                        selected?.id === clip.id && selectedTransitionIndex === null
                          ? 'border-accent-blue ring-1 ring-accent-blue/50'
                          : 'border-border hover:border-border-light'
                      }`}
                      style={{ width }}
                    >
                      {dropIndex === index && (
                        <span className="absolute inset-y-1 left-0 z-30 w-1 rounded-full bg-accent-blue shadow-[0_0_8px_rgba(59,130,246,0.9)]" />
                      )}
                      {dropIndex === index + 1 && index === clips.length - 1 && (
                        <span className="absolute inset-y-1 right-0 z-30 w-1 rounded-full bg-accent-blue shadow-[0_0_8px_rgba(59,130,246,0.9)]" />
                      )}
                      <video src={clip.previewUrl} preload="metadata" muted className="absolute inset-0 w-full h-full object-cover opacity-45" />
                      <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-black/40" />
                      <div className="relative h-full p-2 flex flex-col">
                        <div className="flex items-center gap-1 text-[9px] text-white/70">
                          <GripVertical size={10} /> {index + 1}
                          {clip.muted && <VolumeX size={9} className="ml-auto" />}
                        </div>
                        <div className="mt-auto">
                          <p className="text-[10px] text-white truncate">{clip.name}</p>
                          <p className="text-[9px] text-white/60">{formatTime(effectiveDuration(clip))}</p>
                        </div>
                      </div>
                    </button>
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
              <button onClick={() => setPickerOpen(false)} className="ml-auto p-1 rounded hover:bg-bg-hover">
                <X size={15} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {pickerLoading ? (
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
                      <video src={api.getFileUrl(output.name)} preload="metadata" muted className="w-full aspect-video object-cover bg-black" />
                      <p className="p-2 text-[10px] text-text-secondary truncate">{output.name}</p>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="min-h-48 flex items-center justify-center text-xs text-text-muted">
                  No videos found in workspace “{activeWorkspace}”.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
