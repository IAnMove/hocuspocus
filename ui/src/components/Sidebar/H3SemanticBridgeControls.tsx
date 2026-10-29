import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { supportsSemanticBridge } from '../../lib/h3OptionalSettings'

export function H3SemanticBridgeControls() {
  const { t } = useUiTranslation('studio')
  const model = useStore(s => s.params.model_type)
  const supported = useStore(s => s.modelOptions?.minimax_h3_semantic_bridge === true)
  const alpha = useStore(s => s.params.minimax_h3_semantic_bridge_alpha ?? 0)
  const magnitude = useStore(s => s.params.minimax_h3_semantic_bridge_magnitude ?? 'per_token')
  const setParam = useStore(s => s.setParam)
  if (!supported || !supportsSemanticBridge(model)) return null
  return <div className="space-y-2 border-t border-border pt-2">
    <label className="flex items-center gap-2">
      <input aria-label={t('h3Bridge.label')} type="checkbox" checked={alpha > 0} onChange={e => setParam('minimax_h3_semantic_bridge_alpha', e.target.checked ? 0.1 : 0)} />
      {t('h3Bridge.label')}
    </label>
    <p className="text-text-muted">{t('h3Bridge.hint')}</p>
    {alpha > 0 && <>
      <label className="flex items-center justify-between gap-2">
        {t('h3Bridge.strength')}
        <select aria-label={t('h3Bridge.strength')} value={String(alpha)} className="rounded bg-bg-tertiary p-1"
          onChange={e => setParam('minimax_h3_semantic_bridge_alpha', Number(e.target.value))}>
          <option value="0.1">0.10</option><option value="0.15">0.15</option>
          {alpha !== 0.1 && alpha !== 0.15 && <option value={String(alpha)}>{alpha}</option>}
        </select>
      </label>
      <label className="flex items-center justify-between gap-2">
        {t('h3Bridge.magnitude')}
        <select aria-label={t('h3Bridge.magnitude')} value={magnitude} className="rounded bg-bg-tertiary p-1"
          onChange={e => setParam('minimax_h3_semantic_bridge_magnitude', e.target.value as typeof magnitude)}>
          <option value="per_token">{t('h3Bridge.perToken')}</option>
          <option value="global">{t('h3Bridge.global')}</option>
          <option value="none">{t('h3Bridge.none')}</option>
        </select>
      </label>
    </>}
  </div>
}
