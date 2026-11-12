import { Object3D } from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { worldAnchorOffsetFromSlotRoot } from '../sceneFx/worldRuntime'
import { renderWorld, type GpuWorld } from './gpu'
import { parseHold } from './handHold'
import { pickSceneId, WORLD_SFX_SELECT_PREFIX } from './scenePick'
import { slotTilt } from './slotTilt'
import type { Scene3DSlot } from './types'
import type { WorldSfx } from '../sceneFx/world'

export { WORLD_SFX_SELECT_PREFIX }

export type TransformMode = 'translate' | 'rotate' | 'scale' | 'select'
export type TransformPatch = Partial<Pick<Scene3DSlot, 'position' | 'rotationX' | 'rotationY' | 'rotationZ' | 'scale'>> & {
  worldRotation?: [number, number, number]
  anchorOffset?: { x: number; y: number; z: number }
}

export function transformPatch(proxy: Object3D, mode: TransformMode, axis: string | null, worldAxes = false, tilt = true): TransformPatch {
  if (mode === 'select') return {}
  if (mode === 'translate') return { position: [proxy.position.x, proxy.position.y, proxy.position.z] }
  if (mode === 'rotate') {
    if (worldAxes) return { worldRotation: [proxy.rotation.x, proxy.rotation.y, proxy.rotation.z] }
    if (!tilt) return { rotationY: proxy.rotation.y }
    return { rotationX: proxy.rotation.x, rotationY: proxy.rotation.y, rotationZ: proxy.rotation.z }
  }
  const value = axis === 'Y' ? proxy.scale.y : axis === 'Z' ? proxy.scale.z : proxy.scale.x
  return { scale: Math.max(0.05, Math.min(worldAxes ? 20 : 100, value)) }
}

function poseGizmoProxy(proxy: Object3D, world: GpuWorld, slot: Scene3DSlot | undefined, worldCue: WorldSfx | undefined, tilt: boolean) {
  if (worldCue) {
    const posed = world.worldSfx?.get(worldCue.id)?.root.userData.gizmoAt as { x: number; y: number; z: number } | undefined
    if (posed && [posed.x, posed.y, posed.z].every(Number.isFinite)) proxy.position.set(posed.x, posed.y, posed.z)
    else proxy.position.set(worldCue.position.x, worldCue.position.y, worldCue.position.z)
    proxy.rotation.set(worldCue.rotation.x * Math.PI / 180, worldCue.rotation.y * Math.PI / 180, worldCue.rotation.z * Math.PI / 180)
    proxy.scale.setScalar(worldCue.scale)
    return
  }
  proxy.position.fromArray(slot!.position)
  const [tiltX, tiltY, tiltZ] = slotTilt(slot!)
  proxy.rotation.set(tilt ? tiltX : 0, tiltY, tilt ? tiltZ : 0)
  proxy.scale.setScalar(slot!.scale)
}

/** The gizmo rests for an empty selection, a locked backdrop, or a prop parented to a hand. */
function gizmoRests(slot: Scene3DSlot | undefined, worldCue: WorldSfx | undefined, enabled: boolean) {
  if (!enabled || (!slot && !worldCue)) return true
  if (slot?.media === 'image' && (slot.surface === 'environment' || slot.loop?.cylinder === true)) return true
  return Boolean(slot && parseHold(slot.hold, slot.id))
}

/** A document-space proxy keeps GLB normalization and animation bones separate
 * from user transforms. Helpers never become part of an exported scene. */
export function createTransformGizmo(
  world: GpuWorld,
  onChange: (id: string, patch: TransformPatch) => void,
  onSelect: (id: string) => void,
  onDragging?: (dragging: boolean) => void,
) {
  const canvas = world.renderer.domElement
  const proxy = new Object3D()
  const controls = new TransformControls(world.camera, canvas)
  controls.setSize(0.85)
  const helper = controls.getHelper()
  world.scene.add(proxy, helper)
  let selectedId: string | null = null
  let worldAxes = false
  let tilt = true
  let allowed = true
  let mode: TransformMode = 'translate'
  let attachedAnchorSlotId: string | undefined
  const redraw = () => renderWorld(world)
  let uniformScale = 1
  const objectChange = () => {
    if (!allowed || !selectedId) return
    const patch = transformPatch(proxy, mode, controls.axis, worldAxes, tilt)
    if (patch.scale !== undefined) uniformScale = patch.scale
    if (attachedAnchorSlotId && patch.position) {
      const root = world.slots.get(attachedAnchorSlotId)?.root
      if (root) {
        const local = worldAnchorOffsetFromSlotRoot(root, patch.position)
        if ([local.x, local.y, local.z].every(Number.isFinite)) patch.anchorOffset = local
      }
    }
    onChange(selectedId, patch)
  }
  const finishDrag = () => { if (mode === 'scale') proxy.scale.setScalar(uniformScale) }
  const select = (event: PointerEvent) => {
    if (!allowed || controls.axis || event.button !== 0) return
    onSelect(pickSceneId(world, event.clientX, event.clientY))
  }
  controls.addEventListener('dragging-changed', event => {
    onDragging?.(Boolean((event as { value?: boolean }).value))
  })
  controls.addEventListener('change', redraw)
  controls.addEventListener('objectChange', objectChange)
  controls.addEventListener('mouseUp', finishDrag)
  canvas.addEventListener('pointerdown', select)
  return {
    sync(slot: Scene3DSlot | undefined, nextMode: TransformMode, enabled: boolean, worldCue?: WorldSfx) {
      mode = nextMode
      allowed = enabled && nextMode !== 'select'
      controls.enabled = allowed
      if (nextMode === 'select' || gizmoRests(slot, worldCue, enabled)) { controls.pointerUp(null); controls.detach(); return }
      worldAxes = Boolean(worldCue)
      tilt = worldAxes || slot?.media !== 'image'
      attachedAnchorSlotId = worldCue?.anchor?.slotId
      const id = worldCue ? WORLD_SFX_SELECT_PREFIX + worldCue.id : slot!.id
      if (selectedId !== id) controls.pointerUp(null)
      selectedId = id
      if (!controls.dragging) {
        poseGizmoProxy(proxy, world, slot, worldCue, tilt)
        proxy.updateMatrixWorld(true)
      }
      controls.setMode(nextMode)
      controls.showX = worldAxes || tilt || mode !== 'rotate'
      controls.showY = true
      controls.showZ = worldAxes || tilt || mode !== 'rotate'
      controls.attach(proxy)
    },
    hide() { allowed = false; controls.pointerUp(null); controls.enabled = false; controls.detach() },
    dispose() {
      canvas.removeEventListener('pointerdown', select)
      controls.removeEventListener('change', redraw)
      controls.removeEventListener('objectChange', objectChange)
      controls.removeEventListener('mouseUp', finishDrag)
      controls.detach()
      controls.dispose()
      world.scene.remove(proxy, helper)
    },
  }
}
