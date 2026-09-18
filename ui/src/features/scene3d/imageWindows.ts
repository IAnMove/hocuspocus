import { Path, PlaneGeometry, Shape, ShapeGeometry } from 'three'

/** Normalized image coordinates, origin at the top left. Stored non-destructively. */
export type ImageWindow = [number, number][]
export const MAX_IMAGE_WINDOWS = 8
export const MAX_WINDOW_POINTS = 128

export function parseImageWindows(raw: unknown): ImageWindow[] | undefined {
  if (!Array.isArray(raw)) return undefined
  const windows: ImageWindow[] = []
  for (const polygon of raw.slice(0, MAX_IMAGE_WINDOWS)) {
    if (!Array.isArray(polygon) || polygon.length < 3 || polygon.length > MAX_WINDOW_POINTS) continue
    if (!polygon.every(point => Array.isArray(point) && point.length === 2 && point.every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1))) continue
    const points = polygon.map(([x, y]) => [x, y] as [number, number])
    const area = points.reduce((sum, [x, y], i) => {
      const next = points[(i + 1) % points.length]
      return sum + x * next[1] - next[0] * y
    }, 0)
    if (Math.abs(area) > .000001) windows.push(points)
  }
  return windows.length ? windows : undefined
}

/** Real holes: the background and picking rays pass through the foreground mesh. */
export function imageWindowGeometry(aspect: number, windows?: ImageWindow[]) {
  const holes = parseImageWindows(windows)
  if (!holes) return new PlaneGeometry(2 * aspect, 2)
  const shape = new Shape()
  shape.moveTo(-aspect, -1)
  shape.lineTo(aspect, -1)
  shape.lineTo(aspect, 1)
  shape.lineTo(-aspect, 1)
  shape.closePath()
  for (const polygon of holes) {
    const path = new Path()
    polygon.forEach(([u, v], i) => {
      // Keep an imperceptible outer rim for stable triangulation at image edges.
      const x = (Math.max(.000001, Math.min(.999999, u)) * 2 - 1) * aspect
      const y = 1 - Math.max(.000001, Math.min(.999999, v)) * 2
      if (i === 0) path.moveTo(x, y)
      else path.lineTo(x, y)
    })
    path.closePath()
    shape.holes.push(path)
  }
  const geometry = new ShapeGeometry(shape)
  geometry.userData.imagePlaneSize = { width: 2 * aspect, height: 2 }
  const position = geometry.getAttribute('position'), uv = geometry.getAttribute('uv')
  for (let i = 0; i < uv.count; i++) uv.setXY(i, (position.getX(i) / aspect + 1) / 2, (position.getY(i) + 1) / 2)
  return geometry
}
