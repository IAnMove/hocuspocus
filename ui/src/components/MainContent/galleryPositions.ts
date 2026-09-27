import type { GalleryAnchor } from './mediaGalleryLayout'

/** Where the reader was in each list (workspace or uploads × filter), so
 *  leaving Videos for All and coming back returns to the same item. Kept for
 *  the browser tab's lifetime; a new tab starts at the newest outputs. */
const STORAGE_KEY = 'hocuspocus_gallery_positions'
const LIMIT = 40

const positions = new Map<string, GalleryAnchor>()
let loaded = false

function load() {
  if (loaded) return
  loaded = true
  try {
    const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]') as Array<[string, GalleryAnchor]>
    for (const [key, anchor] of stored) {
      if (typeof key === 'string' && anchor && typeof anchor.name === 'string') positions.set(key, { name: anchor.name, within: Number(anchor.within) || 0 })
    }
  } catch { /* storage unavailable or corrupt: start fresh */ }
}

export function galleryPositionKey(workspace: string, browsingUploads: boolean, filter: string): string {
  return `${browsingUploads ? '__uploads__' : workspace}|${filter}`
}

export function readGalleryPosition(key: string): GalleryAnchor | null {
  load()
  return positions.get(key) ?? null
}

export function writeGalleryPosition(key: string, anchor: GalleryAnchor | null) {
  load()
  positions.delete(key)
  if (anchor) positions.set(key, anchor)
  while (positions.size > LIMIT) positions.delete(positions.keys().next().value as string)
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...positions]))
  } catch { /* storage unavailable: memory still works for this session */ }
}
