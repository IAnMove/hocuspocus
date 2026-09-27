import { Mesh, MeshStandardMaterial, Raycaster, Vector2, Vector3, type Camera, type Intersection, type Object3D } from 'three'
import { faceMeshes, manualFace } from './calibration'
import type { FacePlacement } from './types'
import { restFaceHit } from './faceCoordinates'
import { isGeneratedScreenPlane } from '../screenPlane'

/** Interpolate ORIGINAL vertices using barycentrics on the currently posed triangle. */
export function placementAtHit(root: Object3D, hit: Intersection, previous?: FacePlacement): FacePlacement | undefined {
  const mesh = hit.object
  if (!(mesh instanceof Mesh) || Array.isArray(mesh.material) || !(mesh.material instanceof MeshStandardMaterial) || !hit.face) return undefined
  const rest = restFaceHit(hit)?.point
  if (!rest) return undefined
  const meshIndex = faceMeshes(root).indexOf(mesh)
  if (meshIndex < 0) return undefined
  mesh.geometry.computeBoundingBox()
  const bounds = mesh.geometry.boundingBox!.clone(), extent = bounds.getSize(new Vector3()).length()
  const fits = previous && bounds.expandByScalar(extent * .1).containsPoint(new Vector3().fromArray(previous.center)) && Math.max(...previous.size) <= extent
  const initial = fits && previous.meshIndex === meshIndex ? previous : manualFace(mesh)
  if (!initial) return undefined
  const delta = rest.clone().sub(new Vector3().fromArray(initial.center))
  const moveEye = (eye: readonly [number, number, number]) => new Vector3().fromArray(eye).add(delta).toArray()
  return { ...initial, meshIndex, center: rest.toArray(), eyes: { ...initial.eyes, left: moveEye(initial.eyes.left), right: moveEye(initial.eyes.right) } }
}

export function pickFace(root: Object3D, camera: Camera, canvas: HTMLCanvasElement, x: number, y: number, previous?: FacePlacement) {
  const rect = canvas.getBoundingClientRect()
  const ray = new Raycaster()
  root.updateMatrixWorld(true); camera.updateMatrixWorld(true)
  ray.setFromCamera(new Vector2((x - rect.left) / rect.width * 2 - 1, 1 - (y - rect.top) / rect.height * 2), camera)
  // Only this subject participates; clicking another actor cannot edit it.
  const hit = ray.intersectObject(root, true).find(item => !isGeneratedScreenPlane(item.object))
  return hit ? placementAtHit(root, hit, previous) : undefined
}
