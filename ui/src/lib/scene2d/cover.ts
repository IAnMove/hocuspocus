// Draw-time cover. Saved animation is not rewritten: the painted box grows and
// slides so an image or video cannot reveal the frame edge.
import type { LayerState } from './types'

type Span = { width: number; height: number }

function spanFactors(canvasWidth: number, canvasHeight: number, sourceWidth: number, sourceHeight: number, fill: boolean): Span {
  if (fill) return { width: 1, height: 1 }
  const sourceRatio = sourceWidth / sourceHeight
  const canvasRatio = canvasWidth / canvasHeight
  if (sourceRatio > canvasRatio) return { width: 1, height: canvasRatio / sourceRatio }
  return { width: sourceRatio / canvasRatio, height: 1 }
}

/** Smallest scale that covers one axis while the focus point stays on the anchor. */
function axisScale(anchor: number, focus: number, factor: number): number {
  const towardStart = focus + 50 * (factor - 1)
  const towardEnd = 50 * (factor + 1) - focus
  const start = towardStart > 1e-6 ? anchor / towardStart : 0
  const end = towardEnd > 1e-6 ? (100 - anchor) / towardEnd : 0
  return Math.max(start, end, 1 / Math.max(factor, 1e-6))
}

function upright(rotation: number): boolean {
  const turns = Math.abs(rotation) % 360
  return turns < 1e-6 || turns > 360 - 1e-6
}

function spinMargin(rotation: number): number {
  const theta = (Math.abs(rotation) % 180) * Math.PI / 180
  return Math.abs(Math.cos(theta)) + Math.abs(Math.sin(theta))
}

/** Inverse of pinFocus. 50,50 (and a missing focus) leave the anchor on the center. */
function focusShift(canvasWidth: number, canvasHeight: number, focusX: number, focusY: number, scale: number, rotation: number) {
  const ox = (focusX - 50) / 100 * canvasWidth * scale
  const oy = (focusY - 50) / 100 * canvasHeight * scale
  const theta = rotation * Math.PI / 180
  const cos = Math.cos(theta)
  const sin = Math.sin(theta)
  return {
    x: (cos * ox - sin * oy) / canvasWidth * 100,
    y: (sin * ox + cos * oy) / canvasHeight * 100,
  }
}

function clampPercent(center: number, factor: number, scale: number): number {
  const size = factor * scale * 100
  if (size < 100) return center
  const low = 100 - size / 2
  const high = size / 2
  return Math.min(high, Math.max(low, center))
}

/** Painted x/y/scale so the contained image covers the canvas. Rotation 0 is exact. */
export function coverDrawState(
  canvasWidth: number,
  canvasHeight: number,
  sourceWidth: number,
  sourceHeight: number,
  fill: boolean | undefined,
  focus: { x: number; y: number } | undefined,
  state: LayerState,
): LayerState {
  if (!(sourceWidth > 0) || !(sourceHeight > 0) || !(canvasWidth > 0) || !(canvasHeight > 0)) return state
  const focusX = focus?.x ?? 50
  const focusY = focus?.y ?? 50
  const factor = spanFactors(canvasWidth, canvasHeight, sourceWidth, sourceHeight, fill === true)
  const anchorShift = focusShift(canvasWidth, canvasHeight, focusX, focusY, state.scale, state.rotation)
  const anchorX = state.x + anchorShift.x
  const anchorY = state.y + anchorShift.y
  const needed = Math.max(axisScale(anchorX, focusX, factor.width), axisScale(anchorY, focusY, factor.height))
  const scale = Math.max(state.scale, upright(state.rotation) ? needed : needed * spinMargin(state.rotation))
  const nextShift = focusShift(canvasWidth, canvasHeight, focusX, focusY, scale, state.rotation)
  const x = anchorX - nextShift.x
  const y = anchorY - nextShift.y
  if (!upright(state.rotation)) return { ...state, x, y, scale }
  return { ...state, x: clampPercent(x, factor.width, scale), y: clampPercent(y, factor.height, scale), scale }
}
