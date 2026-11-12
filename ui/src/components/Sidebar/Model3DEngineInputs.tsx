import { Info, X } from 'lucide-react'
import type { Hunyuan3DModel } from '../../api/model3d'
import { useUiTranslation } from '../../i18n'

export function Model3DEngineInputs({ model, resolution, onResolution, lowVram, onLowVram, fov, onFov }: {
  model: Hunyuan3DModel
  resolution: number
  onResolution: (value: number) => void
  lowVram: boolean
  onLowVram: (value: boolean) => void
  fov: number
  onFov: (value: number) => void
}) {
  const { t } = useUiTranslation('scene3d')
  return <div className="space-y-2 rounded-lg border border-border p-3 text-xs">
    <p className="flex items-start gap-2"><Info size={15} aria-hidden="true" />{t('engines.nativePbr')}</p>
    <label className="block">{t('engines.resolution')}
      <select aria-label={t('engines.resolution')} value={resolution} onChange={event => onResolution(Number(event.target.value))} className="ml-2 bg-bg-primary">
        {model.resolutions?.map(value => <option key={value} value={value}>{value}</option>)}
      </select>
    </label>
    <label className="flex items-center gap-2">
      <input aria-label={t('engines.lowVram')} type="checkbox" checked={!!model.supports_low_vram && lowVram} disabled={!model.supports_low_vram} onChange={event => onLowVram(event.target.checked)} />
      {!model.supports_low_vram && <X size={12} aria-hidden="true" />}{t('engines.lowVram')}
    </label>
    {!model.supports_low_vram && <p className="text-text-muted">{t('engines.lowVramUnavailable')}</p>}
    <label className="block">{!model.supports_camera_fov && '✕ '}{t('engines.fov')}
      <input aria-label={t('engines.fov')} type="number" min={0} max={3.13} step={0.01} value={model.supports_camera_fov ? fov : 0} disabled={!model.supports_camera_fov} onChange={event => onFov(Number(event.target.value))} className="ml-2 w-20 bg-bg-primary disabled:opacity-40" />
    </label>
    <p className="text-text-muted">{t(model.supports_camera_fov ? 'engines.fovHelp' : 'engines.fovUnavailable')}</p>
  </div>
}
