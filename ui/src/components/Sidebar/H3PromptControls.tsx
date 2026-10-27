import { controlReason } from '../../i18n/controlLabel'
import { H3SemanticBridgeControls } from './H3SemanticBridgeControls'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'

/** Settings belong to the generation snapshot, so plans can be replayed after a refactor. */
export function H3PromptControls() {
  const { t } = useUiTranslation('studio')
  const model = useStore(s => s.params.model_type)
  const style = useStore(s => s.params.minimax_h3_planning_style ?? 'faithful')
  const policy = useStore(s => s.params.minimax_h3_audio_policy ?? 'native')
  const sequence = useStore(s => s.params.minimax_h3_reference_sequence === true)
  const omni = useStore(s => s.modelOptions?.omni_reference === true)
  const attention = useStore(s => s.params.override_attention ?? '')
  const fused = useStore(s => s.modelOptions?.minimax_h3_fused_turbo === true)
  // FastH3 reuses the fused plumbing but runs dense attention by default.
  const denseDefault = useStore(s => s.modelOptions?.minimax_h3_fasth3 === true)
  const busy = useStore(s => s.isEnhancing)
  const setParam = useStore(s => s.setParam)
  const clearPlan = useStore(s => s.clearH3WindowPlan)
  const enhance = useStore(s => s.enhancePrompt)
  if (!model.startsWith('minimax_h3') || model === 'minimax_h3_legacy') return null
  return <div className="space-y-2 rounded-lg border border-border p-3 text-xs">
    <label className="flex items-center justify-between gap-2">
      {t('h3Adoption.writing')}
      <select aria-label={t('h3Adoption.writing')} value={style} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')}
        onChange={e => { setParam('minimax_h3_planning_style', e.target.value as typeof style); clearPlan() }}
        className="rounded bg-bg-tertiary p-1">
        <option value="faithful">{t('h3Adoption.faithful')}</option>
        <option value="creative">{t('h3Adoption.creative')}</option>
      </select>
    </label>
    <p className="text-text-muted">{t(style === 'creative' ? 'h3Adoption.creativeHint' : 'h3Adoption.faithfulHint')}</p>
    <button type="button" disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onClick={() => enhance()}
      className="rounded bg-accent-blue/15 px-2 py-1 text-accent-blue disabled:opacity-50">
      {t('h3Adoption.enhance')}
    </button>
    <label className="flex items-center justify-between gap-2">
      {t('h3Adoption.audio')}
      <select aria-label={t('h3Adoption.audio')} value={policy} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')}
        onChange={e => { setParam('minimax_h3_audio_policy', e.target.value as typeof policy); clearPlan() }}
        className="rounded bg-bg-tertiary p-1">
        <option value="native">{t('h3Adoption.native')}</option>
        <option value="legacy">{t('h3Adoption.legacy')}</option>
      </select>
    </label>
    {omni && <label className="flex items-center gap-2">
      <input aria-label={t('h3Adoption.sequence')} type="checkbox" checked={sequence} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onChange={e => { setParam('minimax_h3_reference_sequence', e.target.checked); clearPlan() }} />
      {t('h3Adoption.sequence')}
    </label>}
    <label className="flex items-center justify-between gap-2">
      {t('h3Adoption.attention')}
      <select aria-label={t('h3Adoption.attention')} value={fused && !denseDefault && !attention ? 'sla' : attention}
        onChange={e => setParam('override_attention', e.target.value)} className="rounded bg-bg-tertiary p-1">
        {(!fused || denseDefault) && <option value="">{t('h3Adoption.denseAuto')}</option>}
        <option value="sdpa">SDPA</option>
        {fused && <option value="sla">SLA</option>}
        {!fused && <option value="sol">Sol-Attn</option>}
      </select>
    </label>
    <p className="text-text-muted">{t('h3Adoption.fallback')}</p>
    <H3SemanticBridgeControls />
  </div>
}
