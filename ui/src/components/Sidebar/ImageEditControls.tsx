import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'

export function ImageEditControls() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params), options = useStore(s => s.modelOptions)
  const setParam = useStore(s => s.setParam)
  const modes = options?.image_edit_modes, layers = options?.image_layer_count
  const editing = Boolean(params.image_mask || params.video_guide_outpainting)
  return <>
    {layers ? <label className="block text-[11px] text-text-secondary">
      {t('imageEdit.layers')}
      <input type="number" min={layers.min} max={layers.max} value={params.batch_size ?? layers.default}
        className="mt-1 w-full rounded border border-border bg-bg-tertiary px-2 py-1.5 text-xs"
        onChange={event => setParam('batch_size', Math.min(layers.max, Math.max(layers.min, Number(event.target.value) || layers.default)))} />
    </label> : null}
    {editing && modes?.choices.length ? <label className="block text-[11px] text-text-secondary">
      {t('imageEdit.method')}
      <select value={params.model_mode ?? modes.default} onChange={event => setParam('model_mode', Number(event.target.value))}
        className="mt-1 w-full rounded border border-border bg-bg-tertiary px-2 py-1.5 text-xs">
        {modes.choices.map(([label, value]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label> : null}
    {params.image_mask ? <label className="block text-[11px] text-text-secondary">
      {t('imageEdit.maskStrength')} ({params.masking_strength ?? 1})
      <input type="range" min={0} max={1} step={.05} className="mt-1 w-full" value={params.masking_strength ?? 1}
        onChange={event => setParam('masking_strength', Number(event.target.value))} />
    </label> : null}
  </>
}
