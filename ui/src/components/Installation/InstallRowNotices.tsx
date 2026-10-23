import { AlertTriangle, Check } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { InstallComponent } from '../../api/installManager'
import { formatBytes } from '../../lib/format'
import { exceedsFreeSpace, finishedNotice } from '../../lib/installView'

interface Props {
  row: InstallComponent
  freeBytes: number
}

function Failure({ row }: { row: InstallComponent }) {
  const { t } = useUiTranslation('settings')
  if (!row.job) return null
  return (
    <p className="flex items-start gap-1 text-[10px] text-red-400">
      <AlertTriangle size={10} className="mt-px shrink-0" />
      {t(`installation.failure.${row.job.code ?? 'unknown'}`, { defaultValue: row.job.message ?? t('installation.failure.unknown') })}
    </p>
  )
}

function Finished({ row }: { row: InstallComponent }) {
  const { t } = useUiTranslation('settings')
  const notice = finishedNotice(row)
  if (notice === 'failed') return <Failure row={row} />
  if (notice === 'removed') return <p className="text-[10px] text-text-muted">{t('installation.removed')}</p>
  if (notice !== 'installed') return null
  return (
    <p className="flex items-center gap-1 text-[10px] text-green-400">
      <Check size={10} />
      {t(row.restartRequired ? 'installation.installedRestart' : 'installation.installedReady')}
    </p>
  )
}

/** Everything a row says about itself besides its title: why unavailable, low disk, progress, outcome. */
export function InstallRowNotices({ row, freeBytes }: Props) {
  const { t } = useUiTranslation('settings')
  return (
    <>
      {row.state === 'unsupported' && row.reason && <p className="text-[10px] text-text-muted">{row.reason}</p>}
      {exceedsFreeSpace(row, freeBytes) && (
        <p className="flex items-center gap-1 text-[10px] text-indicator-warning">
          <AlertTriangle size={10} />
          {t('installation.lowSpace', { size: formatBytes(row.estimatedBytes), free: formatBytes(freeBytes) })}
        </p>
      )}
      {row.state === 'running' && (
        <p className="text-[10px] text-text-secondary">
          {t(row.job?.kind === 'uninstall' ? 'installation.removing' : 'installation.installing')}
        </p>
      )}
      <Finished row={row} />
    </>
  )
}
