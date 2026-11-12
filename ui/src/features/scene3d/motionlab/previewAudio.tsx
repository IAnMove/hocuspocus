import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../../i18n'
import type { Scene3DDocument } from '../types'
import { hasMotionLabMusic, scheduleMotionLabMusic } from './musicAudio'
import { DEFAULT_MOTION_LAB } from './types'

export function MotionLabAudio({ document, seconds, playing, speed }: {
  document: Scene3DDocument; seconds: number; playing: boolean; speed: number
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const transport = useRef(seconds), [blocked, setBlocked] = useState(false)
  const reschedule = useRef<(() => void) | null>(null)
  useEffect(() => {
    // Workspace transport loops without pausing. Restart the finite tape on that discontinuity.
    const wrapped = playing && seconds < transport.current - .05
    transport.current = seconds
    if (wrapped) reschedule.current?.()
  }, [seconds, playing])
  useEffect(() => {
    if (!playing || !hasMotionLabMusic(document.dressing, document.motionLab) || typeof AudioContext === 'undefined') return
    const context = new AudioContext()
    let stopped = false, ready = false, sources: AudioBufferSourceNode[] = []
    const stopSources = () => sources.forEach(source => { try { source.stop() } catch { /* already finished */ } })
    const start = () => {
      if (!stopped && ready) {
        stopSources()
        sources = scheduleMotionLabMusic(context, document.dressing, document.motionLab ?? { ...DEFAULT_MOTION_LAB }, document.duration, speed, transport.current)
      }
    }
    reschedule.current = start
    void context.resume().then(() => {
      if (!stopped) {
        ready = true; start()
        setBlocked(false)
      }
    }).catch(() => { if (!stopped) setBlocked(true) })
    return () => {
      stopped = true
      if (reschedule.current === start) reschedule.current = null
      stopSources()
      void context.close()
    }
  }, [document.dressing, document.motionLab, document.duration, playing, speed])
  return blocked && playing && hasMotionLabMusic(document.dressing, document.motionLab) ? <p role="alert">{t('motionLab.audioBlocked')}</p> : null
}
