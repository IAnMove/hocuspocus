import { useStore } from '../../stores/useStore'
import type { MediaFilter } from '../../types'
import type { ActivityProjectTarget } from './lineage'

const TAB_FILTER: Partial<Record<string, MediaFilter>> = {
  comics: 'comics',
  story_lab: 'stories',
  series_lab: 'series',
  video_3d: 'scene3d',
  character_kit: 'characters',
  video_editor: 'videoeditor',
  workspaces: 'runs',
  studio: 'all',
}

function tabForActivityTarget(kind?: string): string {
  switch (kind) {
    case 'comic': return 'comics'
    case 'director_production': return 'director'
    case 'story': return 'story_lab'
    case 'series':
    case 'series_episode': return 'series_lab'
    case 'scene': return 'video_3d'
    case 'character_kit': return 'character_kit'
    case 'video_editor': return 'video_editor'
    case 'workspace_collection': return 'workspaces'
    default: return 'studio'
  }
}

function filterForOutput(type: string, name: string): MediaFilter {
  if (type === 'video' || /\.(mp4|webm|mov)$/i.test(name)) return 'videos'
  if (type === 'image' || /\.(png|jpe?g|webp|gif)$/i.test(name)) return 'images'
  if (type === 'audio' || /\.(wav|mp3|flac|ogg)$/i.test(name)) return 'audio'
  if (type === 'model3d' || /\.(glb|gltf)$/i.test(name)) return 'model3d'
  if (type === 'scene') return 'scene3d'
  if (type === 'comic') return 'comics'
  return 'all'
}

export function openActivityArtifact(name: string): boolean {
  const app = useStore.getState()
  const file = (app.outputs || []).find(item => item.name === name || item.name.endsWith(`/${name}`))
  app.setDashboardOpen(false)
  if (!file) {
    app.setMediaFilter(filterForOutput('', name))
    return false
  }
  app.setMediaFilter(filterForOutput(file.type, file.name))
  const filtered = app.filteredOutputs()
  const index = filtered.findIndex(item => item.name === file.name)
  if (index >= 0) {
    app.setSelectedOutput(index)
    return true
  }
  return false
}

export function openActivityProject(target: ActivityProjectTarget): boolean {
  const app = useStore.getState()
  const tab = tabForActivityTarget(target.kind)
  app.setDashboardOpen(tab === 'director')
  const filter = TAB_FILTER[tab]
  if (filter) app.setMediaFilter(filter)
  if (tab === 'story_lab') {
    void import('../stories/store').then(({ useStoryStore }) => {
      useStoryStore.getState().openProject?.(target.id)
    }).catch(() => undefined)
  }
  if (tab === 'series_lab') {
    void import('../series/store').then(({ useSeriesStore }) => {
      const series = useSeriesStore.getState()
      if (target.kind === 'episode' || target.kind === 'series_episode') series.openEpisode?.(target.id)
      else series.openSeries?.(target.id)
    }).catch(() => undefined)
  }
  return Boolean(filter || tab === 'director')
}
