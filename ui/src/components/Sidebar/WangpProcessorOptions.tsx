import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { WangpProcessor } from './useWangpProcessors'

const labels = {
  spatial_upsampler_face_count: 'wangp.faceCount', spatial_upsampler_h3_strength: 'wangp.faceStrength',
  spatial_upsampler_dlss_strength: 'wangp.dlssStrength', spatial_upsampler_prompt: 'wangp.refinerPrompt',
} as const

function supportedName(name: string): name is keyof typeof labels { return name in labels }

export function WangpProcessorOptions({ processor }: { processor?: WangpProcessor }) {
  const { t } = useUiTranslation('studio')
  const storedSettings = useStore(s => s.params.wangp_processor_settings)
  const settings = storedSettings || {}
  const setParam = useStore(s => s.setParam)
  return <div className="space-y-2">
    {processor?.parameters?.filter(parameter => supportedName(parameter.name)).map(parameter => {
      const numeric = parameter.type === 'number' || parameter.type === 'integer'
      const value = settings[parameter.name] ?? parameter.default
      return <label className="block text-xs" key={parameter.name}>{t(labels[parameter.name as keyof typeof labels])}{numeric ? `: ${value}` : ''}
        <input aria-label={t(labels[parameter.name as keyof typeof labels])} className="w-full bg-bg-tertiary rounded p-2" type={numeric ? 'range' : 'text'} min={parameter.minimum} max={parameter.maximum} step={parameter.step}
          value={String(value ?? '')} disabled={!processor.enabled}
          onChange={event => setParam('wangp_processor_settings', { ...settings, [parameter.name]: numeric ? Number(event.target.value) : event.target.value })} />
      </label>
    })}
  </div>
}
