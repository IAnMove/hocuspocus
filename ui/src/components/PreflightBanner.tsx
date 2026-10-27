import { useEffect } from 'react'
import { useSyncExternalStore } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import { preflightText } from './preflightCopy'
import {
  dismissPreflight,
  loadPreflight,
  preflightRevision,
  subscribePreflight,
  visiblePreflightChecks,
} from '../features/notices/preflightNotices'

/**
 * Environment checks (ffmpeg, CUDA, disk, torch). The CUDA row cannot be
 * dismissed. The others share the old session dismissal.
 */
export function PreflightBanner() {
  const { t } = useUiTranslation('shell')
  const revision = useSyncExternalStore(subscribePreflight, preflightRevision, preflightRevision)
  useEffect(() => { void loadPreflight() }, [])
  const checks = visiblePreflightChecks()
  void revision
  if (checks.length === 0) return null

  return (
    <div className="space-y-2" data-testid="preflight-notices">
      {checks.map(check => {
        const cuda = check.id === 'cuda'
        const error = check.level === 'error'
        return (
          <div
            key={check.id}
            data-testid={`preflight-notice-${check.id}`}
            className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 ${
              error ? 'border-red-500/40 bg-red-500/15' : 'border-amber-500/40 bg-amber-500/15'
            }`}
          >
            <AlertTriangle
              size={15}
              className={`mt-0.5 shrink-0 ${error ? 'text-chip-red' : 'text-indicator-warning'}`}
            />
            <p className="min-w-0 flex-1 text-[11px] leading-snug text-text-primary">{preflightText(check)}</p>
            {!cuda && (
              <button
                type="button"
                onClick={() => dismissPreflight()}
                className="shrink-0 rounded p-0.5 text-text-muted hover:text-text-primary"
                aria-label={t('preflight.dismiss')}
              >
                <X size={13} />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
