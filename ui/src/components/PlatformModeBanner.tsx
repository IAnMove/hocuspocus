import { useEffect, useState } from 'react'
import { Monitor } from 'lucide-react'
import { fetchSystemCapabilities, type SystemCapabilities } from '../api/system'
import { useUiTranslation } from '../i18n'

const MODE_KEYS = {
  macosCoreRemote: 'capabilities.macosCoreRemote',
  macosIntel: 'capabilities.macosIntel',
  coreRemote: 'capabilities.coreRemote',
} as const

/** Persistent platform mode for Apple Silicon / core-remote hosts. */
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
      className="fixed left-1/2 top-10 z-[90] -translate-x-1/2 rounded-full border border-border bg-bg-secondary/95 px-3 py-1 text-[10px] font-semibold tracking-[0.08em] text-text-secondary shadow-xl"
    >
      <span className="flex items-center gap-1.5">
        <Monitor size={12} /> {t(key)}
      </span>
    </div>
  )
}
