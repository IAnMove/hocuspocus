import { HardDrive } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { formatBytes } from '../../lib/format'
import { InstallRow } from './InstallRow'
import { useInstallManager } from './useInstallManager'

/** Settings > Installation: what is installed, what could be, and one-click add or remove. */
export function InstallationPanel() {
  const { t } = useUiTranslation('settings')
  const open = useStore(s => s.settingsOpen)
  const setStorageOpen = useStore(s => s.setStorageDashboardOpen)
  const { status, error, actingId, act } = useInstallManager(open)

  return (
    <div className="space-y-4">
      <p className="text-[11px] leading-snug text-text-secondary">{t('installation.intro')}</p>
      {error && <p className="rounded border border-red-500/40 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-400">{error}</p>}
      {!status && !error && <p className="text-xs text-text-muted">{t('installation.loading')}</p>}

      {status && (
        <>
          <div className="flex items-center justify-between text-[10px] text-text-muted">
            <span>{t('installation.freeSpace', { free: formatBytes(status.disk.freeBytes), total: formatBytes(status.disk.totalBytes) })}</span>
          </div>
          {!status.launcher.available && (
            <p className="rounded border border-border bg-bg-tertiary px-2 py-1.5 text-[11px] leading-snug text-text-secondary">
              {t(`installation.launcher.${status.launcher.reason ?? 'no_pterm'}`)}
            </p>
          )}
          {status.busy && (
            <p className="rounded border border-accent-blue/40 bg-accent-blue/10 px-2 py-1.5 text-[11px] text-accent-blue">
              {t('installation.keepOpen')}
            </p>
          )}
          <div className="rounded-lg border border-border p-3 space-y-1">
            <div className="flex items-start gap-2">
              <span className="flex-1 text-xs font-medium text-text-primary">{t('installation.base.title')}</span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] ${status.base.installed ? 'bg-green-500/15 text-green-400' : 'bg-indicator-warning/15 text-indicator-warning'}`}>{t(`installation.state.${status.base.state}`)}</span>
            </div>
            <p className="text-[11px] leading-snug text-text-secondary">{t('installation.base.summary')}</p>
            {!status.base.installed && <p className="text-[10px] text-indicator-warning">{t('installation.base.updateHint')}</p>}
            <div className="text-[10px] text-text-muted tabular-nums">
              {status.base.sizeBytes === null ? t('installation.measuring') : formatBytes(status.base.sizeBytes)}
            </div>
          </div>
          {status.components.map(row => (
            <InstallRow key={row.id} row={row} status={status} acting={actingId === row.id} onAct={act} />
          ))}
        </>
      )}

      <hr className="border-border" />
      <button
        type="button"
        onClick={() => setStorageOpen(true)}
        className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs text-text-secondary transition-colors hover:border-border-light hover:text-text-primary"
      >
        <HardDrive size={13} className="text-accent-blue" />
        <span className="flex-1 text-left">{t('installation.storageManager')}</span>
        <span className="text-[10px] text-text-muted">{t('installation.storageHint')}</span>
      </button>
    </div>
  )
}
