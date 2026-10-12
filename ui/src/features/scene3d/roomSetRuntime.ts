/** Shared preview/export room surfaces. Video uses the existing deterministic screen decoder. */
import { AmbientLight, BackSide, BufferAttribute, Color, DoubleSide, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, PlaneGeometry, PointLight, RepeatWrapping, SphereGeometry, SRGBColorSpace, TextureLoader } from 'three'
import { hasAmbientLife, isExterior, keyLightBreath, roomLightPreset, roomPanels, roomSky, type RoomPanel, type RoomSet, type RoomSky } from './roomSet'
import { defaultMediaScreen, type MediaScreen } from './mediaScreen'
import { bindScreenMedia, type ScreenMediaRuntime } from './screenMediaRuntime'

export class RoomSetRuntime {
  readonly root = new Group()
  ready = false
  error: unknown
  /** The lamp below a ceiling. An exterior has none: its sun (`document.light`) is the key light. */
  readonly key?: PointLight
  private keyIntensity = 0
  private readonly breathing: boolean
  private abort = new AbortController()
  private screens: { runtime: ScreenMediaRuntime; screen: MediaScreen }[] = []
  private repaint: () => void
  constructor(room: RoomSet, repaint: () => void = () => {}) {
    this.repaint = repaint
    this.breathing = hasAmbientLife(room.mold)
    const preset = roomLightPreset(room), [width, depth, height] = room.mold.dimensions
    if (isExterior(room.mold)) {
      // Open to the sky: the document's sun reaches in, the sky adds a soft fill and closes the view past the back wall.
      this.root.add(new AmbientLight('#ffffff', 0.8 * preset.intensity))
      const sky = roomSky(room)
      if (sky) this.root.add(skyDome(sky, Math.min(150, 6 * Math.max(width, depth, height))))
    } else {
      // A closed ceiling blocks the outdoor sun; light the interior independently.
      const fill = new AmbientLight('#ffffff', 1.2 * preset.intensity)
      this.key = new PointLight(preset.color, 35 * preset.intensity, 2 * Math.max(width, depth, height))
      this.keyIntensity = this.key.intensity
      this.key.position.set(0, height - 0.15, depth * 0.12)
      this.root.add(fill, this.key)
    }
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
  /** What the key light is multiplied by at this scene second. */
  breath(seconds: number) { return this.breathing ? keyLightBreath(seconds) : 1 }
  /** The sun's share of the breathing: outdoors the sun is the key light, indoors the lamp breathes instead. */
  sunBreath(seconds: number) { return this.key ? 1 : this.breath(seconds) }
  /** Every painted frame, preview or export: the lamp at this second, then the video skins at theirs. */
  async seek(seconds: number) {
    if (this.key) this.key.intensity = this.keyIntensity * this.breath(seconds)
    await Promise.all(this.screens.map(({ runtime, screen }) => runtime.seek(seconds, screen)))
  }
  dispose() {
    this.abort.abort(); this.screens.forEach(({ runtime }) => runtime.dispose()); this.root.removeFromParent()
    this.root.traverse(object => { if (object instanceof Mesh) { object.geometry.dispose(); const mat = object.material as MeshStandardMaterial; mat.map?.dispose(); mat.dispose() } })
  }
}

export const SKY_DOME = 'room-sky'

/** An unlit dome from the horizon colour at eye level to the zenith colour overhead, centred on the room. */
export function skyDome(sky: RoomSky, radius: number): Mesh {
  const geometry = new SphereGeometry(radius, 32, 16)
  const zenith = new Color(sky.zenith), horizon = new Color(sky.horizon), colour = new Color()
  const positions = geometry.attributes.position, colours = new Float32Array(positions.count * 3)
  for (let i = 0; i < positions.count; i++) {
    const up = Math.max(0, positions.getY(i) / radius)
    colour.copy(horizon).lerp(zenith, Math.sqrt(up)).toArray(colours, i * 3)
  }
  geometry.setAttribute('color', new BufferAttribute(colours, 3))
  const dome = new Mesh(geometry, new MeshBasicMaterial({ vertexColors: true, side: BackSide, depthWrite: false, fog: false }))
  dome.name = SKY_DOME; dome.renderOrder = -1; dome.frustumCulled = false
  return dome
}
