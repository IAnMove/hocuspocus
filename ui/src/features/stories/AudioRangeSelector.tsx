import { useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value))
}

export function formatAudioTime(seconds: number): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  const minutes = Math.floor(safe / 60)
  const remainder = Math.floor(safe % 60)
  const tenths = Math.floor((safe % 1) * 10)
  return `${minutes}:${remainder.toString().padStart(2, '0')}.${tenths}`
}

export function parseAudioTime(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parts = trimmed.split(':')
  const seconds = Number(parts.pop())
  const minutes = parts.length ? Number(parts.pop()) : 0
  const hours = parts.length ? Number(parts.pop()) : 0
  if (![seconds, minutes, hours].every(Number.isFinite) || seconds < 0 || minutes < 0 || hours < 0) return null
  return hours * 3600 + minutes * 60 + seconds
}

function TimeEditor({
  label, value, maximum, onCommit,
}: {
  label: string
  value: number
  maximum: number
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(() => formatAudioTime(value))
  useEffect(() => setDraft(formatAudioTime(value)), [value])
  const commit = () => {
    const parsed = parseAudioTime(draft)
    if (parsed === null) {
      setDraft(formatAudioTime(value))
      return
    }
    onCommit(clamp(parsed, 0, maximum))
  }
  return (
    <label className="flex items-center gap-1.5 text-[10px] text-text-muted">
      {label}
      <input
        value={draft}
        onChange={event => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={event => {
          if (event.key === 'Enter') event.currentTarget.blur()
          if (event.key === 'Escape') {
            setDraft(formatAudioTime(value))
            event.currentTarget.blur()
          }
        }}
        className="w-20 rounded border border-border bg-bg-primary px-1.5 py-1 text-center font-mono text-[10px] text-text-primary"
        aria-label={`${label} in minutes and seconds`}
      />
    </label>
  )
}

export function AudioRangeSelector({
  src,
  durationHint = 0,
  start,
  end,
  onChange,
}: {
  src: string
  durationHint?: number
  start: number
  end: number
  onChange: (range: { start: number; end: number; duration: number }) => void
}) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  const dragging = useRef<'start' | 'end' | null>(null)
  const [duration, setDuration] = useState(Math.max(0, durationHint))
  const [playing, setPlaying] = useState(false)
  const [playhead, setPlayhead] = useState(start)
  const minimumSelection = Math.min(3, Math.max(1, duration || durationHint || 1))
  const safeEnd = end > start ? end : duration

  useEffect(() => {
    setDuration(Math.max(0, durationHint))
    setPlaying(false)
    setPlayhead(0)
  }, [src, durationHint])

  useEffect(() => {
    if (!duration) return
    const nextStart = clamp(start, 0, Math.max(0, duration - minimumSelection))
    const nextEnd = clamp(safeEnd || duration, nextStart + minimumSelection, duration)
    if (nextStart !== start || nextEnd !== end) onChange({ start: nextStart, end: nextEnd, duration })
  }, [duration, end, minimumSelection, onChange, safeEnd, start])

  const setEdge = (edge: 'start' | 'end', clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect || !duration) return
    const value = clamp(((clientX - rect.left) / rect.width) * duration, 0, duration)
    if (edge === 'start') {
      const nextStart = Math.min(value, safeEnd - minimumSelection)
      onChange({ start: nextStart, end: safeEnd, duration })
      setPlayhead(nextStart)
    } else {
      const nextEnd = Math.max(value, start + minimumSelection)
      onChange({ start, end: nextEnd, duration })
    }
  }

  const togglePreview = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (playing) {
      audio.pause()
      setPlaying(false)
      return
    }
    audio.currentTime = start
    setPlayhead(start)
    try {
      await audio.play()
      setPlaying(true)
    } catch {
      setPlaying(false)
    }
  }

  const startPercent = duration ? (start / duration) * 100 : 0
  const endPercent = duration ? (safeEnd / duration) * 100 : 100
  const playheadPercent = duration ? (playhead / duration) * 100 : startPercent

  return (
    <div className="space-y-2 rounded-lg border border-pink-500/25 bg-bg-primary p-2.5">
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onLoadedMetadata={event => {
          const measured = Number(event.currentTarget.duration)
          if (!Number.isFinite(measured) || measured <= 0) return
          setDuration(measured)
          if (!end || end > measured) onChange({ start: 0, end: measured, duration: measured })
        }}
        onTimeUpdate={event => {
          const current = event.currentTarget.currentTime
          setPlayhead(current)
          if (current >= safeEnd) {
            event.currentTarget.pause()
            event.currentTarget.currentTime = start
            setPlayhead(start)
            setPlaying(false)
          }
        }}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        className="hidden"
      />

      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-medium text-text-primary">Trailer excerpt</span>
        <span className="font-mono text-[10px] text-pink-300">
          {formatAudioTime(start)} → {formatAudioTime(safeEnd)} · {formatAudioTime(safeEnd - start)}
        </span>
      </div>

      <div
        ref={trackRef}
        className="relative h-14 touch-none select-none overflow-hidden rounded-md border border-border bg-bg-tertiary"
        onPointerMove={event => {
          if (dragging.current) setEdge(dragging.current, event.clientX)
        }}
        onPointerUp={event => {
          dragging.current = null
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId)
          }
        }}
        onPointerCancel={() => { dragging.current = null }}
      >
        <div className="absolute inset-y-0 bg-black/30" style={{ left: 0, width: `${startPercent}%` }} />
        <div className="absolute inset-y-0 border-x border-pink-400/80 bg-gradient-to-r from-pink-500/35 to-purple-500/35" style={{ left: `${startPercent}%`, width: `${Math.max(0, endPercent - startPercent)}%` }}>
          <div className="absolute inset-0 opacity-30" style={{ backgroundImage: 'repeating-linear-gradient(90deg, transparent 0, transparent 7px, currentColor 8px)' }} />
        </div>
        <div className="absolute inset-y-0 bg-black/30" style={{ left: `${endPercent}%`, right: 0 }} />
        {playing && <div className="absolute inset-y-0 w-px bg-white shadow-[0_0_5px_white]" style={{ left: `${playheadPercent}%` }} />}
        {(['start', 'end'] as const).map(edge => {
          const percent = edge === 'start' ? startPercent : endPercent
          return (
            <button
              key={edge}
              type="button"
              className="absolute inset-y-0 z-10 w-4 -translate-x-1/2 cursor-ew-resize bg-transparent"
              style={{ left: `${percent}%` }}
              onPointerDown={event => {
                dragging.current = edge
                trackRef.current?.setPointerCapture(event.pointerId)
                setEdge(edge, event.clientX)
              }}
              aria-label={`Drag trailer ${edge} time`}
            >
              <span className="mx-auto block h-full w-1 rounded bg-pink-300 shadow-[0_0_5px_rgba(249,168,212,.8)]" />
            </button>
          )
        })}
        <span className="absolute bottom-1 left-1 font-mono text-[9px] text-text-muted">0:00</span>
        <span className="absolute bottom-1 right-1 font-mono text-[9px] text-text-muted">{formatAudioTime(duration)}</span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <TimeEditor
            label="From"
            value={start}
            maximum={Math.max(0, safeEnd - minimumSelection)}
            onCommit={value => onChange({ start: Math.min(value, safeEnd - minimumSelection), end: safeEnd, duration })}
          />
          <TimeEditor
            label="To"
            value={safeEnd}
            maximum={duration}
            onCommit={value => onChange({ start, end: Math.max(value, start + minimumSelection), duration })}
          />
        </div>
        <button
          type="button"
          onClick={() => void togglePreview()}
          disabled={!duration || safeEnd <= start}
          className="inline-flex items-center gap-1.5 rounded-md border border-pink-500/50 px-2 py-1 text-[10px] text-pink-300 disabled:opacity-40"
        >
          {playing ? <Pause size={11} /> : <Play size={11} />}
          {playing ? 'Pause preview' : 'Play selected excerpt'}
        </button>
      </div>
    </div>
  )
}
