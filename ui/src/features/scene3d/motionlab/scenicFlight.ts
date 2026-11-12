import type { Group } from 'three'
import { seeded } from './resources'
import { clock, ScenicBuilder } from './scenicShared'
import type { MotionLabHandle, MotionLabSettings } from './types'

/** An original little mail biplane: thick wings, struts, engine, cockpit, undercarriage and a spinning propeller. */
function aeroplane(kit: ScenicBuilder, name: string, color: string, trim: string): { plane: Group; propeller: Group } {
  const plane = kit.group(name), enamel = kit.material(color), cream = kit.material(trim)
  const brass = kit.material('#d5a75d', { metalness: .7 }), tire = kit.material('#29303b')
  const glass = kit.material('#315872', { roughness: .2, metalness: .45 })
  kit.ellipsoid('fuselage', [2.45, .65, .7], [0, 0, 0], enamel, plane)
  kit.ellipsoid('cockpit', [.7, .45, .48], [.1, .35, 0], glass, plane)
  kit.box('upper-wing', [.92, .11, 3.65], [.1, .58, 0], cream, plane)
  kit.box('lower-wing', [1.05, .12, 3.3], [.2, -.2, 0], enamel, plane)
  for (const side of [-1, 1]) {
    kit.ellipsoid('wingtip', [.92, .12, .25], [.1, .58, side * 1.81], cream, plane)
    for (const x of [-.2, .43]) kit.beam('wing-strut', [x, -.16, side * 1.25], [x - .1, .55, side * 1.4], .025, brass, plane)
    kit.beam('landing-strut', [.48, -.2, side * .22], [.4, -.58, side * .5], .045, brass, plane)
    const wheel = kit.cylinder('wheel', .19, .19, .13, [.4, -.58, side * .5], tire, plane)
    wheel.rotation.x = Math.PI / 2
    const hub = kit.cylinder('wheel-hub', .075, .075, .15, [.4, -.58, side * .5], brass, plane)
    hub.rotation.x = Math.PI / 2
    kit.box('wing-stripe', [.3, .014, .8], [.1, .643, side * 1.05], enamel, plane)
  }
  kit.box('tailplane', [.62, .08, 1.25], [-1.04, .12, 0], cream, plane)
  const fin = kit.box('tail-fin', [.56, .53, .09], [-1, .35, 0], enamel, plane)
  fin.rotation.z = -.2
  const engine = kit.cylinder('engine-cowling', .3, .3, .3, [1.04, 0, 0], brass, plane)
  engine.rotation.z = Math.PI / 2
  const propeller = kit.group('propeller', plane); propeller.position.x = 1.28
  kit.box('propeller-blade-a', [.075, 1.35, .12], [0, 0, 0], tire, propeller)
  kit.box('propeller-blade-b', [.075, .12, 1.35], [0, 0, 0], tire, propeller)
  kit.ellipsoid('spinner', [.24, .22, .22], [.1, 0, 0], cream, propeller)
  return { plane, propeller }
}

/** Two courier aircraft bank together above a tangible ocean and sculpted sunset clouds. */
export function buildSunsetFlight(settings: MotionLabSettings): MotionLabHandle {
  const kit = new ScenicBuilder('motion-sunset-flight')
  const sea = kit.material('#243e69', { metalness: .35, roughness: .38 })
  const glint = kit.material('#ef9d79', { emissive: '#aa523b', emissiveIntensity: .22 })
  const cloud = kit.material('#efd9ca'), shadow = kit.material('#bd9abc')
  kit.box('ocean', [96, .5, 96], [0, -.75, 0], sea)
  const rock = kit.material('#6e7374'), grass = kit.material('#667b57'), trunk = kit.material('#73573e')
  for (const [index, position] of [[-8, -7], [8, -9], [-1, -13]].entries()) {
    const island = kit.group(`distant-island-${index}`); island.position.set(position[0], -.15, position[1])
    kit.ellipsoid('island-rock', [3.4, .9, 2.5], [0, 0, 0], rock, island)
    kit.ellipsoid('island-grass', [2.8, .35, 2.1], [0, .36, 0], grass, island)
    kit.cylinder('island-tree-trunk', .08, .12, 1, [.25, 1, 0], trunk, island)
    kit.ellipsoid('island-tree-crown', [.9, 1, .9], [.25, 1.7, 0], grass, island)
  }
  const sunMaterial = kit.material('#ffbd6a', { emissive: '#ff793e', emissiveIntensity: .8 })
  kit.ellipsoid('setting-sun', [4, 4, 1.1], [0, 5.2, -9], sunMaterial)
  const waves = Array.from({ length: Math.min(72, Math.max(16, Math.round(settings.density / 40))) }, (_, i) => {
    const x = (seeded(settings.seed, i * 4) - .5) * 21, z = (seeded(settings.seed, i * 4 + 1) - .5) * 21
    const width = .35 + seeded(settings.seed, i * 4 + 2) * 1.15
    const mesh = kit.ellipsoid('ocean-glint', [width, .045, .13], [x, -.47, z], glint)
    return { mesh, width, phase: seeded(settings.seed, i * 4 + 3) * Math.PI * 2 }
  })
  const clouds = Array.from({ length: 9 }, (_, i) => {
    const group = kit.group(`cloud-${i}`)
    const x = (seeded(settings.seed + 11, i) - .5) * 18, y = 1.8 + seeded(settings.seed + 22, i) * 4.3
    group.position.set(x, y, -7 + seeded(settings.seed + 33, i) * 13)
    for (let puff = 0; puff < 4; puff++) kit.ellipsoid('cloud-puff', [1.6, .6 + .2 * (puff % 2), .95],
      [(puff - 1.5) * .7, (puff % 2) * .12, 0], puff % 3 ? cloud : shadow, group)
    return { group, x, y }
  })
  const lead = aeroplane(kit, 'lead-aircraft', settings.color, '#ffdc9c')
  const wingman = aeroplane(kit, 'wingman-aircraft', settings.secondaryColor, '#eff0da')
  wingman.plane.scale.setScalar(.74)
  const amplitude = settings.amplitude
  const update = (seconds: number) => {
    const t = clock(seconds, settings.speed), angle = t * .19
    for (const [index, craft] of [lead, wingman].entries()) {
      const phase = angle - index * .28
      craft.plane.position.set(Math.sin(phase) * 3.4 - index * 1.15,
        3.1 - index * .5 + Math.sin(phase * 1.8) * .3 * amplitude, Math.cos(phase) * 2.5 + index * 1.6)
      // Local X is the nose axis: roll into the turn, independently of the route's heading.
      craft.plane.rotation.set(-.2 - Math.sin(phase) * .12 * amplitude,
        Math.atan2(2.5 * Math.sin(phase), 3.4 * Math.cos(phase)), Math.cos(phase * 1.8) * .1 * amplitude, 'YZX')
      craft.propeller.rotation.x = t * 32 + index
    }
    for (const { mesh, width, phase } of waves) {
      mesh.position.y = -.47 + Math.sin(t * .75 + phase) * .024 * amplitude
      mesh.scale.x = width * (1 + Math.sin(t * .6 + phase) * .16)
    }
    for (const { group, x, y } of clouds) { group.position.x = x + Math.sin(t * .05) * .7; group.position.y = y + Math.sin(t * .11 + x) * .08 }
  }
  update(0)
  return { root: kit.root, update, dispose: kit.dispose }
}
