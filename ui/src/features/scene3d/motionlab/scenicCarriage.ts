import { Color } from 'three'
import { seeded } from './resources'
import { clock, ScenicBuilder, smooth, wrap } from './scenicShared'
import type { MotionLabHandle, MotionLabSettings } from './types'

const SEASONS = ['spring', 'summer', 'autumn', 'winter'] as const
const LEAVES = ['#e7a5bd', '#4f8153', '#c47739', '#e1e9e7'].map(color => new Color(color))
const EARTH = ['#9da76c', '#64805c', '#9b7759', '#d2dde2'].map(color => new Color(color))
const SKY = ['#bdcbd6', '#83b5c4', '#c8a4a0', '#aabdcf'].map(color => new Color(color))

function carriageInterior(kit: ScenicBuilder, settings: MotionLabSettings) {
  const wood = kit.material('#493d3c'), warmWood = kit.material('#9a654b'), cream = kit.material('#e4d7bd')
  const brass = kit.material('#c5a365', { metalness: .65 }), fabric = kit.material(settings.color)
  const ceramic = kit.material(settings.secondaryColor, { roughness: .24 })
  kit.box('carriage-floor', [7, .25, 4.5], [0, -.12, .45], wood)
  for (let i = 0; i < 14; i++) kit.box('floor-plank', [.46, .04, 4.4], [-3.24 + i * .5, .025, .45], warmWood)
  // Four substantial wall pieces leave an actual aperture. Nothing opaque covers the landscape.
  kit.box('window-wall-base', [7, 1.05, .3], [0, .53, -1.65], wood)
  kit.box('window-wall-top', [7, .55, .3], [0, 4.05, -1.65], wood)
  for (const side of [-1, 1]) {
    kit.box('window-wall-pier', [.6, 2.72, .3], [side * 3.2, 2.41, -1.65], wood)
    kit.box('window-brass-upright', [.07, 2.74, .1], [side * 2.87, 2.41, -1.44], brass)
    kit.box('velvet-seat', [1.1, .3, 2.4], [side * 2.7, .65, .15], fabric)
    kit.box('seat-back', [.28, 1.2, 2.4], [side * 3.18, 1.2, .15], fabric)
    for (const z of [-.8, 1.05]) {
      kit.cylinder('seat-leg', .065, .09, .5, [side * 2.7, .25, z], brass)
      kit.box('seat-button', [.032, .12, .12], [side * 3.02, 1.35, z], cream)
    }
    kit.box('luggage-shelf', [.9, .12, 2.7], [side * 2.94, 3.68, .1], warmWood)
    kit.box('travel-case', [.64, .4, .88], [side * 2.95, 3.93, -.35], ceramic)
  }
  for (const y of [1.08, 3.75]) kit.box('window-brass-rail', [5.82, .08, .12], [0, y, -1.44], brass)
  kit.box('window-sill', [6.1, .1, .52], [0, 1.01, -1.35], warmWood)
  kit.box('window-glass', [5.7, 2.61, .045], [0, 2.42, -1.62], kit.material('#b7dcde', { transparent: true, opacity: .055, depthWrite: false, roughness: .08 }))
  kit.box('tabletop', [2.9, .16, 1.65], [0, 1.18, .25], warmWood)
  for (const x of [-.9, .9]) {
    kit.cylinder('table-pedestal', .09, .15, 1.1, [x, .56, .25], brass)
    kit.box('table-foot', [.6, .1, 1.08], [x, .09, .25], wood)
  }
  kit.box('linen-runner', [.72, .018, 1.57], [.62, 1.272, .25], cream)
  kit.box('closed-book', [.67, .08, .82], [-.82, 1.3, .33], fabric)
  kit.box('book-pages', [.62, .045, .77], [-.8, 1.345, .33], cream)
  kit.cylinder('saucer', .36, .32, .035, [.2, 1.3, .18], ceramic)
  kit.cylinder('cup-bottom', .18, .16, .035, [.2, 1.335, .18], ceramic)
  for (let i = 0; i < 5; i++) {
    const ring = kit.torus('cup-thick-wall', .17, .037, [.2, 1.36 + i * .054, .18], ceramic)
    ring.rotation.x = Math.PI / 2
  }
  kit.cylinder('coffee', .138, .138, .02, [.2, 1.568, .18], kit.material('#382626'))
  kit.torus('cup-handle', .12, .033, [.43, 1.47, .18], ceramic)
  for (const x of [-1.65, 1.65]) {
    kit.cylinder('lamp-stem', .025, .025, .78, [x, 3.48, -.2], brass)
    kit.cylinder('lamp-shade', .17, .4, .33, [x, 3.08, -.2], fabric)
    kit.cylinder('lamp-diffuser', .33, .33, .035, [x, 2.89, -.2], kit.material('#ffe7ad', { emissive: '#ffcb76', emissiveIntensity: 1.4 }))
  }
  const steamMaterial = kit.material('#f5e9d6', { transparent: true, opacity: .28, depthWrite: false })
  return Array.from({ length: 4 }, (_, i) => kit.ellipsoid(`steam-${i}`, [.045, .12, .045], [.2, 1.7, .18], steamMaterial))
}

/** A cutaway railway carriage; three landscape depths pass a real window over a 32-second seasonal journey. */
export function buildSeasonalCarriage(settings: MotionLabSettings): MotionLabHandle {
  const kit = new ScenicBuilder('motion-seasonal-carriage'), steam = carriageInterior(kit, settings)
  const ground = kit.material(EARTH[0].getHex()), foliage = kit.material(LEAVES[0].getHex())
  const sky = kit.material(SKY[0].getHex(), { roughness: 1 }), bark = kit.material('#655443')
  const rock = kit.material('#8a8e96'), snow = kit.material('#faf9f2', { transparent: true, opacity: 0, depthWrite: false })
  kit.box('outside-ground', [39, .75, 17], [0, -.38, -10.5], ground)
  kit.ellipsoid('distant-sky', [40, 14, 5], [0, 5, -21], sky)
  const mountains = Array.from({ length: 7 }, (_, i) => {
    const x = -17 + i * 5.5
    const mesh = kit.cylinder(`distant-mountain-${i}`, .15, 3.5, 3 + seeded(settings.seed + 1, i) * 3, [x, 1.4, -16], rock)
    return { mesh, x }
  })
  const trees = Array.from({ length: 22 }, (_, i) => {
    const group = kit.group(`landscape-tree-${i}`), depth = i % 2 ? -5.2 : -9.5
    const x = -18 + seeded(settings.seed, i) * 36, height = 1.3 + seeded(settings.seed + 7, i) * 1.1
    group.position.set(x, 0, depth)
    kit.cylinder('tree-trunk', .055, .13, height, [0, height / 2, 0], bark, group)
    kit.beam('tree-branch', [0, height * .55, 0], [.4, height * .9, .1], .035, bark, group)
    for (const side of [-1, 0, 1]) kit.ellipsoid('seasonal-canopy', [.95, 1.05, .9], [side * .35, height + Math.abs(side) * .1, .04], foliage, group)
    return { group, x, depth }
  })
  const flakes = Array.from({ length: Math.min(48, Math.max(12, Math.round(settings.density / 60))) }, (_, i) => {
    const x = (seeded(settings.seed + 20, i) - .5) * 16, z = -3.3 - seeded(settings.seed + 30, i) * 7
    const mesh = kit.ellipsoid('winter-snow', [.05, .05, .05], [x, 0, z], snow)
    return { mesh, x, phase: seeded(settings.seed + 40, i) * 5 }
  })
  const update = (seconds: number) => {
    const t = clock(seconds, settings.speed), year = wrap(t, 32), season = Math.floor(year / 8), blend = smooth((year % 8 - 6) / 2)
    const next = (season + 1) % 4
    kit.root.userData.season = SEASONS[season]
    ground.color.copy(EARTH[season]).lerp(EARTH[next], blend)
    foliage.color.copy(LEAVES[season]).lerp(LEAVES[next], blend)
    sky.color.copy(SKY[season]).lerp(SKY[next], blend)
    snow.opacity = .8 * ((season === 3 ? 1 - blend : 0) + (next === 3 ? blend : 0))
    for (const { group, x, depth } of trees) group.position.x = wrap(x - t * (depth > -6 ? 2.7 : 1.45) + 18, 36) - 18
    for (const { mesh, x } of mountains) mesh.position.x = wrap(x - t * .28 + 20, 40) - 20
    for (const { mesh, x, phase } of flakes) {
      mesh.visible = snow.opacity > 0
      mesh.position.set(x + Math.sin(t + phase) * .15 * settings.amplitude, wrap(phase - t * .75, 5), mesh.position.z)
    }
    steam.forEach((mesh, i) => {
      const rise = wrap(t * .38 + i / 4, 1)
      mesh.position.set(.2 + Math.sin(t * 1.2 + i) * .055 * settings.amplitude, 1.65 + rise * .65, .18)
      mesh.scale.set(.045 * (1 + rise), .12 * (1 - rise * .6), .045 * (1 + rise))
    })
  }
  update(0)
  return { root: kit.root, update, dispose: kit.dispose }
}
