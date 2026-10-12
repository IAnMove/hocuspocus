import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { LoopEngine } from './audioLoop'
import { buttonClass, choiceClass, errorClass } from './styles'

interface Source { key: string; url: string }

/** SFX variants, jingles and voices: plain playback, no loop. */
export function AudioVariants({ sources }: { sources: Source[] }) {
  const { t } = useUiTranslation('gameAssets')
  const [active, setActive] = useState(0)
  const source = sources[active] || sources[0]
  if (!source) return null
  return (
    <div className="space-y-2">
      <audio key={source.url} src={source.url} controls />
      {sources.length > 1 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label={t('variants')}>
          {sources.map((item, index) => (
            <button key={item.key} type="button" className={choiceClass(index === active)} aria-pressed={index === active}
              onClick={() => setActive(index)}>{t('variant', { name: item.key })}</button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Music: Web Audio loops between the sample-exact loop points and counts the wraps. */
export function MusicLoopPlayer({ url, loop }: { url: string; loop: { start: number; end: number } | null }) {
  const { t } = useUiTranslation('gameAssets')
  const [playing, setPlaying] = useState(false)
  const [turns, setTurns] = useState(0)
  const [error, setError] = useState('')
  const engineRef = useRef<LoopEngine | null>(null)
  const loopStart = loop?.start ?? null
  const loopEnd = loop?.end ?? null

  useEffect(() => {
    engineRef.current = new LoopEngine(url, loopEnd === null ? null : { start: loopStart ?? 0, end: loopEnd })
    return () => {
      engineRef.current?.close()
      engineRef.current = null
    }
  }, [url, loopStart, loopEnd])

  useEffect(() => {
    if (!playing) return undefined
    const timer = setInterval(() => setTurns(engineRef.current?.turns() ?? 0), 200)
    return () => clearInterval(timer)
  }, [playing])

  const play = (fromSeam: boolean) => {
    const engine = engineRef.current
    if (!engine) return
    setError('')
    setTurns(0)
    engine.play(fromSeam).then(() => setPlaying(true), () => {
      setPlaying(false)
      setError(t('couldNotPlay'))
    })
  }

  const stop = () => {
    engineRef.current?.stop()
    setPlaying(false)
  }

  if (!url) return null
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} onClick={() => play(false)}>{t('playLoop')}</button>
        <button type="button" className={buttonClass} onClick={() => play(true)}>{t('listenSeam')}</button>
        <button type="button" className={buttonClass} disabled={!playing} onClick={stop}>{t('stop')}</button>
      </div>
      <p className="text-sm" aria-live="polite">{t('loopTurns', { count: turns })}</p>
      {error && <p role="alert" className={errorClass}>{error}</p>}
    </div>
  )
}
