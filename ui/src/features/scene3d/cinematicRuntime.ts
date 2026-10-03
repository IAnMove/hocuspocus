import { EndlessRoad } from './endlessRoad'
import { ACESFilmicToneMapping, Color, CylinderGeometry, Group, Mesh, MeshStandardMaterial, NoToneMapping, PlaneGeometry, PointLight, ShaderMaterial, TorusGeometry, UniformsUtils, Vector2, type IUniform, type Texture } from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { LUTPass } from 'three/addons/postprocessing/LUTPass.js'
import { ENERGY_NOISE } from '../sceneFx/energyShaders'
import { lightningGlow } from '../sceneFx/lightningMesh'
import type { GpuWorld } from './gpu'
import type { Scene3DDocument } from './types'
import { cinematicReflectorVisible } from './cinematicSettings'
import { BackdropFloor } from './backdropFloor'
import { createPixelPass, syncPixelPass } from './pixel/pixelPass'
import type { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import type { Pass } from 'three/addons/postprocessing/Pass.js'
import { bindAtmosPasses, ensureComposerDepth, publishAtmosStats } from './atmos/composerBind.ts'
import { atmosHandle, isAtmosDressing } from './atmos/index.ts'

/** Shared preview/export pipeline. No frame delta, random state or private assets. */
export class CinematicRuntime {
  private road?: EndlessRoad
  private mirror?: Reflector
  private platform?: Group
  private composer?: EffectComposer
  private bloom?: UnrealBloomPass
  private pixel?: ShaderPass
  /** The look's LUT, applied to the display-referred frame after OutputPass. 2.F3 loads the texture. */
  private lut?: LUTPass
  private lutTexture: LUTPass['lut'] = undefined
  private lutStrength = 1
  private atmosPasses: Pass[] = []
  private lights: PointLight[] = []
  private background?: Texture
  private source?: Texture
  private size = new Vector2()
  private document?: Scene3DDocument
  private world: GpuWorld
  private backdropFloor: BackdropFloor
  constructor(world: GpuWorld) { this.world = world; this.backdropFloor = new BackdropFloor(world) }

  private createMirror() {
    const reflectorShader = (Reflector as unknown as { ReflectorShader: { uniforms: Record<string, IUniform>; vertexShader: string } }).ReflectorShader
    const shader = {
      uniforms: { ...UniformsUtils.clone(reflectorShader.uniforms), tileStrength: { value: 1 } },
      vertexShader: reflectorShader.vertexShader.replace('varying vec4 vUv;', 'varying vec4 vUv; varying vec3 groundPos;')
        .replace('vUv = textureMatrix', 'groundPos=(modelMatrix*vec4(position,1.)).xyz; vUv = textureMatrix'),
      fragmentShader: `uniform vec3 color; uniform float tileStrength; uniform sampler2D tDiffuse; varying vec4 vUv; varying vec3 groundPos; ${ENERGY_NOISE}
      void main(){vec2 p=groundPos.xz;vec2 uv=vUv.xy/vUv.w;float grain=noise2(p*145.);
        vec3 refl=texture2D(tDiffuse,uv+vec2((grain-.5)*.0007,0.)).rgb;
        vec2 seam=abs(fract(p*vec2(.52,.35))-.5);float joint=smoothstep(.476,.495,max(seam.x,seam.y));
        float brushed=noise2(vec2(p.x*320.,p.y*4.));vec3 steel=vec3(.035,.043,.075)+brushed*.018;
        vec3 c=mix(steel,refl,.58)*(1.-joint*.63*tileStrength);float fade=1.-smoothstep(4.,11.,length(p));
        gl_FragColor=vec4(c,fade*.95);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
    }
    const mirror = new Reflector(new PlaneGeometry(40, 40), { textureWidth: 1280, textureHeight: 720, clipBias: .003, shader })
    mirror.rotation.x = -Math.PI / 2; mirror.position.y = -.018
    const material = mirror.material as ShaderMaterial
    material.transparent = true; material.depthWrite = false
    this.world.scene.add(mirror); this.mirror = mirror
  }
  private createPlatform() {
    const root = new Group()
    for (const [top, bottom, height, y, color] of [[1.45, 1.6, .2, .1, 0x171925], [1.37, 1.43, .035, .214, 0x414052]]) {
      const disk = new Mesh(new CylinderGeometry(top, bottom, height, 96), new MeshStandardMaterial({ color, metalness: .72, roughness: .27 }))
      disk.position.y = y; root.add(disk)
    }
    for (const radius of [1.44, 1.59]) {
      const ring = new Mesh(new TorusGeometry(radius, .009, 8, 128), new MeshStandardMaterial({ color: '#83e8ff', emissive: '#83e8ff', emissiveIntensity: 3 }))
      ring.rotation.x = Math.PI / 2; ring.position.y = radius > 1.5 ? .025 : .195; root.add(ring)
    }
    for (let i = 0; i < 16; i++) {
      const bolt = new Mesh(new CylinderGeometry(.025, .025, .009, 8), new MeshStandardMaterial({ color: 0x88859e, metalness: .8, roughness: .3 }))
      bolt.position.set(Math.cos(i * Math.PI / 8) * 1.28, .238, Math.sin(i * Math.PI / 8) * 1.28); root.add(bolt)
    }
    this.world.scene.add(root); this.platform = root
  }
  private syncBackground(doc: Scene3DDocument) {
    const { world } = this
    const slot = doc.slots.find(s => s.surface === 'environment' && s.media === 'image')
    const texture = slot ? world.slots.get(slot.id)?.loopTexture ?? undefined : undefined
    if (texture !== this.source) {
      this.background?.dispose(); this.source = texture; this.background = texture?.clone()
      if (this.background) this.background.needsUpdate = true
    }
    world.scene.background = this.background ?? new Color(world.pixelPalette?.sky[0] ?? 0x10141c)
    this.fitBackground()
    for (const s of doc.slots) if (s.surface === 'environment') {
      const gpu = world.slots.get(s.id); if (gpu) gpu.root.visible = false
    }
  }
  private fitBackground() {
    const { world } = this
    if (this.background) {
      const image = this.background.image as { width?: number; height?: number }
      const aspect = (image.width ?? 16) / (image.height ?? 9), cameraAspect = world.camera.aspect
      this.background.repeat.set(Math.min(1, cameraAspect / aspect), Math.min(1, aspect / cameraAspect))
      this.background.offset.set((1 - this.background.repeat.x) / 2, (1 - this.background.repeat.y) / 2)
    }
  }
  private syncStage(doc: Scene3DDocument) {
    const useMirror = cinematicReflectorVisible(doc.environment)
    if (useMirror && !this.mirror) this.createMirror()
    if (this.mirror) {
      this.mirror.visible = useMirror
      ;(this.mirror.material as ShaderMaterial).uniforms.tileStrength.value = doc.environment?.floorStyle === 'mirror' ? 0 : 1
    }
    this.backdropFloor.sync(doc)
    if (doc.environment?.platform && !this.platform) this.createPlatform()
    if (this.platform) this.platform.visible = doc.environment?.platform === true
  }
  private ensureComposer() {
    if (this.composer) return
    const { world } = this
    this.composer = new EffectComposer(world.renderer)
    this.composer.addPass(new RenderPass(world.scene, world.camera))
    this.bloom = new UnrealBloomPass(new Vector2(1280, 720), .48, .55, 1.15)
    this.composer.addPass(this.bloom); this.composer.addPass(new OutputPass())
    this.lut = new LUTPass({}); this.composer.addPass(this.lut); this.applyLut()
    this.pixel = createPixelPass(); this.composer.addPass(this.pixel)
    // Fixed pool: many overlapping cues cannot create unbounded shader/light work.
    for (let i = 0; i < 3; i++) { const light = new PointLight(0xffffff, 0, 7, 2); world.scene.add(light); this.lights.push(light) }
  }
  private syncRoad(doc: Scene3DDocument, seconds: number) {
    const road = doc.environment?.floorStyle === 'road'
    if (road && !this.road) this.road = new EndlessRoad(this.world.scene)
    this.road?.sync(road, doc.environment?.road, seconds)
    if (road) this.world.floor.visible = false
  }
  sync(doc: Scene3DDocument, seconds: number) {
    this.document = doc
    this.syncBackground(doc); this.syncStage(doc)
    const active = Boolean(doc?.environment || doc?.worldSfx?.length || doc?.pixelWorld || isAtmosDressing(doc?.dressing))
    // Pixel worlds show their palette as painted; filmic curves would shift it. A scene with its own
    // look sets tone mapping in applyLook; setting it here too would flip programs every frame.
    if (!doc.look || doc.pixelWorld) this.world.renderer.toneMapping = active && !doc.pixelWorld ? ACESFilmicToneMapping : NoToneMapping
    if (!active) { this.road?.sync(false, undefined, seconds); return }
    this.ensureComposer()
    this.bloom!.strength = doc.environment?.bloom ?? .48
    const frame = this.world.renderer.getDrawingBufferSize(new Vector2())
    syncPixelPass(this.pixel!, doc.pixelWorld, frame.x, frame.y)
    this.syncRoad(doc, seconds)
    this.syncLights(doc, seconds)
    this.syncAtmos(doc, seconds)
  }
  private syncAtmos(doc: Scene3DDocument, seconds: number) {
    const handle = atmosHandle(this.world)
    if (!this.composer || !handle) {
      if (this.composer) this.atmosPasses = bindAtmosPasses(this.composer, this.atmosPasses, undefined)
      return
    }
    this.world.camera.updateMatrixWorld()
    ensureComposerDepth(this.composer)
    this.atmosPasses = bindAtmosPasses(this.composer, this.atmosPasses, handle)
    const slot = doc.slots.find(item => item.slot === 'subject_1')
    const distance = slot
      ? Math.hypot(this.world.camera.position.x - slot.position[0], this.world.camera.position.y - slot.position[1], this.world.camera.position.z - slot.position[2])
      : 3.5
    const high = this.world.renderer.shadowMap.enabled && this.world.dir.shadow.mapSize.x >= 2048
    handle.sync(seconds, this.world.camera, this.world.dir, high ? 'high' : 'low', distance > 0.4 ? distance : 3.5, doc.atmos)
  }
  /** Set or clear the look's 3D LUT; a disabled pass costs nothing and leaves the frame unchanged. */
  setLut(texture: LUTPass['lut'], strength = 1) {
    this.lutTexture = texture; this.lutStrength = Math.min(1, Math.max(0, strength))
    this.applyLut()
  }
  private applyLut() {
    if (!this.lut) return
    this.lut.lut = this.lutTexture
    this.lut.intensity = this.lutStrength
    this.lut.enabled = Boolean(this.lutTexture) && this.lutStrength > 0
  }
  detachAtmos() {
    if (!this.composer) { this.atmosPasses = []; return }
    this.atmosPasses = bindAtmosPasses(this.composer, this.atmosPasses, undefined)
  }
  private syncLights(doc: Scene3DDocument, seconds: number) {
    const { world } = this
    const glowing = (doc.worldSfx ?? []).filter(cue => seconds >= cue.start && seconds < cue.end && cue.kind !== 'smoke').slice(0, 3)
    this.lights.forEach((light, i) => {
      const cue = glowing[i], gpu = cue && world.worldSfx?.get(cue.id)
      // A strike lights the scene only while its channel is lit.
      const bolt = cue?.kind === 'lightning'
      light.intensity = !cue ? 0 : bolt ? Math.min(90, lightningGlow(cue, seconds) * 45) : Math.min(9, cue.intensity * 2) * (.8 + .2 * Math.sin(seconds * 31) ** 2)
      light.distance = bolt ? 18 : 7
      if (cue && gpu) {
        light.color.set(cue.color)
        // A bolt lights the ground it strikes, not the cloud it leaves.
        light.position.copy(gpu.root.userData.strikeAt ?? gpu.root.userData.gizmoAt ?? gpu.root.position); light.position.y += bolt ? 1.2 : .3
      }
    })
  }
  render(doc = this.document) {
    const { renderer, scene, camera } = this.world
    if (this.composer && (doc?.environment || doc?.worldSfx?.length || doc?.pixelWorld || isAtmosDressing(doc?.dressing))) {
      const size = renderer.getDrawingBufferSize(new Vector2())
      if (!size.equals(this.size)) {
        this.size.copy(size); this.composer.setPixelRatio(1); this.composer.setSize(size.x, size.y)
        ensureComposerDepth(this.composer)
        this.mirror?.getRenderTarget().setSize(Math.min(1280, size.x), Math.min(720, size.y))
      }
      this.composer.render(0)
      const handle = atmosHandle(this.world)
      if (handle) publishAtmosStats({
        calls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
        geometries: renderer.info.memory.geometries,
        textures: renderer.info.memory.textures,
      }, handle.ms)
    } else { this.lights.forEach(light => { light.intensity = 0 }); renderer.render(scene, camera) }
  }
  dispose() {
    this.road?.dispose()
    this.backdropFloor.dispose()
    this.background?.dispose()
    this.composer?.passes.forEach(pass => pass.dispose()); this.composer?.dispose()
    this.mirror?.removeFromParent(); this.mirror?.geometry.dispose(); this.mirror?.dispose()
    if (this.platform) {
      this.platform.removeFromParent()
      this.platform.traverse(child => { if (child instanceof Mesh) { child.geometry.dispose(); child.material.dispose() } })
    }
    this.lights.forEach(light => { light.removeFromParent(); light.dispose() })
  }
}
