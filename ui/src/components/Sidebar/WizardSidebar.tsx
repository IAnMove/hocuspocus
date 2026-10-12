import { lazy, Suspense, useEffect, useState } from 'react'
import { PanelLeftOpen } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useCanonicalTaskFeed } from '../../features/activity/canonicalTaskFeed'
import { AgentAvatar } from '../../features/agent/AgentAvatar'
import { useIsMobile } from '../../lib/useIsMobile'
import { safeStorageGet, safeStorageSet } from '../../lib/safeStorage'

const AgentAssistantPanel = lazy(() =>
  import('../../features/agent/AgentAssistantPanel').then(module => ({ default: module.AgentAssistantPanel })),
)

export function WizardSidebar() {
  const [collapsed, setCollapsed] = useState(() =>
    safeStorageGet('local', 'hocuspocus-wizard-sidebar-collapsed') === 'true')
  const workspace = useStore(state => state.activeWorkspace)
  const tasks = useCanonicalTaskFeed()
  const isMobile = useIsMobile()

  const setWizardCollapsed = (next: boolean) => {
    setCollapsed(next)
    safeStorageSet('local', 'hocuspocus-wizard-sidebar-collapsed', String(next))
  }

  useEffect(() => {
    const open = () => setWizardCollapsed(false)
    window.addEventListener('hocuspocus:wizard-open', open)
    return () => window.removeEventListener('hocuspocus:wizard-open', open)
  }, [])

  if (isMobile) {
    if (collapsed) {
      return (
        <button type="button" onClick={() => setWizardCollapsed(false)} className="fixed left-0 top-24 z-40 flex items-center gap-1 rounded-r-xl border border-l-0 border-wizard-soft/20 bg-wizard-ground px-2 py-2 text-[9px] text-wizard-pale shadow-xl" aria-label="Expand Ask to the Wizard">
          <AgentAvatar state="idle" size={24} /> Wizard
        </button>
      )
    }
    return (
      <>
        <button type="button" className="fixed inset-0 z-[54] bg-black/60" onClick={() => setWizardCollapsed(true)} aria-label="Close Wizard backdrop" />
        <aside className="fixed inset-y-0 left-0 z-[55] w-[min(25rem,88vw)] border-r border-wizard-soft/15 bg-wizard-ground">
          <Suspense fallback={<div className="flex h-full items-center justify-center text-xs text-wizard-pale/50">Opening the Wizard…</div>}>
            <AgentAssistantPanel workspace={workspace} tasks={tasks} onClose={() => setWizardCollapsed(true)} embedded />
          </Suspense>
        </aside>
      </>
    )
  }

  if (collapsed) {
    return (
      <aside className="flex h-full w-11 shrink-0 flex-col items-center border-r border-wizard-soft/15 bg-wizard-ground">
        <button type="button" onClick={() => setWizardCollapsed(false)} className="m-1.5 rounded-lg p-2 text-wizard-pale/70 hover:bg-wizard-pale/10 hover:text-wizard-lit" title="Expand Ask to the Wizard" aria-label="Expand Ask to the Wizard">
          <PanelLeftOpen size={17} />
        </button>
        <AgentAvatar state="idle" size={26} />
        <span className="mt-3 text-[9px] uppercase tracking-[0.2em] text-wizard-pale/45 [writing-mode:vertical-rl]">Ask to the Wizard</span>
      </aside>
    )
  }

  return (
    <aside className="h-full w-[360px] shrink-0 border-r border-wizard-soft/15 bg-wizard-ground">
      <Suspense fallback={<div className="flex h-full items-center justify-center text-xs text-wizard-pale/50">Opening the Wizard…</div>}>
        <AgentAssistantPanel workspace={workspace} tasks={tasks} onClose={() => setWizardCollapsed(true)} embedded />
      </Suspense>
    </aside>
  )
}
