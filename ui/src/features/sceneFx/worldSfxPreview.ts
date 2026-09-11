import { AmbientLight, Color, DirectionalLight, Mesh, MeshStandardMaterial, PerspectiveCamera, PlaneGeometry, Scene, WebGLRenderer } from 'three'
import { parseWorldSfx, type WorldSfxKind } from './world'
import { syncWorldSfx, type WorldSfxGpu } from './worldRuntime'

type Gpu = {
  renderer: WebGLRenderer
  scene: Scene
  camera: PerspectiveCamera
  nodes: Map<string, WorldSfxGpu>
  canvas: HTMLCanvasElement
}

let gpu: Gpu | null | undefined
const watchers = new Set<{ kind: WorldSfxKind; canvas: HTMLCanvasElement }>()
let raf = 0
let cursor = 0

function ensure(): Gpu | null {
  if (gpu !== undefined) return gpu
  try {
    if (typeof document === 'undefined') { gpu = null; return null }
    const canvas = document.createElement('canvas')
    canvas.width = 192
    canvas.height = 108
    const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: true })
    renderer.setSize(192, 108, false)
    renderer.setClearColor(new Color('#10131c'), 1)
    const scene = new Scene()
    scene.background = new Color('#10131c')
    const camera = new PerspectiveCamera(40, 192 / 108, 0.1, 30)
    camera.position.set(2.5, 1.45, 4.6)
    camera.lookAt(0.15, 0.7, 0)
    scene.add(new AmbientLight(0xffe8d0, 0.4))
    const sun = new DirectionalLight(0xffd7b0, 2.2)
    sun.position.set(-2, 5, 3)
    scene.add(sun)
    const floor = new Mesh(new PlaneGeometry(10, 10), new MeshStandardMaterial({ color: '#3a414c', metalness: 0.88, roughness: 0.22 }))
    floor.rotation.x = -Math.PI / 2
    scene.add(floor)
    gpu = { renderer, scene, camera, nodes: new Map(), canvas }
    return gpu
  } catch {
    gpu = null
    return null
  }
}

function spanFor(kind: string) {
  return kind === 'explosion' || kind === 'splash' || kind === 'ice_burst' || kind.endsWith('_burst') || kind === 'nova' || kind === 'parry' ? 2.6 : 4.5
}

function tick(now: number) {
  const pack = ensure()
  if (!pack || !watchers.size) { raf = 0; return }
  // Share one GPU context and bound work to one visible tile per frame.
  const visible = [...watchers]
  for (const watcher of [visible[cursor++ % visible.length]]) {
    const seconds = (now / 1000) % spanFor(watcher.kind)
    if (watcher.kind === 'media_portal' || watcher.kind === 'portal') {
      pack.camera.position.set(0.2, 1.2, 3.4)
      pack.camera.lookAt(0, 1.05, 0)
    } else {
      pack.camera.position.set(2.5, 1.45, 4.6)
      pack.camera.lookAt(0.15, 0.7, 0)
    }
    const cues = parseWorldSfx([{
      id: `thumb-${watcher.kind}`,
      kind: watcher.kind,
      start: 0,
      end: spanFor(watcher.kind),
    }])
    syncWorldSfx(pack.scene, pack.nodes, cues, seconds, [])
    pack.renderer.render(pack.scene, pack.camera)
    const ctx = watcher.canvas.getContext('2d')
    if (ctx) ctx.drawImage(pack.canvas, 0, 0, watcher.canvas.width, watcher.canvas.height)
  }
  raf = requestAnimationFrame(tick)
}

export function subscribeWorldSfxThumb(kind: WorldSfxKind, canvas: HTMLCanvasElement) {
  const watcher = { kind, canvas }
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
  }, { threshold: 0.15 })
  io.observe(canvas)
  return () => { io.disconnect(); watchers.delete(watcher) }
}
