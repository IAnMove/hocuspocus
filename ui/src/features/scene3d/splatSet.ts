// Stage a file splat as the shot's background and stand the cast on its floor.
// Shared by the production compiler. The editor operation uses the same lift.
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types'

export const SPLAT_GROUNDED_Y = 0.05

export interface SplatBackground {
  source?: string
  splat?: boolean
  floorY?: number
  scale?: number
}

function finite(value: unknown, fallback: number): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export function splatBackgroundSlot(background: SplatBackground): Scene3DSlot {
  const floorY = Math.min(50, Math.max(-50, finite(background.floorY, 0)))
  const scale = Math.min(100, Math.max(0.05, finite(background.scale, 1)))
  return {
    id: 'set-splat', slot: 'background', position: [0, floorY, 0], rotationY: 0, scale,
    sourceUrl: typeof background.source === 'string' ? background.source : '', media: 'splat', clip: null,
    splat: { floorY },
  }
}

/** A model standing on the world floor (y within 5 cm, and not marked as flying) stands on floorY instead. */
export function liftCastToSplatFloor<T extends { media: string; grounded?: boolean; position: Vec3 }>(slots: readonly T[], floorY: number): T[] {
  return slots.map(slot => {
    if (slot.media !== 'model3d' || slot.grounded === false) return slot
    if (Math.abs(slot.position[1] ?? 0) > SPLAT_GROUNDED_Y) return slot
    const [x, , z] = slot.position
    return { ...slot, grounded: true, position: [x, floorY, z] as Vec3 }
  })
}

export function stageSplatDocument(document: Scene3DDocument, background: SplatBackground) {
  const splat = splatBackgroundSlot(background)
  const rest = document.slots.filter(slot => slot.slot !== 'background' && slot.id !== splat.id)
  document.slots = [...liftCastToSplatFloor(rest, splat.splat?.floorY ?? 0), splat]
  document.dressing = 'none'
  document.environment = { reflectiveFloor: false, platform: false, bloom: 0, ...document.environment, floorStyle: 'none' }
}
