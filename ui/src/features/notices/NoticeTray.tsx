import { useEffect, useId, useState } from 'react'
import { useSyncExternalStore } from 'react'
import { Bell } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { PreflightBanner } from '../../components/PreflightBanner'
import { ProductionProfileNotice } from '../../components/ProductionProfileNotice'
import {
  loadPreflight,
  preflightRevision,
  subscribePreflight,
  visiblePreflightChecks,
} from './preflightNotices'
import {
  isProfileNoticeVisible,
  profileNoticeRevision,
  profileNoticeSignature,
  subscribeProfileNotice,
} from './profileNoticeState'

function useNoticeCount() {
  const preflight = useSyncExternalStore(subscribePreflight, preflightRevision, preflightRevision)
  const profile = useSyncExternalStore(subscribeProfileNotice, profileNoticeRevision, profileNoticeRevision)
  const loaded = useStore(state => state.productionProfileLoaded)
  const configured = useStore(state => state.productionProfileConfigured)
  const invalidReason = useStore(state => state.productionProfileInvalidReason)
  const productionProfile = useStore(state => state.productionProfile)
  void preflight
  void profile
  const signature = profileNoticeSignature(invalidReason, productionProfile)
  const profileOn = isProfileNoticeVisible(loaded, configured, signature)
  return visiblePreflightChecks().length + (profileOn ? 1 : 0)
}

/** Bell in the top bar. Notices that used to cover the navigation live here. */
export function NoticeTray() {
  const { t } = useUiTranslation('shell')
  const count = useNoticeCount()
  const [open, setOpen] = useState(false)
  const panelId = useId()

  useEffect(() => { void loadPreflight() }, [])

  useEffect(() => {
    if (!open) return undefined
    const close = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Element)) return
      if (target.closest('[data-testid="notice-tray"]')) return
      setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const label = count > 0 ? t('notices.bellCount', { count }) : t('notices.bell')

  return (
    <div className="relative shrink-0" data-testid="notice-tray">
      <button
        type="button"
        className="relative rounded-lg p-1.5 text-text-muted hover:bg-bg-hover hover:text-text-secondary"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={label}
        title={label}
        data-testid="notice-tray-button"
        onClick={() => setOpen(value => !value)}
      >
        <Bell size={14} />
        {count > 0 && (
          <span
            data-testid="notice-tray-count"
            className="absolute -right-1 -top-1 min-w-4 rounded-full bg-red-500 px-1 text-center text-[9px] font-semibold leading-4 text-white tabular-nums"
          >
            {count}
          </span>
        )}
      </button>
      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label={t('notices.bell')}
          data-testid="notice-tray-panel"
          className="absolute right-0 top-full z-50 mt-1 w-80 max-w-[80vw] space-y-2 rounded-lg border border-border bg-bg-secondary p-2 shadow-xl"
        >
          <PreflightBanner />
          <ProductionProfileNotice />
          {count === 0 && <p className="px-1 py-2 text-xs text-text-muted">{t('notices.empty')}</p>}
        </div>
      )}
    </div>
  )
}
