import { BoxGeometry, BufferGeometry, Color, Float32BufferAttribute, Group, IcosahedronGeometry, Mesh, MeshStandardMaterial, Points, PointsMaterial, TorusGeometry } from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { glyphPoints, glyphScale } from './glyphs'
import { disposal, seeded } from './resources'
import type { MotionLabHandle, MotionLabSettings } from './types'

export function buildPosterBreakout(settings: MotionLabSettings): MotionLabHandle {
  const root = new Group(); root.name = 'motion-poster-breakout'
  const dark = new MeshStandardMaterial({ color: '#151d35', roughness: .55 })
  const ink = new MeshStandardMaterial({ color: settings.color, metalness: .35, roughness: .25, emissive: settings.color, emissiveIntensity: .12 })
  const accent = new MeshStandardMaterial({ color: settings.secondaryColor, roughness: .28, metalness: .3 })
  const box = (x: number, y: number, z: number, w: number, h: number, d: number, material = dark) => {
    const mesh = new Mesh(new BoxGeometry(w, h, d), material); mesh.position.set(x, y, z); root.add(mesh); return mesh
  }
  box(0, -.15, 0, 10, .3, 7)
  box(0, 2.4, -.9, 7.4, 4.8, .22)
  box(-3.8, 2.4, -.63, .2, 5, .55, accent); box(3.8, 2.4, -.63, .2, 5, .55, accent)
  box(0, 4.9, -.63, 7.8, .2, .55, accent); box(0, .1, -.63, 7.8, .2, .55, accent)
  const points = glyphPoints(settings.title || 'HOCUS')
  const cell = glyphScale(settings.title || 'HOCUS')
  const pieces = points.map(([x, y]) => new BoxGeometry(cell * .84, cell * .84, .22).translate(x, y, 0))
  const geometry = mergeGeometries(pieces)
  pieces.forEach(piece => piece.dispose())
  const title = new Mesh(geometry ?? new BoxGeometry(.1, .1, .1), ink); title.name = 'volume-title'; root.add(title)
  const rings = [0, 1].map(index => {
    const ring = new Mesh(new TorusGeometry(.58, .09, 8, 36), index ? ink : accent)
    ring.name = `frame-crossing-ring-${index}`; root.add(ring); return ring
  })
  const orb = new Mesh(new IcosahedronGeometry(.38, 1), accent); orb.name = 'frame-crossing-orb'; root.add(orb)
  const slats = Array.from({ length: 12 }, (_, index) => box((index - 5.5) * .52, 1, -.66, .26, .3, .12, index % 2 ? ink : accent))
  const handle = { root, dispose: disposal(root), update(seconds: number) {
    const t = Math.max(0, Number.isFinite(seconds) ? seconds : 0) * settings.speed, phase = t % 10
    const forward = phase < 2 ? 0 : phase < 5 ? (phase - 2) / 3 : phase < 8 ? 1 : (10 - phase) / 2
    const ease = forward * forward * (3 - 2 * forward)
    title.position.set(0, 2.8, -.55 + ease * 2.1 * settings.amplitude)
    title.rotation.set(-ease * .15, Math.sin(t * .7) * ease * .12, ease * Math.sin(t) * .05)
    rings.forEach((ring, index) => {
      const a = t * .65 + index * Math.PI
      ring.position.set(Math.cos(a) * 2.45, 2.1 + Math.sin(a) * 1.15, -.4 + Math.sin(a * 1.5) * 1.5)
      ring.rotation.set(a * .45, a, a * .15)
    })
    orb.position.set(Math.sin(t * .6) * 2.9, 1.2 + .3 * Math.cos(t), -.5 + Math.cos(t * .6) * 1.8)
    orb.rotation.set(t * .2, t * .45, 0)
    slats.forEach((slat, index) => { slat.scale.y = 1 + .7 * Math.sin(t * 2 + index * .6); slat.position.z = -.66 + .12 * Math.sin(t + index) })
  } }
  handle.update(0); return handle
}

/** Four genuinely volumetric point targets: sphere, torus, heart and block lettering. */
export function buildParticleMorph(settings: MotionLabSettings): MotionLabHandle {
  const root = new Group(); root.name = 'motion-particle-morph'
  const count = settings.density, targets = Array.from({ length: 4 }, () => new Float32Array(count * 3))
  const glyph = glyphPoints(settings.title || 'HOCUS')
  for (let index = 0; index < count; index++) {
    const a = index * Math.PI * (3 - Math.sqrt(5)), y = 1 - 2 * (index + .5) / count, r = Math.sqrt(1 - y * y)
    targets[0].set([Math.cos(a) * r * 2.1, y * 2.1, Math.sin(a) * r * 2.1], index * 3)
    const b = seeded(settings.seed, index) * Math.PI * 2
    targets[1].set([(1.7 + .55 * Math.cos(b)) * Math.cos(a), .55 * Math.sin(b), (1.7 + .55 * Math.cos(b)) * Math.sin(a)], index * 3)
    const h = index / count * Math.PI * 2
    targets[2].set([Math.pow(Math.sin(h), 3) * 2.1, (13 * Math.cos(h) - 5 * Math.cos(2 * h) - 2 * Math.cos(3 * h) - Math.cos(4 * h)) * .13, (seeded(settings.seed + 1, index) - .5) * .75], index * 3)
    const point = glyph[index % Math.max(1, glyph.length)] ?? [0, 0]
    targets[3].set([point[0], point[1], (seeded(settings.seed + 2, index) - .5) * .32], index * 3)
  }
  const positions = new Float32Array(count * 3), colors = new Float32Array(count * 3)
  const primary = new Color(settings.color), secondary = new Color(settings.secondaryColor)
  for (let index = 0; index < count; index++) new Color().copy(primary).lerp(secondary, seeded(settings.seed + 3, index)).toArray(colors, index * 3)
  const geometry = new BufferGeometry(); geometry.setAttribute('position', new Float32BufferAttribute(positions, 3)); geometry.setAttribute('color', new Float32BufferAttribute(colors, 3))
  const material = new PointsMaterial({ size: .065, vertexColors: true, sizeAttenuation: true, toneMapped: false })
  const cloud = new Points(geometry, material); cloud.name = 'morph-cloud'; cloud.frustumCulled = false; cloud.position.y = 2.6; root.add(cloud)
  const plinth = new Mesh(new BoxGeometry(8, .2, 7), new MeshStandardMaterial({ color: '#101a2b', roughness: .45 })); plinth.position.y = -.1; root.add(plinth)
  const ring = new Mesh(new TorusGeometry(2.7, .035, 6, 64), new MeshStandardMaterial({ color: settings.secondaryColor, emissive: settings.secondaryColor, emissiveIntensity: .4 }))
  ring.rotation.x = Math.PI / 2; ring.position.y = .035; root.add(ring)
  const handle = { root, dispose: disposal(root), update(seconds: number) {
    const t = Math.max(0, Number.isFinite(seconds) ? seconds : 0) * settings.speed, phase = t / 6, from = Math.floor(phase) % 4, to = (from + 1) % 4
    const progress = Math.max(0, Math.min(1, (phase % 1 - .45) / .5)), ease = progress * progress * (3 - 2 * progress)
    const attribute = geometry.getAttribute('position')
    // Keep the full cloud framed across the editable range; amplitude controls a bounded excursion.
    const size = .9 + settings.amplitude * .1
    for (let index = 0; index < count * 3; index++) attribute.array[index] = (targets[from][index] * (1 - ease) + targets[to][index] * ease) * size
    attribute.needsUpdate = true
    // Lettering holds front-on; all other shapes rotate gently.
    cloud.rotation.y = from === 3 ? 0 : Math.sin(t * .2) * .25
  } }
  handle.update(0); return handle
}
