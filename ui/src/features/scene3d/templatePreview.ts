import { applyScene3DTemplate } from './templates.ts'
import { syncDressing } from './dressing.ts'
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
import type { Scene3DLight, Scene3DSlot, Scene3DTemplateId } from './types.ts'

const WIDTH = 320
const HEIGHT = 180
const FALLBACK_LIGHT: Scene3DLight = { kind: 'directional', direction: [-0.5, -1, -0.3], intensity: 1.6, color: '#fff0d9' }

type Watcher = { id: Scene3DTemplateId; canvas: HTMLCanvasElement }

let world: GpuWorld | null | undefined
let lastDressing: string | undefined
const watchers = new Set<Watcher>()
let raf = 0
let cursor = 0

function visibleSlots(slots: readonly Scene3DSlot[]) {
  return slots.filter(slot => !(slot.media === 'image' && !slot.sourceUrl))
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
  const doc = applyScene3DTemplate(watcher.id)
  const slots = visibleSlots(doc.slots)
  const dressingKey = doc.dressing ?? 'none'
  if (lastDressing !== dressingKey) {
    syncDressing(pack, doc.dressing)
    lastDressing = dressingKey
  }
  applyLight(pack.dir, doc.light)
  pruneSlots(pack, slots)
  for (const slot of slots) {
    if (!pack.slots.has(slot.id)) placeSlot(pack, slot, placeholderMesh(slot), [], 1, true)
  }
  const seconds = (now / 1000) % Math.max(0.5, doc.duration)
  paintWorld(pack, { ...doc, slots: [...slots] }, seconds)
  const ctx = watcher.canvas.getContext('2d')
  if (ctx) ctx.drawImage(pack.renderer.domElement, 0, 0, watcher.canvas.width, watcher.canvas.height)
  raf = requestAnimationFrame(tick)
}

export function subscribeTemplateThumb(id: Scene3DTemplateId, canvas: HTMLCanvasElement) {
  const watcher: Watcher = { id, canvas }
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
