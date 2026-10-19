import { useUiTranslation } from '../../i18n'
import type { ServicesConfig } from '../../types'

/** Settings › Services: «Modo un solo disparo». Off (the default, agent_autonomy = review) a person approves what an agent makes; on
 * (one_shot) the agent approves it too, marked as the agent's in the app so the owner can audit and revert it. */
export function AgentAutonomySettings({ config, onChange }: {
  config: Pick<ServicesConfig, 'agent_autonomy'>
  onChange: (partial: Pick<ServicesConfig, 'agent_autonomy'>) => void
}) {
  const { t } = useUiTranslation('settings')
  const on = config.agent_autonomy === 'one_shot'
  return (
    <label className="flex items-center justify-between cursor-pointer group">
      <div className="flex-1 mr-3 min-w-0">
        <div className="text-sm text-text-primary group-hover:text-accent-blue transition-colors">{t('services.oneShotTitle')}</div>
        <div className="text-[10px] text-text-muted mt-0.5">{t('services.oneShotHint')}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={t('services.oneShotTitle')}
        onClick={() => onChange({ agent_autonomy: on ? 'review' : 'one_shot' })}
        className={`w-9 h-5 rounded-full transition-colors relative shrink-0 ${on ? 'bg-accent-blue' : 'bg-bg-tertiary border border-border'}`}
      >
        <span className={`absolute top-0.5 left-0 w-4 h-4 rounded-full bg-white border border-border shadow transition-transform ${on ? 'translate-x-4' : 'translate-x-0.5'}`} />
      </button>
    </label>
  )
}
