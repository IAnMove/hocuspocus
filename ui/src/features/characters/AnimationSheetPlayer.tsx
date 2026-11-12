import { useEffect, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { animationFrame, sheetCellStyle, type KitAnimation } from '../../lib/characterAnimations'

const reducedMotion = (): boolean => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Plays a made animation as it will play in a scene: one cell of the sheet at a time, at its fps and loop. A person who asked
 * for less motion gets it paused on its first frame, and can still step through it. */
export function AnimationSheetPlayer({ animation, title }: { animation: Pick<KitAnimation, 'sheet' | 'fps' | 'loop'>; title: string }) {
  const { t } = useUiTranslation('characters')
  const [playing, setPlaying] = useState(() => !reducedMotion())
  const [frame, setFrame] = useState(0)
  const { sheet, fps, loop } = animation
  useEffect(() => {
    if (!playing) return undefined
    const started = Date.now()
    const timer = setInterval(() => setFrame(animationFrame({ sheet, fps, loop }, (Date.now() - started) / 1000)), Math.max(30, 1000 / fps / 2))
    return () => clearInterval(timer)
  }, [playing, sheet, fps, loop])
  const shown = Math.min(frame, sheet.count - 1)
  return <div className="space-y-1">
    <div role="img" aria-label={title} data-testid="animation-player" data-frame={shown}
      className="mx-auto max-h-64 w-full max-w-[14rem] rounded-lg border border-border bg-bg-tertiary"
      style={{ ...sheetCellStyle(sheet, shown), aspectRatio: `${sheet.cell.width} / ${sheet.cell.height}` }} />
    <div className="flex items-center justify-center gap-2 text-[11px] text-text-muted">
      <button type="button" aria-label={t(playing ? 'animations.pause' : 'animations.play')} onClick={() => setPlaying(value => !value)}
        className="rounded border border-border p-1">{playing ? <Pause size={12} /> : <Play size={12} />}</button>
      <span>{t('animations.frameOf', { frame: shown + 1, count: sheet.count })}</span>
      {!playing && <button type="button" className="rounded border border-border px-1.5" onClick={() => setFrame(value => (value + 1) % sheet.count)}>{t('animations.nextFrame')}</button>}
    </div>
  </div>
}
