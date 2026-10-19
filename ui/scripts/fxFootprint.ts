// Measures whether a screen effect, painted alone on a transparent frame, ends against a box.
//
// The placed painters draw in a unit square around the cue point (x, y), scaled by size: the cue's footprint. An
// effect that decays to nothing before its edge reads as light in the air; one that is cut, flat, at a rectangle
// reads as a sticker ("a square, always"). The measure is made on the alpha of the painted pixels only, so it works
// for any painter, the 2D ones and the filmed 3D sprites alike.
//
// Two findings, both on the painted box (the bounding box of the pixels above the alpha floor):
//  * a straight cut: along a side of the box, a run of solid paint at least ``CUT_RUN`` of the footprint long. A soft
//    glow, a beam's rounded end or a ring's curve never makes one; a gradient that stops at a rectangle does;
//  * a rectangular scatter: particles spread evenly into all four corners of the box (``cornerFill``), the way a
//    field of rain clipped to a rectangle looks, instead of thinning out before them.
//
// Pure functions: ``fxFootprintEntry.ts`` bundles them into the browser that paints, ``fx-footprint-audit.mjs`` and
// ``tests/sceneFxFootprint.test.ts`` call them on alpha buffers.

/** A pixel counts as painted above this alpha (2 % of 255). */
export const ALPHA_FLOOR = 5
/** Paint on the edge of the box counts as solid from this alpha (8 % of 255). */
const SOLID = 20
/** The outer layers of the box searched for the solid paint of a cut: a rounded end shows only its tip on the outermost one. */
const LAYERS = 2
/** A cut leaves paint at the edge at least this share of what stands ``DEPTH`` inside it: soft flanks rise slowly, a cut does not. */
const STEP = 0.5
/** A cut is body, not a line: paint this deep inside the edge (in footprints) is solid too, which a stroke along the side is not. */
const DEPTH = 0.1
/** Gaps of this many pixels do not break a run (the hairlines of a stroked edge). */
const GAP = 2
/** A cut run is at least this fraction of the footprint's side. */
export const CUT_RUN = 0.15
/** A corner zone of a scatter's box: this fraction of each of its sides. */
const CORNER = 0.2
/** A box thinner than this many footprints is a line or a beam, not a scatter. */
const THIN = 0.4
/** A scatter whose corners hold this share of what an even rectangle would put there fills a rectangle. */
export const CORNER_LIMIT = 0.5
/** The painted box covering this share of the frame in a direction makes the effect a whole-frame one. */
const SCREEN_SHARE = 0.9

export type Box = { left: number; top: number; right: number; bottom: number }
export type Footprint = { cx: number; cy: number; side: number }
export type FootprintMeasure = {
  /** Share of the frame's pixels painted above the floor. */
  coverage: number
  box: Box | null
  /** The effect spans the frame: its own box says it has no footprint to end against. */
  screen: boolean
  /** Longest straight cut along a side of the box, in footprints (0 when the sides are soft). */
  cut: number
}

export function paintedBox(alpha: ArrayLike<number>, width: number, height: number): Box | null {
  let left = width, top = height, right = -1, bottom = -1
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (alpha[y * width + x] <= ALPHA_FLOOR) continue
    if (x < left) left = x
    if (x > right) right = x
    if (y < top) top = y
    if (y > bottom) bottom = y
  }
  return right < 0 ? null : { left, top, right, bottom }
}

/** Longest run of positions where `solid(i)` holds, gaps of up to GAP positions bridged. */
function longestRun(length: number, solid: (index: number) => boolean): number {
  let best = 0, start = -1, last = -1
  for (let i = 0; i < length; i++) {
    if (!solid(i)) continue
    if (start < 0 || i - last > GAP + 1) start = i
    last = i
    best = Math.max(best, last - start + 1)
  }
  return best
}

/** The straight cut along one side: positions along it where paint stands at the edge as it does inside, not where it
 * rises from nothing over a few pixels (the flank of a flame, a beam's glow) and not where it is a stroke. */
function sideRun(alpha: ArrayLike<number>, width: number, box: Box, side: 'left' | 'right' | 'top' | 'bottom', footprint: Footprint): number {
  const vertical = side === 'left' || side === 'right'
  const length = vertical ? box.bottom - box.top + 1 : box.right - box.left + 1
  const outer = vertical ? (side === 'left' ? box.left : box.right) : (side === 'top' ? box.top : box.bottom)
  const inward = side === 'left' || side === 'top' ? 1 : -1
  const at = (along: number, layer: number) => {
    const x = vertical ? outer + inward * layer : box.left + along
    const y = vertical ? box.top + along : outer + inward * layer
    return alpha[y * width + x] ?? 0
  }
  const most = (along: number, from: number, to: number) => {
    let found = 0
    for (let layer = from; layer <= to; layer++) found = Math.max(found, at(along, layer))
    return found
  }
  const deep = Math.max(LAYERS + 1, Math.round(footprint.side * DEPTH))
  return longestRun(length, along => {
    const edge = most(along, 0, LAYERS - 1), inside = most(along, deep, deep + LAYERS - 1)
    return edge >= SOLID && inside >= SOLID / 2 && edge >= STEP * inside
  })
}

export function measureAlpha(alpha: ArrayLike<number>, width: number, height: number, footprint: Footprint): FootprintMeasure {
  const box = paintedBox(alpha, width, height)
  let painted = 0
  for (let i = 0; i < alpha.length; i++) if (alpha[i] > ALPHA_FLOOR) painted++
  const coverage = painted / (width * height)
  if (!box) return { coverage, box, screen: false, cut: 0 }
  const screen = (box.right - box.left + 1) >= width * SCREEN_SHARE || (box.bottom - box.top + 1) >= height * SCREEN_SHARE
  const sides = (['left', 'right', 'top', 'bottom'] as const).filter(side =>
    side === 'left' ? box.left > 0 : side === 'right' ? box.right < width - 1 : side === 'top' ? box.top > 0 : box.bottom < height - 1)
  const run = sides.reduce((most, side) => Math.max(most, sideRun(alpha, width, box, side, footprint)), 0)
  return { coverage, box, screen, cut: run / footprint.side }
}

/** How evenly a scatter fills its box: the paint of the emptiest corner over what an even rectangle puts in a
 * corner (1: every corner as full as the middle, 0: a corner is empty, as it is in a disc, a blob or a stroke).
 * `mass` is the summed alpha of several frames of the same effect. A thin box, a beam or a line, is not a scatter. */
export function cornerFill(mass: ArrayLike<number>, width: number, height: number, footprint: Footprint): number {
  const box = paintedBox(mass, width, height)
  if (!box) return 0
  const boxWidth = box.right - box.left + 1, boxHeight = box.bottom - box.top + 1
  if (Math.min(boxWidth, boxHeight) < footprint.side * THIN) return 0
  const zoneX = Math.max(1, Math.round(boxWidth * CORNER)), zoneY = Math.max(1, Math.round(boxHeight * CORNER))
  let total = 0
  const corners = [0, 0, 0, 0]
  for (let y = box.top; y <= box.bottom; y++) for (let x = box.left; x <= box.right; x++) {
    const value = mass[y * width + x]
    total += value
    const right = box.right - x < zoneX, bottom = box.bottom - y < zoneY
    if ((x - box.left < zoneX || right) && (y - box.top < zoneY || bottom)) corners[(bottom ? 2 : 0) + (right ? 1 : 0)] += value
  }
  return total > 0 ? Math.min(...corners) / total / (CORNER * CORNER) : 0
}

/** A frame is cut when a side of its painted box is a straight run of paint; a scatter is when it fills its rectangle. */
export function isBoxCut(measure: FootprintMeasure, fill = 0): boolean {
  return !measure.screen && measure.box !== null && (measure.cut >= CUT_RUN || fill >= CORNER_LIMIT)
}
