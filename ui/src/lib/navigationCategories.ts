import type { MediaFilter } from '../types'

export const NAVIGATION_CATEGORIES = [
  'direct-generation', 'studios', 'production', 'media',
] as const

export type NavigationCategory = typeof NAVIGATION_CATEGORIES[number]

const STUDIOS = new Set<MediaFilter>([
  'stories', 'series', 'comics', 'scene3d', 'animate3d', 'characters',
])
const PRODUCTION = new Set<MediaFilter>(['videoeditor'])
const MEDIA = new Set<MediaFilter>([
  'all', 'assets', 'projects', 'images', 'videos', 'videoclips', 'trailers',
  'series_episodes', 'audio', 'model3d', 'scenes', 'styles', 'avatars',
  'multiclip', 'favorites', 'auditdev',
])

export function categoryForMediaFilter(filter: MediaFilter): NavigationCategory | null {
  if (STUDIOS.has(filter)) return 'studios'
  if (PRODUCTION.has(filter)) return 'production'
  if (MEDIA.has(filter)) return 'media'
  return null
}

export function categoryForNavigationDestination(destination: string): NavigationCategory | null {
  if (destination === 'studio') return 'direct-generation'
  if (destination === 'director' || destination === 'productions' || destination === 'video_editor') return 'production'
  if (['story_lab', 'series_lab', 'comics', 'video_3d', 'animate_3d', 'character_creator', 'character_kit'].includes(destination)) return 'studios'
  if (['images', 'videos', 'audio', '3d'].includes(destination)) return 'media'
  return null
}

export const WIZARD_NAVIGATION_EVENT = 'hocuspocus:wizard-navigation'

export function announceWizardNavigation(destination: string): void {
  if (typeof window === 'undefined') return
  const category = categoryForNavigationDestination(destination)
  if (!category) return
  window.dispatchEvent(new window.CustomEvent(WIZARD_NAVIGATION_EVENT, {
    detail: { category, destination },
  }))
}
