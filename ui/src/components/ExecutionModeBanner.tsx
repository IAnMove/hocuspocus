import { FlaskConical } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import { useStore } from '../stores/useStore'

/**
 * Persistent safety marker for non-production execution modes. It floats over full-screen
 * overlays, so it must not take their clicks (it used to cover the Director dashboard header actions).
 */
export function ExecutionModeBanner() {
  const { t } = useUiTranslation('shell')
  const config = useStore(state => state.systemConfig)
  const mode = config?.execution_mode
  if (!mode || mode === 'real') return null
  const workspace = config.execution_workspace || 'unknown'
  const paid = t(config.execution_allow_paid ? 'execution.allowed' : 'execution.blocked')

  return (
    <div
      role="status"
      data-testid="execution-mode-banner"
      className="pointer-events-none fixed left-1/2 top-2 z-[100] -translate-x-1/2 rounded-full border border-amber-300/60 bg-amber-950/95 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-100 shadow-xl"
      title={t('execution.title', { mode, workspace, paid })}
    >
      <span className="flex items-center gap-1.5">
        <FlaskConical size={12} /> {t('execution.banner', { mode, workspace })}
      </span>
    </div>
  )
}
