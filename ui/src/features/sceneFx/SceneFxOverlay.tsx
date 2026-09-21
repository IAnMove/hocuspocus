import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { paintSceneFx } from './paint'
import { scheduleFx } from './audio'
import type { SceneFx } from './types'

export function SceneFxOverlay({ cues, soundCues, seconds, width, height, playing = false, speed = 1, duration, getSource }: {
  cues?: SceneFx[]; soundCues?: SceneFx[]; seconds: number; width: number; height: number; playing?: boolean; speed?: number; duration: number
  getSource?: () => CanvasImageSource | null
}) {
  const ref = useRef<HTMLCanvasElement>(null), audio = useRef<AudioContext | null>(null)
  const transport = useRef({ seconds, playing })
  const getSourceRef = useRef(getSource)
  const [blocked, setBlocked] = useState(false)
  const { t } = useUiTranslation('sceneFx')
  useEffect(() => { transport.current = { seconds, playing } }, [seconds, playing])
  useEffect(() => { getSourceRef.current = getSource }, [getSource])
  useEffect(() => {
    const ctx = ref.current?.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, width, height); paintSceneFx(ctx, width, height, seconds, cues, getSourceRef.current?.() ?? null)
  }, [cues, seconds, width, height])
  useEffect(() => {
    const audible = soundCues ?? cues
    if (!playing || !audible?.some(cue => cue.sound && cue.volume)) return
    const context = new AudioContext(); audio.current = context
    let stopped = false, sources: AudioBufferSourceNode[] = []
    void context.resume().then(() => {
      if (!stopped) sources = scheduleFx(context, audible, duration, speed, transport.current.seconds)
    }).catch(() => { if (!stopped) setBlocked(true) })
    return () => { stopped = true; sources.forEach(source => source.stop()); void context.close(); audio.current = null }
  }, [cues, soundCues, duration, playing, speed])
  return <>
    <canvas ref={ref} width={width} height={height} className="pointer-events-none absolute inset-0 z-[899] h-full w-full" aria-hidden="true" data-testid="scene-fx-overlay" />
    {blocked && <p role="alert">{t('audioBlocked')}</p>}
  </>
}
