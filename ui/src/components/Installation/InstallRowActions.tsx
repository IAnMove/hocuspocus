import { useEffect, useState } from 'react'
import { Download, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { InstallComponent, InstallStatus } from '../../api/installManager'
import { formatBytes } from '../../lib/format'
import { reclaimLabel, rowActions } from '../../lib/installView'
import type { InstallAction } from './useInstallManager'

const CONFIRM_WINDOW_MS = 4000

interface Props {
  row: InstallComponent
  status: InstallStatus
  acting: boolean
  onAct: (id: string, action: InstallAction) => Promise<void>
}

function PrimaryButton({ row, kind, disabled, acting, onAct }: {
  row: InstallComponent
  kind: 'install' | 'update'
  disabled: boolean
  acting: boolean
  onAct: Props['onAct']
}) {
  const { t } = useUiTranslation('settings')
  const Icon = kind === 'update' ? RefreshCw : Download
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onAct(row.id, 'install')}
      className="flex items-center gap-1 rounded border border-accent-blue/50 px-2 py-1 text-[11px] text-accent-blue transition-colors hover:bg-accent-blue/10 disabled:opacity-40"
    >
      {acting ? <Loader2 size={11} className="animate-spin" /> : <Icon size={11} />}
      {t(kind === 'update' ? 'installation.update' : 'installation.install')}
    </button>
  )
}

/** Install or update, and a two-click remove: the first click only asks, the second deletes. */
export function InstallRowActions({ row, status, acting, onAct }: Props) {
  const { t } = useUiTranslation('settings')
  const [confirming, setConfirming] = useState(false)
  const actions = rowActions(row, status)
  const freed = reclaimLabel(row)?.bytes ?? null

  useEffect(() => {
    if (!confirming) return undefined
    const timer = setTimeout(() => setConfirming(false), CONFIRM_WINDOW_MS)
    return () => clearTimeout(timer)
  }, [confirming])

  if (!actions.primary && !actions.canUninstall) return null

  const remove = async () => {
    if (!confirming) { setConfirming(true); return }
    setConfirming(false)
    await onAct(row.id, 'uninstall')
  }
  const removeStyle = confirming
    ? 'border-red-500/50 bg-red-500/20 text-red-400'
    : 'border-border text-text-muted hover:border-red-500/40 hover:text-red-400'

  return (
    <div className="flex items-center gap-2 pt-0.5">
      {actions.primary && (
        <PrimaryButton row={row} kind={actions.primary} disabled={acting || actions.blockedBy !== null} acting={acting} onAct={onAct} />
      )}
      {actions.canUninstall && (
        <button
          type="button"
          disabled={acting || status.busy !== null}
          onClick={remove}
          className={`ml-auto flex items-center gap-1 rounded border px-2 py-1 text-[11px] transition-colors disabled:opacity-40 ${removeStyle}`}
        >
          <Trash2 size={11} />
          {confirming ? (freed === null ? t('installation.confirmUninstallUnknown') : t('installation.confirmUninstall', { size: formatBytes(freed) })) : t('installation.uninstall')}
        </button>
      )}
    </div>
  )
}
