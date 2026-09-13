import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import type { FaceRigDialogueViseme } from '../../lib/characterKitFaceRig'
import { sampleMouthCues } from './sampleMouthCues'

/** Ships with the app: no upload, speech job, model download or library write. */
export function FaceRigSamplePreview({ kit, disabled, onStart, onViseme, stopRef }: {
  kit: CharacterKit; disabled: boolean; onStart: () => void; onViseme: (viseme?: FaceRigDialogueViseme) => void
  stopRef: RefObject<(() => void) | null>
}) {
  const { t } = useUiTranslation('characters')
  const audio = useRef<HTMLAudioElement>(null), frame = useRef(0), token = useRef(0)
  const [playing, setPlaying] = useState(false), [error, setError] = useState('')
  const callbacks = useRef({ onStart, onViseme }); callbacks.current = { onStart, onViseme }
  const stop = useCallback(() => {
    token.current++
    if (frame.current) { cancelAnimationFrame(frame.current); frame.current = 0 }
    if (audio.current && !audio.current.paused) audio.current.pause()
    callbacks.current.onViseme(undefined); setPlaying(false)
  }, [])
  useEffect(() => {
    setPlaying(false)
    stopRef.current = stop
    return () => {
      stop(); stopRef.current = null
    }
  }, [kit, stopRef, stop])
  const play = async () => {
    stop(); callbacks.current.onStart(); setError(''); setPlaying(true)
    const owner = token.current
    try {
      const response = await fetch('/speech-examples/english-preview.json')
      if (!response.ok) throw new Error(t('faceRig.sampleUnavailable'))
      const cues = sampleMouthCues(await response.json(), kit)
      if (owner !== token.current || !audio.current) return
      audio.current.currentTime = 0
      await audio.current.play()
      const tick = () => {
        if (owner !== token.current || !audio.current) return
        const time = audio.current.currentTime
        callbacks.current.onViseme(cues.find(cue => time >= cue.start && time < cue.end))
        if (!audio.current.ended) frame.current = requestAnimationFrame(tick)
        else stop()
      }
      tick()
    } catch (cause) { if (owner === token.current) { stop(); setError((cause as Error).message) } }
  }
  return <div className="space-y-2 rounded-lg border border-cyan-400/30 p-3">
    <button type="button" disabled={disabled || !Object.values(kit.mouth).some(asset => asset?.source)}
      onClick={() => { if (playing) stop(); else void play() }} className="rounded bg-cyan-500 px-4 py-2 text-sm font-semibold text-black disabled:opacity-40">
      {t(playing ? 'faceRig.stopSample' : 'faceRig.playSample')}
    </button>
    <p className="text-xs text-text-secondary">{t('faceRig.sampleHint')}</p>
    <p className="text-xs">Hello! This is a quick voice test. Watch my lips move as I speak.</p>
    <audio ref={audio} src="/speech-examples/english-preview.mp3" preload="none" onEnded={stop} />
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </div>
}
