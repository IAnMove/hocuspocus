import { ACESFilmicToneMapping, Color, CylinderGeometry, Group, Mesh, MeshStandardMaterial, NoToneMapping, PlaneGeometry, PointLight, ShaderMaterial, TorusGeometry, UniformsUtils, Vector2, type IUniform, type Texture } from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { ENERGY_NOISE } from '../sceneFx/energyShaders'
import type { GpuWorld } from './gpu'
import type { Scene3DDocument } from './types'

/** Shared preview/export pipeline. No frame delta, random state or private assets. */
export class CinematicRuntime {
  private mirror?: Reflector
  private platform?: Group
  private composer?: EffectComposer
  private bloom?: UnrealBloomPass
  private lights: PointLight[] = []
  private background?: Texture
  private source?: Texture
  private size = new Vector2()
  private document?: Scene3DDocument
  private world: GpuWorld
  constructor(world: GpuWorld) { this.world = world }

  private createMirror() {
    const reflectorShader = (Reflector as unknown as { ReflectorShader: { uniforms: Record<string, IUniform>; vertexShader: string } }).ReflectorShader
    const shader = {
      uniforms: UniformsUtils.clone(reflectorShader.uniforms),
      vertexShader: reflectorShader.vertexShader.replace('varying vec4 vUv;', 'varying vec4 vUv; varying vec3 groundPos;')
        .replace('vUv = textureMatrix', 'groundPos=(modelMatrix*vec4(position,1.)).xyz; vUv = textureMatrix'),
      fragmentShader: `uniform vec3 color; uniform sampler2D tDiffuse; varying vec4 vUv; varying vec3 groundPos; ${ENERGY_NOISE}
      void main(){vec2 p=groundPos.xz;vec2 uv=vUv.xy/vUv.w;float grain=noise2(p*145.);
        vec3 refl=texture2D(tDiffuse,uv+vec2((grain-.5)*.0007,0.)).rgb;
        vec2 seam=abs(fract(p*vec2(.52,.35))-.5);float joint=smoothstep(.476,.495,max(seam.x,seam.y));
        float brushed=noise2(vec2(p.x*320.,p.y*4.));vec3 steel=vec3(.035,.043,.075)+brushed*.018;
        vec3 c=mix(steel,refl,.58)*(1.-joint*.63);float fade=1.-smoothstep(4.,11.,length(p));
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
    world.scene.background = this.background ?? new Color(0x10141c)
    if (this.background) {
      const image = this.background.image as { width?: number; height?: number }
      const aspect = (image.width ?? 16) / (image.height ?? 9), cameraAspect = world.camera.aspect
      this.background.repeat.set(Math.min(1, cameraAspect / aspect), Math.min(1, aspect / cameraAspect))
      this.background.offset.set((1 - this.background.repeat.x) / 2, (1 - this.background.repeat.y) / 2)
    }
    for (const s of doc.slots) if (s.surface === 'environment') {
      const gpu = world.slots.get(s.id); if (gpu) gpu.root.visible = false
    }
  }
  private syncStage(doc: Scene3DDocument) {
    const { world } = this
    if (doc.environment?.reflectiveFloor && !this.mirror) this.createMirror()
    if (this.mirror) this.mirror.visible = doc.environment?.reflectiveFloor === true
    world.floor.visible = !doc.environment?.reflectiveFloor
    if (doc.environment?.platform && !this.platform) this.createPlatform()
    if (this.platform) this.platform.visible = doc.environment?.platform === true
  }
  sync(doc: Scene3DDocument, seconds: number) {
    this.document = doc
    this.syncBackground(doc); this.syncStage(doc)
    const { world } = this
    const active = Boolean(doc?.environment || doc?.worldSfx?.length)
    world.renderer.toneMapping = active ? ACESFilmicToneMapping : NoToneMapping
    if (!active) return
    if (!this.composer) {
      this.composer = new EffectComposer(world.renderer)
      this.composer.addPass(new RenderPass(world.scene, world.camera))
      this.bloom = new UnrealBloomPass(new Vector2(1280, 720), .48, .55, 1.15)
      this.composer.addPass(this.bloom); this.composer.addPass(new OutputPass())
      // Fixed pool: many overlapping cues cannot create unbounded shader/light work.
      for (let i = 0; i < 3; i++) { const light = new PointLight(0xffffff, 0, 7, 2); world.scene.add(light); this.lights.push(light) }
    }
    this.bloom!.strength = doc.environment?.bloom ?? .48
    this.syncLights(doc, seconds)
  }
  private syncLights(doc: Scene3DDocument, seconds: number) {
    const { world } = this
    const glowing = (doc.worldSfx ?? []).filter(cue => seconds >= cue.start && seconds < cue.end && cue.kind !== 'smoke').slice(0, 3)
    this.lights.forEach((light, i) => {
      const cue = glowing[i], gpu = cue && world.worldSfx?.get(cue.id)
      light.intensity = cue ? Math.min(9, cue.intensity * (cue.kind === 'lightning' ? 6 : 2)) * (.8 + .2 * Math.sin(seconds * 31) ** 2) : 0
      if (cue && gpu) { light.color.set(cue.color); light.position.copy(gpu.root.userData.gizmoAt ?? gpu.root.position); light.position.y += .3 }
    })
  }
  render(doc = this.document) {
    const { renderer, scene, camera } = this.world
    if (this.composer && (doc?.environment || doc?.worldSfx?.length)) {
      const size = renderer.getDrawingBufferSize(new Vector2())
      if (!size.equals(this.size)) {
        this.size.copy(size); this.composer.setPixelRatio(1); this.composer.setSize(size.x, size.y)
        this.mirror?.getRenderTarget().setSize(Math.min(1280, size.x), Math.min(720, size.y))
      }
      this.composer.render(0)
    } else { this.lights.forEach(light => { light.intensity = 0 }); renderer.render(scene, camera) }
  }
  dispose() {
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
