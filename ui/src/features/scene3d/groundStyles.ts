// Ground styles: a floor drawn by the scene itself, in the look of a Nintendo 64 / GameCube field. A seamless painted
// tile (grass blades, sand ripples, asphalt grit, cobbles...) is generated from a seed, with its large patches inside the
// tile so the repeat does not show, and small 3D pieces are scattered on it (grass tufts, flowers, pebbles, snow lumps).
// No picture is generated or downloaded; the same seed always draws the same ground. With ``scroll`` the ground slides
// under a cast that runs on the spot, and the scattered pieces wrap around the cast.
import {
  BufferGeometry, Color, DataTexture, DoubleSide, Float32BufferAttribute, Group, IcosahedronGeometry, InstancedMesh,
  LinearFilter, LinearMipmapLinearFilter, Matrix4, Mesh, MeshStandardMaterial, PlaneGeometry, Quaternion, RepeatWrapping,
  SRGBColorSpace, Vector3, type Scene,
} from 'three'

export const GROUND_STYLES = ['grass', 'meadow', 'sand', 'asphalt', 'dirt', 'snow', 'cobble'] as const
export type GroundStyle = typeof GROUND_STYLES[number]
export type GroundScroll = { speed: number; direction: [number, number] }

export function isGroundStyle(value: unknown): value is GroundStyle {
  return typeof value === 'string' && (GROUND_STYLES as readonly string[]).includes(value)
}

/** Metres per second along a horizontal direction (normalised here); anything malformed is dropped. */
export function parseGroundScroll(raw: unknown): GroundScroll | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<GroundScroll>
  const speed = typeof value.speed === 'number' && Number.isFinite(value.speed) ? Math.max(-30, Math.min(30, value.speed)) : 0
  const [x, z] = Array.isArray(value.direction) ? value.direction.map(Number) : [NaN, NaN]
  const length = Math.hypot(x, z)
  if (!speed || !(length > 1e-6)) return undefined
  return { speed, direction: [x / length, z / length] }
}

type Rgb = [number, number, number]
type Scatter = { kind: 'tuft' | 'flower' | 'pebble' | 'lump'; count: number; size: [number, number]; colors: Rgb[] }
type StyleRecipe = { period: number; base: Rgb[]; scatter: Scatter[] }

const TEXTURE = 512          // pixels across one tile
const RADIUS = 22            // scattered pieces cover a square this many metres either side of the cast
const PLANE = 240            // metres across the ground plane
const LIFT = 0.002           // the ground sits this far above y = 0 so a template's own floor never flickers through

/** Each style's tile size in metres, its palette (shadow, body, light) and what is scattered on it. */
export const GROUND_RECIPES: Record<GroundStyle, StyleRecipe> = {
  grass: { period: 12, base: [[46, 92, 30], [74, 128, 44], [118, 164, 64]], scatter: [
    { kind: 'tuft', count: 1600, size: [0.09, 0.24], colors: [[112, 166, 60], [134, 184, 70], [96, 150, 52]] }] },
  meadow: { period: 12, base: [[58, 98, 34], [92, 140, 52], [146, 176, 78]], scatter: [
    { kind: 'tuft', count: 1300, size: [0.12, 0.3], colors: [[124, 170, 66], [146, 186, 76], [108, 156, 58]] },
    { kind: 'flower', count: 420, size: [0.08, 0.14], colors: [[250, 244, 230], [250, 214, 70], [236, 128, 170], [160, 150, 240]] }] },
  sand: { period: 14, base: [[188, 150, 96], [218, 186, 128], [240, 214, 162]], scatter: [
    { kind: 'pebble', count: 160, size: [0.04, 0.11], colors: [[176, 150, 120], [204, 186, 160], [150, 122, 96]] }] },
  asphalt: { period: 10, base: [[34, 36, 40], [54, 56, 60], [84, 86, 90]], scatter: [] },
  dirt: { period: 12, base: [[84, 58, 36], [118, 86, 56], [152, 118, 80]], scatter: [
    { kind: 'pebble', count: 420, size: [0.05, 0.14], colors: [[126, 112, 98], [150, 138, 120], [98, 84, 70]] },
    { kind: 'tuft', count: 160, size: [0.08, 0.18], colors: [[128, 146, 62], [150, 156, 72]] }] },
  snow: { period: 14, base: [[178, 196, 220], [222, 232, 244], [250, 252, 255]], scatter: [
    { kind: 'lump', count: 220, size: [0.12, 0.34], colors: [[236, 242, 250], [222, 232, 246]] }] },
  cobble: { period: 8, base: [[70, 68, 66], [118, 112, 104], [160, 152, 140]], scatter: [] },
}

/** A small deterministic generator (mulberry32). */
export function random(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** The style's main ground colour, #rrggbb: what set layers shade to where they meet this floor. */
export function groundColor(style: GroundStyle): string {
  return `#${GROUND_RECIPES[style].base[1].map(channel => Math.round(channel).toString(16).padStart(2, '0')).join('')}`
}

const styleSeed = (style: GroundStyle, seed: number) => [...style].reduce((sum, char) => sum * 31 + char.charCodeAt(0), seed + 7) >>> 0

/** Periodic value noise: a lattice of ``cells`` × ``cells`` that wraps, so the tile repeats without a seam. */
function periodicNoise(next: () => number, cells: number) {
  const lattice = Array.from({ length: cells * cells }, () => next())
  const at = (x: number, y: number) => lattice[((y % cells) + cells) % cells * cells + ((x % cells) + cells) % cells]
  const smooth = (t: number) => t * t * (3 - 2 * t)
  return (u: number, v: number) => {
    const x = u * cells, y = v * cells
    const x0 = Math.floor(x), y0 = Math.floor(y), fx = smooth(x - x0), fy = smooth(y - y0)
    const top = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * fx
    const bottom = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * fx
    return top + (bottom - top) * fy
  }
}

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
const shade = ([r, g, b]: Rgb, f: number): Rgb => [r * f, g * f, b * f]

/** The style's tile: RGBA, ``size`` pixels square, seamless. */
export function groundPixels(style: GroundStyle, seed = 1, size = TEXTURE): Uint8Array {
  const recipe = GROUND_RECIPES[style]
  const next = random(styleSeed(style, seed))
  const patches = periodicNoise(next, 4), mottle = periodicNoise(next, 16), grain = periodicNoise(next, 96)
  const [dark, body, light] = recipe.base
  const colors: Rgb[] = new Array(size * size)
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const u = x / size, v = y / size
    const tone = 0.55 * patches(u, v) + 0.3 * mottle(u, v) + 0.15 * grain(u, v)
    let color = tone < 0.5 ? mix(dark, body, tone * 2) : mix(body, light, (tone - 0.5) * 2)
    if (style === 'sand') color = shade(color, 0.92 + 0.08 * Math.sin((v * 9 + patches(u, v) * 1.6) * Math.PI * 2))
    if (style === 'snow') color = mix(color, [196, 214, 240], Math.max(0, 0.45 - patches(u, v)) * 0.8)
    colors[y * size + x] = color
  }
  const put = (x: number, y: number, color: Rgb, alpha = 1) => {
    const index = (((y % size) + size) % size) * size + (((x % size) + size) % size)
    colors[index] = mix(colors[index], color, alpha)
  }
  const strokes = { grass: 9000, meadow: 7000, dirt: 900, sand: 0, asphalt: 0, snow: 0, cobble: 0 }[style]
  for (let i = 0; i < strokes; i++) {          // grass blades: short strokes leaning one way, darker at the root
    const x = Math.floor(next() * size), y = Math.floor(next() * size), length = 2 + Math.floor(next() * 4)
    const lean = next() < 0.5 ? -1 : 1, tint = next()
    for (let step = 0; step < length; step++)
      put(x + Math.round(lean * step * 0.4), y - step, shade(tint < 0.5 ? light : body, 0.75 + 0.35 * step / length), 0.75)
  }
  if (style === 'meadow') for (let i = 0; i < 900; i++) {
    const x = Math.floor(next() * size), y = Math.floor(next() * size)
    const petal: Rgb = ([[250, 246, 236], [250, 220, 80], [238, 140, 178]] as Rgb[])[Math.floor(next() * 3)]
    put(x, y, petal); put(x + 1, y, petal, 0.6); put(x, y + 1, petal, 0.6)
  }
  if (style === 'asphalt' || style === 'sand' || style === 'dirt') for (let i = 0; i < (style === 'asphalt' ? 26000 : 9000); i++) {
    const x = Math.floor(next() * size), y = Math.floor(next() * size)
    put(x, y, next() < 0.5 ? shade(light, 1.15) : shade(dark, 0.8), 0.7)
  }
  if (style === 'asphalt') for (let crack = 0; crack < 7; crack++) {   // hairline cracks and a few dark patches
    let x = next() * size, y = next() * size, angle = next() * Math.PI * 2
    for (let step = 0; step < 60 + next() * 80; step++) {
      put(Math.round(x), Math.round(y), shade(dark, 0.55), 0.85)
      angle += (next() - 0.5) * 0.7; x += Math.cos(angle); y += Math.sin(angle)
    }
  }
  if (style === 'dirt' || style === 'sand') for (let i = 0; i < (style === 'dirt' ? 700 : 260); i++) {   // pebbles
    const x = Math.floor(next() * size), y = Math.floor(next() * size), r = 1 + Math.floor(next() * 2)
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++)
      if (dx * dx + dy * dy <= r * r) put(x + dx, y + dy, dy > 0 ? shade(dark, 0.9) : shade(light, 1.05), 0.9)
  }
  if (style === 'cobble') {                    // stones: periodic Voronoi cells with mortar between them
    const cells = 14, seeds: [number, number, number][] = []
    for (let cy = 0; cy < cells; cy++) for (let cx = 0; cx < cells; cx++) seeds.push([(cx + 0.2 + next() * 0.6) / cells, (cy + 0.2 + next() * 0.6) / cells, next()])
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      const u = x / size, v = y / size
      let first = Infinity, second = Infinity, tone = 0
      for (const [sx, sy, t] of seeds) {
        const dx = Math.min(Math.abs(u - sx), 1 - Math.abs(u - sx)), dy = Math.min(Math.abs(v - sy), 1 - Math.abs(v - sy))
        const d = Math.hypot(dx, dy)
        if (d < first) { second = first; first = d; tone = t } else if (d < second) second = d
      }
      const edge = (second - first) * cells
      const stone = mix(mix(dark, body, 0.5 + tone * 0.5), light, Math.max(0, 0.25 - first * cells * 0.4))
      colors[y * size + x] = edge < 0.08 ? mix(shade(dark, 0.55), colors[y * size + x], 0.25) : mix(stone, colors[y * size + x], 0.25)
    }
  }
  const pixels = new Uint8Array(size * size * 4)
  colors.forEach((color, index) => {
    pixels[index * 4] = Math.max(0, Math.min(255, Math.round(color[0])))
    pixels[index * 4 + 1] = Math.max(0, Math.min(255, Math.round(color[1])))
    pixels[index * 4 + 2] = Math.max(0, Math.min(255, Math.round(color[2])))
    pixels[index * 4 + 3] = 255
  })
  return pixels
}

/** A tuft's picture: a few blades on a transparent ground, darker at the root. */
function tuftPixels(next: () => number, size = 64): Uint8Array {
  const pixels = new Uint8Array(size * size * 4)
  for (let blade = 0; blade < 9; blade++) {
    const root = size * (0.15 + next() * 0.7), lean = (next() - 0.5) * 0.6, height = size * (0.45 + next() * 0.55), width = 1 + next() * 1.4
    for (let y = 0; y < height; y++) {
      const t = y / height, x0 = root + lean * y, w = width * (1 - t)
      for (let x = Math.floor(x0 - w); x <= Math.ceil(x0 + w); x++) {
        if (x < 0 || x >= size) continue
        const index = ((size - 1 - y) * size + x) * 4, f = 0.7 + 0.3 * t, tip = Math.max(0, t - 0.6) * 0.9   // tips lighter and warmer
        pixels[index] = Math.min(255, Math.round(255 * f * (1 + tip * 0.35))); pixels[index + 1] = Math.round(255 * f); pixels[index + 2] = Math.round(255 * f * (1 - tip * 0.4)); pixels[index + 3] = 255
      }
    }
  }
  return pixels
}

/** A flower's picture: five round petals around a yellow heart, white so each flower takes its own colour. */
function flowerPixels(size = 32): Uint8Array {
  const pixels = new Uint8Array(size * size * 4), c = size / 2
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const dx = x - c + 0.5, dy = y - c + 0.5, r = Math.hypot(dx, dy), a = Math.atan2(dy, dx)
    const petal = r < size * (0.3 + 0.16 * Math.cos(a * 5)), heart = r < size * 0.12
    if (!petal) continue
    const index = (y * size + x) * 4
    const color = heart ? [255, 210, 60] : [255, 255, 255]
    pixels[index] = color[0]; pixels[index + 1] = color[1]; pixels[index + 2] = color[2]; pixels[index + 3] = 255
  }
  return pixels
}

function pixelTexture(pixels: Uint8Array, size: number, repeat: boolean) {
  const texture = new DataTexture(pixels, size, size)
  texture.colorSpace = SRGBColorSpace
  texture.magFilter = LinearFilter
  texture.minFilter = LinearMipmapLinearFilter
  texture.generateMipmaps = true
  if (repeat) texture.wrapS = texture.wrapT = RepeatWrapping
  texture.anisotropy = 4
  texture.needsUpdate = true
  return texture
}

/** Three crossed quads standing on their base: a tuft or a flower seen from any side. */
function crossedQuads(): BufferGeometry {
  const positions: number[] = [], uvs: number[] = [], indices: number[] = []
  for (let i = 0; i < 3; i++) {
    const angle = (i * Math.PI) / 3, cx = Math.cos(angle) * 0.5, cz = Math.sin(angle) * 0.5, base = positions.length / 3
    positions.push(-cx, 0, -cz, cx, 0, cz, cx, 1, cz, -cx, 1, -cz)
    uvs.push(0, 0, 1, 0, 1, 1, 0, 1)
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3)
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geometry.setAttribute('uv', new Float32BufferAttribute(uvs, 2))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

type Piece = { mesh: InstancedMesh; base: Vector3[]; scale: number[]; turn: number[]; lift: number[] }

/** The scattered pieces of one kind, placed once in a square round the origin. */
function scatterPieces(scatter: Scatter, next: () => number): Piece {
  let geometry: BufferGeometry, material: MeshStandardMaterial
  if (scatter.kind === 'tuft' || scatter.kind === 'flower') {
    geometry = crossedQuads()
    const map = scatter.kind === 'tuft' ? pixelTexture(tuftPixels(next), 64, false) : pixelTexture(flowerPixels(), 32, false)
    material = new MeshStandardMaterial({ map, alphaTest: 0.5, side: DoubleSide, roughness: 1, metalness: 0 })
  } else {
    geometry = new IcosahedronGeometry(0.5, scatter.kind === 'lump' ? 1 : 0)
    material = new MeshStandardMaterial({ roughness: 1, metalness: 0, flatShading: scatter.kind === 'pebble' })
  }
  const mesh = new InstancedMesh(geometry, material, scatter.count)
  mesh.name = `ground-${scatter.kind}`
  mesh.frustumCulled = false
  const piece: Piece = { mesh, base: [], scale: [], turn: [], lift: [] }
  const color = new Color()
  for (let i = 0; i < scatter.count; i++) {
    // Denser near the cast, sparser towards the edge of the square.
    const r = RADIUS * Math.sqrt(next()) * (0.35 + 0.65 * next()), angle = next() * Math.PI * 2
    piece.base.push(new Vector3(Math.cos(angle) * r * 1.4, 0, Math.sin(angle) * r * 1.4))
    piece.scale.push(scatter.size[0] + (scatter.size[1] - scatter.size[0]) * next())
    piece.turn.push(next() * Math.PI * 2)
    piece.lift.push(scatter.kind === 'pebble' ? -0.35 : scatter.kind === 'lump' ? -0.42 : scatter.kind === 'flower' ? 0.45 + next() * 0.9 : 0)
    const [r8, g8, b8] = scatter.colors[Math.floor(next() * scatter.colors.length)]
    color.setRGB(r8 / 255, g8 / 255, b8 / 255, SRGBColorSpace).multiplyScalar(0.9 + next() * 0.2)
    mesh.setColorAt(i, color)
  }
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  return piece
}

const wrap = (value: number, half: number) => ((((value + half) % (2 * half)) + 2 * half) % (2 * half)) - half
const CLEARING = 0.55         // pieces this close to where a cast member stands shrink away, so feet are never hidden

/** Put every piece where the ground has carried it: ``shift`` metres, wrapped round the square, shrinking the ones
 * standing in a clearing (where the cast stands). */
function placePieces(piece: Piece, shift: [number, number], kind: Scatter['kind'], clearings: [number, number][]) {
  const matrix = new Matrix4(), rotation = new Quaternion(), up = new Vector3(0, 1, 0), position = new Vector3(), size = new Vector3()
  const half = RADIUS * 1.4
  piece.base.forEach((base, i) => {
    position.set(wrap(base.x + shift[0], half), 0, wrap(base.z + shift[1], half))
    const near = clearings.reduce((least, [x, z]) => Math.min(least, Math.hypot(position.x - x, position.z - z)), Infinity)
    const s = piece.scale[i] * Math.min(1, Math.max(0, (near - CLEARING * 0.5) / (CLEARING * 0.5)))
    if (kind === 'flower') { position.y = s * piece.lift[i]; size.set(s, s, s) }
    else if (kind === 'tuft') size.set(s * 1.2, s, s * 1.2)
    else { size.set(s * 1.6, s * (kind === 'lump' ? 0.7 : 0.55), s * 1.3); position.y = s * piece.lift[i] }
    rotation.setFromAxisAngle(up, piece.turn[i])
    piece.mesh.setMatrixAt(i, matrix.compose(position, rotation, size))
  })
  piece.mesh.instanceMatrix.needsUpdate = true
}

/** The scene's ground in a named style: one big plane with the painted tile and the scattered pieces. */
export class GroundStyleRuntime {
  readonly root = new Group()
  private style?: GroundStyle
  private seed = 1
  private plane?: Mesh<PlaneGeometry, MeshStandardMaterial>
  private pieces: { piece: Piece; kind: Scatter['kind'] }[] = []
  private lastShift: [number, number] = [NaN, NaN]
  private cleared = ''

  constructor(scene: Scene) {
    this.root.name = 'ground-style'
    scene.add(this.root)
  }

  /** Show ``style`` (or nothing), slid by ``scroll`` at ``seconds``, with clearings where the cast stands (x, z);
   * returns whether a styled ground is showing. */
  sync(style: GroundStyle | undefined, seconds: number, scroll?: GroundScroll, seed = 1, clearings: [number, number][] = []): boolean {
    if (style !== this.style || seed !== this.seed) this.build(style, seed)
    this.root.visible = Boolean(style)
    if (!style || !this.plane) return false
    const travel = scroll ? scroll.speed * seconds : 0
    const shift: [number, number] = scroll ? [scroll.direction[0] * travel, scroll.direction[1] * travel] : [0, 0]
    const period = GROUND_RECIPES[style].period
    // The plane's uv runs along +x and +z; the picture moves with the ground.
    this.plane.material.map!.offset.set(-shift[0] / period, -shift[1] / period)
    const cleared = JSON.stringify(clearings)
    if (shift[0] !== this.lastShift[0] || shift[1] !== this.lastShift[1] || cleared !== this.cleared) {
      for (const { piece, kind } of this.pieces) placePieces(piece, shift, kind, clearings)
      this.lastShift = shift; this.cleared = cleared
    }
    return true
  }

  private build(style: GroundStyle | undefined, seed: number) {
    this.clear()
    this.style = style; this.seed = seed; this.lastShift = [NaN, NaN]
    if (!style) return
    const recipe = GROUND_RECIPES[style]
    const map = pixelTexture(groundPixels(style, seed), TEXTURE, true)
    const geometry = new PlaneGeometry(PLANE, PLANE, 1, 1)
    geometry.rotateX(-Math.PI / 2)
    const uv = geometry.getAttribute('uv'), position = geometry.getAttribute('position')
    for (let i = 0; i < uv.count; i++) uv.setXY(i, position.getX(i) / recipe.period, position.getZ(i) / recipe.period)
    this.plane = new Mesh(geometry, new MeshStandardMaterial({ map, roughness: 1, metalness: 0 }))
    this.plane.name = `ground-${style}`
    this.plane.position.y = LIFT
    this.plane.receiveShadow = true
    this.root.add(this.plane)
    const next = random(styleSeed(style, seed) ^ 0x9e3779b9)
    for (const scatter of recipe.scatter) {
      const piece = scatterPieces(scatter, next)
      piece.mesh.receiveShadow = true
      this.root.add(piece.mesh)
      this.pieces.push({ piece, kind: scatter.kind })
    }
  }

  private clear() {
    if (this.plane) { this.plane.geometry.dispose(); this.plane.material.map?.dispose(); this.plane.material.dispose(); this.plane.removeFromParent() }
    for (const { piece } of this.pieces) {
      piece.mesh.geometry.dispose()
      const material = piece.mesh.material as MeshStandardMaterial
      material.map?.dispose(); material.dispose(); piece.mesh.removeFromParent()
    }
    this.plane = undefined; this.pieces = []
  }

  dispose() { this.clear(); this.root.removeFromParent() }
}
