import { cameraEyeAtTime } from './camera.ts'
import { DirectionMemory, LIGHT_TINT, directionalPosition, directionalView, lightTint, spriteFrame, type V2 } from './directionalSprite.ts'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types.ts'

/** The slot-side half of a directional figure (`screen.directional`): where it stands, and what the camera pass of
 * `paintWorld` paints. The choice of the drawing is `directionalSprite.ts`; this only feeds it the document. */
export type Tint = readonly [number, number, number]

export const isDirectional = (slot: Scene3DSlot): boolean => slot.media === 'image' && Boolean(slot.screen?.directional)
/** A figure drawn from sheets (the others turn and walk in the one picture they have). */
export const hasSheets = (slot: Pick<Scene3DSlot, 'screen'>): boolean => Boolean(slot.screen?.directional?.sheets.length)
/** The first pass of a frame has no camera yet, so it leaves a directional figure for the camera pass. */
export const awaitsView = (slot: Pick<Scene3DSlot, 'screen'>): boolean => Boolean(slot.screen?.directional && !slot.screen.directional.view)

/** The slot where its walk has put it at `t`, and as big as its sheets' plane needs: `scale` is the half height of the figure, as for any
 * cutout (`heightM / 2`), and the plane of the sheets is the cell, so it is that much taller than the figure inside it. Done in the first
 * pass, so a camera that frames the figure measures the plane it will be painted on. Any other slot as it came. */
export function walkedSlot(posed: Scene3DSlot, placed: Vec3, t: number): Scene3DSlot {
  const directional = isDirectional(posed) ? posed.screen?.directional : undefined
  if (!directional) return posed
  const cell = directional.sheets.length ? spriteFrame(directional).figure : 1
  const position = directional.walk ? [...directionalPosition(directional, placed, t)] as unknown as Vec3 : posed.position
  return cell === 1 && !directional.walk ? posed : { ...posed, position, scale: posed.scale / cell }
}

export type DirectionalFrame = { memory: DirectionMemory; eye: Vec3; eye0: V2; t: number }

/** The ground point the camera of the start of the shot stands on, which a heading is read against. */
export function referenceEye(document: Scene3DDocument): V2 {
  const eye = cameraEyeAtTime(document.camera, 0, document.duration, document.slots)
  return [eye[0], eye[2]]
}

/** The slot to paint once the camera is known: turned toward it, with the drawing its angle asks for in
 * `screen.directional.view` (a copy: the document is never written to). */
export function facingSlot(posed: Scene3DSlot, placed: Vec3, frame: DirectionalFrame): Scene3DSlot {
  const screen = posed.screen!, directional = screen.directional!
  const { view } = directionalView(directional, { start: [placed[0], placed[2]], eye0: frame.eye0, eye: [frame.eye[0], frame.eye[2]], t: frame.t, memory: frame.memory, id: posed.id })
  return { ...posed, rotationY: Math.atan2(frame.eye[0] - posed.position[0], frame.eye[2] - posed.position[2]), screen: { ...screen, directional: { ...directional, view } } }
}

/** What a sprite is multiplied by to sit in the key light of the scene. */
export function tintOf(slot: Scene3DSlot, light: Scene3DDocument['light']): Tint | undefined {
  const directional = slot.screen?.directional
  return directional?.sheets.length ? lightTint(light.color, light.intensity, directional.lightTint ?? LIGHT_TINT) : undefined
}

/** The camera pass of a frame, once the eye is known: every directional figure turned to it with its drawing, and every cutout
 * that asked to be a billboard turned to it. `paint` draws a slot (and its tint, for a sprite). */
export function cameraPass(document: Scene3DDocument, posed: readonly Scene3DSlot[], frame: Omit<DirectionalFrame, 'eye0'>, paint: (slot: Scene3DSlot, tint?: Tint) => void) {
  const eye0 = posed.some(isDirectional) ? referenceEye(document) : [0, 0] as const
  posed.forEach((slot, index) => {
    if (isDirectional(slot)) {
      const facing = facingSlot(slot, document.slots[index].position, { ...frame, eye0 })
      paint(facing, tintOf(facing, document.light))
    } else if (slot.billboard && slot.media === 'image') paint({ ...slot, rotationY: Math.atan2(frame.eye[0] - slot.position[0], frame.eye[2] - slot.position[2]) })
  })
}
