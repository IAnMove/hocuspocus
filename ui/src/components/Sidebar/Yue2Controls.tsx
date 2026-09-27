import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { GenerateParams } from '../../types'

export function Yue2Controls() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const setParam = useStore(s => s.setParam)
  if (params.model_type !== 'yue2') return null
  return <div className="space-y-2 rounded border border-border p-2 text-xs text-text-secondary">
    <label className="block">{t('yue2.planning')}
      <select className="mt-1 w-full rounded border border-border bg-bg-tertiary p-2"
        value={Number(params.model_mode ?? 0)}
        onChange={event => setParam('model_mode' as keyof GenerateParams, Number(event.target.value))}>
        <option value={0}>{t('yue2.chords')}</option>
        <option value={1}>{t('yue2.melody')}</option>
        <option value={2}>{t('yue2.direct')}</option>
      </select>
    </label>
    <label className="block">{t('advanced.inferenceSteps')}
      <input className="ml-2 w-20 rounded border border-border bg-bg-tertiary p-1" type="number" min={1} max={100}
        value={params.num_inference_steps ?? 32}
        onChange={event => setParam('num_inference_steps', Number(event.target.value))} />
    </label>
    <p>{t('yue2.durationHint')}</p>
    <p>{t('yue2.license')}</p>
  </div>
}
