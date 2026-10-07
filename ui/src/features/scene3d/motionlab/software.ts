import { Color, Mesh, PerspectiveCamera, Points, Vector3, type Object3D } from 'three'
import { cameraEyeAtTime, cameraLookAtTime } from '../camera'
import { shakeCamera } from '../cameraShake'
import type { Scene3DDocument } from '../types'
import type { SoftwareFrame } from '../softwareRender'
import { buildMotionLab, motionLabSky } from './runtime'
import { isMotionLab } from './types'

type Vertex = { x: number; y: number; z: number }
function clipDepth(polygon: Vector3[], z: number, keepLess: boolean): Vector3[] {
  const result: Vector3[] = []
  polygon.forEach((b, index) => {
    const a = polygon[(index + polygon.length - 1) % polygon.length]
    const aIn = keepLess ? a.z <= z : a.z >= z, bIn = keepLess ? b.z <= z : b.z >= z
    if (aIn !== bIn) result.push(a.clone().lerp(b, (z - a.z) / (b.z - a.z)))
    if (bIn) result.push(b)
  })
  return result
}
function project(point: Vector3, camera: PerspectiveCamera, frame: SoftwareFrame): Vertex {
  const ndc = point.clone().applyMatrix4(camera.projectionMatrix)
  return { x: (ndc.x * .5 + .5) * frame.width, y: (-ndc.y * .5 + .5) * frame.height, z: ndc.z }
}
function edge(a: Vertex, b: Vertex, x: number, y: number) { return (x - a.x) * (b.y - a.y) - (y - a.y) * (b.x - a.x) }
function put(frame: SoftwareFrame, depth: Float32Array, x: number, y: number, z: number, color: Color) {
  const index = y * frame.width + x
  if (z >= depth[index]) return
  depth[index] = z
  frame.pixels[index * 4] = Math.round(color.r * 255)
  frame.pixels[index * 4 + 1] = Math.round(color.g * 255)
  frame.pixels[index * 4 + 2] = Math.round(color.b * 255)
}
function triangle(frame: SoftwareFrame, depth: Float32Array, vertices: Vertex[], color: Color) {
  const [a, b, c] = vertices, area = edge(a, b, c.x, c.y)
  if (Math.abs(area) < .00001 || vertices.some(vertex => vertex.z < -1.000001 || vertex.z > 1.000001)) return
  const x0 = Math.max(0, Math.floor(Math.min(a.x, b.x, c.x))), x1 = Math.min(frame.width - 1, Math.ceil(Math.max(a.x, b.x, c.x)))
  const y0 = Math.max(0, Math.floor(Math.min(a.y, b.y, c.y))), y1 = Math.min(frame.height - 1, Math.ceil(Math.max(a.y, b.y, c.y)))
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const wa = edge(b, c, x + .5, y + .5) / area, wb = edge(c, a, x + .5, y + .5) / area, wc = 1 - wa - wb
    if (wa >= 0 && wb >= 0 && wc >= 0) put(frame, depth, x, y, wa * a.z + wb * b.z + wc * c.z, color)
  }
}
function visible(object: Object3D) {
  for (let node: Object3D | null = object; node; node = node.parent) if (!node.visible) return false
  return true
}

/** Diagnostic CPU rasterization of the actual native meshes/Points, not slot placeholder boxes.
 * Shadows, transparency, tone mapping and postprocessing remain exclusive to the WebGL renderer. */
export function renderMotionLabSoftware(document: Scene3DDocument, seconds: number): SoftwareFrame | null {
  if (!isMotionLab(document.dressing)) return null
  const handle = buildMotionLab(document.dressing, document.motionLab)
  if (!handle) return null
  try {
    const width = 160, height = Math.max(1, Math.round(width * document.height / document.width))
    const frame = { width, height, pixels: new Uint8Array(width * height * 4) }, depth = new Float32Array(width * height).fill(Infinity)
    const sky = new Color(motionLabSky(document.dressing)).convertLinearToSRGB()
    for (let index = 0; index < width * height; index++) { frame.pixels.set([sky.r * 255, sky.g * 255, sky.b * 255, 255], index * 4) }
    const raw = cameraEyeAtTime(document.camera, seconds, document.duration, document.slots)
    const posed = shakeCamera(document.camera.shake, seconds, raw, cameraLookAtTime(document.camera, seconds, document.duration, document.slots))
    const camera = new PerspectiveCamera(document.camera.fov, width / height, .1, 200)
    camera.position.set(...posed.eye); camera.lookAt(...posed.look); camera.rotateZ(posed.roll); camera.updateMatrixWorld(true)
    handle.update(seconds); handle.root.updateMatrixWorld(true)
    const light = new Vector3(.4, .8, .6).normalize(), position = new Vector3()
    handle.root.traverse(object => {
      if ((! (object instanceof Mesh) && !(object instanceof Points)) || !visible(object)) return
      const attribute = object.geometry.getAttribute('position')
      if (!attribute) return
      const projected: Vertex[] = [], world: Vector3[] = [], view: Vector3[] = []
      for (let index = 0; index < attribute.count; index++) {
        position.fromBufferAttribute(attribute, index).applyMatrix4(object.matrixWorld)
        world.push(position.clone()); position.applyMatrix4(camera.matrixWorldInverse); view.push(position.clone())
        projected.push(project(position, camera, frame))
      }
      const materials = Array.isArray(object.material) ? object.material : [object.material]
      // Diagnostic rasterization has no alpha pass. Do not turn glass/soft beams into opaque walls.
      if (materials.every(material => material.transparent && material.opacity < .5)) return
      const primary = materials[0] as { color?: Color }
      const base = primary.color?.clone() ?? new Color('#ffffff')
      if (object instanceof Points) {
        const colors = object.geometry.getAttribute('color')
        projected.forEach((point, index) => {
          const x = Math.round(point.x), y = Math.round(point.y)
          if (point.z < -1 || point.z > 1 || x < 0 || y < 0 || x >= width || y >= height) return
          const color = colors ? new Color().fromArray(colors.array, index * 3) : base.clone()
          put(frame, depth, x, y, point.z, color.convertLinearToSRGB())
        })
        return
      }
      const indices = object.geometry.index, length = indices?.count ?? attribute.count
      for (let index = 0; index < length; index += 3) {
        const ids = [0, 1, 2].map(offset => indices ? indices.getX(index + offset) : index + offset)
        const normal = new Vector3().subVectors(world[ids[1]], world[ids[0]]).cross(new Vector3().subVectors(world[ids[2]], world[ids[0]])).normalize()
        const color = base.clone().multiplyScalar(.45 + .55 * Math.abs(normal.dot(light))).convertLinearToSRGB()
        // Clip in camera space before projection: a sea crossing the near plane must stay visible.
        const clipped = clipDepth(clipDepth(ids.map(id => view[id]), -camera.near, true), -camera.far, false)
        const vertices = clipped.map(point => project(point, camera, frame))
        for (let fan = 1; fan < vertices.length - 1; fan++) triangle(frame, depth, [vertices[0], vertices[fan], vertices[fan + 1]], color)
      }
    })
    return frame
  } finally { handle.dispose() }
}
