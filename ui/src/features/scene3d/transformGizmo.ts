import { Object3D, Raycaster, Vector2 } from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { worldAnchorOffsetFromSlotRoot, worldSfxIdFromObject } from '../sceneFx/worldRuntime'
import { renderWorld, type GpuWorld } from './gpu'
import type { Scene3DSlot } from './types'
import type { WorldSfx } from '../sceneFx/world'

export type TransformMode = 'translate' | 'rotate' | 'scale'
export type TransformPatch = Partial<Pick<Scene3DSlot, 'position' | 'rotationY' | 'scale'>> & {
  worldRotation?: [number, number, number]
  anchorOffset?: { x: number; y: number; z: number }
}

export const WORLD_SFX_SELECT_PREFIX = 'wsfx:'

export function transformPatch(proxy: Object3D, mode: TransformMode, axis: string | null, worldAxes = false): TransformPatch {
  if (mode === 'translate') return { position: [proxy.position.x, proxy.position.y, proxy.position.z] }
  if (mode === 'rotate') {
    if (worldAxes) return { worldRotation: [proxy.rotation.x, proxy.rotation.y, proxy.rotation.z] }
    return { rotationY: proxy.rotation.y }
  }
  const value = axis === 'Y' ? proxy.scale.y : axis === 'Z' ? proxy.scale.z : proxy.scale.x
  return { scale: Math.max(0.05, Math.min(worldAxes ? 20 : 100, value)) }
}

/** A document-space proxy keeps GLB normalization and animation bones separate
 * from user transforms. Helpers never become part of an exported scene. */
export function createTransformGizmo(world: GpuWorld, onChange: (id: string, patch: TransformPatch) => void, onSelect: (id: string) => void) {
  const canvas = world.renderer.domElement
  const proxy = new Object3D()
  const controls = new TransformControls(world.camera, canvas)
  controls.setSize(0.85)
  const helper = controls.getHelper()
  world.scene.add(proxy, helper)
  let selectedId: string | null = null
  let worldAxes = false
  let allowed = true
  let mode: TransformMode = 'translate'
  let attachedAnchorSlotId: string | undefined
  const redraw = () => renderWorld(world)
  let uniformScale = 1
  const objectChange = () => {
    if (!allowed || !selectedId) return
    const patch = transformPatch(proxy, mode, controls.axis, worldAxes)
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
  const raycaster = new Raycaster()
  const select = (event: PointerEvent) => {
    if (!allowed || controls.axis || event.button !== 0) return
    const rect = canvas.getBoundingClientRect()
    raycaster.setFromCamera(new Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), world.camera)
    const slotTargets = [...world.slots.entries()].filter(([, slot]) => slot.kind === 'model')
    const worldTargets = [...(world.worldSfx?.values() ?? [])].filter(item => item.root.visible).map(item => item.root)
    const hits = raycaster.intersectObjects([...worldTargets, ...slotTargets.map(([, slot]) => slot.root)], true)
    const hit = hits[0]
    if (!hit) return
    const worldId = worldSfxIdFromObject(hit.object)
    if (worldId) { onSelect(WORLD_SFX_SELECT_PREFIX + worldId); return }
    const selected = slotTargets.find(([, slot]) => {
      let object: Object3D | null = hit.object
      while (object) { if (object === slot.root) return true; object = object.parent }
      return false
    })
    if (selected) onSelect(selected[0])
  }
  controls.addEventListener('change', redraw)
  controls.addEventListener('objectChange', objectChange)
  controls.addEventListener('mouseUp', finishDrag)
  canvas.addEventListener('pointerdown', select)
  return {
    sync(slot: Scene3DSlot | undefined, nextMode: TransformMode, enabled: boolean, worldCue?: WorldSfx) {
      allowed = enabled
      mode = nextMode
      controls.enabled = enabled
      if ((!slot && !worldCue) || slot?.media === 'image' || !enabled) { controls.pointerUp(null); controls.detach(); return }
      worldAxes = Boolean(worldCue)
      attachedAnchorSlotId = worldCue?.anchor?.slotId
      const id = worldCue ? WORLD_SFX_SELECT_PREFIX + worldCue.id : slot!.id
      if (selectedId !== id) controls.pointerUp(null)
      selectedId = id
      if (!controls.dragging) {
        if (worldCue) {
          const posed = world.worldSfx?.get(worldCue.id)?.root.userData.gizmoAt as { x: number; y: number; z: number } | undefined
          if (posed && Number.isFinite(posed.x) && Number.isFinite(posed.y) && Number.isFinite(posed.z)) {
            proxy.position.set(posed.x, posed.y, posed.z)
          } else proxy.position.set(worldCue.position.x, worldCue.position.y, worldCue.position.z)
          proxy.rotation.set(worldCue.rotation.x * Math.PI / 180, worldCue.rotation.y * Math.PI / 180, worldCue.rotation.z * Math.PI / 180)
          proxy.scale.setScalar(worldCue.scale)
        } else {
          proxy.position.fromArray(slot!.position)
          proxy.rotation.set(0, slot!.rotationY, 0)
          proxy.scale.setScalar(slot!.scale)
        }
        proxy.updateMatrixWorld(true)
      }
      controls.setMode(mode)
      controls.showX = worldAxes || mode !== 'rotate'
      controls.showY = true
      controls.showZ = worldAxes || mode !== 'rotate'
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
