/** A real night for the procedural worlds: dark sky gradient, stars, a lit moon with a halo and the palette the sets read when `timeOfDay` is `night`.
 *  Day-for-night (low exposure on a day world) leaves the grass lime-green, the fog bright and no sky body; a set that offers `night` paints all of it dark instead. */
import {
  AdditiveBlending, BufferGeometry, CircleGeometry, Color, Float32BufferAttribute, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, Points, PointsMaterial, Sprite, SpriteMaterial,
  type Material, type Texture,
} from 'three'
import { hash2 } from './noise.ts'
import { canvasTexture } from './textures.ts'

export const NIGHT_PALETTE = 'night'
export const NIGHT = {
  horizon: '#111c35', zenith: '#03060f', cloud: '#1f2a45', moon: '#eef2ff', halo: '#7f9ad8',
  hemiSky: 0x5a70b0, hemiGround: 0x141b2c, hemiIntensity: 0.55,
} as const

export type NightKept = { geometries: BufferGeometry[]; materials: Material[]; textures: Texture[] }

export const isNight = (time: string | undefined): boolean => time === 'night'

/** The palette a set paints with: the night one whenever the time of day is night, whatever palette the document names. */
export function effectivePalette(settings: { palette: string; timeOfDay: string }): string {
  return isNight(settings.timeOfDay) ? NIGHT_PALETTE : settings.palette
}

function starPoints(count: number, radius: number, seed: number, size: number, opacity: number, salt: number): Points {
  const positions: number[] = []
  const colors: number[] = []
  const tint = new Color()
  for (let i = 0; i < count; i += 1) {
    const azimuth = hash2(i, salt, seed) * Math.PI * 2
    const sinElevation = 0.04 + hash2(i, salt + 1, seed) * 0.96
    const flat = Math.sqrt(1 - sinElevation * sinElevation)
    positions.push(Math.cos(azimuth) * flat * radius, sinElevation * radius, Math.sin(azimuth) * flat * radius)
    tint.setHSL(0.58 + (hash2(i, salt + 2, seed) - 0.5) * 0.16, 0.45, 0.82 + hash2(i, salt + 3, seed) * 0.16)
    colors.push(tint.r, tint.g, tint.b)
  }
  const geo = new BufferGeometry()
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geo.setAttribute('color', new Float32BufferAttribute(colors, 3))
  const mat = new PointsMaterial({ size, sizeAttenuation: false, vertexColors: true, transparent: true, opacity, depthWrite: false, fog: false })
  const points = new Points(geo, mat)
  points.name = 'atmos-stars'
  points.frustumCulled = false
  points.renderOrder = -1
  return points
}

function moonTexture(): Texture | null {
  return canvasTexture(256, (ctx, size) => {
    const c = size / 2
    const disc = ctx.createRadialGradient(c * 0.86, c * 0.84, c * 0.1, c, c, c)
    disc.addColorStop(0, '#fbfcff')
    disc.addColorStop(1, '#c9d2ea')
    ctx.fillStyle = disc
    ctx.beginPath()
    ctx.arc(c, c, c - 2, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = 'rgba(120,132,168,0.32)'
    for (const [x, y, r] of [[0.38, 0.4, 0.17], [0.62, 0.34, 0.1], [0.55, 0.64, 0.21], [0.3, 0.68, 0.09], [0.72, 0.6, 0.08]]) {
      ctx.beginPath()
      ctx.arc(size * x, size * y, size * r * 0.5, 0, Math.PI * 2)
      ctx.fill()
    }
  })
}

function haloTexture(): Texture | null {
  return canvasTexture(128, (ctx, size) => {
    const c = size / 2
    const glow = ctx.createRadialGradient(c, c, 0, c, c, c)
    glow.addColorStop(0, 'rgba(190,208,255,0.85)')
    glow.addColorStop(0.28, 'rgba(140,165,235,0.34)')
    glow.addColorStop(1, 'rgba(90,120,210,0)')
    ctx.fillStyle = glow
    ctx.fillRect(0, 0, size, size)
  })
}

/** Stars on the upper dome and a moon along `-sun` (the sun vector is the direction the light travels). Everything is unlit and ignores the fog,
 *  so the sky bodies stay crisp at any distance; `radius` is the sky dome's radius and the bodies sit just inside it. */
export function addNightSky(root: Group, kept: NightKept, sun: readonly [number, number, number], radius: number, seed: number): Group {
  const sky = new Group()
  sky.name = 'atmos-night-sky'
  const inner = radius * 0.94
  for (const stars of [starPoints(700, inner, seed, 1.3, 0.62, 11), starPoints(110, inner, seed, 2.6, 0.95, 41)]) {
    sky.add(stars)
    kept.geometries.push(stars.geometry)
    kept.materials.push(stars.material as Material)
  }
  const length = Math.hypot(sun[0], sun[1], sun[2]) || 1
  const direction = [-sun[0] / length, -sun[1] / length, -sun[2] / length] as const
  const distance = radius * 0.9
  const moonRadius = distance * 0.05
  const moonMap = moonTexture()
  if (moonMap) kept.textures.push(moonMap)
  const geo = new CircleGeometry(moonRadius, 48)
  const mat = new MeshBasicMaterial({ map: moonMap ?? null, color: moonMap ? 0xffffff : NIGHT.moon, fog: false, depthWrite: false, transparent: true })
  const moon = new Mesh(geo, mat)
  moon.name = 'atmos-moon'
  moon.position.set(direction[0] * distance, direction[1] * distance, direction[2] * distance)
  moon.lookAt(0, 0, 0)
  moon.renderOrder = 1
  moon.frustumCulled = false
  sky.add(moon)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  const haloMap = haloTexture()
  if (haloMap) {
    kept.textures.push(haloMap)
    const halo = new Sprite(new SpriteMaterial({ map: haloMap, color: NIGHT.halo, fog: false, depthWrite: false, transparent: true, blending: AdditiveBlending, opacity: 0.55 }))
    halo.name = 'atmos-moon-halo'
    halo.position.copy(moon.position)
    halo.scale.setScalar(moonRadius * 7)
    halo.renderOrder = 0
    sky.add(halo)
    kept.materials.push(halo.material)
  }
  root.add(sky)
  return sky
}

/** Day worlds light their wood, leaves and rocks with a faint self-glow so they read in shade; at night that glow must go or the forest looks lit from inside. */
export function dimEmissives(root: Group, factor: number): void {
  const seen = new Set<Material>()
  root.traverse(object => {
    const material = (object as Mesh).material
    for (const item of Array.isArray(material) ? material : material ? [material] : []) {
      if (seen.has(item) || !(item instanceof MeshStandardMaterial)) continue
      seen.add(item)
      item.emissiveIntensity *= factor
    }
  })
}
