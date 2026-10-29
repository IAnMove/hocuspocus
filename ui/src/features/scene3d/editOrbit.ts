import { Box3, Vector3, type Object3D } from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { EditView } from './editCamera'
import { renderWorld, type GpuWorld } from './gpu'

/** Orbit, zoom and pan on the edit camera. It never writes the shot document. */
export function createEditOrbit(world: GpuWorld) {
  const orbit = new OrbitControls(world.camera, world.renderer.domElement)
  orbit.enabled = false
  orbit.enableDamping = false
  orbit.target.set(0, 1, 0)
  let free = false
  let gizmoDragging = false
  let held: EditView | null = null
  const aim = new Vector3()
  const applyEnabled = () => { orbit.enabled = free && !gizmoDragging && !world.exporting }
  const capture = (): EditView => ({
    eye: [world.camera.position.x, world.camera.position.y, world.camera.position.z],
    look: [orbit.target.x, orbit.target.y, orbit.target.z],
    fov: world.camera.fov,
  })
  const redraw = () => { if (!world.exporting) renderWorld(world) }
  orbit.addEventListener('change', redraw)
  return {
    setFree(next: boolean) {
      if (next && !free) {
        world.camera.getWorldDirection(aim)
        orbit.target.copy(world.camera.position).addScaledVector(aim, 3)
        orbit.update()
      }
      free = next
      world.freeView = next
      applyEnabled()
    },
    setGizmoDragging(value: boolean) {
      gizmoDragging = value
      applyEnabled()
    },
    pose(): EditView | null {
      return free && !held ? capture() : null
    },
    frame(root?: Object3D) {
      if (!free) return
      const target = new Vector3(0, 1, 0)
      if (root) new Box3().setFromObject(root).getCenter(target)
      const back = world.camera.position.clone().sub(orbit.target)
      if (back.lengthSq() < 1e-8) back.set(0, 0.4, 3)
      const distance = Math.max(1.5, back.length())
      orbit.target.copy(target)
      world.camera.position.copy(target).add(back.normalize().multiplyScalar(distance))
      orbit.update()
    },
    hold() {
      held = free ? capture() : null
      if (!held) return
      world.freeView = false
      orbit.enabled = false
    },
    resume() {
      if (!held) return
      world.camera.position.set(held.eye[0], held.eye[1], held.eye[2])
      orbit.target.set(held.look[0], held.look[1], held.look[2])
      world.camera.fov = held.fov
      world.freeView = true
      held = null
      applyEnabled()
      orbit.update()
    },
    dispose() {
      orbit.removeEventListener('change', redraw)
      orbit.dispose()
    },
  }
}
