import type { SceneFx } from '../types'
import { auraEffect } from './aura'
import { auroraEffect } from './aurora'
import { bubblesEffect } from './bubbles'
import { dustEffect } from './dust'
import { embersEffect } from './embers'
import { fogEffect } from './fog'
import { meteorsEffect } from './meteors'
import { shieldEffect } from './shield'
import { smokeEffect } from './smoke'
import { starsEffect } from './stars'
import { presenceAvailable, presenceFrame, type Layer, type PresenceFrame } from './stage'

/** Presence effects drawn with Three.js (see `stage.ts`): the painter, which returns false when it could not paint, and
 * the layers it is made of (the tests read them). */
type PresenceEffect = { paint: (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => boolean; layers: Array<() => Layer> }

const EFFECTS: Record<string, PresenceEffect> = {
  anime_aura: auraEffect, shield: shieldEffect, fog: fogEffect, smoke: smokeEffect, dust: dustEffect,
  stars: starsEffect, aurora: auroraEffect, bubbles: bubblesEffect, embers: embersEffect, meteor_shower: meteorsEffect,
}

let enabled = true
const failed = new Set<string>()
/** Off, every effect is painted by its 2D painter (tests and before/after sheets compare the two). */
export function setPresenceEnabled(value: boolean) { enabled = value }

/** The kinds that have a Three.js painter. */
export const PRESENCE_KINDS: ReadonlySet<string> = new Set(Object.keys(EFFECTS))

/** The layers of a kind's Three.js painter, built (no WebGL needed): what the shader tests read. */
export function presenceLayers(kind: string): Layer[] {
  return (EFFECTS[kind]?.layers ?? []).map(layer => layer())
}

/** Paint the cue with its Three.js painter, in the cue's space (translated to x/y, scaled by size, turned by rotation).
 * False when the kind has none, WebGL is not there or the pass failed: the caller then paints the 2D effect. */
export function paintPresence(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number): boolean {
  const effect = EFFECTS[cue.kind]
  if (!effect || !enabled || !presenceAvailable(ctx)) return false
  try {
    return effect.paint(ctx, presenceFrame(ctx, cue, time))
  } catch (error) {
    if (!failed.has(cue.kind)) { failed.add(cue.kind); console.warn(`presence effect ${cue.kind} fell back to 2D:`, error) }
    return false
  }
}
