import { getOutputThumbnailUrl } from '../../api/outputs'
import type { OutputFile } from '../../types'

/** `sm` ≤ 320 px for tiles and the history strip, `md` ≤ 640 px for one-up
 *  cards. Both keep the source aspect; the full file is only fetched when the
 *  details dialog opens. */
export type GalleryThumbnailSize = 'sm' | 'md'

/** Aspect-preserving preview for images and videos. Saved scenes, comics and
 *  3D models already publish their own small preview image, used as-is. */
export function galleryThumbnailUrl(
  file: Pick<OutputFile, 'name' | 'type' | 'thumbnail_url'>,
  workspace: string | undefined,
  size: GalleryThumbnailSize,
): string | null {
  if (file.type !== 'image' && file.type !== 'video') return file.thumbnail_url || null
  const base = file.thumbnail_url || getOutputThumbnailUrl(file.name, workspace)
  return `${base}${base.includes('?') ? '&' : '?'}size=${size}`
}

/** Tiles use the small preview unless they are drawn large on a dense screen. */
export function tileThumbnailSize(width: number, height: number): GalleryThumbnailSize {
  const ratio = typeof window === 'undefined' ? 1 : Math.min(2, window.devicePixelRatio || 1)
  return Math.max(width, height) * ratio <= 480 ? 'sm' : 'md'
}
