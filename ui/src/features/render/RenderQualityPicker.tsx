import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import {
  clampShutter,
  estimateRender,
  formatEstimateAmount,
  renderDeviceOf,
  type RenderChoice,
  type RenderDevice,
  type RenderLevel,
} from './renderEstimate.ts'

const LEVELS: RenderLevel[] = ['draft', 'final', 'master']
const LEVEL_KEY = {
  draft: 'stage.renderDraft',
  final: 'stage.renderFinal',
  master: 'stage.renderMaster',
} as const

export function RenderQualityPicker({
  width,
  height,
  fps,
  duration,
  disabled,
  capabilitiesUrl,
  onChange,
}: {
  width: number
  height: number
  fps: number
  duration: number
  disabled?: boolean
  capabilitiesUrl?: string
  onChange: (choice: RenderChoice) => void
}) {
  const { t } = useUiTranslation('scene3d')
  const [level, setLevel] = useState<RenderLevel>('draft')
  const [shutter, setShutter] = useState(180)
  const [device, setDevice] = useState<RenderDevice>('cpu')

  useEffect(() => {
    const load = globalThis.fetch
    if (!capabilitiesUrl || typeof load !== 'function') return undefined
    const controller = new AbortController()
    void load(capabilitiesUrl, { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(body => {
        if (!controller.signal.aborted && body && typeof body === 'object') {
          setDevice(renderDeviceOf((body as { renderDevice?: unknown }).renderDevice))
        }
      })
      .catch(() => undefined)
    return () => controller.abort()
  }, [capabilitiesUrl])

  const choice: RenderChoice = { level, shutter: level === 'draft' ? 0 : clampShutter(shutter) }
  const estimate = estimateRender({ ...choice, width, height, fps, duration, device })
  const amount = formatEstimateAmount(estimate.seconds, estimate.bytes)
  const time = t(amount.timeUnit === 'seconds' ? 'stage.renderSeconds' : 'stage.renderMinutes', { count: amount.time })
  const size = t(amount.sizeUnit === 'megabytes' ? 'stage.renderMegabytes' : 'stage.renderGigabytes', { count: amount.size })

  const publish = (nextLevel: RenderLevel, nextShutter: number) => {
    onChange({ level: nextLevel, shutter: nextLevel === 'draft' ? 0 : clampShutter(nextShutter) })
  }

  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="render-quality">
      <label className="flex flex-col gap-1 text-xs text-text-muted">
        {t('stage.renderLevel')}
        <select
          disabled={disabled}
          value={level}
          data-testid="render-level"
          onChange={event => {
            const next = event.target.value as RenderLevel
            setLevel(next)
            publish(next, shutter)
          }}
          className="min-h-11 rounded-lg border border-border bg-bg-primary px-3 text-xs text-text-primary disabled:opacity-40"
        >
          {LEVELS.map(item => <option key={item} value={item}>{t(LEVEL_KEY[item])}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-text-muted">
        {t('stage.renderShutter')}
        <input
          type="number"
          min={0}
          max={360}
          step={1}
          disabled={disabled || level === 'draft'}
          value={shutter}
          data-testid="render-shutter"
          onChange={event => {
            const next = clampShutter(Number(event.target.value))
            setShutter(next)
            publish(level, next)
          }}
          className="min-h-11 w-24 rounded-lg border border-border bg-bg-primary px-3 text-xs text-text-primary disabled:opacity-40"
        />
      </label>
      <p className="max-w-xl text-xs text-text-muted" data-testid="render-estimate">
        {t('stage.renderEstimate', { time, size })}
        {' '}
        {device === 'cpu' ? t('stage.renderDeviceCpu') : t('stage.renderDeviceGpu')}
        {' '}
        {t('stage.renderHint')}
      </p>
    </div>
  )
}
