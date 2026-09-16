import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { Loader2, Pause, Play, RotateCcw, TriangleAlert } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { VideoJsSandbox } from './sandbox.ts'
import type { VideoJsSandboxStatus } from './useVideoJsSandbox.ts'
import type { VideoJsSceneError } from './types.ts'

export interface VideoJsStageHandle {
  seek: (seconds: number) => void
}

interface StageProps {
  sandbox: VideoJsSandbox | null
  status: VideoJsSandboxStatus
  revision: number
  width: number
  height: number
  duration: number
  handle: Ref<VideoJsStageHandle>
  locked: boolean
  onFrameErrors: (errors: VideoJsSceneError[]) => void
  onCrash: (error: unknown) => void
  onReload: () => void
}

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(2).padStart(5, '0')}`
}

function usePainter(props: Pick<StageProps, 'sandbox' | 'onFrameErrors' | 'onCrash'>) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const busy = useRef(false)
  const wanted = useRef<number | null>(null)
  const { sandbox, onFrameErrors, onCrash } = props
  const paint = useCallback((seconds: number) => {
    wanted.current = seconds
    if (busy.current || !sandbox?.isLoaded) return
    busy.current = true
    void (async () => {
      try {
        while (wanted.current !== null && sandbox.isLoaded) {
          const time = wanted.current
          wanted.current = null
          const { bitmap, errors } = await sandbox.frame(time)
          const canvas = canvasRef.current
          if (canvas) {
            if (canvas.width !== bitmap.width) canvas.width = bitmap.width
            if (canvas.height !== bitmap.height) canvas.height = bitmap.height
            canvas.getContext('2d')?.drawImage(bitmap, 0, 0)
          }
          bitmap.close()
          if (errors.length) onFrameErrors(errors)
        }
      } catch (error) {
        onCrash(error)
      } finally {
        busy.current = false
      }
    })()
  }, [sandbox, onFrameErrors, onCrash])
  return { canvasRef, paint }
}

export function VideoJsStage(props: StageProps) {
  const { t } = useUiTranslation('videojs')
  const { status, revision, width, height, duration, handle, locked } = props
  const { canvasRef, paint } = usePainter(props)
  const [seconds, setSeconds] = useState(0)
  const [playing, setPlaying] = useState(false)
  const secondsRef = useRef(0)

  const moveTo = useCallback((value: number) => {
    const next = Math.max(0, Math.min(duration, value))
    secondsRef.current = next
    setSeconds(next)
    paint(next)
  }, [duration, paint])

  // Repaint the current time after every successful (re)load.
  useEffect(() => {
    if (status === 'ready') paint(Math.min(secondsRef.current, duration))
  }, [status, revision, duration, paint])

  useImperativeHandle(handle, () => ({ seek: moveTo }), [moveTo])

  useEffect(() => {
    if (!playing || status !== 'ready') return
    const origin = performance.now() - secondsRef.current * 1000
    let handle = 0
    const tick = (now: number) => {
      const next = (now - origin) / 1000
      if (next >= duration) {
        moveTo(duration)
        setPlaying(false)
        return
      }
      moveTo(next)
      handle = window.requestAnimationFrame(tick)
    }
    handle = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(handle)
  }, [playing, status, duration, moveTo])

  const toggle = () => {
    if (!playing && secondsRef.current >= duration) moveTo(0)
    setPlaying(value => !value)
  }
  const disabled = locked || status !== 'ready' || duration <= 0

  return (
    <section className="flex flex-col gap-3" aria-label={t('stage.region')}>
      <div className="relative w-full overflow-hidden rounded-xl border border-border bg-black" style={{ aspectRatio: `${width} / ${height}`, maxHeight: '62vh' }}>
        <canvas ref={canvasRef} width={width} height={height} className="h-full w-full object-contain" data-testid="videojs-canvas" />
        {status === 'loading' && (
          <div role="status" className="absolute right-3 top-3 inline-flex items-center gap-2 rounded-full bg-black/70 px-3 py-1 text-xs text-white">
            <Loader2 size={14} className="animate-spin" />{t('stage.loading')}
          </div>
        )}
        {status === 'crashed' && (
          <div role="alert" className="absolute inset-x-3 bottom-3 flex flex-wrap items-center gap-3 rounded-lg bg-red-950/90 p-3 text-sm text-red-100">
            <TriangleAlert size={18} />{t('stage.crashed')}
            <button type="button" onClick={props.onReload} className="ml-auto min-h-9 rounded-md bg-red-200 px-3 text-xs font-semibold text-red-950">{t('stage.reload')}</button>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-bg-secondary p-2">
        <button type="button" disabled={disabled} onClick={toggle} aria-pressed={playing}
          className="inline-flex min-h-11 min-w-28 items-center justify-center gap-2 rounded-lg bg-accent-blue px-4 text-sm font-semibold text-white disabled:opacity-40">
          {playing ? <Pause size={18} /> : <Play size={18} />}{playing ? t('stage.pause') : t('stage.play')}
        </button>
        <button type="button" disabled={disabled} onClick={() => moveTo(0)} aria-label={t('stage.restart')} title={t('stage.restart')}
          className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-border text-text-primary hover:bg-bg-hover disabled:opacity-40"><RotateCcw size={17} /></button>
        <input type="range" min={0} max={Math.max(0.01, duration)} step={0.01} value={seconds} disabled={disabled} aria-label={t('stage.timeline')}
          onChange={event => { setPlaying(false); moveTo(Number(event.target.value)) }} className="h-7 min-w-40 flex-1 cursor-pointer disabled:opacity-40" />
        <span className="text-xs tabular-nums text-text-secondary" data-testid="videojs-time">{formatTime(seconds)} / {formatTime(duration)}</span>
      </div>
    </section>
  )
}
