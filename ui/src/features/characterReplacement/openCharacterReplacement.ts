import { useEffect, useMemo } from 'react'
import { useStore } from '../../stores/useStore'
import type { EditSubMode, GenerationMode, MediaFilter } from '../../types'

/** Old Estudios destination. Opening it lands in Direct generation → Edit. */
export const CHARACTER_REPLACEMENT_FILTER: MediaFilter = 'character-replacement'

export interface CharacterReplacementHost {
  generationMode: GenerationMode
  editSubMode: EditSubMode
  mediaFilter: MediaFilter
  sidebarMode: 'studio' | 'director'
  sidebarOpen: boolean
  settingsOpen: boolean
  dashboardOpen: boolean
  setGenerationMode: (mode: GenerationMode) => void
  setEditSubMode: (mode: EditSubMode, recastEngine?: 'scail' | 'viggle') => void
  setMediaFilter: (filter: MediaFilter) => void
  setSidebarMode: (mode: 'studio' | 'director') => void
  setSidebarOpen: (open: boolean) => void
  setSettingsOpen: (open: boolean) => void
  setDashboardOpen: (open: boolean) => void
}

export function characterReplacementReady(state: CharacterReplacementHost): boolean {
  return state.mediaFilter === CHARACTER_REPLACEMENT_FILTER
    && state.generationMode === 'avatar'
    && state.editSubMode === 'replace_character'
    && state.sidebarMode === 'studio'
    && state.sidebarOpen
    && !state.settingsOpen
    && !state.dashboardOpen
}

/** One destination for the UI, the Wizard and a saved `character-replacement` filter. */
export function openCharacterReplacement(state: CharacterReplacementHost): void {
  if (characterReplacementReady(state)) return
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  if (state.generationMode !== 'avatar') state.setGenerationMode('avatar')
  if (state.editSubMode !== 'replace_character') state.setEditSubMode('replace_character')
  if (state.sidebarMode !== 'studio') state.setSidebarMode('studio')
  if (!state.sidebarOpen) state.setSidebarOpen(true)
  if (state.mediaFilter !== CHARACTER_REPLACEMENT_FILTER) state.setMediaFilter(CHARACTER_REPLACEMENT_FILTER)
}

export function leaveCharacterReplacement(state: CharacterReplacementHost, next: EditSubMode, recastEngine?: 'scail' | 'viggle'): void {
  const leaving = state.mediaFilter === CHARACTER_REPLACEMENT_FILTER
  state.setEditSubMode(next, recastEngine)
  if (leaving) state.setMediaFilter('avatars')
}

export function useCharacterReplacementHost(): CharacterReplacementHost {
  const generationMode = useStore(state => state.generationMode)
  const editSubMode = useStore(state => state.editSubMode)
  const mediaFilter = useStore(state => state.mediaFilter)
  const sidebarMode = useStore(state => state.sidebarMode)
  const sidebarOpen = useStore(state => state.sidebarOpen)
  const settingsOpen = useStore(state => state.settingsOpen)
  const dashboardOpen = useStore(state => state.dashboardOpen)
  const setGenerationMode = useStore(state => state.setGenerationMode)
  const setEditSubMode = useStore(state => state.setEditSubMode)
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const setSidebarMode = useStore(state => state.setSidebarMode)
  const setSidebarOpen = useStore(state => state.setSidebarOpen)
  const setSettingsOpen = useStore(state => state.setSettingsOpen)
  const setDashboardOpen = useStore(state => state.setDashboardOpen)
  return useMemo(() => ({
    generationMode, editSubMode, mediaFilter, sidebarMode, sidebarOpen, settingsOpen, dashboardOpen,
    setGenerationMode, setEditSubMode, setMediaFilter, setSidebarMode, setSidebarOpen, setSettingsOpen, setDashboardOpen,
  }), [
    generationMode, editSubMode, mediaFilter, sidebarMode, sidebarOpen, settingsOpen, dashboardOpen,
    setGenerationMode, setEditSubMode, setMediaFilter, setSidebarMode, setSidebarOpen, setSettingsOpen, setDashboardOpen,
  ])
}

/** `useStore.setState({ mediaFilter: 'character-replacement' })` skips the setter, so the screen watches the filter. */
export function useCharacterReplacementRedirect(): void {
  const host = useCharacterReplacementHost()
  const { mediaFilter, editSubMode, generationMode, sidebarMode, sidebarOpen, settingsOpen, dashboardOpen } = host
  useEffect(() => {
    if (mediaFilter !== CHARACTER_REPLACEMENT_FILTER) return
    if (characterReplacementReady(host)) return
    openCharacterReplacement(host)
  }, [host, mediaFilter, editSubMode, generationMode, sidebarMode, sidebarOpen, settingsOpen, dashboardOpen])
}
