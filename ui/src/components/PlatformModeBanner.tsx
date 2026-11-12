import { useEffect, useState } from 'react'
import { Monitor } from 'lucide-react'
import { fetchSystemCapabilities, type SystemCapabilities } from '../api/system'
import { useUiTranslation } from '../i18n'

const MODE_KEYS = {
  macosCoreRemote: 'capabilities.macosCoreRemote',
  macosIntel: 'capabilities.macosIntel',
  coreRemote: 'capabilities.coreRemote',
} as const

/** Persistent platform mode for Apple Silicon / core-remote hosts, shown as a line in the notices tray. */
export function PlatformModeBanner() {
  const { t } = useUiTranslation('shell')
  const [snapshot, setSnapshot] = useState<SystemCapabilities | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchSystemCapabilities()
      .then(value => { if (!cancelled) setSnapshot(value) })
      .catch(() => { /* older backend / transient */ })
    return () => { cancelled = true }
  }, [])

  const mode = snapshot?.ui.mode
  const key = mode && mode in MODE_KEYS ? MODE_KEYS[mode as keyof typeof MODE_KEYS] : null
  if (!key) return null

  return (
    <div
      role="status"
      data-testid="platform-mode-banner"
      className="flex items-start gap-2 rounded-lg border border-border bg-bg-secondary px-3 py-2 text-xs text-text-secondary"
    >
      <Monitor size={14} className="mt-0.5 shrink-0" />
      <p className="min-w-0 flex-1">{t(key)}</p>
    </div>
  )
}
