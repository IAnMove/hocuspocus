import { useCallback, useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import { fetchAbout, type AboutInfo } from '../api/about'
import { useStore } from '../stores/useStore'
import { BUNDLE_COMMIT, buildState, shortCommit } from '../lib/buildIdentity'
import { AboutDialog } from './AboutDialog'

export const ABOUT_OPEN_EVENT = 'hocuspocus:about-open'

/** Tiny deployed-commit tag from the polled runtime identity; opens the About dialog. */
export function BuildBadge() {
  const { t } = useUiTranslation('common')
  const runtime = useStore(state => state.systemStats?.runtime)
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [error, setError] = useState(false)
  const [open, setOpen] = useState(false)

  const show = useCallback(() => {
    setOpen(true)
    fetchAbout().then(info => { setAbout(info); setError(false) }).catch(() => setError(true))
  }, [])
  useEffect(() => {
    window.addEventListener(ABOUT_OPEN_EVENT, show)
    return () => window.removeEventListener(ABOUT_OPEN_EVENT, show)
  }, [show])

  const state = buildState(runtime ? { backend: { commit: runtime.commit }, ui: { commit: runtime.ui_commit } } : null)
  const label = shortCommit(runtime?.commit) || shortCommit(BUNDLE_COMMIT)
  const warn = state === 'reload' || state === 'rebuild'
  return <>
    <button type="button" onClick={show} title={warn ? t(`about.state.${state}`) : t('about.open')} aria-label={t('about.open')}
      className={`ml-auto inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[9px] leading-none hover:bg-bg-hover ${warn ? 'text-amber-300' : 'text-text-muted hover:text-text-secondary'}`}>
      <Info size={10} aria-hidden />{warn ? '⚠ ' : ''}{label}
    </button>
    {open && <AboutDialog about={about} error={error} onClose={() => setOpen(false)} />}
  </>
}
