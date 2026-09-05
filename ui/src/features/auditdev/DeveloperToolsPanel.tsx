import { lazy, Suspense, useState } from 'react'
import { Activity, GitBranch, Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { AuditDevPanel } from './AuditDevPanel'

const ArchitectureViewer = lazy(() => import('../architecture/ArchitectureViewer')
  .then(module => ({ default: module.ArchitectureViewer })))

type DeveloperTool = 'audit' | 'architecture'

function LazyPanelFallback() {
  const { t } = useUiTranslation('auditDev')
  return (
    <div className="flex flex-1 items-center justify-center text-text-muted">
      <Loader2 size={18} className="animate-spin" />
      <span className="ml-2 text-xs">{t('architecture.loading')}</span>
    </div>
  )
}
export function DeveloperToolsPanel() {
  const { t } = useUiTranslation('auditDev')
  const [tool, setTool] = useState<DeveloperTool>('audit')
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div role="tablist" aria-label={t('developerTools')} className="flex shrink-0 gap-1 rounded-lg border border-border bg-bg-secondary/50 p-1">
        <button
          type="button"
          role="tab"
          aria-selected={tool === 'audit'}
          onClick={() => setTool('audit')}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-text-secondary aria-selected:bg-bg-hover aria-selected:text-text-primary"
        >
          <Activity size={14} />{t('auditTab')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tool === 'architecture'}
          onClick={() => setTool('architecture')}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-text-secondary aria-selected:bg-bg-hover aria-selected:text-text-primary"
        >
          <GitBranch size={14} />{t('architectureTab')}
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {tool === 'audit' ? <AuditDevPanel /> : <Suspense fallback={<LazyPanelFallback />}><ArchitectureViewer /></Suspense>}
      </div>
    </div>
  )
}
