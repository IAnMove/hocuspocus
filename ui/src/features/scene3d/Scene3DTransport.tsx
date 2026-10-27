import { Pause, Play, RotateCcw } from 'lucide-react'
import { useUiTranslation } from '../../i18n'

export function Scene3DTransport({ playing, disabled, seconds, duration, speed, onToggle, onSeek, onSpeed }: {
  playing: boolean; disabled: boolean; seconds: number; duration: number; speed: number
  onToggle: () => void; onSeek: (seconds: number) => void; onSpeed: (speed: number) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return <div className="flex flex-wrap items-center gap-3 border-t border-cyan-300/30 bg-bg-secondary p-3" data-testid="world3d-transport">
    <button type="button" disabled={disabled} onClick={onToggle} aria-pressed={playing}
      className="inline-flex min-h-12 min-w-36 items-center justify-center gap-2 rounded-lg bg-cyan-300 px-5 text-sm font-bold text-slate-950 shadow-lg shadow-cyan-950/30 hover:bg-cyan-200 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-200 disabled:opacity-40">
      {playing ? <Pause size={22} fill="currentColor" aria-hidden="true" /> : <Play size={22} fill="currentColor" aria-hidden="true" />}
      {playing ? t('pause') : t('play')}
    </button>
    <button type="button" disabled={disabled} onClick={() => onSeek(0)} aria-label={t('restart')} title={t('restart')}
      className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-border text-text-primary hover:bg-bg-hover disabled:opacity-40"><RotateCcw size={19} /></button>
    <div className="min-w-36 flex-1">
      <input type="range" min={0} max={duration} step={0.01} value={seconds} disabled={disabled} aria-label={t('timeline')}
        onChange={event => onSeek(Number(event.target.value))} className="h-7 w-full cursor-pointer accent-cyan-300 disabled:opacity-40" />
      <div className="flex justify-between text-xs tabular-nums text-text-secondary"><span>{(seconds / speed).toFixed(2)} s</span><span>{t('outputDuration', { seconds: (duration / speed).toFixed(2) })}</span></div>
    </div>
    <label className="flex items-center gap-2 text-sm text-text-primary" title={t('speedHelp')}>
      {t('speed')}
      <select aria-label={t('speed')} value={speed} disabled={disabled} onChange={event => onSpeed(Number(event.target.value))} className="min-h-11 rounded-lg border border-border bg-bg-primary px-3 font-semibold disabled:opacity-40">
        {[0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4].map(rate => <option key={rate} value={rate}>{rate}×</option>)}
      </select>
    </label>
    <p className="w-full text-xs text-text-muted">{t('speedHelp')}</p>
  </div>
}
