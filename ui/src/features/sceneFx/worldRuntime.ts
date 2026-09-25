import { Box3, BoxGeometry, Group, Mesh, MeshBasicMaterial, Object3D, Points, Scene, ShaderMaterial, Vector3, VideoTexture } from 'three'
import { buildEnergyEffect } from './energyObjects'
import { poseLightning } from './lightningMesh'
import { bindPortalMedia, type PortalMediaRuntime } from './portalMediaRuntime'
import { worldSfxAtTime } from './worldMotion'
import { fxRandom } from './types'
import { WORLD_BEAM_KINDS, type WorldSfx, type WorldSfxAnchor, type WorldVec3 } from './world'

export type WorldSfxGpu = { root: Group; kind: WorldSfx['kind']; color: string; sourceUrl?: string; media?: PortalMediaRuntime; mediaProjection?: string; mediaAspect?: number }
export type WorldSlotPose = {
  id: string
  position: readonly [number, number, number]
  rotationY: number
  scale?: number
  root?: Object3D
}
const DEG = Math.PI / 180
const UP = new Vector3(0, 1, 0)
const scratch = new Vector3()
const scratchB = new Vector3()

function disposeRoot(root: Group) {
  root.traverse(child => {
    if (!(child instanceof Mesh) && !(child instanceof Points)) return
    child.geometry.dispose()
    const materials = Array.isArray(child.material) ? child.material : [child.material]
    materials.forEach(material => material.dispose())
  })
}
function build(kind: WorldSfx['kind'], color: string) {
  const root = buildEnergyEffect(kind, color)
  const marker = new Mesh(new BoxGeometry(.12, .12, .12), new MeshBasicMaterial({ color: 0xff4466 }))
  marker.userData.kind = 'missing'; marker.visible = false
  root.add(marker)
  return root
}

export function worldAnchorOffsetFromSlotRoot(
  root: Object3D,
  point: readonly [number, number, number],
): WorldVec3 {
  root.updateMatrixWorld(true)
  const local = root.worldToLocal(new Vector3(point[0], point[1], point[2]))
  return { x: local.x, y: local.y, z: local.z }
}

function resolvePoint(anchor: WorldSfxAnchor | undefined, fallback: WorldVec3, slots: readonly WorldSlotPose[]): { point: Vector3; missing: boolean } {
  if (!anchor?.slotId) return { point: new Vector3(fallback.x, fallback.y, fallback.z), missing: false }
  const slot = slots.find(item => item.id === anchor.slotId)
  if (!slot) return { point: new Vector3(fallback.x, fallback.y, fallback.z), missing: true }
  const ox = anchor.offset?.x ?? 0, oy = anchor.offset?.y ?? 0, oz = anchor.offset?.z ?? 0
  if (slot.root) {
    slot.root.updateMatrixWorld(true)
    return { point: slot.root.localToWorld(new Vector3(ox, oy, oz)), missing: false }
  }
  const cos = Math.cos(slot.rotationY), sin = Math.sin(slot.rotationY)
  return {
    point: new Vector3(slot.position[0] + ox * cos + oz * sin, slot.position[1] + oy, slot.position[2] - ox * sin + oz * cos),
    missing: false,
  }
}

function orientBetween(object: Object3D, from: Vector3, to: Vector3, radial = 1) {
  const dir = scratch.copy(to).sub(from)
  const len = Math.max(0.08, dir.length())
  object.position.copy(from).add(to).multiplyScalar(0.5)
  object.quaternion.setFromUnitVectors(UP, scratchB.copy(dir).multiplyScalar(1 / len))
  object.scale.set(radial, len, radial)
}

function poseFixed(root: Group, cue: WorldSfx, origin: Vector3) {
  root.position.copy(origin)
  root.rotation.set(cue.rotation.x * DEG, cue.rotation.y * DEG, cue.rotation.z * DEG)
  root.scale.setScalar(cue.scale)
}

function poseAura(root: Group, cue: WorldSfx, origin: Vector3, slots: readonly WorldSlotPose[]) {
  const slot = cue.anchor?.slotId ? slots.find(item => item.id === cue.anchor!.slotId) : undefined
  if (slot?.root) {
    slot.root.updateMatrixWorld(true)
    const box = new Box3().setFromObject(slot.root)
    if (!box.isEmpty()) {
      box.getCenter(root.position)
      const size = box.getSize(scratch)
      const span = Math.max(size.x, size.y, size.z, 0.6)
      root.scale.setScalar(span * 0.85 * cue.scale)
      return
    }
  }
  poseFixed(root, cue, origin)
}

function poseBeam(root: Group, cue: WorldSfx, from: Vector3, to: Vector3, seconds: number) {
  const radial = cue.kind === 'laser' ? 0.55 * cue.scale : cue.scale
  if (cue.kind === 'lightning') { poseLightning(root, cue, from, to, seconds); return }
  const shaft = root.children.find(child => child.userData.kind === 'beam')
  if (shaft) orientBetween(shaft, from, to, radial)
}

function poseMissiles(root: Group, cue: WorldSfx, from: Vector3, to: Vector3, local: number, span: number) {
  const progress = Math.min(1, local / span)
  const kids = root.children.filter(child => child.userData.kind === 'missile')
  kids.forEach((bolt, index) => {
    const t = Math.min(1, Math.max(0, progress * 1.15 - index * 0.12))
    bolt.position.copy(from).lerp(to, t)
    bolt.scale.setScalar(cue.scale * (0.7 + 0.3 * t))
    bolt.visible = progress < 0.98
  })
  const impact = root.children.find(child => child.userData.kind === 'impact')
  if (impact instanceof Mesh) {
    impact.position.copy(to)
    const material = impact.material as MeshBasicMaterial
    const burst = Math.max(0, (progress - 0.82) / 0.18)
    material.opacity = burst * 0.7 * cue.intensity
    impact.scale.setScalar(cue.scale * (0.4 + burst * 1.8))
  }
}

function animateMaterials(child: Mesh | Points, cue: WorldSfx, local: number, span: number) {
  const materials = Array.isArray(child.material) ? child.material : [child.material]
  for (const material of materials) {
    if (material instanceof MeshBasicMaterial && material.userData.energyBaseColor) {
      material.color.copy(material.userData.energyBaseColor).multiplyScalar(cue.intensity)
    }
    if (!(material instanceof ShaderMaterial)) continue
    const uniforms = material.uniforms
    if (uniforms.uTime) uniforms.uTime.value = local
    if (uniforms.uPower) {
      const p = Math.min(1, local / span)
      uniforms.uPower.value = child.parent?.userData.kind === 'plume'
        ? cue.intensity * Math.min(1, Math.max(0, p - 0.28) * 1.8) * 0.65
        : cue.intensity
    }
    if (uniforms.uSeed) uniforms.uSeed.value = cue.seed + (child.userData.seedOffset ?? 0)
    if (uniforms.uProgress) uniforms.uProgress.value = Math.min(1, local / span)
    if (uniforms.uMap?.value instanceof VideoTexture) uniforms.uMap.value.needsUpdate = true
  }
  if (child instanceof Mesh && cue.kind === 'explosion') {
    const p = Math.min(1, local / span)
    if (child.userData.kind === 'fireball') child.scale.setScalar(0.55 + Math.sin(Math.min(1, p * 1.35) * Math.PI) * 0.95)
    if (child.userData.kind === 'flash') child.scale.setScalar(Math.max(0.2, 1.8 * (1 - p * 1.35)))
  }
}

function animateParticles(child: Points, cue: WorldSfx, local: number, span: number) {
  const geometry = child.geometry
  const base = geometry.getAttribute('base')
  const position = geometry.getAttribute('position')
  if (!base || !position) return
  for (let i = 0; i < position.count; i++) {
    const bx = base.getX(i), by = base.getY(i), bz = base.getZ(i)
    if (child.userData.kind === 'rise' || child.userData.kind === 'shockdust') {
      const climb = (local * (0.35 + cue.intensity * 0.25) + fxRandom(cue.seed, i) * 1.2) % 1.4
      position.setXYZ(i, bx * (1 + (child.userData.kind === 'shockdust' ? local * 0.4 : 0)), climb, bz * (1 + (child.userData.kind === 'shockdust' ? local * 0.4 : 0)))
    } else if (child.userData.kind === 'fall') {
      const speed = cue.kind === 'snow' ? 0.45 : 1.55
      const y = ((by - local * speed) % 3.2 + 3.2) % 3.2
      const sway = Math.sin(local * (cue.kind === 'snow' ? 1.1 : 4) + i) * (cue.kind === 'snow' ? 0.14 : 0.02)
      position.setXYZ(i, bx + sway, y, bz)
    } else if (child.userData.kind === 'drift') {
      position.setXYZ(i, bx + Math.sin(local * 0.3 + i) * 0.2, by + Math.sin(local * 0.5 + i) * 0.12, bz)
    } else if (child.userData.kind === 'spin') {
      const spin = local * 1.7
      const cos = Math.cos(spin), sin = Math.sin(spin)
      position.setXYZ(i, bx * cos - bz * sin, by, bx * sin + bz * cos)
    } else if (child.userData.kind === 'burst') {
      const p = Math.min(1, local / span)
      const expand = Math.pow(p, 0.36) * (3.8 + cue.intensity * 1.4)
      const drag = 1 - p * 0.28
      position.setXYZ(i, bx * expand * drag, by * expand * drag - p * p * 1.7, bz * expand * drag)
    } else if (child.userData.kind === 'fountain') {
      // Ballistic sparks: launched from the base, pulled down, relaunched.
      const period = .7 + fxRandom(cue.seed, i + 300) * .6
      const life = ((local + fxRandom(cue.seed, i + 400) * period) % period) / period
      const speed = 1.6 + fxRandom(cue.seed, i + 500) * 1.4 * cue.intensity
      const t = life * period
      const y = speed * t - 4.2 * t * t
      position.setXYZ(i, bx * t * 1.4, y < 0 || life > .92 ? -40 : y, bz * t * 1.4)
    } else if (child.userData.kind === 'orb') {
      const spin = local * 1.4
      const cos = Math.cos(spin), sin = Math.sin(spin)
      position.setXYZ(i, bx * cos - bz * sin, by + Math.sin(local * 5 + i) * 0.04, bx * sin + bz * cos)
    } else {
      const spin = local * (0.7 + cue.intensity * 0.4)
      const cos = Math.cos(spin), sin = Math.sin(spin)
      position.setXYZ(i, bx * cos - bz * sin, by + Math.sin(local * 6 + i) * 0.02, bx * sin + bz * cos)
    }
  }
  position.needsUpdate = true
}

function animatePuff(child: Mesh, cue: WorldSfx, local: number) {
  const life = (local * .16 + child.userData.phase) % 1
  child.position.set(Math.sin(life * 4 + child.userData.seedOffset) * .18 + life * .35, .15 + life * 2.6, 0)
  child.scale.setScalar(.45 + life * 1.5)
  const material = child.material as ShaderMaterial
  if (material.uniforms?.uPower) material.uniforms.uPower.value = cue.intensity * Math.sin(life * Math.PI) * 1.3
}

function animate(root: Group, cue: WorldSfx, seconds: number) {
  const local = Math.max(0, seconds - cue.start)
  const span = Math.max(.001, cue.end - cue.start)
  root.traverse(child => {
    if (child instanceof Mesh && child.userData.kind === 'puff') { animateMaterials(child, cue, local, span); animatePuff(child, cue, local); return }
    if (child instanceof Mesh || child instanceof Points) animateMaterials(child, cue, local, span)
    if (cue.kind === 'explosion' && child.userData.kind === 'plume') {
      const p = Math.min(1, local / span)
      child.visible = p > 0.28
      child.position.y = 0.18 + Math.max(0, p - 0.28) * 0.9
    }
    if (child instanceof Points) animateParticles(child, cue, local, span)
  })
}

function sameWorldMedia(gpu: WorldSfxGpu, cue: WorldSfx, aspect: number) {
  return gpu.kind === cue.kind && gpu.color === cue.color && gpu.sourceUrl === cue.sourceUrl
    && gpu.mediaProjection === cue.mediaProjection && Math.abs((gpu.mediaAspect ?? 1) - aspect) <= .005
}

function ensureWorldSfx(scene: Scene, nodes: Map<string, WorldSfxGpu>, cue: WorldSfx, mediaAspect: number) {
  const previous = nodes.get(cue.id)
  if (previous && sameWorldMedia(previous, cue, mediaAspect)) return previous
  if (previous) { scene.remove(previous.root); previous.media?.dispose(); disposeRoot(previous.root) }
  const gpu: WorldSfxGpu = { root: build(cue.kind, cue.color), kind: cue.kind, color: cue.color, sourceUrl: cue.sourceUrl, mediaProjection: cue.mediaProjection, mediaAspect }
  gpu.root.userData.worldSfxId = cue.id
  if (cue.kind === 'media_portal') gpu.media = bindPortalMedia(gpu.root, cue.sourceUrl, mediaAspect)
  scene.add(gpu.root); nodes.set(cue.id, gpu)
  return gpu
}

function syncPortalProjection(gpu: WorldSfxGpu, cue: WorldSfx, viewport: { width: number; height: number }) {
  const glass = gpu.root.children.find(child => child.userData.kind === 'portalMedia')
  if (!(glass instanceof Mesh) || !(glass.material instanceof ShaderMaterial)) return
  glass.material.uniforms.uViewport.value.set(viewport.width, viewport.height)
  glass.material.uniforms.uScreenSpace.value = cue.mediaProjection === 'screen' ? 1 : 0
}

function poseWorldCue(gpu: WorldSfxGpu, cue: WorldSfx, seconds: number, slots: readonly WorldSlotPose[]) {
    const origin = resolvePoint(cue.anchor, cue.position, slots)
    const destination = WORLD_BEAM_KINDS.has(cue.kind)
      ? resolvePoint(cue.target, cue.targetPosition ?? { x: cue.position.x, y: cue.position.y, z: cue.position.z + 2.2 }, slots)
      : origin
    gpu.root.userData.gizmoAt = origin.point.clone()
    const missing = origin.missing || destination.missing
    const marker = gpu.root.children.find(child => child.userData.kind === 'missing')
    if (marker) marker.visible = missing
    if (cue.kind === 'anime_aura') poseAura(gpu.root, cue, origin.point, slots)
    else if (cue.kind === 'arcane_missiles') poseMissiles(gpu.root, cue, origin.point, destination.point, Math.max(0, seconds - cue.start), Math.max(0.001, cue.end - cue.start))
    else if (WORLD_BEAM_KINDS.has(cue.kind)) poseBeam(gpu.root, cue, origin.point, destination.point, seconds)
    else poseFixed(gpu.root, cue, origin.point)
}

export function syncWorldSfx(
  scene: Scene,
  nodes: Map<string, WorldSfxGpu> | undefined,
  cues: readonly WorldSfx[] | undefined,
  seconds: number,
  slots: readonly WorldSlotPose[],
  viewport = { width: 1, height: 1 },
) {
  if (!scene || !nodes || typeof nodes.set !== 'function') return
  const entries = cues ?? []
  const live = new Set(entries.map(cue => cue.id))
  for (const [id, gpu] of nodes) {
    if (live.has(id)) continue
    scene.remove(gpu.root)
    gpu.media?.dispose()
    disposeRoot(gpu.root)
    nodes.delete(id)
  }
  for (const sourceCue of entries) {
    const cue = worldSfxAtTime(sourceCue, seconds)
    const mediaAspect = cue.mediaProjection === 'screen' ? viewport.width / viewport.height : 1
    const gpu = ensureWorldSfx(scene, nodes, cue, mediaAspect)
    syncPortalProjection(gpu, cue, viewport)
    const active = seconds >= cue.start && seconds < cue.end
    gpu.root.visible = active
    poseWorldCue(gpu, cue, seconds, slots)
    if (gpu.media) void gpu.media.seek(worldSfxMediaTime(cue, seconds), cue.mediaPlayback).catch(error => { gpu.media!.error = error })
    if (active) animate(gpu.root, cue, seconds)
  }
}

export function worldSfxIdFromObject(object: { userData?: { worldSfxId?: string }; parent?: unknown } | null): string | undefined {
  let current = object as { userData?: { worldSfxId?: string }; parent?: unknown } | null
  while (current) {
    if (typeof current.userData?.worldSfxId === 'string') return current.userData.worldSfxId
    current = current.parent as typeof current
  }
  return undefined
}

export function worldSfxWorldPosition(cue: WorldSfx): Vector3 {
  return scratch.set(cue.position.x, cue.position.y, cue.position.z)
}

/** Hold before/after the cue; seeking backwards restores the same media frame. */
export function worldSfxMediaTime(cue: WorldSfx, seconds: number) {
  return Math.max(0, Math.min(seconds - cue.start, cue.end - cue.start))
}

export function worldSfxMediaReady(nodes: Map<string, WorldSfxGpu> | undefined, cues: readonly WorldSfx[] = []) {
  return cues.every(cue => {
    if (cue.kind !== 'media_portal' || !cue.sourceUrl) return true
    const gpu = nodes?.get(cue.id)
    if (!gpu || gpu.sourceUrl !== cue.sourceUrl || gpu.kind !== cue.kind || gpu.mediaProjection !== cue.mediaProjection) return false
    if (gpu.media?.error) throw gpu.media.error
    return Boolean(gpu.media?.ready)
  })
}

export async function prepareWorldSfxMedia(nodes: Map<string, WorldSfxGpu> | undefined, cues: readonly WorldSfx[] = [], seconds: number) {
  await Promise.all(cues.map(cue => nodes?.get(cue.id)?.media?.seek(worldSfxMediaTime(cue, seconds), cue.mediaPlayback)))
}
