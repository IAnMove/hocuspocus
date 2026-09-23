import { memo, useCallback, useMemo, useState } from 'react'
import { ImagePreview } from '../common/ImagePreview'
import type { CSSProperties } from 'react'
import type { OutputFile } from '../../types'
import { galleryThumbnailUrl, tileThumbnailSize } from './galleryThumbnail'

/** Short kind tag. Deliberately text rather than an icon: at tile scale a
 *  glyph for "scene" versus "3D model" is a guess, and every extra icon is
 *  another module in the entry chunk. */
const KIND_TAG: Record<string, string> = {
  video: 'VID', image: 'IMG', audio: 'AUD', model3d: '3D', scene: 'ESC', comic: 'COM',
}

/** One cell of the grid and mosaic layouts. Deliberately lighter than
 *  MediaFeedItem: no player, no action bar, no metadata row. Those belong to
 *  the one-up view and the details dialog. Geometry arrives as numbers so a
 *  scroll that keeps this cell on screen does not re-render it. */
export const GalleryTile = memo(function GalleryTile({
  file, workspace, index, active, cover, top, left, width, height, onOpen,
}: {
  file: OutputFile
  workspace: string
  index: number
  active: boolean
  /** Grid crops to fill a square; mosaic cells already match the aspect. */
  cover: boolean
  top: number
  left: number
  width: number
  height: number
  onOpen: (index: number) => void
}) {
  // Not every kind publishes a thumbnail — audio and some 3D outputs do not.
  // Without this the tile is a black rectangle with no way to tell an
  // unrenderable kind from a broken file.
  const [thumbFailed, setThumbFailed] = useState(false)
  const tag = KIND_TAG[file.type] ?? file.type.slice(0, 3).toUpperCase()
  const src = galleryThumbnailUrl(file, workspace, tileThumbnailSize(width, height))
  const style = useMemo<CSSProperties>(() => ({ position: 'absolute', top, left, width, height }), [top, left, width, height])
  const open = useCallback(() => onOpen(index), [onOpen, index])

  const className = `group relative block h-full w-full overflow-hidden rounded-lg border bg-black/40 text-left transition-colors ${active ? 'border-accent-blue' : 'border-white/[0.07] hover:border-white/25'}`
  const content = <>
      {thumbFailed || !src ? (
        <span className="flex h-full w-full flex-col items-center justify-center gap-1.5 bg-bg-secondary px-3 text-text-muted">
          <span className="text-[10px] font-semibold tracking-widest">{tag}</span>
          <span className="line-clamp-2 text-center text-[9px] leading-tight">{file.name}</span>
        </span>
      ) : (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setThumbFailed(true)}
          className={`h-full w-full ${cover ? 'object-cover' : 'object-contain'}`}
        />
      )}
      <span className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-0.5 text-[8.5px] font-semibold tracking-wider text-white/85 backdrop-blur-sm">
        {tag}
      </span>
      {file.favorite && (
        <span aria-hidden="true" className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-amber-300" />
      )}
      <span className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/80 to-transparent px-2 pb-1 pt-4 text-[9px] text-white/80">
        {file.name}
      </span>
    </>
  if (file.type === 'image' || file.type === 'video') {
    return <div style={style} aria-current={active ? 'true' : undefined}>
      <ImagePreview image={{ ...file, type: file.type, workspace_id: workspace }} className={className} onOpen={open}>{content}</ImagePreview>
    </div>
  }
  return <button type="button" style={style} aria-current={active ? 'true' : undefined} className={className} onClick={open}>{content}</button>
})
