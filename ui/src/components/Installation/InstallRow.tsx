import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Download, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { InstallComponent, InstallState, InstallStatus } from '../../api/installManager'
import { formatBytes } from '../../lib/format'
import { exceedsFreeSpace, finishedNotice, rowActions, sizeLabel } from '../../lib/installView'
import { InstallOutput } from './InstallOutput'
import type { InstallAction } from './useInstallManager'

const CONFIRM_WINDOW_MS = 4000

const BADGE: Record<InstallState, string> = {
  installed: 'bg-green-500/15 text-green-400',
  needs_update: 'bg-indicator-warning/15 text-indicator-warning',
  running: 'bg-accent-blue/15 text-accent-blue',
  not_installed: 'bg-bg-tertiary text-text-muted',
  unsupported: 'bg-bg-tertiary text-text-muted',
}

interface Props {
  row: InstallComponent
  status: InstallStatus
  acting: boolean
  onAct: (id: string, action: InstallAction) => Promise<void>
}

export function InstallRow({ row, status, acting, onAct }: Props) {
  const { t } = useUiTranslation('settings')
  const [confirming, setConfirming] = useState(false)
  const [showOutput, setShowOutput] = useState(false)
  const actions = rowActions(row, status)
  const size = sizeLabel(row)
  const notice = finishedNotice(row)
  const running = row.state === 'running'
  const disabled = acting || actions.blockedBy !== null

  useEffect(() => {
    if (!confirming) return undefined
    const timer = setTimeout(() => setConfirming(false), CONFIRM_WINDOW_MS)
    return () => clearTimeout(timer)
  }, [confirming])

  const sizeText = size.kind === 'measuring'
    ? t('installation.measuring')
    : size.kind === 'estimated'
      ? t('installation.estimated', { size: formatBytes(size.bytes ?? 0) })
      : formatBytes(size.bytes ?? 0)
  const title = t(`installation.components.${row.id}.title`, { defaultValue: row.title })
  const summary = t(`installation.components.${row.id}.summary`, { defaultValue: row.summary })

  const uninstall = async () => {
    if (!confirming) { setConfirming(true); return }
    setConfirming(false)
    await onAct(row.id, 'uninstall')
  }

  return (
    <div className="rounded-lg border border-border p-3 space-y-1.5" data-testid={`install-row-${row.id}`}>
      <div className="flex items-start gap-2">
        <span className="flex-1 min-w-0 text-xs font-medium text-text-primary">{title}</span>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${BADGE[row.state]}`}>
          {running ? <Loader2 size={9} className="inline animate-spin mr-1" /> : null}
          {t(`installation.state.${row.state}`)}
        </span>
      </div>
      <p className="text-[11px] leading-snug text-text-secondary">{summary}</p>
      <div className="text-[10px] text-text-muted tabular-nums">{sizeText}</div>

      {row.state === 'unsupported' && row.reason && (
        <p className="text-[10px] text-text-muted">{row.reason}</p>
      )}
      {exceedsFreeSpace(row, status.disk.freeBytes) && (
        <p className="flex items-center gap-1 text-[10px] text-indicator-warning">
          <AlertTriangle size={10} />
          {t('installation.lowSpace', { size: formatBytes(row.estimatedBytes), free: formatBytes(status.disk.freeBytes) })}
        </p>
      )}
      {running && (
        <p className="text-[10px] text-text-secondary">
          {t(row.job?.kind === 'uninstall' ? 'installation.removing' : 'installation.installing')}
        </p>
      )}
      {notice === 'installed' && (
        <p className="flex items-center gap-1 text-[10px] text-green-400">
          <Check size={10} />
          {t(row.restartRequired ? 'installation.installedRestart' : 'installation.installedReady')}
        </p>
      )}
      {notice === 'removed' && <p className="text-[10px] text-text-muted">{t('installation.removed')}</p>}
      {notice === 'failed' && row.job && (
        <p className="flex items-start gap-1 text-[10px] text-red-400">
          <AlertTriangle size={10} className="mt-px shrink-0" />
          {t(`installation.failure.${row.job.code ?? 'unknown'}`, { defaultValue: row.job.message ?? t('installation.failure.unknown') })}
        </p>
      )}

      {(actions.primary || actions.canUninstall) && (
        <div className="flex items-center gap-2 pt-0.5">
          {actions.primary && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => onAct(row.id, 'install')}
              className="flex items-center gap-1 rounded border border-accent-blue/50 px-2 py-1 text-[11px] text-accent-blue transition-colors hover:bg-accent-blue/10 disabled:opacity-40"
            >
              {acting ? <Loader2 size={11} className="animate-spin" /> : actions.primary === 'update' ? <RefreshCw size={11} /> : <Download size={11} />}
              {t(actions.primary === 'update' ? 'installation.update' : 'installation.install')}
            </button>
          )}
          {actions.canUninstall && (
            <button
              type="button"
              disabled={acting || status.busy !== null}
              onClick={uninstall}
              className={`ml-auto flex items-center gap-1 rounded border px-2 py-1 text-[11px] transition-colors disabled:opacity-40 ${
                confirming
                  ? 'border-red-500/50 bg-red-500/20 text-red-400'
                  : 'border-border text-text-muted hover:border-red-500/40 hover:text-red-400'
              }`}
            >
              <Trash2 size={11} />
              {confirming ? t('installation.confirmUninstall', { size: formatBytes(row.sizeBytes ?? row.estimatedBytes) }) : t('installation.uninstall')}
            </button>
          )}
        </div>
      )}

      {(running || notice === 'failed') && (
        <>
          <button
            type="button"
            onClick={() => setShowOutput(open => !open)}
            className="text-[10px] text-text-muted underline hover:text-text-primary"
          >
            {t(showOutput || running ? 'installation.hideOutput' : 'installation.showOutput')}
          </button>
          {(showOutput || running) && <InstallOutput id={row.id} running={running} />}
        </>
      )}
    </div>
  )
}
