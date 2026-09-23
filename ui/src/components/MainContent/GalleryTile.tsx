import { memo, useCallback, useMemo, useRef, useState } from 'react'
import { Check } from 'lucide-react'
import { ImagePreview } from '../common/ImagePreview'
import type { CSSProperties, MouseEvent, PointerEvent } from 'react'
import type { OutputFile } from '../../types'
import { galleryThumbnailUrl, tileThumbnailSize } from './galleryThumbnail'

/** Short kind tag. Deliberately text rather than an icon: at tile scale a
 *  glyph for "scene" versus "3D model" is a guess, and every extra icon is
 *  another module in the entry chunk. */
const KIND_TAG: Record<string, string> = {
  video: 'VID', image: 'IMG', audio: 'AUD', model3d: '3D', scene: 'ESC', comic: 'COM',
}

const LONG_PRESS_MS = 450
const PRESS_SLOP = 8

/** One cell of the grid and mosaic layouts. Deliberately lighter than
 *  MediaFeedItem: no player, no action bar, no metadata row. Those belong to
 *  the one-up view and the details dialog. Geometry arrives as numbers so a
 *  scroll that keeps this cell on screen does not re-render it. */
export const GalleryTile = memo(function GalleryTile({
  file, workspace, index, active, cover, top, left, width, height, selecting, picked,
  onOpen, onOpenDetails, onPick, onLongPress,
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
  selecting: boolean
  picked: boolean
  onOpen: (index: number) => void
  onOpenDetails: (index: number) => void
  onPick: (index: number, range: boolean) => void
  onLongPress: (index: number) => void
}) {
  // Not every kind publishes a thumbnail — audio and some 3D outputs do not.
  // Without this the tile is a black rectangle with no way to tell an
  // unrenderable kind from a broken file.
  const [thumbFailed, setThumbFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const tag = KIND_TAG[file.type] ?? file.type.slice(0, 3).toUpperCase()
  const src = galleryThumbnailUrl(file, workspace, tileThumbnailSize(width, height))
  const style = useMemo<CSSProperties>(() => ({ position: 'absolute', top, left, width, height }), [top, left, width, height])
  const open = useCallback(() => onOpen(index), [onOpen, index])
  const openDetails = useCallback(() => onOpenDetails(index), [onOpenDetails, index])

  // Touch long-press starts a selection, like a phone photo library.
  const press = useRef<{ timer: number; x: number; y: number } | null>(null)
  const longPressed = useRef(false)
  const cancelPress = () => {
    if (press.current) window.clearTimeout(press.current.timer)
    press.current = null
  }
  const pressHandlers = {
    onPointerDown: (event: PointerEvent) => {
      if (event.pointerType === 'mouse' || selecting) return
      longPressed.current = false
      const x = event.clientX, y = event.clientY
      press.current = { x, y, timer: window.setTimeout(() => { longPressed.current = true; press.current = null; onLongPress(index) }, LONG_PRESS_MS) }
    },
    onPointerMove: (event: PointerEvent) => {
      if (press.current && Math.hypot(event.clientX - press.current.x, event.clientY - press.current.y) > PRESS_SLOP) cancelPress()
    },
    onPointerUp: cancelPress,
    onPointerCancel: cancelPress,
    onContextMenu: (event: MouseEvent) => { if (longPressed.current) event.preventDefault() },
    onClickCapture: (event: MouseEvent) => {
      // The tap that ended a long press must not also open or toggle the item.
      if (longPressed.current) {
        longPressed.current = false
        event.preventDefault()
        event.stopPropagation()
      }
    },
  }

  const placeholder = !loaded && !thumbFailed && file.color ? { backgroundColor: file.color } : undefined
  const className = `group relative block h-full w-full overflow-hidden rounded-lg border bg-black/40 text-left transition-colors ${
    picked ? 'border-accent-blue ring-2 ring-accent-blue' : active ? 'border-accent-blue' : 'border-white/[0.07] hover:border-white/25'}`
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
          onLoad={() => setLoaded(true)}
          onError={() => setThumbFailed(true)}
          className={`h-full w-full transition-opacity duration-200 [-webkit-touch-callout:none] ${cover ? 'object-cover' : 'object-contain'} ${loaded ? 'opacity-100' : 'opacity-0'}`}
        />
      )}
      <span className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-0.5 text-[8.5px] font-semibold tracking-wider text-white/85 backdrop-blur-sm">
        {tag}
      </span>
      {file.favorite && !selecting && (
        <span aria-hidden="true" className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-amber-300" />
      )}
      {selecting && (
        <span aria-hidden="true" className={`absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full border-2 ${
          picked ? 'border-accent-blue bg-accent-blue text-white' : 'border-white/80 bg-black/40 text-transparent'}`}>
          <Check size={14} strokeWidth={3} />
        </span>
      )}
      {selecting && picked && <span aria-hidden="true" className="pointer-events-none absolute inset-0 bg-accent-blue/15" />}
      <span className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/80 to-transparent px-2 pb-1 pt-4 text-[9px] text-white/80">
        {file.name}
      </span>
    </>

  if (selecting) {
    // Keeps the long-press guard: the tap that started selecting lands here.
    return <button type="button" role="checkbox" aria-checked={picked} aria-label={file.name} data-gallery-index={index} style={{ ...style, ...placeholder }}
      className={className} onClickCapture={pressHandlers.onClickCapture} onContextMenu={pressHandlers.onContextMenu}
      onClick={event => onPick(index, event.shiftKey)}>{content}</button>
  }
  if (file.type === 'image' || file.type === 'video') {
    return <div style={style} data-gallery-index={index} aria-current={active ? 'true' : undefined} {...pressHandlers}>
      <ImagePreview image={{ ...file, type: file.type, workspace_id: workspace }} className={className} onOpen={open} onOpenDialog={openDetails}>
        {placeholder ? <span aria-hidden="true" className="absolute inset-0" style={placeholder} /> : null}
        {content}
      </ImagePreview>
    </div>
  }
  return <button type="button" style={{ ...style, ...placeholder }} data-gallery-index={index} aria-current={active ? 'true' : undefined} className={className} onClick={open} {...pressHandlers}>{content}</button>
})
