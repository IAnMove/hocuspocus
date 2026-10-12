import { cameraPath } from './dioramaSet'
import type { ImageLook } from './imageLook'
import { slotPoseAtTime } from './performance'
import type { Scene3DDocument, Scene3DSlot } from './types'

/** fitGltf scales a model to this height times its scale; a cutout of scale 1 is a plane this tall (imageCutoutMesh). */
export const MODEL_HEIGHT = 1.7
export const CUTOUT_HEIGHT = 2
/** A picture in a model's place stands as tall as the model would, so the box the camera frames, and with it the
 * head point of a framing, is the same for both. Mirrored in app/services/world3d_scenes.py (PICTURE_SCALE). */
export const PICTURE_SCALE = MODEL_HEIGHT / CUTOUT_HEIGHT

/** What a cast entry may say about the picture it binds. */
export type PictureCast = { scale?: number; grounded?: boolean; imageLook?: ImageLook }

/** The slot a picture takes over from a 3D model: a standing cutout (a picture with no surface would be drawn as a
 * flat backdrop card, not a figure). It stands on its feet unless the cast says `grounded: false`, keeps any
 * `imageLook` the cast brings, and is as tall as the model unless the cast gives a scale or the marker was already
 * sized as a cutout (a Series room marker). A model that travels nose first would turn the flat picture edge-on along
 * its path, so the picture faces the camera instead, mirrored when the path runs to the left. */
export function pictureInModelSlot(slot: Scene3DSlot, cast: PictureCast = {}): Scene3DSlot {
  const sized = slot.surface === 'cutout'
  const next: Scene3DSlot = {
    ...slot, media: 'image', surface: 'cutout',
    imageLook: { ...(cast.grounded === false ? {} : { grounded: true }), ...cast.imageLook },
    scale: cast.scale ?? (sized ? slot.scale : Math.round(slot.scale * PICTURE_SCALE * 1e4) / 1e4),
  }
  if (slot.motion?.faceTravel) {
    const motion = { ...slot.motion }
    delete motion.faceTravel
    delete motion.headingOffset
    next.motion = motion
    next.rotationY = motion.to[0] < slot.position[0] ? Math.PI : 0
  }
  return next
}

/** A picture turned further than this from the camera, front or back, reads as a sliver (half its width at most). */
export const PICTURE_MAX_TURN = Math.PI / 3

const wrap = (angle: number) => Math.atan2(Math.sin(angle), Math.cos(angle))

/** Pictures standing in for models keep the side the template turned the model to, but never further than
 * PICTURE_MAX_TURN from facing the camera along the shot: a model in profile at a table or in a circle reads, a flat
 * picture in profile is a sliver. One that shows its back at mid-shot (a shoulder in the foreground) keeps its back,
 * turned the same way. One that moves or turns by itself (pictureInModelSlot already faces a runner to the camera),
 * or a billboard, stays as it is. */
export function turnPicturesToCamera(document: Scene3DDocument, ids: ReadonlySet<string>) {
  if (!ids.size) return
  const path = cameraPath(document)
  const at = (index: number) => (document.duration * index) / (path.length - 1)
  document.slots = document.slots.map(slot => {
    if (!ids.has(slot.id) || slot.billboard || slot.motion) return slot
    const offs = path.map(({ eye }, index) => {
      const { position, rotationY } = slotPoseAtTime(slot, at(index), document.duration)
      return wrap(rotationY - Math.atan2(eye[0] - position[0], eye[2] - position[2]))
    })
    const back = Math.abs(offs[Math.floor(offs.length / 2)]) > Math.PI / 2
    const seen = back ? offs.map(off => wrap(off + Math.PI)) : offs
    const side = Math.sign(seen[Math.floor(seen.length / 2)]) || 1
    const worst = Math.max(...seen.map(off => side * off))
    return worst > PICTURE_MAX_TURN ? { ...slot, rotationY: slot.rotationY - side * (worst - PICTURE_MAX_TURN) } : slot
  })
}
