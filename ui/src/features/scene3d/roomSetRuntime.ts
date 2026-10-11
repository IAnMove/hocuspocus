/** Shared preview/export room surfaces. Video uses the existing deterministic screen decoder. */
import { AmbientLight, DoubleSide, Group, Mesh, MeshStandardMaterial, PlaneGeometry, PointLight, RepeatWrapping, SRGBColorSpace, TextureLoader } from 'three'
import { roomLightPreset, roomPanels, type RoomPanel, type RoomSet } from './roomSet'
import { defaultMediaScreen, type MediaScreen } from './mediaScreen'
import { bindScreenMedia, type ScreenMediaRuntime } from './screenMediaRuntime'

export class RoomSetRuntime {
  readonly root = new Group()
  ready = false
  error: unknown
  private abort = new AbortController()
  private screens: { runtime: ScreenMediaRuntime; screen: MediaScreen }[] = []
  private repaint: () => void
  constructor(room: RoomSet, repaint: () => void = () => {}) {
    this.repaint = repaint
    // A closed ceiling blocks the outdoor sun; light the interior independently.
    const preset = roomLightPreset(room), [width, depth, height] = room.mold.dimensions
    const fill = new AmbientLight('#ffffff', 1.2 * preset.intensity)
    const key = new PointLight(preset.color, 35 * preset.intensity, 2 * Math.max(width, depth, height))
    key.position.set(0, height - 0.15, depth * 0.12)
    this.root.add(fill, key)
    void Promise.all(roomPanels(room).map(panel => this.panel(panel))).then(() => { this.ready = !this.abort.signal.aborted; this.repaint() }).catch(error => { this.error = error })
  }
  private async panel(panel: RoomPanel) {
    const geometry = new PlaneGeometry(...panel.size)
    const material = new MeshStandardMaterial({ color: panel.material.color ?? '#ffffff', roughness: 0.85, side: DoubleSide })
    const mesh = new Mesh(geometry, material)
    mesh.name = panel.id; mesh.position.fromArray(panel.position); mesh.rotation.set(...panel.rotation)
    mesh.receiveShadow = true; mesh.castShadow = true; this.root.add(mesh)
    const media = panel.material
    if (media.video) {
      const screen: MediaScreen = { ...defaultMediaScreen(), media: 'video', sourceUrl: media.video.asset, targetMesh: mesh.name, width: panel.size[0], height: panel.size[1], fit: 'cover' }
      const runtime = await bindScreenMedia(this.root, screen, false, this.abort.signal, this.repaint)
      if (this.abort.signal.aborted) runtime.dispose()
      else this.screens.push({ runtime, screen })
      return
    }
    const asset = media.texture?.asset ?? media.image?.asset
    if (!asset) return
    const texture = await new TextureLoader().loadAsync(asset)
    if (this.abort.signal.aborted) { texture.dispose(); return }
    texture.colorSpace = SRGBColorSpace
    if (media.texture) { texture.wrapS = texture.wrapT = RepeatWrapping; texture.repeat.set(panel.fullSize[0] / (media.tile_m ?? 1), panel.fullSize[1] / (media.tile_m ?? 1)) }
    else {
      const aspect = texture.image.width / texture.image.height, target = panel.fullSize[0] / panel.fullSize[1]
      texture.repeat.set(Math.min(1, target/aspect), Math.min(1, aspect/target)); texture.offset.set((1-texture.repeat.x)/2, (1-texture.repeat.y)/2)
    }
    const uv = geometry.attributes.uv, [left,bottom,right,top] = panel.uv
    for (let i=0; i<uv.count; i++) uv.setXY(i, left+uv.getX(i)*(right-left), bottom+uv.getY(i)*(top-bottom))
    uv.needsUpdate = true; material.map = texture; material.needsUpdate = true
  }
  async seek(seconds: number) { await Promise.all(this.screens.map(({ runtime, screen }) => runtime.seek(seconds, screen))) }
  dispose() {
    this.abort.abort(); this.screens.forEach(({ runtime }) => runtime.dispose()); this.root.removeFromParent()
    this.root.traverse(object => { if (object instanceof Mesh) { object.geometry.dispose(); const mat = object.material as MeshStandardMaterial; mat.map?.dispose(); mat.dispose() } })
  }
}
