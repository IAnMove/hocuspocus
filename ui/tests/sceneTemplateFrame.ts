// Where a picture of a given aspect lands on screen in a compiled template, measured with the real 2D evaluator
// (keyframes, strips, orbits, the camera) and the painter's contain fit. Shared by the template framing tests.
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import type { KineticText } from '../src/lib/kineticText/types.ts'
import type { Scene } from '../src/types/index.ts'

export type Rect = { left: number; right: number; top: number; bottom: number }

/** The drawn box of each instance of `layerId` at scene progress `time`, in frame percent, for a picture whose
 * width/height is `aspect` (a GLB fills its viewer box). Rotation is applied to the corners. */
export function drawnRects(scene: Scene, layerId: string, aspect: number, time: number): Rect[] {
  const normalized = normalizeScene2D(scene)
  const evaluator = createSceneEvaluator(normalized)
  const layer = normalized.layers.find(item => item.id === layerId)
  if (!layer) throw new Error(`no layer ${layerId}`)
  return evaluator.renderedLayerStates(layer, time).map(state => {
    const model = layer.type === 'model3d'
    const boxWidth = normalized.width * (model ? .52 : 1) * state.scale
    const boxHeight = normalized.height * (model ? .75 : 1) * state.scale
    const boxRatio = boxWidth / boxHeight
    const fill = layer.fill === true
    const wide = aspect > boxRatio
    const [width, height] = model ? [boxWidth, boxHeight]
      : !fill ? (wide ? [boxWidth, boxWidth / aspect] : [boxHeight * aspect, boxHeight])
        : (wide ? [boxHeight * aspect, boxHeight] : [boxWidth, boxWidth / aspect])
    const angle = state.rotation * Math.PI / 180
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => {
      const dx = sx * width / 2, dy = sy * height / 2
      return [normalized.width * state.x / 100 + dx * Math.cos(angle) - dy * Math.sin(angle), normalized.height * state.y / 100 + dx * Math.sin(angle) + dy * Math.cos(angle)]
    })
    const xs = corners.map(([x]) => x / normalized.width * 100)
    const ys = corners.map(([, y]) => y / normalized.height * 100)
    return { left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys) }
  })
}

/** The worst overflow past the frame edge (percent, positive means cut) of a layer over the shot. */
export function worstOverflow(scene: Scene, layerId: string, aspect: number, samples = 60): number {
  let worst = -Infinity
  for (let index = 0; index <= samples; index += 1) {
    for (const rect of drawnRects(scene, layerId, aspect, index / samples)) {
      worst = Math.max(worst, -rect.left, rect.right - 100, -rect.top, rect.bottom - 100)
    }
  }
  return worst
}

export const overlaps = (a: Rect, b: Rect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom

/** A generous estimate of where a title cue is drawn (frame percent): .62 em per character, the painter's wrap and
 * shrink rules, its box padding and 6 % for a pulse. Good enough to say whether a title sits over a subject. */
export function textRect(cue: KineticText, frame: { width: number; height: number }): Rect {
  const font = frame.height * cue.size / 100
  const text = cue.counter ? String(Math.max(Math.abs(cue.counter.from), Math.abs(cue.counter.to))) : cue.text
  const natural = [...text].length * font * .62
  const maxWidth = cue.maxWidth != null ? frame.width * cue.maxWidth / 100 : 0
  const shrink = cue.maxWidth == null ? Math.min(1, frame.width * .86 / natural) : 1
  const lines = maxWidth ? Math.ceil(natural / maxWidth) : 1
  const blockWidth = (maxWidth ? Math.min(natural, maxWidth) : natural * shrink) * 1.06
  const lineHeight = font * shrink * (cue.lineHeight ?? 1.12) * 1.06
  const pad = cue.box ? cue.box.padding * lineHeight : 0
  const align = cue.align ?? 'center'
  const centre = frame.width * cue.x / 100 + (align === 'left' ? blockWidth / 2 : align === 'right' ? -blockWidth / 2 : 0)
  const half = { x: blockWidth / 2 + pad, y: lines * lineHeight / 2 + pad }
  const y = frame.height * cue.y / 100
  return {
    left: (centre - half.x) / frame.width * 100, right: (centre + half.x) / frame.width * 100,
    top: (y - half.y) / frame.height * 100, bottom: (y + half.y) / frame.height * 100,
  }
}
