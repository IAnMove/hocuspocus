import type { Scene3DCamera, Scene3DDocument, Vec3 } from './types'

export type EditView = { eye: Vec3; look: Vec3; fov: number }

/** The edit view is not the shot. Passing no view leaves the document untouched. */
export function applyEditCamera(document: Scene3DDocument, view: EditView | null): Scene3DDocument {
  if (!view) return document
  return { ...document, camera: commitEditView(document.camera, view) }
}

/** Write the shot from the edit view. The family becomes fixed so the pose is what plays. */
export function commitEditView(camera: Scene3DCamera, view: EditView): Scene3DCamera {
  return {
    ...camera,
    family: 'fixed',
    eye: view.eye,
    look: view.look,
    fov: view.fov,
    framing: undefined,
  }
}

/** Keep the current offset and aim it at a target. The shot camera is not an input. */
export function framedView(eye: Vec3, look: Vec3, target: Vec3): { eye: Vec3; look: Vec3 } {
  const back: Vec3 = [eye[0] - look[0], eye[1] - look[1], eye[2] - look[2]]
  const distance = Math.hypot(back[0], back[1], back[2])
  const length = distance > 1e-6 ? distance : 3
  const scale = Math.max(1.5, length) / length
  return {
    eye: [target[0] + back[0] * scale, target[1] + back[1] * scale, target[2] + back[2] * scale],
    look: target,
  }
}
