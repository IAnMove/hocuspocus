import { useStore } from '../../stores/useStore'

export {
  boundedDuration,
  creativeCharacters,
  creativeLocations,
  explicitMusicLanguage,
  normalizeName,
  outlineBeats,
} from '../../lib/labHelpers'
export type { CreativeCharacter, CreativeLocation } from '../../lib/labHelpers'

export function showLab(filter: 'stories' | 'series'): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter(filter)
  state.setSidebarOpen(false)
}
