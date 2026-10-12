// The named cameras of a staged room (two_shot, ots_a, ots_b, wide, close_1, close_2, entrance) in the editor.
import { adaptAuthoredCameraToFrame } from './frameFormat.ts'
import type { Scene3DCamera, Scene3DDocument, Vec3 } from './types.ts'

const NEAR = 1e-6

/** The fixed camera a room camera gives this document, adapted to a portrait frame as a remounted stage is. */
export function roomCameraPose(document: Scene3DDocument, id: string): Scene3DCamera | undefined {
  const named = document.room?.mold.cameras.find(camera => camera.id === id)
  if (!named) return undefined
  return adaptAuthoredCameraToFrame({ family: 'fixed', eye: [...named.position], look: [...named.lookAt], fov: named.fov }, document.width, document.height)
}

/** Look through a room camera: the same fixed pose `stageRoomSet` gives it, remembered as `room.camera`.
 *  Shake windows are timing, not position, so they stay. An unknown id leaves the document alone. */
export function withRoomCamera(document: Scene3DDocument, id: string): Scene3DDocument {
  const pose = roomCameraPose(document, id)
  if (!pose || !document.room) return document
  const shake = document.camera.shake
  return { ...document, room: { ...document.room, camera: id }, camera: shake?.length ? { ...pose, shake } : pose }
}

const same = (a: Vec3, b: Vec3) => a.every((value, index) => Math.abs(value - b[index]) < NEAR)

/** The room camera the document looks through now, or '' once another family or a hand-made pose replaced it. */
export function activeRoomCamera(document: Scene3DDocument): string {
  const id = document.room?.camera ?? 'two_shot'
  const pose = roomCameraPose(document, id)
  const camera = document.camera
  if (!pose || camera.family !== 'fixed') return ''
  return same(camera.eye, pose.eye) && same(camera.look, pose.look) && Math.abs(camera.fov - pose.fov) < NEAR ? id : ''
}
