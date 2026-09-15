import { CinematicRuntime } from './cinematicRuntime'
import { MaterializationRuntime } from './materialization'
import { framingPose } from './framing'
import { SpeechFaceRuntime } from './speech/runtime'
import { FACE_PACK_SCREEN_ERROR, FacePackRuntime } from './speech/facePack'
import { screenGeometry } from './screenGeometry'
import type { ScreenMediaRuntime } from './screenMediaRuntime'
import { framingAnchor } from './framingAnchor'
import {
  AnimationMixer,
  BackSide,
  Box3,
  BoxGeometry,
  CanvasTexture,
  CircleGeometry,
  ClampToEdgeWrapping,
  Color,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  HemisphereLight,
  LoopOnce,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PCFSoftShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  RepeatWrapping,
  Scene,
  SRGBColorSpace,
  Vector3,
  WebGLRenderer,
  type Material,
  type Texture,
} from 'three'
import type { GLTF } from 'three/addons/loaders/GLTFLoader.js'
import { cameraEyeAtTime, cameraLookAtTime } from './camera.ts'
import { performanceClipTime, slotPoseAtTime } from './performance.ts'
import { cylinderUvOffset, isCylinderBackdrop, slotMountKey } from './backdrop.ts'
import { scene3dSlotColor } from './document.ts'
import { paintDrive } from './driveMotion.ts'
import { applyTypingPose, resetTypingPose } from './typingPose.ts'
import { paintWorkshop } from './workshopSet.ts'
import { paintCitadel } from './citadelSet.ts'
import { paintActionSet } from './actionSets.ts'
import type { Scene3DClipCatalogEntry, Scene3DDocument, Scene3DLight, Scene3DSlot } from './types.ts'
import { syncWorldSfx, type WorldSfxGpu } from '../sceneFx/worldRuntime'

export const CYLINDER_RADIUS = 12
export const CYLINDER_HEIGHT = 18

export const MAX_VIEW_WIDTH = 1280
export const MAX_VIEW_HEIGHT = 720
export const MAX_PIXEL_RATIO = 1.25

export type SlotGpu = {
  sourceUrl: string
  mountKey: string
  clipKey: string
  root: Object3D
  baseScale: number
  animations: GLTF['animations']
  mixer: AnimationMixer | null
  kind: 'model' | 'image'
  loopTexture: Texture | null
  loopSpeed: number
  looping: boolean
  loaded: boolean
  contactShadow?: Mesh
  appearance?: MaterializationRuntime
  speechFace?: SpeechFaceRuntime
  facePack?: FacePackRuntime
  screen?: ScreenMediaRuntime
  screenAbort?: AbortController
  screenError?: Error
}

export type GpuWorld = {
  cinema?: CinematicRuntime
  renderer: WebGLRenderer
  scene: Scene
  camera: PerspectiveCamera
  dir: DirectionalLight
  floor: Mesh
  dressing: Object3D | null
  dressingReady: boolean
  driveWheels: Mesh[]
  driveRoad: Texture | null
  driveMovers: Object3D[]
  driveSpeed: number
  slots: Map<string, SlotGpu>
  worldSfx?: Map<string, WorldSfxGpu>
}

export function clipKeyOf(clip: Scene3DSlot['clip']): string {
  return clip ? `${clip.index}\0${clip.name}` : ''
}

export function catalogFromClips(animations: GLTF['animations']): Scene3DClipCatalogEntry[] {
  return animations.map((clip: { name: string; duration: number }, index: number) => ({
    index,
    name: clip.name,
    durationSeconds: Number.isFinite(clip.duration) && clip.duration > 0 ? clip.duration : null,
  }))
}

function isTexture(value: unknown): value is Texture {
  return Boolean(value && typeof value === 'object' && 'isTexture' in value)
}

export function disposeMaterial(material: Material) {
  material.dispose()
  for (const value of Object.values(material)) {
    if (isTexture(value)) value.dispose()
  }
}

export function disposeObject(object: Object3D) {
  object.traverse((child: Object3D) => {
    if (!(child instanceof Mesh)) return
    child.geometry.dispose()
    const materials = Array.isArray(child.material) ? child.material : [child.material]
    for (const material of materials) disposeMaterial(material)
  })
}

export function viewSize(host: HTMLElement) {
  const width = host.clientWidth || 640
  const height = host.clientHeight || 360
  const portrait = height > width
  const maxW = portrait ? MAX_VIEW_HEIGHT : MAX_VIEW_WIDTH
  const maxH = portrait ? MAX_VIEW_WIDTH : MAX_VIEW_HEIGHT
  const scale = Math.min(1, maxW / width, maxH / height)
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

export function applyLight(dir: DirectionalLight, light: Scene3DLight) {
  dir.color = new Color(light.color)
  dir.intensity = light.intensity
  dir.position
    .set(-light.direction[0], -light.direction[1], -light.direction[2])
    .normalize()
    .multiplyScalar(6)
}

export function prepareBackdropTexture(texture: Texture) {
  texture.wrapS = RepeatWrapping
  texture.wrapT = ClampToEdgeWrapping
  texture.colorSpace = SRGBColorSpace
  texture.needsUpdate = true
  return texture
}

export function makeStripeTexture(): Texture {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 16
  const ctx = canvas.getContext('2d')
  if (ctx) {
    for (let i = 0; i < 8; i += 1) {
      ctx.fillStyle = i % 2 ? '#4a6078' : '#1c2838'
      ctx.fillRect(i * 32, 0, 32, 16)
    }
  }
  return prepareBackdropTexture(new CanvasTexture(canvas))
}

export function imageBackdropMesh(slot: Scene3DSlot, texture: Texture | null): Mesh {
  if (texture && slot.surface && slot.surface !== 'environment') {
    texture.wrapT = RepeatWrapping
    const repeat = slot.textureRepeat ?? (slot.surface === 'floor' ? 4 : 2)
    texture.repeat.set(repeat, repeat)
    texture.needsUpdate = true
  }
  const MaterialType = slot.surface && slot.surface !== 'environment' ? MeshStandardMaterial : MeshBasicMaterial
  const material = new MaterialType({
    map: texture,
    color: texture ? 0xffffff : 0x243044,
    depthWrite: Boolean(slot.surface),
    side: isCylinderBackdrop(slot) ? BackSide : DoubleSide,
  })
  const scale = Math.max(0.05, slot.scale)
  if (isCylinderBackdrop(slot)) {
    const mesh = new Mesh(new CylinderGeometry(CYLINDER_RADIUS, CYLINDER_RADIUS, CYLINDER_HEIGHT, 48, 1, true), material)
    mesh.position.set(0, CYLINDER_HEIGHT * 0.35 * scale, 0)
    mesh.scale.setScalar(scale)
    mesh.rotation.y = slot.rotationY
    mesh.renderOrder = -1
    return mesh
  }
  const mesh = new Mesh(new PlaneGeometry(2, 1.125), material)
  mesh.rotation.order = 'YXZ'
  mesh.position.set(slot.position[0], slot.position[1] + (slot.surface === 'floor' ? 0 : 2.2), slot.position[2])
  mesh.rotation.x = slot.surface === 'floor' ? -Math.PI / 2 : 0
  mesh.rotation.y = slot.rotationY
  mesh.scale.setScalar(scale)
  mesh.renderOrder = -1
  return mesh
}

function firstMap(root: Object3D): Texture | null {
  let found: Texture | null = null
  root.traverse((child: Object3D) => {
    if (found || !(child instanceof Mesh)) return
    const material = Array.isArray(child.material) ? child.material[0] : child.material
    if (material && 'map' in material && isTexture(material.map)) found = material.map
  })
  return found
}

export function placeholderMesh(slot: Scene3DSlot) {
  if (slot.media === 'screen') return screenGeometry(slot)
  if (slot.media === 'image') {
    const texture = isCylinderBackdrop(slot) ? makeStripeTexture() : null
    return imageBackdropMesh(slot, texture)
  }
  const color = scene3dSlotColor(slot.slot)
  const mesh = new Mesh(
    new BoxGeometry(0.6, 1.6, 0.6).translate(0, 0.8, 0),
    new MeshStandardMaterial({ color: new Color(color[0] / 255, color[1] / 255, color[2] / 255) }),
  )
  mesh.position.fromArray(slot.position)
  mesh.scale.setScalar(slot.scale)
  mesh.rotation.y = slot.rotationY
  return mesh
}

export function fitGltf(root: Object3D, slot: Scene3DSlot) {
  const box = new Box3().setFromObject(root)
  const size = new Vector3()
  box.getSize(size)
  const baseScale = 1.7 / Math.max(size.y, 0.001)
  root.scale.setScalar(baseScale * slot.scale)
  root.position.set(slot.position[0], slot.position[1], slot.position[2])
  root.rotation.y = slot.rotationY
  return baseScale
}

export function bindMixer(root: Object3D, animations: GLTF['animations'], slot: Scene3DSlot) {
  if (!slot.clip) return null
  const clip = animations[slot.clip.index]
  if (!clip || clip.name !== slot.clip.name) return null
  const mixer = new AnimationMixer(root)
  const action = mixer.clipAction(clip)
  action.setLoop(LoopOnce, 1)
  action.clampWhenFinished = true
  action.play()
  return mixer
}

/** Re-enable clamped actions so seeking backwards is independent of prior paints. */
export function seekBoundMixer(mixer: AnimationMixer, clip: GLTF['animations'][number], time: number) {
  const action = mixer.clipAction(clip)
  action.paused = false
  action.enabled = true
  mixer.setTime(time)
}

export function dropSlot(world: GpuWorld, slotId: string) {
  const current = world.slots.get(slotId)
  if (!current) return
  current.mixer?.stopAllAction()
  current.appearance?.clear()
  current.speechFace?.dispose()
  current.facePack?.dispose()
  current.screenAbort?.abort()
  current.screen?.dispose()
  world.scene.remove(current.root)
  if (current.contactShadow) {
    world.scene.remove(current.contactShadow)
    disposeObject(current.contactShadow)
  }
  disposeObject(current.root)
  world.slots.delete(slotId)
}

export function placeSlot(
  world: GpuWorld,
  slot: Scene3DSlot,
  root: Object3D,
  animations: GLTF['animations'],
  baseScale = 1,
  loaded = true,
) {
  dropSlot(world, slot.id)
  world.scene.add(root)
  const contactShadow = slot.media === 'model3d' ? new Mesh(new CircleGeometry(.4, 24), new MeshBasicMaterial({ color: 0x03070d, transparent: true, opacity: .25, depthWrite: false })) : undefined
  if (contactShadow) {
    contactShadow.rotation.x = -Math.PI / 2
    world.scene.add(contactShadow)
  }
  applyMeshShadows(root, world.renderer.shadowMap.enabled, slot.media === 'model3d')
  if (contactShadow && world.renderer.shadowMap.enabled) contactShadow.visible = false
  world.slots.set(slot.id, {
    contactShadow,
    sourceUrl: slot.sourceUrl,
    mountKey: slotMountKey(slot),
    clipKey: clipKeyOf(slot.clip),
    root,
    baseScale,
    animations,
    mixer: slot.media === 'image' ? null : bindMixer(root, animations, slot),
    kind: slot.media === 'image' ? 'image' : 'model',
    loopTexture: firstMap(root),
    loopSpeed: slot.loop?.speed ?? 0,
    looping: isCylinderBackdrop(slot),
    loaded,
  })
}

function speechAssetsReady(gpu: SlotGpu | undefined, slot: Scene3DSlot): boolean {
  if (!slot.speech?.enabled) return true
  if (!slot.sourceUrl) throw new Error('Choose a 3D model before exporting a speech scene.')
  if (slot.speech.facePack) {
    if (!slot.screen) throw new Error(FACE_PACK_SCREEN_ERROR)
    if (gpu?.facePack?.error) throw gpu.facePack.error
    return Boolean(gpu?.facePack?.ready)
  }
  if (!slot.speech.face) throw new Error('Calibrate the face before exporting a speech scene.')
  if (gpu?.speechFace?.error) throw gpu.speechFace.error
  return Boolean(gpu?.speechFace?.ready)
}

function screenAssetsReady(gpu: SlotGpu | undefined, slot: Scene3DSlot): boolean {
  if (slot.screen && gpu?.mountKey !== slotMountKey(slot)) return false
  if (gpu?.screenError) throw gpu.screenError
  if (gpu?.screen?.error) throw gpu.screen.error
  if (slot.screen?.sourceUrl && !slot.speech?.facePack && !gpu?.screen?.ready) return false
  return true
}

export function worldAssetsReady(world: GpuWorld, slots: readonly Scene3DSlot[]): boolean {
  if (!world.dressingReady) return false
  return slots.every(slot => {
    const gpu = world.slots.get(slot.id)
    if (!speechAssetsReady(gpu, slot) || !screenAssetsReady(gpu, slot)) return false
    if (!slot.sourceUrl) return true
    return Boolean(gpu && gpu.mountKey === slotMountKey(slot) && gpu.loaded)
  })
}

export function clipMatches(gpu: Pick<SlotGpu, 'clipKey' | 'animations'>, index: number) {
  const clip = gpu.animations[index]
  return Boolean(clip && gpu.clipKey === `${index}\0${clip.name}`)
}

function groundLoadedSlot(gpu: SlotGpu, slot: Scene3DSlot) {
  if (slot.grounded && gpu.kind === 'model') {
    gpu.root.updateMatrixWorld(true)
    const bounds = new Box3().setFromObject(gpu.root, true)
    if (Number.isFinite(bounds.min.y)) gpu.root.position.y += slot.position[1] - bounds.min.y
    if (gpu.contactShadow && !gpu.animations.length && !bounds.isEmpty()) {
      const size = bounds.getSize(new Vector3()), center = bounds.getCenter(new Vector3())
      gpu.contactShadow.position.set(center.x, slot.position[1] + .025, center.z)
      gpu.contactShadow.scale.set(Math.max(.1, size.x), Math.max(.1, size.z), 1)
    }
  }
}

function syncActorSpeech(world: GpuWorld, gpu: SlotGpu, slot: Scene3DSlot, sceneSeconds: number) {
  if (gpu.loaded && gpu.kind === 'model' && slot.speech?.face) {
    gpu.speechFace ??= new SpeechFaceRuntime(() => renderWorld(world))
    gpu.speechFace.sync(gpu.root, slot.speech, sceneSeconds)
  } else if (gpu.speechFace && !slot.speech?.face) {
    gpu.speechFace.sync(gpu.root, undefined, sceneSeconds)
  }
  if (gpu.loaded && gpu.kind === 'model' && (slot.speech?.facePack || gpu.facePack)) {
    gpu.facePack ??= new FacePackRuntime(() => renderWorld(world))
    gpu.facePack.sync(gpu.root, slot.speech, slot.screen, sceneSeconds)
  }
}

function paintActor(world: GpuWorld, slot: Scene3DSlot, sceneSeconds: number) {
  const gpu = world.slots.get(slot.id)
  if (!gpu) return
  if (gpu.screen && slot.screen) void gpu.screen.seek(sceneSeconds, slot.screen).catch(() => {})
  poseLoadedSlot(gpu, slot)
  resetTypingPose(gpu.root)
  const clip = gpu.animations.find((_clip: { duration?: number }, index: number) => clipMatches(gpu, index))
  const local = performanceClipTime(slot.performance === 'idle' ? 0 : sceneSeconds, clip?.duration ?? null, slot.clipPlayback)
  if (local != null && clip && gpu.mixer) seekBoundMixer(gpu.mixer, clip, local)
  if (slot.performance === 'idle' && clip && gpu.mixer) {
    gpu.root.updateMatrixWorld(true)
    const center = new Box3().setFromObject(gpu.root, true).getCenter(new Vector3())
    gpu.root.position.x += slot.position[0] - center.x; gpu.root.position.z += slot.position[2] - center.z
    gpu.root.rotation.y += Math.sin(sceneSeconds * .8) * .025
  }
  groundLoadedSlot(gpu, slot)
  if (slot.performance === 'typing') applyTypingPose(gpu.root, slot, sceneSeconds)
  syncActorSpeech(world, gpu, slot, sceneSeconds)
  if (slot.appearance || gpu.appearance) {
    gpu.appearance ??= new MaterializationRuntime()
    gpu.appearance.sync(gpu.root, slot.appearance, sceneSeconds)
    if (gpu.contactShadow) gpu.contactShadow.visible = gpu.root.visible
  }
  if (gpu.contactShadow && world.renderer.shadowMap.enabled) gpu.contactShadow.visible = false
}

export function paintWorld(world: GpuWorld, document: Scene3DDocument, sceneSeconds: number) {
  const posedSlots = document.slots.map(slot => ({ ...slot, ...slotPoseAtTime(slot, sceneSeconds, document.duration) }))
  applyLoopOffset(world, sceneSeconds)
  paintCitadel(world.dressing, sceneSeconds)
  paintWorkshop(world.dressing, sceneSeconds, document.workshopScreen)
  paintActionSet(world.dressing, sceneSeconds)
  const bg = document.slots.find(isCylinderBackdrop)
  paintDrive(world, sceneSeconds, bg?.loop?.speed ?? world.driveSpeed)
  for (const slot of posedSlots) paintActor(world, slot, sceneSeconds)
  const framing = document.camera.framing
  const target = posedSlots.find(slot => slot.id === framing?.targetSlot)
  const root = target && world.slots.get(target.id)?.root
  const shot = framing && target && root ? framingPose(framing, framingAnchor(root, framing.anchor), target, sceneSeconds, document.duration) : null
  const eye = shot?.eye ?? cameraEyeAtTime(document.camera, sceneSeconds, document.duration, posedSlots)
  const look = shot?.look ?? cameraLookAtTime(document.camera, sceneSeconds, document.duration, posedSlots)
  world.camera.fov = document.camera.fov
  world.camera.position.set(...eye)
  world.camera.lookAt(...look)
  if (shot) world.camera.rotateZ(shot.roll)
  world.camera.updateProjectionMatrix()
  world.worldSfx ??= new Map()
  if (world.scene) {
    syncWorldSfx(world.scene, world.worldSfx, document.worldSfx, sceneSeconds, posedSlots.map(slot => ({
      id: slot.id,
      position: slot.position,
      rotationY: slot.rotationY,
      scale: slot.scale,
      root: world.slots.get(slot.id)?.root,
    })))
  }
  if (world.cinema || document.environment || document.worldSfx?.length || document.slots.some(s => s.surface === 'environment')) {
    world.cinema ??= new CinematicRuntime(world)
    world.cinema.sync(document, sceneSeconds)
    world.cinema.render(document)
  } else world.renderer.render(world.scene, world.camera)
}

export function setWorldSize(world: GpuWorld, width: number, height: number) {
  world.renderer.setPixelRatio(1)
  world.renderer.setSize(Math.max(2, width), Math.max(2, height), false)
  world.camera.aspect = Math.max(2, width) / Math.max(2, height)
  world.camera.updateProjectionMatrix()
}

export function applyLoopOffset(world: GpuWorld, sceneSeconds: number) {
  for (const gpu of world.slots.values()) {
    if (!gpu.loopTexture) continue
    gpu.loopTexture.offset.x = gpu.looping ? cylinderUvOffset(sceneSeconds, gpu.loopSpeed) : 0
  }
}

export function syncSlotClip(world: GpuWorld, slot: Scene3DSlot) {
  const current = world.slots.get(slot.id)
  if (!current) return
  const nextKey = clipKeyOf(slot.clip)
  if (current.clipKey === nextKey) return
  resetTypingPose(current.root)
  current.mixer?.stopAllAction()
  current.mixer = bindMixer(current.root, current.animations, slot)
  current.clipKey = nextKey
}

export function slotNeedsReload(current: SlotGpu | undefined, slot: Scene3DSlot): boolean {
  return !current || current.mountKey !== slotMountKey(slot)
}

export function pruneSlots(world: GpuWorld, slots: readonly Scene3DSlot[]) {
  const wanted = new Set(slots.map(slot => slot.id))
  for (const id of [...world.slots.keys()]) {
    if (!wanted.has(id)) dropSlot(world, id)
  }
}

function applyMeshShadows(root: Object3D, enabled: boolean, cast: boolean) {
  root.traverse((child: Object3D) => {
    if (!(child instanceof Mesh)) return
    child.castShadow = enabled && cast
    child.receiveShadow = enabled
  })
}

export function setWorldExportQuality(world: GpuWorld, enabled: boolean) {
  world.renderer.shadowMap.enabled = enabled
  world.renderer.shadowMap.type = PCFSoftShadowMap
  world.dir.castShadow = enabled
  world.floor.receiveShadow = enabled
  if (enabled) {
    world.dir.shadow.mapSize.set(2048, 2048)
    world.dir.shadow.bias = -0.0006
    world.dir.shadow.normalBias = 0.02
    const cam = world.dir.shadow.camera
    cam.near = 0.4
    cam.far = 48
    cam.left = -14
    cam.right = 14
    cam.top = 14
    cam.bottom = -14
    cam.updateProjectionMatrix()
  }
  applyMeshShadows(world.floor, enabled, false)
  if (world.dressing) applyMeshShadows(world.dressing, enabled, true)
  for (const gpu of world.slots.values()) {
    applyMeshShadows(gpu.root, enabled, gpu.kind === 'model')
    if (gpu.contactShadow) gpu.contactShadow.visible = !enabled
  }
}

export function createWorld(host: HTMLDivElement, light: Scene3DLight, fov: number): GpuWorld {
  const renderer = new WebGLRenderer({
    antialias: true,
    alpha: false,
    powerPreference: 'high-performance',
    preserveDrawingBuffer: true,
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO))
  renderer.shadowMap.enabled = false
  renderer.domElement.style.display = 'block'
  renderer.domElement.style.width = '100%'
  renderer.domElement.style.height = '100%'
  host.append(renderer.domElement)
  const scene = new Scene()
  scene.background = new Color(0x10141c)
  const camera = new PerspectiveCamera(fov, 16 / 9, 0.05, 200)
  scene.add(new HemisphereLight(0xc8d8ff, 0x2a2118, 0.55))
  const dir = new DirectionalLight(light.color, light.intensity)
  applyLight(dir, light)
  scene.add(dir)
  const floor = new Mesh(
    new CircleGeometry(11.5, 48),
    new MeshStandardMaterial({ color: 0x1c222c, roughness: 0.92 }),
  )
  floor.rotation.x = -Math.PI / 2
  floor.name = 'world-floor'
  scene.add(floor)
  return {
    renderer, scene, camera, dir, floor, dressing: null, dressingReady: true,
    driveWheels: [], driveRoad: null, driveMovers: [], driveSpeed: 0,
    slots: new Map(),
    worldSfx: new Map(),
  }
}

export function disposeWorld(world: GpuWorld) {
  world.cinema?.dispose()
  for (const id of [...world.slots.keys()]) dropSlot(world, id)
  if (world.scene && world.worldSfx) syncWorldSfx(world.scene, world.worldSfx, [], 0, [])
  disposeObject(world.scene)
  world.renderer.dispose()
  world.renderer.forceContextLoss()
  world.renderer.domElement.remove()
}

export function resizeWorld(world: GpuWorld, host: HTMLDivElement) {
  const size = viewSize(host)
  world.renderer.setSize(size.width, size.height, false)
  world.camera.aspect = size.width / size.height
  world.camera.updateProjectionMatrix()
}

export function poseLoadedSlot(current: SlotGpu, slot: Scene3DSlot) {
  if (current.contactShadow) {
    current.contactShadow.position.set(slot.position[0], slot.position[1] + .025, slot.position[2])
    current.contactShadow.scale.set(slot.scale, slot.scale * .65, 1)
  }
  current.loopSpeed = slot.loop?.speed ?? 0
  current.looping = isCylinderBackdrop(slot)
  const scale = Math.max(0.05, slot.scale)
  if (current.kind === 'image' && isCylinderBackdrop(slot)) {
    current.root.position.set(0, CYLINDER_HEIGHT * 0.35 * scale, 0)
    current.root.rotation.y = slot.rotationY
    current.root.scale.setScalar(scale)
    return
  }
  if (current.kind === 'image') {
    current.root.rotation.order = 'YXZ'
    current.root.position.set(slot.position[0], slot.position[1] + (slot.surface === 'floor' ? 0 : 2.2), slot.position[2])
    current.root.rotation.x = slot.surface === 'floor' ? -Math.PI / 2 : 0
    current.root.rotation.y = slot.rotationY
    current.root.scale.setScalar(scale)
    return
  }
  current.root.position.set(slot.position[0], slot.position[1], slot.position[2])
  current.root.rotation.y = slot.rotationY
  current.root.scale.setScalar(current.baseScale * slot.scale)
}

/** All interaction/media redraws share preview and export postprocessing. */
export function renderWorld(world: GpuWorld) {
  if (world.cinema) world.cinema.render()
  else world.renderer.render(world.scene, world.camera)
}
