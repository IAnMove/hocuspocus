import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { checkPublishPreset, publishVideo, type PublishPreset, type PublishWarning } from '../../api/publish'

const PRESETS: PublishPreset[] = ['x', 'youtube', 'shorts', 'archive']

export function PublishPresetBar({
  width,
  height,
  duration,
  overlays,
  source,
  workspace,
  onError,
  check = checkPublishPreset,
  publish = publishVideo,
}: {
  width: number
  height: number
  duration: number
  overlays: Array<{ id: string; y: number; width: number }>
  source: string
  workspace: string
  onError: (message: string) => void
  check?: typeof checkPublishPreset
  publish?: typeof publishVideo
}) {
  const { t } = useUiTranslation('videoEditor')
  const [preset, setPreset] = useState<PublishPreset>('x')
  const [premium, setPremium] = useState(false)
  const [warnings, setWarnings] = useState<PublishWarning[]>([])
  const [busy, setBusy] = useState(false)
  const review = (nextPreset: PublishPreset, nextPremium: boolean) => {
    check({ preset: nextPreset, premium: nextPremium, width, height, duration, overlays })
      .then(setWarnings)
      .catch(reason => onError(reason instanceof Error ? reason.message : String(reason)))
  }
  return (
    <div className="flex items-center gap-1">
      <label className="sr-only" htmlFor="publish-preset">{t('toolbar.publish')}</label>
      <select
        id="publish-preset"
        aria-label={t('toolbar.publish')}
        value={preset}
        onChange={event => {
          const next = event.target.value as PublishPreset
          setPreset(next)
          review(next, premium)
        }}
        className="max-w-[9rem] rounded border border-border bg-bg-secondary px-1.5 py-1 text-[10px] text-text-secondary"
      >
        {PRESETS.map(value => <option key={value} value={value}>{t(`toolbar.publish_${value}`)}</option>)}
      </select>
      <label className="flex items-center gap-1 text-[10px] text-text-muted">
        <input type="checkbox" checked={premium} onChange={event => { setPremium(event.target.checked); review(preset, event.target.checked) }} />
        {t('toolbar.publishPremium')}
      </label>
      {source && (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true)
            publish({ workspace, source, preset, premium, width, height, duration, overlays, loudnorm: true })
              .catch(reason => onError(reason instanceof Error ? reason.message : String(reason)))
              .finally(() => setBusy(false))
          }}
          className="rounded border border-border px-1.5 py-1 text-[10px] text-text-secondary disabled:opacity-40"
        >
          {busy ? t('toolbar.publishWorking') : t('toolbar.publishApply')}
        </button>
      )}
      {warnings.length > 0 && (
        <span className="max-w-48 truncate text-[10px] text-amber-300" title={warnings.map(item => item.code).join(', ')}>
          {warnings.map(item => t(`toolbar.publishWarning_${item.code}`, { limit: item.limit, expected: item.expected })).join(' · ')}
        </span>
      )}
    </div>
  )
}
