import { previewSceneDocument, previewTemplateDocument } from './templateCatalog.ts'
import { dropDressing, syncDressing } from './dressing.ts'
import {
  applyLight,
  createWorld,
  paintWorld,
  placeSlot,
  placeholderMesh,
  pruneSlots,
  setWorldSize,
  type GpuWorld,
} from './gpu.ts'
import { createPixelWorldCache, isPixelDressing } from './pixel/pixelWorldSet'
import { RoomSetRuntime } from './roomSetRuntime.ts'
import type { RoomSet } from './roomSet'
import type { Scene3DDocument, Scene3DDressing, Scene3DLight, Scene3DSlot, Scene3DTemplateId } from './types.ts'
import type { MotionLabSettings } from './motionlab/types'

const WIDTH = 320
const HEIGHT = 180
const PREVIEW_SLOT_CAP = 8
const FALLBACK_LIGHT: Scene3DLight = { kind: 'directional', direction: [-0.5, -1, -0.3], intensity: 1.6, color: '#fff0d9' }
const previewPixels = createPixelWorldCache(8)
const ROOM_CACHE = 8
const previewRooms = new Map<string, RoomSetRuntime>()

/** `read` throws for a template with no built-in preview; the loop then drops that watcher. */
type Watcher = { read: () => Scene3DDocument; canvas: HTMLCanvasElement }

let world: GpuWorld | null | undefined
let lastDressing: string | undefined
const watchers = new Set<Watcher>()
let raf = 0
let cursor = 0

function visibleSlots(slots: readonly Scene3DSlot[]) {
  return slots.filter(slot => !(slot.media === 'image' && !slot.sourceUrl)).slice(0, PREVIEW_SLOT_CAP)
}

function attachPreviewDressing(pack: GpuWorld, kind: Scene3DDressing | undefined, motionLab?: MotionLabSettings) {
  const key = `${kind ?? 'none'}:${JSON.stringify(motionLab)}`
  if (lastDressing === key) return
  if (pack.dressing?.userData.pixelWorld) {
    pack.scene.remove(pack.dressing)
    pack.dressing = null
  } else {
    dropDressing(pack)
  }
  lastDressing = key
  if (isPixelDressing(kind)) {
    pack.dressing = previewPixels.take(kind)
    pack.scene.add(pack.dressing)
    pack.floor.visible = false
    pack.floor.position.y = -80
    return
  }
  syncDressing(pack, kind, undefined, undefined, motionLab)
}

/** Stage thumbs take turns on the shared renderer: keep each room's meshes instead of rebuilding them every frame.
 *  Exported for tests. */
export function attachPreviewRoom(pack: Pick<GpuWorld, 'scene' | 'room' | 'roomKey'>, room: RoomSet | undefined) {
  const key = JSON.stringify(room)
  if (pack.roomKey === key) return
  pack.room?.root.removeFromParent()
  pack.room = undefined
  pack.roomKey = key
  if (!room || key === undefined) return
  let runtime = previewRooms.get(key)
  if (runtime) previewRooms.delete(key)
  else {
    runtime = new RoomSetRuntime(room)
    const oldest = previewRooms.keys().next().value
    if (previewRooms.size >= ROOM_CACHE && oldest !== undefined) {
      previewRooms.get(oldest)?.dispose()
      previewRooms.delete(oldest)
    }
  }
  previewRooms.set(key, runtime)
  pack.room = runtime
  pack.scene.add(runtime.root)
}

function ensure(): GpuWorld | null {
  if (world !== undefined) return world
  try {
    if (typeof document === 'undefined' || (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent))) {
      world = null
      return null
    }
    const probe = document.createElement('canvas')
    if (!probe.getContext('webgl2') && !probe.getContext('webgl')) {
      world = null
      return null
    }
    const host = document.createElement('div')
    host.style.cssText = 'position:fixed;left:-9999px;top:0;width:320px;height:180px;overflow:hidden;pointer-events:none'
    document.body.append(host)
    const created = createWorld(host, FALLBACK_LIGHT, 42)
    setWorldSize(created, WIDTH, HEIGHT)
    world = created
    return created
  } catch {
    world = null
    return null
  }
}

function tick(now: number) {
  const pack = ensure()
  const list = [...watchers]
  if (!pack || !list.length) {
    raf = 0
    return
  }
  const watcher = list[cursor % list.length]
  cursor++
  let doc: Scene3DDocument
  try {
    doc = watcher.read()
  } catch {
    // A shot based on a workspace template (user-…, often an agent's) has no built-in preview.
    // Drop that watcher and keep the shared loop alive for every other thumbnail.
    watchers.delete(watcher)
    raf = requestAnimationFrame(tick)
    return
  }
  const slots = visibleSlots(doc.slots)
  attachPreviewDressing(pack, doc.dressing, doc.motionLab)
  attachPreviewRoom(pack, doc.room)
  applyLight(pack.dir, doc.light)
  pruneSlots(pack, slots)
  for (const slot of slots) {
    if (!pack.slots.has(slot.id)) placeSlot(pack, slot, placeholderMesh(slot), [], 1, true)
  }
  const seconds = (now / 1000) % Math.max(0.5, doc.duration)
  // Thumbnails draw placeholder boxes in a shared background loop; environment light and the look
  // would only make every background frame dearer.
  paintWorld(pack, { ...doc, slots: [...slots], lighting: undefined, look: undefined }, seconds)
  const ctx = watcher.canvas.getContext('2d')
  if (ctx) ctx.drawImage(pack.renderer.domElement, 0, 0, watcher.canvas.width, watcher.canvas.height)
  raf = requestAnimationFrame(tick)
}

export function subscribeTemplateThumb(id: Scene3DTemplateId, canvas: HTMLCanvasElement) {
  return subscribe(() => previewTemplateDocument(id), canvas)
}

/** A document built elsewhere (a stage card from the server) in the same shared loop. Nothing is fetched where
 *  no renderer can draw; `load` runs once and the thumb starts when it resolves. */
export function subscribeDocumentThumb(load: () => Promise<Scene3DDocument>, canvas: HTMLCanvasElement) {
  if (!ensure()) return () => {}
  let stop: (() => void) | undefined
  let cancelled = false
  load().then(loaded => {
    if (cancelled) return
    const preview = previewSceneDocument(loaded)
    stop = subscribe(() => preview, canvas)
  }).catch(() => { /* the canvas stays blank; the shelf reports the failed request when the card is opened */ })
  return () => { cancelled = true; stop?.() }
}

function subscribe(read: () => Scene3DDocument, canvas: HTMLCanvasElement) {
  const watcher: Watcher = { read, canvas }
  const start = () => {
    if (!ensure()) return
    watchers.add(watcher)
    if (!raf) raf = requestAnimationFrame(tick)
  }
  if (typeof IntersectionObserver === 'undefined') {
    start()
    return () => { watchers.delete(watcher) }
  }
  const io = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) start()
      else watchers.delete(watcher)
    }
  }, { threshold: 0.12 })
  io.observe(canvas)
  return () => {
    io.disconnect()
    watchers.delete(watcher)
  }
}
