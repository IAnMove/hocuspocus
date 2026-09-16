import { Clapperboard, ExternalLink, Loader2, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { isVideoJsExporting, type VideoJsExportState } from './useVideoJsExport.ts'

interface ExportBarProps {
  state: VideoJsExportState
  canExport: boolean
  blockedReason: string | null
  onStart: () => void
  onCancel: () => void
}

export function VideoJsExportBar({ state, canExport, blockedReason, onStart, onCancel }: ExportBarProps) {
  const { t } = useUiTranslation('videojs')
  const progress = state.phase === 'rendering' ? state.current / Math.max(1, state.total) : state.phase === 'publishing' ? 1 : 0
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-bg-secondary p-2" data-testid="videojs-export">
      {isVideoJsExporting(state) ? (
        <>
          <Loader2 size={16} className="animate-spin text-accent-blue" />
          <span className="text-xs text-text-secondary" role="status">
            {state.phase === 'rendering' ? t('export.rendering', { current: state.current, total: state.total }) : t('export.publishing')}
          </span>
          <progress value={progress} max={1} className="h-2 min-w-32 flex-1" aria-label={t('export.progress')} />
          {state.phase === 'rendering' && (
            <button type="button" onClick={onCancel} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-border px-3 text-xs text-text-primary hover:bg-bg-hover">
              <X size={14} />{t('export.cancel')}
            </button>
          )}
        </>
      ) : (
        <>
          <button type="button" disabled={!canExport} onClick={onStart}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-40">
            <Clapperboard size={16} />{t('export.start')}
          </button>
          {blockedReason && <span className="text-xs text-amber-300">{blockedReason}</span>}
          {state.phase === 'done' && (
            <a href={state.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-emerald-300 underline" data-testid="videojs-export-done">
              {t('export.done', { name: state.name })}<ExternalLink size={12} />
            </a>
          )}
          {state.phase === 'error' && <span role="alert" className="text-xs text-red-300">{t('export.failed', { message: state.message })}</span>}
        </>
      )}
    </div>
  )
}
