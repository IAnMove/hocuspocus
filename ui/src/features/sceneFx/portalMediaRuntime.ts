import { Group, Mesh, MeshBasicMaterial, PlaneGeometry, ShaderMaterial } from 'three'
import { defaultMediaScreen } from '../scene3d/mediaScreen'
import { bindScreenMedia, type ScreenMediaRuntime } from '../scene3d/screenMediaRuntime'

export type PortalMediaRuntime = {
  ready: boolean
  error: Error | null
  seek: (seconds: number) => Promise<void>
  dispose: () => void
}

/** Each portal owns a paused, scene-clock-driven source, just like a video layer. */
export function bindPortalMedia(root: Group, sourceUrl?: string): PortalMediaRuntime | undefined {
  const glass = root.children.find(child => child.userData.kind === 'portalMedia')
  if (!sourceUrl || typeof document === 'undefined' || !(glass instanceof Mesh) || !(glass.material instanceof ShaderMaterial)) return
  const uniforms = glass.material.uniforms
  const surface = new Mesh(new PlaneGeometry(2, 2), new MeshBasicMaterial())
  const original = surface.material
  const abort = new AbortController()
  const screen = { ...defaultMediaScreen(), sourceUrl, width: 1, height: 1, fit: 'cover' as const,
    media: /\.(mp4|webm|mov|mkv)(\?|$)/i.test(sourceUrl) ? 'video' as const : 'image' as const }
  let media: ScreenMediaRuntime | undefined, released = false
  const runtime: PortalMediaRuntime = {
    ready: false, error: null,
    async seek(seconds) {
      await loaded
      if (runtime.error) throw runtime.error
      if (!released) await media?.seek(seconds, screen)
    },
    dispose() {
      if (released) return
      released = true; abort.abort(); media?.dispose()
      uniforms.uMap.value = null; uniforms.uHasMap.value = 0
      surface.geometry.dispose(); original.dispose()
    },
  }
  const loaded = bindScreenMedia(surface, screen, false, abort.signal, undefined, {}).then(value => {
    if (released) { value.dispose(); return }
    media = value
    uniforms.uMap.value = surface.material.map; uniforms.uHasMap.value = 1
    runtime.ready = true
  }).catch(error => {
    if (!released) runtime.error = error instanceof Error ? error : new Error(String(error))
  })
  return runtime
}
