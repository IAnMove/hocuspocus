import { useState } from 'react'
import { Info, X } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import { useStore } from '../stores/useStore'
import type { ProductionProfile } from '../types'

const DISMISSED_KEY = 'hocuspocus-production-profile-notice'

function dismissedFor(signature: string): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === signature
  } catch {
    return false
  }
}

function remember(signature: string) {
  try {
    localStorage.setItem(DISMISSED_KEY, signature)
  } catch {
    // Storage can be unavailable; the notice then simply closes for this visit.
  }
}

function describe(choice: { provider: string; model: string }, local: string): string {
  return `${choice.model} (${choice.provider === 'local' ? local : choice.provider})`
}

/** Says which providers text and pictures use until the user saves a profile. It never blocks the app. */
export function ProductionProfileNotice() {
  const { t } = useUiTranslation('shell')
  const loaded = useStore(s => s.productionProfileLoaded)
  const configured = useStore(s => s.productionProfileConfigured)
  const invalidReason = useStore(s => s.productionProfileInvalidReason)
  const profile: ProductionProfile = useStore(s => s.productionProfile)
  const setSettingsOpen = useStore(s => s.setSettingsOpen)
  const signature = invalidReason ? `invalid:${invalidReason}` : `defaults:${profile.text.provider}:${profile.image.provider}`
  const [closed, setClosed] = useState(() => dismissedFor(signature))

  if (!loaded || configured || closed || dismissedFor(signature)) return null
  const local = t('profileNotice.local')
  const message = invalidReason
    ? t('profileNotice.invalid', { reason: invalidReason })
    : t('profileNotice.defaults', { text: describe(profile.text, local), image: describe(profile.image, local) })
  const close = () => {
    remember(signature)
    setClosed(true)
  }

  return (
    <div
      role="status"
      data-testid="production-profile-notice"
      className="mx-3 mt-2 flex items-start gap-2 rounded-lg border border-border bg-bg-secondary px-3 py-2 text-xs text-text-secondary"
    >
      <Info size={14} className="mt-0.5 shrink-0 text-accent-blue" />
      <p className="flex-1 min-w-0">{message}</p>
      <button
        type="button"
        onClick={() => { setSettingsOpen(true); close() }}
        className="shrink-0 rounded-md bg-accent-blue px-2 py-1 text-[11px] text-white"
      >
        {t('profileNotice.choose')}
      </button>
      <button type="button" onClick={close} aria-label={t('profileNotice.dismiss')} className="shrink-0 p-0.5 text-text-muted hover:text-text-primary">
        <X size={14} />
      </button>
    </div>
  )
}
