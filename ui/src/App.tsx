import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { Menu, Settings } from 'lucide-react'
import { WizardSidebar } from './components/Sidebar/WizardSidebar'
import { WorkspaceEventBridge } from './components/Sidebar/WorkspaceEventBridge'
import { MainContent } from './components/MainContent/MainContent'
import { LoraBrowser } from './components/LoraBrowser/LoraBrowser'
import { StorageDashboard } from './components/StorageDashboard/StorageDashboard'
import { RetakeDialog } from './components/RetakeDialog'
import { OomRecoveryBanner } from './components/OomRecoveryBanner'
import { DownloadStatusBanner } from './components/DownloadStatusBanner'
import { PreflightBanner } from './components/PreflightBanner'
import { PlatformModeBanner } from './components/PlatformModeBanner'
import { ActivityFooter } from './components/ActivityFooter'
import { GalleryReadyToast } from './components/MainContent/GalleryReadyToast'
import { WelcomeModal } from './components/WelcomeModal'
import { QueueRecoveryDialog } from './components/QueueRecoveryDialog'
import { RecipesOverlay } from './components/Recipes/RecipesOverlay'
import { BrandIdentity } from './components/BrandIdentity'
import { HocusPocusIntro } from './components/HocusPocusIntro'
import { LanAuthGate } from './components/LanAuthGate'
import { ExecutionModeBanner } from './components/ExecutionModeBanner'
import { SeriesNativeBatchBanner } from './features/series/SeriesNativeBatchBanner'
import { catalogFromOutputs, GenerationInspectorHost } from './features/generation-inspector'
import { useStore } from './stores/useStore'
import { useIsMobile } from './lib/useIsMobile'

// Productions is an overlay opened on demand. Keep its sizeable workflow
// code out of the initial route and load it only on the first open.
const DirectorDashboard = lazy(() => import('./components/DirectorDashboard/DirectorDashboard').then(module => ({
  default: module.DirectorDashboard,
})))

// Settings is a drawer that boots closed, and the two panels behind it are
// the largest thing in the app that nobody sees on load — hardware and
// service configuration, plus the theme catalogue. Loading it on first open
// keeps all of that out of the initial chunk. The open event is handled by
// WorkspaceEventBridge (always mounted) and lands in the store. Direct
// generation only mounts while that workspace is visible, so the listener
// cannot live there.
const SettingsDrawer = lazy(() => import('./components/SettingsDrawer/SettingsDrawer').then(module => ({
  default: module.SettingsDrawer,
})))

export function LazySettingsDrawer({ open }: { open: boolean }) {
  // Loads on the first open and then stays mounted. The drawer slides itself
  // with a transform driven by the store, so unmounting it on close would
  // throw that transition away on every subsequent open. The first open is
  // the one that appears without the slide, which is the price of not
  // shipping the panel to people who never open it.
  // Adjusted during render rather than in an effect: React re-renders on the
  // spot without committing, so the drawer appears on the same open, and no
  // cascading-render lint rule is tripped.
  const [everOpened, setEverOpened] = useState(false)
  if (open && !everOpened) setEverOpened(true)
  if (!everOpened) return null
  return <Suspense fallback={<div role="status" className="sr-only">Loading settings…</div>}>
    <SettingsDrawer />
  </Suspense>
}

export function LazyDirectorOverlay({ open }: { open: boolean }) {
  if (!open) return null
  return <Suspense fallback={<div role="status" className="sr-only">Loading video workflows…</div>}>
    <DirectorDashboard />
  </Suspense>
}

function AppContent() {
  const [introComplete, setIntroComplete] = useState(false)
  const completeIntro = useCallback(() => setIntroComplete(true), [])
  const loadModels = useStore(s => s.loadModels)
  const loadOutputs = useStore(s => s.loadOutputs)
  const maybeRefreshGallery = useStore(s => s.maybeRefreshGallery)
  const loadWorkspaces = useStore(s => s.loadWorkspaces)
  const reconnectJobs = useStore(s => s.reconnectJobs)
  const reconnectDirectorPipelines = useStore(s => s.reconnectDirectorPipelines)
  const loadSystemConfig = useStore(s => s.loadSystemConfig)
  const loadServicesConfig = useStore(s => s.loadServicesConfig)
  const loadProductionProfile = useStore(s => s.loadProductionProfile)
  const loadLlmStatus = useStore(s => s.loadLlmStatus)
  const loadLlmModels = useStore(s => s.loadLlmModels)
  const servicesConfig = useStore(s => s.servicesConfig)
  const dashboardOpen = useStore(s => s.dashboardOpen)
  const settingsOpen = useStore(s => s.settingsOpen)
  const runtimeIdentity = useStore(s => s.systemStats?.runtime)
  const toggleSettings = useStore(s => s.toggleSettings)
  const appVersion = useStore(s => s.systemConfig?.app_version)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const outputs = useStore(s => s.outputs)
  const params = useStore(s => s.params)
  const isMobile = useIsMobile()

  useEffect(() => {
    loadModels()
    loadWorkspaces()
    loadOutputs()
    loadSystemConfig()
    loadServicesConfig()
    loadProductionProfile()
    loadLlmStatus()
    loadLlmModels()
    reconnectJobs()
    reconnectDirectorPipelines()
  }, [loadModels, loadWorkspaces, loadOutputs, loadSystemConfig, loadServicesConfig, loadProductionProfile, loadLlmStatus, loadLlmModels, reconnectJobs, reconnectDirectorPipelines])

  // Keep the output library live even when a job was submitted by another
  // tab, restored after a browser restart, or its terminal poll was missed.
  // Incremental refresh only reads the newest page and does not disturb the
  // output the user is currently viewing.
  useEffect(() => {
    let inFlight = false
    const refresh = async () => {
      if (document.hidden || inFlight) return
      inFlight = true
      try {
        await maybeRefreshGallery()
      } finally {
        inFlight = false
      }
    }
    const interval = window.setInterval(() => { void refresh() }, 5000)
    const onVisible = () => { if (!document.hidden) void refresh() }
    window.addEventListener('focus', onVisible)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', onVisible)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [maybeRefreshGallery])

  // Pinokio popup tabs can outlive the backend process. Reload once when the
  // server instance or the served React build changes so an old bundle cannot
  // keep mounting videos or showing stale telemetry after an update.
  useEffect(() => {
    if (!runtimeIdentity?.instance_id || !runtimeIdentity.ui_build_id) return
    const key = 'maestro_runtime_identity'
    const current = `${runtimeIdentity.instance_id}:${runtimeIdentity.ui_build_id}`
    try {
      const previous = window.sessionStorage.getItem(key)
      window.sessionStorage.setItem(key, current)
      if (previous && previous !== current) window.location.reload()
    } catch {
      // Storage may be disabled; periodic output refresh still keeps the tab
      // functional, it simply cannot auto-reload across server versions.
    }
  }, [runtimeIdentity?.instance_id, runtimeIdentity?.ui_build_id])

  // Poll LLM status to stay in sync with backend auto-load/unload
  useEffect(() => {
    let inFlight = false
    const tick = async () => {
      if (document.hidden || inFlight) return
      inFlight = true
      try {
        await loadLlmStatus()
      } finally {
        inFlight = false
      }
    }
    const interval = setInterval(() => { void tick() }, 15000)
    return () => clearInterval(interval)
  }, [loadLlmStatus])

  // Debug-only interaction journal. It records control labels/navigation,
  // never input values or keystrokes. API mutations are traced server-side.
  useEffect(() => {
    if (!servicesConfig?.debug_trace_enabled) return
    const recordControl = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      const control = target?.closest<HTMLElement>('button, a, [role="button"], [role="tab"]')
      if (!control) return
      const label = (
        control.getAttribute('aria-label')
        || control.getAttribute('title')
        || control.textContent
        || control.tagName
      ).replace(/\s+/g, ' ').trim().slice(0, 500)
      if (!label) return
      void fetch('/api/v1/debug/user-action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          control: label,
          control_type: control.getAttribute('role') || control.tagName.toLowerCase(),
          view: window.location.pathname,
        }),
      }).catch(() => undefined)
    }
    document.addEventListener('click', recordControl, true)
    return () => document.removeEventListener('click', recordControl, true)
  }, [servicesConfig?.debug_trace_enabled])

  return (
    <div className="flex flex-col h-full w-full bg-bg-primary">
      <ExecutionModeBanner />
      <SeriesNativeBatchBanner />
      {/* Mobile header */}
      {isMobile && (
        <header className="h-12 shrink-0 px-4 border-b border-border flex items-center justify-between bg-bg-secondary">
          <button
            onClick={() => window.dispatchEvent(new Event('hocuspocus:wizard-open'))}
            className="p-2 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
            aria-label="Ask to the Wizard"
          >
            <Menu size={20} />
          </button>
          <BrandIdentity appVersion={appVersion} />
          <button
            onClick={() => { toggleSettings() }}
            className="p-2 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
          >
            <Settings size={20} />
          </button>
        </header>
      )}

      <div className="flex flex-1 min-h-0 w-full">
        <WorkspaceEventBridge />
        <WizardSidebar />
        <MainContent />
      </div>
      <GalleryReadyToast />
      <ActivityFooter />
      <LazySettingsDrawer open={settingsOpen} />
      <LoraBrowser />
      <LazyDirectorOverlay open={dashboardOpen} />
      <StorageDashboard />
      <RecipesOverlay />
      <GenerationInspectorHost
        workspace={activeWorkspace}
        catalog={catalogFromOutputs(outputs || [])}
        currentModel={{ id: params.model_type }}
      />
      <RetakeDialog />
      {/* OomRecoveryBanner is a fixed-position overlay — renders nothing
          unless the latest job/pipeline failure has oom_info attached.
          Lives at the App root so it floats above whichever screen the
          user is looking at when their generation OOMs. */}
      <OomRecoveryBanner />
      {/* PreflightBanner — fixed top overlay shown once on startup if the
          environment is missing ffmpeg / CUDA or low on disk. Renders
          nothing when everything checks out. */}
      <PreflightBanner />
      <PlatformModeBanner />
      {/* DownloadStatusBanner — fixed bottom-right overlay, polls
          /api/v1/downloads/active every 2s. Renders nothing unless
          a model file is being downloaded. Highlights stalled
          downloads in amber so users know the system is recovering
          rather than frozen. */}
      <DownloadStatusBanner />
      {/* The startup mark hands over to the existing first-run / updates dialog. */}
      {introComplete && <WelcomeModal />}
      {/* Explicit choice after an interrupted Pinokio/server session. */}
      <QueueRecoveryDialog />
      {!introComplete && <HocusPocusIntro onComplete={completeIntro} version={appVersion} />}
    </div>
  )
}

function App() {
  return <LanAuthGate><AppContent /></LanAuthGate>
}

export default App
