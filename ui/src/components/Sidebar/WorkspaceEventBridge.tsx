import { useEffect } from 'react'
import { useStore } from '../../stores/useStore'
import { revealDirectorWorkspace } from '../../lib/navigationCategories'

function setToolsSidebarCollapsed(collapsed: boolean) {
  window.localStorage.setItem('hocuspocus-tools-sidebar-collapsed', String(collapsed))
}

/** Always-mounted host for navigation events. Direct generation and Director
 *  only mount while their workspace is visible, so these listeners cannot
 *  live in those panels. */
export function WorkspaceEventBridge() {
  const setSidebarOpen = useStore(s => s.setSidebarOpen)
  const setSidebarMode = useStore(s => s.setSidebarMode)
  const setSettingsOpen = useStore(s => s.setSettingsOpen)
  const setDashboardOpen = useStore(s => s.setDashboardOpen)

  useEffect(() => {
    const openImageSubmission = () => {
      setToolsSidebarCollapsed(false)
      setSidebarOpen(true)
    }
    const openSpeechSubmission = () => {
      setToolsSidebarCollapsed(false)
      setSidebarOpen(true)
    }
    window.addEventListener('hocuspocus:studio-image-open', openImageSubmission)
    window.addEventListener('hocuspocus:studio-speech-open', openSpeechSubmission)
    return () => {
      window.removeEventListener('hocuspocus:studio-image-open', openImageSubmission)
      window.removeEventListener('hocuspocus:studio-speech-open', openSpeechSubmission)
    }
  }, [setSidebarOpen])

  useEffect(() => {
    const openStudio = () => {
      setSidebarMode('studio')
      setToolsSidebarCollapsed(false)
      setSidebarOpen(true)
    }
    const openSettings = () => {
      setDashboardOpen(false)
      setSidebarOpen(false)
      setSettingsOpen(true)
    }
    const openDirector = () => {
      revealDirectorWorkspace(useStore.getState())
      setToolsSidebarCollapsed(false)
    }
    window.addEventListener('hocuspocus:studio-open', openStudio)
    window.addEventListener('hocuspocus:settings-open', openSettings)
    window.addEventListener('maestro:director-open', openDirector)
    return () => {
      window.removeEventListener('hocuspocus:studio-open', openStudio)
      window.removeEventListener('hocuspocus:settings-open', openSettings)
      window.removeEventListener('maestro:director-open', openDirector)
    }
  }, [setDashboardOpen, setSettingsOpen, setSidebarMode, setSidebarOpen])

  return null
}
