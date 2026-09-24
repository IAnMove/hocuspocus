import { Color, PerspectiveCamera, Scene, WebGLRenderer } from 'three'
import type { SceneFx } from './types'
import { isWorldSfxKind, parseWorldSfx, type WorldSfxKind } from './world'
import { syncWorldSfx, type WorldSfxGpu } from './worldRuntime'

type Gpu = {
  renderer: WebGLRenderer
  scene: Scene
  camera: PerspectiveCamera
  nodes: Map<string, WorldSfxGpu>
  canvas: HTMLCanvasElement
  /** The filmed frame with its edges faded, so a big effect never shows the
   *  sprite's square border. */
  soft: HTMLCanvasElement
}

const SIZE = 640
/** Wider than the effect: frames the whole of portals, clouds and blasts. */
const FOV = 44
/** Where the sprite lands in cue units, scaled with the lens so an effect
 *  keeps the size it had with the old 34° framing. */
export const SPRITE_RECT = (() => {
  const grow = Math.tan(FOV * Math.PI / 360) / Math.tan(34 * Math.PI / 360)
  return { x: -.62 * grow, y: -.78 * grow + .14 * (grow - 1), width: 1.24 * grow, height: 1.28 * grow }
})()

function feather(pack: Gpu) {
  const context = pack.soft.getContext('2d')
  if (!context) return pack.canvas
  context.globalCompositeOperation = 'copy'
  context.drawImage(pack.canvas, 0, 0)
  context.globalCompositeOperation = 'destination-in'
  const gradient = context.createRadialGradient(SIZE / 2, SIZE / 2, SIZE * .3, SIZE / 2, SIZE / 2, SIZE * .5)
  gradient.addColorStop(0, '#000'); gradient.addColorStop(1, 'rgba(0,0,0,0)')
  context.fillStyle = gradient; context.fillRect(0, 0, SIZE, SIZE)
  context.globalCompositeOperation = 'source-over'
  return pack.soft
}

let gpu: Gpu | null | undefined

function ensureGpu(): Gpu | null {
  if (gpu !== undefined) return gpu
  try {
    if (typeof document === 'undefined') { gpu = null; return null }
    const canvas = document.createElement('canvas')
    canvas.width = SIZE
    canvas.height = SIZE
    const renderer = new WebGLRenderer({
      canvas, alpha: true, antialias: true, premultipliedAlpha: false, preserveDrawingBuffer: true,
    })
    renderer.setClearColor(new Color(0x000000), 0)
    renderer.setSize(SIZE, SIZE, false)
    renderer.toneMappingExposure = 1.25
    const scene = new Scene()
    const camera = new PerspectiveCamera(FOV, 1, 0.08, 40)
    camera.position.set(2.7, 1.85, 5.1)
    camera.lookAt(0, 0.48, 0)
    const soft = document.createElement('canvas')
    soft.width = SIZE
    soft.height = SIZE
    gpu = { renderer, scene, camera, nodes: new Map(), canvas, soft }
    return gpu
  } catch {
    gpu = null
    return null
  }
}

/** Same 3D effect, filmed for the 2D overlay. */
export function rasterizeWorldFx(cue: SceneFx, time: number): HTMLCanvasElement | null {
  if (!isWorldSfxKind(cue.kind)) return null
  const pack = ensureGpu()
  if (!pack) return null
  const kind = cue.kind as WorldSfxKind
  const span = Math.max(0.35, cue.end - cue.start || 1)
  const portal = kind === 'media_portal' || kind === 'portal' || kind === 'summoning_gate'
  pack.camera.position.set(portal ? 0.25 : 2.7, portal ? 1.2 : 1.85, portal ? 4.6 : 5.1)
  pack.camera.lookAt(0, portal ? 1.1 : 0.48, 0)
  const world = parseWorldSfx([{
    id: `overlay-${cue.id}`,
    kind,
    start: 0,
    end: span,
    scale: (kind === 'explosion' ? 1.55 : 1.35) + cue.intensity * 0.3,
    color: cue.color,
    intensity: cue.intensity,
    seed: cue.seed,

  }])
  syncWorldSfx(pack.scene, pack.nodes, world, time, [])
  pack.renderer.setClearColor(new Color(0x000000), 0)
  pack.renderer.clear()
  pack.renderer.render(pack.scene, pack.camera)
  return feather(pack)
}

export function rasterizeExplosion(cue: SceneFx, time: number) {
  return rasterizeWorldFx(cue, time)
}
