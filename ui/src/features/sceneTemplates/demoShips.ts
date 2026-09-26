/** Original low-poly demo geometry. No downloaded meshes, textures or inference.
 * glTF is intentionally uncompressed so the ordinary editor needs no decoder. */
type Vec = [number, number, number]
type Part = { positions: number[]; normals: number[]; color: Vec; emissive?: Vec }

function triangle(part: Part, a: Vec, b: Vec, c: Vec) {
  const u = b.map((v, i) => v - a[i])
  const v = c.map((n, i) => n - a[i])
  const n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
  const length = Math.hypot(...n) || 1
  part.positions.push(...a, ...b, ...c)
  for (let i = 0; i < 3; i++) part.normals.push(...n.map(value => value / length))
}

function ellipsoid(center: Vec, size: Vec, color: Vec, emissive?: Vec): Part {
  const part: Part = { positions: [], normals: [], color, emissive }
  const vertex = (ring: number, slice: number): Vec => {
    const phi = Math.PI * ring / 10
    const theta = Math.PI * 2 * slice / 24
    return [center[0] + size[0] * Math.sin(phi) * Math.cos(theta), center[1] + size[1] * Math.cos(phi), center[2] + size[2] * Math.sin(phi) * Math.sin(theta)]
  }
  for (let r = 0; r < 10; r++) for (let s = 0; s < 24; s++) {
    const a = vertex(r, s), b = vertex(r + 1, s), c = vertex(r + 1, s + 1), d = vertex(r, s + 1)
    if (r > 0) triangle(part, a, d, b)
    if (r < 9) triangle(part, b, d, c)
  }
  return part
}

function box(center: Vec, size: Vec, color: Vec): Part {
  const part: Part = { positions: [], normals: [], color }
  const vertices: Vec[] = [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]]
    .map(p => p.map((n, i) => center[i] + n * size[i] / 2) as Vec)
  for (const [a, b, c, d] of [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [3, 7, 6, 2], [0, 4, 7, 3], [1, 2, 6, 5]]) {
    triangle(part, vertices[a], vertices[b], vertices[c])
    triangle(part, vertices[a], vertices[c], vertices[d])
  }
  return part
}

function encodeGlb(parts: Part[]): string {
  const floats: number[] = []
  const views: Array<Record<string, number>> = []
  const accessors: Array<Record<string, unknown>> = []
  const primitives = parts.map((part, index) => {
    const position = accessors.length
    for (const values of [part.positions, part.normals]) {
      const byteOffset = floats.length * 4
      floats.push(...values)
      const bufferView = views.length
      views.push({ buffer: 0, byteOffset, byteLength: values.length * 4, target: 34962 })
      const axes = [0, 1, 2].map(axis => values.filter((_, i) => i % 3 === axis))
      accessors.push({ bufferView, componentType: 5126, count: values.length / 3, type: 'VEC3', min: axes.map(a => Math.min(...a)), max: axes.map(a => Math.max(...a)) })
    }
    return { attributes: { POSITION: position, NORMAL: position + 1 }, material: index }
  })
  const binary = new Uint8Array(floats.length * 4)
  const floatView = new DataView(binary.buffer)
  floats.forEach((value, i) => floatView.setFloat32(i * 4, value, true))
  const json = new TextEncoder().encode(JSON.stringify({
    asset: { version: '2.0', generator: 'HocusPocus original procedural review ships v1' },
    scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }], meshes: [{ primitives }],
    buffers: [{ byteLength: binary.length }], bufferViews: views, accessors,
    materials: parts.map(p => ({ doubleSided: true, pbrMetallicRoughness: { baseColorFactor: [...p.color, 1], metallicFactor: .55, roughnessFactor: .34 }, ...(p.emissive ? { emissiveFactor: p.emissive } : {}) })),
  }))
  const jsonLength = Math.ceil(json.length / 4) * 4
  const output = new Uint8Array(28 + jsonLength + binary.length)
  const header = new DataView(output.buffer)
  header.setUint32(0, 0x46546c67, true); header.setUint32(4, 2, true); header.setUint32(8, output.length, true)
  header.setUint32(12, jsonLength, true); header.setUint32(16, 0x4e4f534a, true)
  output.fill(32, 20, 20 + jsonLength); output.set(json, 20)
  header.setUint32(20 + jsonLength, binary.length, true); header.setUint32(24 + jsonLength, 0x004e4942, true)
  output.set(binary, 28 + jsonLength)
  let base64Input = ''
  for (let offset = 0; offset < output.length; offset += 8192) base64Input += String.fromCharCode(...output.subarray(offset, offset + 8192))
  return `data:model/gltf-binary;base64,${btoa(base64Input)}`
}

const cache = new Map<string, string>()
export function demoShip(variant: 'coral' | 'teal' = 'coral') {
  if (variant !== 'coral' && variant !== 'teal') throw new Error('Unknown ship variant.')
  if (!cache.has(variant)) {
    const hull: Vec = variant === 'coral' ? [.65, .73, .82] : [.19, .26, .34]
    const accent: Vec = variant === 'coral' ? [.1, .76, .87] : [.98, .31, .16]
    const parts = [
      ellipsoid([0, 0, 0], variant === 'coral' ? [1.7, .23, 1.25] : [1.3, .34, 1.8], hull),
      ellipsoid([0, .23, -.22], [.52, .19, .58], accent, accent.map(v => v * .35) as Vec),
      box([0, -.15, 1.25], [.52, .3, 1.8], hull),
      box([0, -.05, 1.7], [3.8, .15, .36], hull),
    ]
    for (const side of [-1, 1]) {
      parts.push(ellipsoid([side * 1.8, .14, 1.2], [.22, .22, 1.25], hull))
      parts.push(ellipsoid([side * 1.8, .14, 2.35], [.18, .18, .17], accent, accent))
      parts.push(box([side * .7, .22, .3], [.12, .06, .5], accent))
    }
    cache.set(variant, encodeGlb(parts))
  }
  return { name: variant === 'coral' ? 'Aurora · original GLB' : 'Obsidian · original GLB', type: 'model3d' as const, source: cache.get(variant)! }
}
