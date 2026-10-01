/** A small contour mesh for the Lips Creator preview; never changes saved sprites. */
export type MorphPoint = { x: number; y: number }
export type MouthMorphMesh = { points: MorphPoint[]; columns: number; rows: number }
export type MouthMorphFrame = { image: HTMLCanvasElement; mesh?: MouthMorphMesh }

/** Match columns along the lips and rows from their top contour to their bottom. */
export function mouthContourMesh(rgba: ArrayLike<number>, width: number, height: number): MouthMorphMesh | undefined {
  let left = width, right = -1, count = 0
  const tops = Array<number>(width).fill(height), bottoms = Array<number>(width).fill(-1)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (rgba[(y * width + x) * 4 + 3] < 24) continue
    tops[x] = Math.min(tops[x], y); bottoms[x] = y
    left = Math.min(left, x); right = Math.max(right, x); count++
  }
  // A background/face rectangle has no useful lip contour. Keep the direct preview.
  if (right <= left || count > width * height * .96) return undefined
  const points: MorphPoint[] = [], segments = 12, rows = 5
  const edgeLeft = Math.max(0, left - 2), edgeRight = Math.min(width, right + 3)
  const radius = Math.max(2, Math.ceil((right - left) / segments / 2))
  for (let column = 0; column <= segments + 2; column++) {
    const x = column === 0 ? 0 : column === segments + 2 ? width : edgeLeft + (edgeRight - edgeLeft) * (column - 1) / segments
    let top = height, bottom = -1
    for (let scan = Math.max(left, Math.floor(x) - radius); scan <= Math.min(right, Math.ceil(x) + radius); scan++) {
      top = Math.min(top, tops[scan]); bottom = Math.max(bottom, bottoms[scan])
    }
    if (bottom < top) { top = 0; bottom = height - 1 }
    top = Math.max(0, top - 2); bottom = Math.min(height, bottom + 3)
    for (const y of [0, top, (top + bottom) / 2, bottom, height]) points.push({ x, y })
  }
  return { points, columns: segments + 3, rows }
}

export function interpolateMouthMesh(from: MouthMorphMesh, to: MouthMorphMesh, progress: number): MouthMorphMesh {
  const mix = Math.max(0, Math.min(1, progress))
  return { columns: from.columns, rows: from.rows,
    points: from.points.map((point, index) => ({ x: point.x + (to.points[index].x - point.x) * mix, y: point.y + (to.points[index].y - point.y) * mix })) }
}

/** Affine map from a source triangle onto its moving destination triangle. */
export function mouthTriangleTransform(source: readonly MorphPoint[], target: readonly MorphPoint[]): [number, number, number, number, number, number] | undefined {
  const [p, q, r] = source, [u, v, w] = target
  const x1 = q.x - p.x, y1 = q.y - p.y, x2 = r.x - p.x, y2 = r.y - p.y
  const determinant = x1 * y2 - x2 * y1
  if (Math.abs(determinant) < .0001) return undefined
  const a = ((v.x - u.x) * y2 - (w.x - u.x) * y1) / determinant
  const c = ((w.x - u.x) * x1 - (v.x - u.x) * x2) / determinant
  const b = ((v.y - u.y) * y2 - (w.y - u.y) * y1) / determinant
  const d = ((w.y - u.y) * x1 - (v.y - u.y) * x2) / determinant
  return [a, b, c, d, u.x - a * p.x - c * p.y, u.y - b * p.x - d * p.y]
}

function warpMouth(context: CanvasRenderingContext2D, frame: MouthMorphFrame, target: MouthMorphMesh) {
  const source = frame.mesh!
  for (let x = 0; x < source.columns - 1; x++) for (let y = 0; y < source.rows - 1; y++) {
    const a = x * source.rows + y, b = a + source.rows, c = b + 1, d = a + 1
    for (const indices of [[a, b, c], [a, c, d]]) {
      const triangle = indices.map(index => target.points[index])
      const matrix = mouthTriangleTransform(indices.map(index => source.points[index]), triangle)
      if (!matrix) continue
      // Slightly overlap clips: otherwise Canvas antialiasing leaves mesh-shaped seams.
      const [p, q, r] = triangle
      const sign = Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x))
      const normals = triangle.map((point, index) => {
        const next = triangle[(index + 1) % 3], dx = next.x - point.x, dy = next.y - point.y, length = Math.hypot(dx, dy) || 1
        return { x: sign * dy / length, y: -sign * dx / length }
      })
      const clip = triangle.map((point, index) => {
        const first = normals[(index + 2) % 3], second = normals[index]
        const factor = .7 / Math.max(.05, 1 + first.x * second.x + first.y * second.y)
        const dx = (first.x + second.x) * factor, dy = (first.y + second.y) * factor
        const limit = Math.min(1, 6 / (Math.hypot(dx, dy) || 1))
        return { x: point.x + dx * limit, y: point.y + dy * limit }
      })
      context.save()
      context.beginPath(); context.moveTo(clip[0].x, clip[0].y)
      context.lineTo(clip[1].x, clip[1].y); context.lineTo(clip[2].x, clip[2].y); context.closePath()
      context.clip(); context.transform(...matrix); context.drawImage(frame.image, 0, 0)
      context.restore()
    }
  }
}

/** Both drawings move onto ONE shared outline before their interior colors blend. */
export function renderMouthMorph(context: CanvasRenderingContext2D, from: MouthMorphFrame, to: MouthMorphFrame, progress: number,
  layers: readonly [HTMLCanvasElement, HTMLCanvasElement]): MouthMorphMesh | undefined {
  const mix = Math.max(0, Math.min(1, progress)), { width, height } = context.canvas
  context.clearRect(0, 0, width, height)
  if (!from.mesh || !to.mesh || mix === 0 || mix === 1) {
    const frame = mix < .5 ? from : to
    context.drawImage(frame.image, 0, 0); return frame.mesh
  }
  const mesh = interpolateMouthMesh(from.mesh, to.mesh, mix)
  for (let index = 0; index < 2; index++) {
    const layer = layers[index].getContext('2d')!
    layer.clearRect(0, 0, width, height); warpMouth(layer, index ? to : from, mesh)
  }
  context.save()
  context.globalAlpha = 1 - mix; context.drawImage(layers[0], 0, 0)
  // Add premultiplied colors/alpha, so overlapping transparent lips do not dim.
  context.globalCompositeOperation = 'lighter'; context.globalAlpha = mix; context.drawImage(layers[1], 0, 0)
  context.restore()
  return mesh
}
