import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { InstallComponent, InstallState, InstallStatus } from '../../api/installManager'
import { formatBytes } from '../../lib/format'
import { finishedNotice, reclaimLabel, sizeLabel } from '../../lib/installView'
import { InstallOutput } from './InstallOutput'
import { InstallRowActions } from './InstallRowActions'
import { InstallRowNotices } from './InstallRowNotices'
import type { InstallAction } from './useInstallManager'

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

function SizeText({ row }: { row: InstallComponent }) {
  const { t } = useUiTranslation('settings')
  const size = sizeLabel(row)
  if (size.kind === 'measuring') return <>{t('installation.measuring')}</>
  if (size.kind === 'estimated') return <>{t('installation.estimated', { size: formatBytes(size.bytes ?? 0) })}</>
  return <>{formatBytes(size.bytes ?? 0)}</>
}

/** Removing frees less than the folder size when uv linked its packages from Pinokio's shared cache. */
function ReclaimHint({ row }: { row: InstallComponent }) {
  const { t } = useUiTranslation('settings')
  const reclaim = reclaimLabel(row)
  if (!reclaim?.mostlyShared || reclaim.bytes === null) return null
  return <p className="text-[10px] leading-snug text-text-muted">{t('installation.reclaimHint', { size: formatBytes(reclaim.bytes) })}</p>
}

/** The installer's terminal: always visible while it runs, on request after a failure. */
function OutputToggle({ row }: { row: InstallComponent }) {
  const { t } = useUiTranslation('settings')
  const [shown, setShown] = useState(false)
  const running = row.state === 'running'
  if (!running && finishedNotice(row) !== 'failed') return null
  return (
    <>
      <button type="button" onClick={() => setShown(open => !open)} className="text-[10px] text-text-muted underline hover:text-text-primary">
        {t(shown || running ? 'installation.hideOutput' : 'installation.showOutput')}
      </button>
      {(shown || running) && <InstallOutput id={row.id} running={running} />}
    </>
  )
}

/** One optional component: what it is, its state and size, and what can be done with it. */
export function InstallRow({ row, status, acting, onAct }: Props) {
  const { t } = useUiTranslation('settings')
  return (
    <div className="rounded-lg border border-border p-3 space-y-1.5" data-testid={`install-row-${row.id}`}>
      <div className="flex items-start gap-2">
        <span className="flex-1 min-w-0 text-xs font-medium text-text-primary">
          {t(`installation.components.${row.id}.title`, { defaultValue: row.title })}
        </span>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${BADGE[row.state]}`}>
          {row.state === 'running' && <Loader2 size={9} className="inline animate-spin mr-1" />}
          {t(`installation.state.${row.state}`)}
        </span>
      </div>
      <p className="text-[11px] leading-snug text-text-secondary">
        {t(`installation.components.${row.id}.summary`, { defaultValue: row.summary })}
      </p>
      <div className="text-[10px] text-text-muted tabular-nums"><SizeText row={row} /></div>
      <ReclaimHint row={row} />
      <InstallRowNotices row={row} freeBytes={status.disk.freeBytes} />
      <InstallRowActions row={row} status={status} acting={acting} onAct={onAct} />
      <OutputToggle row={row} />
    </div>
  )
}
