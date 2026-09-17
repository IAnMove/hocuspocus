import { useUiTranslation } from '../../i18n'
import type { MediaScreen } from './mediaScreen'

export function Scene3DLoopControls({ screen, disabled, patch }: {
  screen: MediaScreen; disabled: boolean; patch: (value: Partial<MediaScreen>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  if (screen.media !== 'video') return null
  return <details className="space-y-2 text-xs">
    <summary className="cursor-pointer py-2">{t('screens.loopDetails')}</summary>
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" disabled={disabled || !screen.loop} checked={Boolean(screen.pingPong)} onChange={e => patch({ pingPong: e.target.checked })} />{t('screens.pingPong')}</label>
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" disabled={disabled || !screen.loop} checked={Boolean(screen.loopRange)} onChange={e => patch({ loopRange: e.target.checked ? [screen.start, screen.start + 1] : undefined })} />{t('screens.loopRange')}</label>
    {screen.loopRange && <div className="grid grid-cols-2 gap-2">{([0, 1] as const).map(index => <label key={index}>{t(index ? 'screens.loopEnd' : 'screens.loopStart')}
      <input type="number" min={0} max={86400} step={.01} disabled={disabled} value={screen.loopRange![index]} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-primary p-1" onChange={e => {
        const value = Number(e.target.value), range: [number, number] = [...screen.loopRange!]
        range[index] = value
        if (e.target.value && Number.isFinite(value) && range[0] >= 0 && range[1] > range[0] && range[1] <= 86400) patch({ loopRange: range })
      }} /></label>)}</div>}
    <label className="block">{t('screens.timeOffset')}<input type="number" min={0} max={86400} step={.01} disabled={disabled} value={screen.timeOffset ?? 0} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-primary p-1" onChange={e => {
      const value = Number(e.target.value)
      if (e.target.value && Number.isFinite(value)) patch({ timeOffset: Math.max(0, Math.min(86400, value)) })
    }} /></label>
    <p className="text-text-muted">{t('screens.loopDetailsHelp')}</p>
  </details>
}
