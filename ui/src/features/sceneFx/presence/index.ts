import type { SceneFx } from '../types'
import { paintAura } from './aura'
import { paintAurora } from './aurora'
import { paintBubbles } from './bubbles'
import { paintDust } from './dust'
import { paintEmbers } from './embers'
import { paintFog } from './fog'
import { paintMeteors } from './meteors'
import { paintShield } from './shield'
import { paintSmoke } from './smoke'
import { paintStars } from './stars'
import { presenceAvailable, presenceFrame, type PresenceFrame } from './stage'

/** Presence effects drawn with Three.js (see `stage.ts`). A painter returns false when it could not paint. */
type PresencePainter = (ctx: CanvasRenderingContext2D, frame: PresenceFrame) => boolean

const PAINTERS: Record<string, PresencePainter> = {
  anime_aura: paintAura, shield: paintShield, fog: paintFog, smoke: paintSmoke, dust: paintDust,
  stars: paintStars, aurora: paintAurora, bubbles: paintBubbles, embers: paintEmbers,
  meteor_shower: paintMeteors,
}

let enabled = true
const failed = new Set<string>()
/** Off, every effect is painted by its 2D painter (tests and before/after sheets compare the two). */
export function setPresenceEnabled(value: boolean) { enabled = value }

/** The kinds that have a Three.js painter. */
export const PRESENCE_KINDS: ReadonlySet<string> = new Set(Object.keys(PAINTERS))

/** Paint the cue with its Three.js painter, in the cue's space (translated to x/y, scaled by size, turned by rotation).
 * False when the kind has none, WebGL is not there or the pass failed: the caller then paints the 2D effect. */
export function paintPresence(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number): boolean {
  const painter = PAINTERS[cue.kind]
  if (!painter || !enabled || !presenceAvailable(ctx)) return false
  try {
    return painter(ctx, presenceFrame(ctx, cue, time))
  } catch (error) {
    if (!failed.has(cue.kind)) { failed.add(cue.kind); console.warn(`presence effect ${cue.kind} fell back to 2D:`, error) }
    return false
  }
}
