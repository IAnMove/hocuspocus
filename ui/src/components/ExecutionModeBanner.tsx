import { FlaskConical } from 'lucide-react'
import { useStore } from '../stores/useStore'

/** Persistent safety marker for non-production execution modes. */
export function ExecutionModeBanner() {
  const config = useStore(state => state.systemConfig)
  const mode = config?.execution_mode
  if (!mode || mode === 'real') return null

  return (
    <div
      role="status"
      data-testid="execution-mode-banner"
      className="fixed left-1/2 top-2 z-[100] -translate-x-1/2 rounded-full border border-amber-300/60 bg-amber-950/95 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-100 shadow-xl"
      title={`Boot-locked ${mode} mode · isolated workspace ${config.execution_workspace || 'unknown'} · paid providers ${config.execution_allow_paid ? 'allowed' : 'blocked'}`}
    >
      <span className="flex items-center gap-1.5">
        <FlaskConical size={12} /> {mode} mode · {config.execution_workspace}
      </span>
    </div>
  )
}
