import type { ApiOutput } from '../api/client'
import type { GenerationJob, MediaFilter } from '../types'

export const GALLERY_LIST_FILTERS = new Set<MediaFilter>([
  'all',
  'images',
  'videos',
  'audio',
  'model3d',
  'scenes',
  'comics',
  'videoclips',
  'trailers',
  'series_episodes',
  'multiclip',
  'favorites',
  'avatars',
])

export function galleryListQuery(mediaFilter: MediaFilter, searchQuery = '') {
  const search = searchQuery.trim() || undefined
  const resultKind = mediaFilter === 'videoclips' ? 'music_video' as const
    : mediaFilter === 'trailers' ? 'trailer' as const
    : mediaFilter === 'series_episodes' ? 'series_episode' as const
    : undefined
  const mediaType: ApiOutput['type'] | undefined =
    mediaFilter === 'images' ? 'image'
    : mediaFilter === 'videos'
      || mediaFilter === 'videoclips'
      || mediaFilter === 'trailers'
      || mediaFilter === 'series_episodes'
      || mediaFilter === 'multiclip' ? 'video'
    : mediaFilter === 'audio' ? 'audio'
    : mediaFilter === 'model3d' ? 'model3d'
    : mediaFilter === 'scenes' ? 'scene'
    : mediaFilter === 'comics' ? 'comic'
    : undefined
  return {
    search,
    resultKind,
    mediaType,
    favoritesOnly: mediaFilter === 'favorites',
    multiclipOnly: mediaFilter === 'multiclip',
    editsOnly: mediaFilter === 'avatars',
    useServerList: Boolean(
      search
      || resultKind
      || mediaType
      || mediaFilter === 'favorites'
      || mediaFilter === 'multiclip'
      || mediaFilter === 'avatars',
    ),
  }
}

export function jobFitsGalleryFilter(job: GenerationJob, filter: MediaFilter): boolean {
  if (filter === 'all') return true
  const mode = String(job.generationDetails?.generation_mode || '')
  if (filter === 'images') return mode === 'image'
  if (filter === 'audio') return mode === 'audio'
  if (filter === 'model3d') return mode === 'model3d'
  if (filter === 'avatars') {
    const details = job.generationDetails as { edit_sub_mode?: string } | undefined
    return mode === 'avatar' || Boolean(details?.edit_sub_mode)
  }
  if (
    filter === 'videos'
    || filter === 'videoclips'
    || filter === 'trailers'
    || filter === 'series_episodes'
    || filter === 'multiclip'
  ) {
    return mode !== 'image' && mode !== 'audio' && mode !== 'model3d'
  }
  return false
}
