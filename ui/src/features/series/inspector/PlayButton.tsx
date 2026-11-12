import { useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { secondaryButton } from '../styles'

/** One sound at a time in the inspector: a line, its room copy, a sound effect (from `start`, for `length` s). */
let shared: HTMLAudioElement | null = null
let stopCurrent: (() => void) | null = null

export function PlayButton({ url, label, start = 0, length, text }: { url?: string; label: string; start?: number; length?: number; text?: string }) {
  const [playing, setPlaying] = useState(false)
  const mine = useRef<(() => void) | null>(null)
  // Leaving the page (another shot, another tab) stops this button's sound, not another one's.
  useEffect(() => () => { if (mine.current && stopCurrent === mine.current) mine.current() }, [])
  const toggle = () => {
    if (!url) return
    if (playing) { stopCurrent?.(); return }
    stopCurrent?.()
    shared ??= typeof Audio === 'undefined' ? null : new Audio()
    const audio = shared
    if (!audio) return
    const stop = () => { audio.pause(); audio.ontimeupdate = null; audio.onended = null; setPlaying(false); if (stopCurrent === stop) stopCurrent = null }
    stopCurrent = stop
    mine.current = stop
    audio.src = url
    audio.onended = stop
    audio.ontimeupdate = () => { if (length && audio.currentTime >= start + length) stop() }
    const begin = () => { audio.currentTime = start; void audio.play().catch(stop) }
    audio.onloadedmetadata = start ? begin : null
    setPlaying(true)
    if (!start) void audio.play().catch(stop); else audio.load()
  }
  return <button type="button" className={`${secondaryButton} min-h-10 px-2 sm:min-h-0 sm:py-1`} disabled={!url} aria-label={label} title={label}
    aria-pressed={playing} onClick={toggle}>{playing ? <Pause size={13} /> : <Play size={13} />}{text && <span>{text}</span>}</button>
}
