import { cameraEyeAtTime } from './camera.ts'
import { DirectionMemory, directionalPosition, directionalView, spriteFrame, type V2 } from './directionalSprite.ts'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types.ts'

/** The slot-side half of a directional figure (`screen.directional`): where it stands, and what the camera pass of
 * `paintWorld` paints. The choice of the drawing is `directionalSprite.ts`; this only feeds it the document. */
export const isDirectional = (slot: Scene3DSlot): boolean => slot.media === 'image' && Boolean(slot.screen?.directional)

/** The slot where its walk has put it at `t`; any other slot as it came. */
export function walkedSlot(posed: Scene3DSlot, placed: Vec3, t: number): Scene3DSlot {
  const directional = isDirectional(posed) ? posed.screen?.directional : undefined
  if (!directional?.walk) return posed
  return { ...posed, position: [...directionalPosition(directional, placed, t)] as unknown as Vec3 }
}

export type DirectionalFrame = { memory: DirectionMemory; eye: Vec3; eye0: V2; t: number }

/** The ground point the camera of the start of the shot stands on, which a heading is read against. */
export function referenceEye(document: Scene3DDocument): V2 {
  const eye = cameraEyeAtTime(document.camera, 0, document.duration, document.slots)
  return [eye[0], eye[2]]
}

/** The slot to paint once the camera is known: turned toward it, with the drawing its angle asks for in
 * `screen.directional.view` (a copy: the document is never written to). Its `scale` is the half height of the figure, as for any
 * cutout (`heightM / 2`); the plane of the sheets is the cell, so it is that much taller than the figure inside it. */
export function facingSlot(posed: Scene3DSlot, placed: Vec3, frame: DirectionalFrame): Scene3DSlot {
  const screen = posed.screen!, directional = screen.directional!
  const { view } = directionalView(directional, { start: [placed[0], placed[2]], eye0: frame.eye0, eye: [frame.eye[0], frame.eye[2]], t: frame.t, memory: frame.memory, id: posed.id })
  const cell = directional.sheets.length ? spriteFrame(directional).figure : 1
  return { ...posed, scale: posed.scale / cell, rotationY: Math.atan2(frame.eye[0] - posed.position[0], frame.eye[2] - posed.position[2]), screen: { ...screen, directional: { ...directional, view } } }
}
