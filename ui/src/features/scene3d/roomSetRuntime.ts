/** Shared preview/export room surfaces. Video uses the existing deterministic screen decoder. */
import { AmbientLight, BackSide, BufferAttribute, BufferGeometry, CanvasTexture, Color, DoubleSide, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, PlaneGeometry, PointLight, RepeatWrapping, SphereGeometry, SRGBColorSpace, TextureLoader, type Texture } from 'three'
import { hasAmbientLife, isExterior, keyLightBreath, roomLightPreset, roomPanels, roomSky, type RoomPanel, type RoomSet, type RoomSky } from './roomSet'
import { defaultMediaScreen, type MediaScreen } from './mediaScreen'
import { bindScreenMedia, type ScreenMediaRuntime } from './screenMediaRuntime'
import { isFacePattern, isRoomPattern, patternTexture, PATTERN_TILE_M } from './roomPatterns'
import { DEFAULT_SPEED_MPS, drawRoomView, isRoomView, isWallView, viewRole, viewSize, type RoomView, type ViewRole } from './roomViews'

type LiveView = { ctx: CanvasRenderingContext2D; texture: CanvasTexture; width: number; height: number; view: RoomView; role: ViewRole; speed: number }

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
  private views = new Map<string, LiveView>()
  private patterns = new Map<string, Texture | null>()
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
      // The lamp hangs under the roof; in a low room (a vehicle cabin) 0.15 m is so close that the ceiling burns out, so it hangs at 60 % of the height there.
      this.key.position.set(0, height < 2 ? height * 0.6 : height - 0.15, depth * 0.12)
      this.root.add(fill, this.key)
    }
    void Promise.all(roomPanels(room).map(panel => this.panel(panel))).then(() => { this.ready = !this.abort.signal.aborted; this.repaint() }).catch(error => { this.error = error })
  }
  private async panel(panel: RoomPanel) {
    const geometry = new PlaneGeometry(...panel.size)
    const material = new MeshStandardMaterial({ color: panel.material.color ?? '#ffffff', roughness: 0.85, side: DoubleSide })
    const mesh = new Mesh<PlaneGeometry, MeshStandardMaterial | MeshBasicMaterial>(geometry, material)
    mesh.name = panel.id; mesh.position.fromArray(panel.position); mesh.rotation.set(...panel.rotation)
    mesh.receiveShadow = true; mesh.castShadow = true; this.root.add(mesh)
    const media = panel.material
    if (isRoomView(media.view) && panel.wall) { mesh.material = this.windowView(geometry, panel, media.view, media.speed_mps, media.seed); material.dispose(); return }
    if (isRoomPattern(media.pattern)) {
      const texture = this.pattern(media.pattern, media.seed)
      const repeat: [number, number] = isFacePattern(media.pattern) ? [1, 1] : [panel.fullSize[0] / (media.tile_m ?? PATTERN_TILE_M[media.pattern]), panel.fullSize[1] / (media.tile_m ?? PATTERN_TILE_M[media.pattern])]
      if (texture) { remapUv(geometry, panel.uv, repeat); material.map = texture; material.needsUpdate = true }
      return
    }
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
    remapUv(geometry, panel.uv); material.map = texture; material.needsUpdate = true
  }
  /** One tile per pattern and seed for the whole room: each face scales its own uv, so the texture is never copied. */
  private pattern(name: Parameters<typeof patternTexture>[0], seed = 3): Texture | null {
    const key = `${name}:${seed}`
    if (!this.patterns.has(key)) { const texture = patternTexture(name, seed); texture?.repeat.set(1, 1); this.patterns.set(key, texture) }
    return this.patterns.get(key) ?? null
  }
  /** A window onto a moving world. One canvas per wall and view paints the whole wall, so the windows of one side share it and show their own parts. */
  private windowView(geometry: PlaneGeometry, panel: RoomPanel, view: RoomView, speed = DEFAULT_SPEED_MPS, seed = 5): MeshBasicMaterial {
    const key = isWallView(view) ? `${panel.wall}:${panel.surface}` : panel.id
    let live = this.views.get(key)
    if (!live && typeof document !== 'undefined') {
      const [width, height] = viewSize(panel.fullSize[0], panel.fullSize[1]), canvas = document.createElement('canvas'), ctx = canvas.getContext('2d')
      canvas.width = width; canvas.height = height
      if (ctx) {
        const texture = new CanvasTexture(canvas); texture.colorSpace = SRGBColorSpace
        live = { ctx, texture, width, height, view, role: viewRole(panel.wall ?? 'back'), speed }
        this.views.set(key, live)
        drawRoomView(ctx, width, height, 0, view, live.role, speed, seed)
      }
    }
    remapUv(geometry, panel.uv)
    return new MeshBasicMaterial({ map: live?.texture ?? null, color: live ? '#ffffff' : '#101828', side: DoubleSide })
  }
  /** What the key light is multiplied by at this scene second. */
  breath(seconds: number) { return this.breathing ? keyLightBreath(seconds) : 1 }
  /** The sun's share of the breathing: outdoors the sun is the key light, indoors the lamp breathes instead. */
  sunBreath(seconds: number) { return this.key ? 1 : this.breath(seconds) }
  /** Every painted frame, preview or export: the lamp at this second, then the video skins at theirs. */
  async seek(seconds: number) {
    if (this.key) this.key.intensity = this.keyIntensity * this.breath(seconds)
    for (const live of this.views.values()) { drawRoomView(live.ctx, live.width, live.height, seconds, live.view, live.role, live.speed); live.texture.needsUpdate = true }
    await Promise.all(this.screens.map(({ runtime, screen }) => runtime.seek(seconds, screen)))
  }
  dispose() {
    this.abort.abort(); this.screens.forEach(({ runtime }) => runtime.dispose()); this.root.removeFromParent()
    this.root.traverse(object => { if (object instanceof Mesh) { object.geometry.dispose(); const mat = object.material as MeshStandardMaterial; mat.map?.dispose(); mat.dispose() } })
    this.views.clear(); this.patterns.clear()
  }
}

/** Map a plane's 0..1 uv onto the part `[left, bottom, right, top]` of the face it belongs to, optionally repeated `[x, y]` times over that face. */
function remapUv(geometry: BufferGeometry, [left, bottom, right, top]: [number, number, number, number], repeat: [number, number] = [1, 1]) {
  const uv = geometry.attributes.uv
  for (let i = 0; i < uv.count; i++) uv.setXY(i, (left + uv.getX(i) * (right - left)) * repeat[0], (bottom + uv.getY(i) * (top - bottom)) * repeat[1])
  uv.needsUpdate = true
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
