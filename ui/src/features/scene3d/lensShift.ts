// Lens shift: a level camera whose picture is moved up or down, so the horizon sits above or below the middle of the frame
// while verticals stay vertical. A plate room (app/services/room_plate.py) needs it: the plate's horizon is rarely at 0.5.
import type { PerspectiveCamera } from 'three'

/** The most a lens may shift, as a share of the frame's height (half a frame puts the horizon on the top or bottom edge). */
export const MAX_LENS_SHIFT = 0.5

/** `shift` is the fraction of the frame's height the horizon sits ABOVE the middle (0.28: horizon at 0.22 from the top). Without a
 * shift the camera is left exactly as it was. three reads the aspect from the full-size pair, so the pair keeps `camera.aspect`. */
export function applyLensShift(camera: PerspectiveCamera, shift: number | undefined): void {
  if (typeof shift === 'number' && Number.isFinite(shift) && shift !== 0) {
    const clamped = Math.max(-MAX_LENS_SHIFT, Math.min(MAX_LENS_SHIFT, shift))
    const width = Math.max(1e-3, camera.aspect) * 1000
    camera.setViewOffset(width, 1000, 0, clamped * 1000, width, 1000)
  } else if (camera.view?.enabled) {
    camera.clearViewOffset()
  }
}

export function validLensShift(value: unknown): boolean {
  return value == null || (typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= MAX_LENS_SHIFT)
}
