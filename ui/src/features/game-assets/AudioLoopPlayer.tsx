import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { countLoop, seamTime } from './reviewModel'
import { buttonClass } from './styles'

interface Source { key: string; url: string }

export function AudioLoopPlayer({ sources, loopStart, loopEnd }: { sources: Source[]; loopStart: number; loopEnd: number }) {
  const { t } = useUiTranslation('gameAssets')
  const [active, setActive] = useState(0)
  const [turns, setTurns] = useState(0)
  const [error, setError] = useState('')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const previousRef = useRef(0)
  const source = sources[active] || sources[0]

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.loop = true
    if ('loopStart' in audio) audio.loopStart = loopStart
    if ('loopEnd' in audio) audio.loopEnd = loopEnd > loopStart ? loopEnd : loopStart
  }, [loopStart, loopEnd, source?.url])

  useEffect(() => {
    const timer = setInterval(() => {
      const audio = audioRef.current
      if (!audio) return
      const end = loopEnd > loopStart ? loopEnd : audio.duration || loopEnd
      setTurns(current => countLoop(previousRef.current, audio.currentTime, end, current))
      previousRef.current = audio.currentTime
    }, 200)
    return () => clearInterval(timer)
  }, [loopStart, loopEnd])

  const listen = () => {
    const audio = audioRef.current
    if (!audio) return
    const end = loopEnd > loopStart ? loopEnd : audio.duration || 0
    audio.currentTime = seamTime(end)
    void audio.play().catch(reason => setError(reason instanceof Error ? reason.message : 'Could not play'))
  }

  if (!source) return null
  return (
    <div className="space-y-2">
      <audio ref={audioRef} src={source.url} controls loop />
      <p className="text-sm">{t('loopTurns', { count: turns })}</p>
      <button type="button" className={buttonClass} onClick={listen}>{t('listenSeam')}</button>
      {sources.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {sources.map((item, index) => (
            <button key={item.key} type="button" className={buttonClass} aria-pressed={index === active} onClick={() => { setActive(index); setTurns(0) }}>{item.key}</button>
          ))}
        </div>
      )}
      {error && <p className="text-sm text-red-500">{error}</p>}
    </div>
  )
}
