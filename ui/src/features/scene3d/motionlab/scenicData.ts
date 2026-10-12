import type { Group, Material } from 'three'
import { seeded } from './resources'
import { clock, ScenicBuilder, smooth, wrap } from './scenicShared'
import type { MotionLabHandle, MotionLabSettings } from './types'

function rack(kit: ScenicBuilder, parent: Group, name: string, x: number, z: number, led: Material, tint: Material) {
  const group = kit.group(name, parent); group.position.set(x, .28, z)
  const steel = kit.material('#34404f', { metalness: .65 }), silver = kit.material('#8d9da8', { metalness: .75 })
  for (const dx of [-.57, .57]) for (const dz of [-.53, .53]) kit.box('rack-post', [.085, 3.1, .085], [dx, 1.55, dz], steel, group)
  for (const y of [.04, 3.05]) kit.box('rack-frame', [1.24, .12, 1.18], [0, y, 0], steel, group)
  for (let shelf = 0; shelf < 6; shelf++) {
    const y = .4 + shelf * .43
    kit.box('server-module', [1.03, .29, .95], [0, y, 0], silver, group)
    kit.box('server-front', [.99, .21, .06], [0, y, .51], tint, group)
    for (let slot = 0; slot < 4; slot++) kit.box('vent-slot', [.032, .105, .017], [.03 + slot * .15, y, .55], steel, group)
    for (const dx of [-.39, -.24]) kit.ellipsoid('status-led', [.052, .052, .034], [dx, y, .56], led, group)
    kit.box('drawer-handle', [.08, .045, .09], [.41, y, .59], silver, group)
  }
  return group
}

function chipLayers(kit: ScenicBuilder, parent: Group, primary: Material, accent: Material) {
  const gold = kit.material('#d3b469', { metalness: .8 }), dark = kit.material('#263140')
  const silver = kit.material('#9baeb7', { metalness: .8, roughness: .3 })
  const groups = Array.from({ length: 6 }, (_, i) => kit.group(`assembly-layer-${i}`, parent))
  kit.box('main-board', [2.6, .16, 2.3], [0, 0, 0], primary, groups[0])
  for (let i = 0; i < 8; i++) for (const side of [-1, 1]) {
    kit.box('gold-contact', [.11, .035, .19], [-1.02 + i * .29, .1, side * 1.12], gold, groups[0])
    kit.box('board-capacitor', [.13, .25, .13], [side * 1.04, .17, -.8 + i * .22], silver, groups[0])
  }
  kit.box('processor-socket', [1.67, .18, 1.53], [0, 0, 0], dark, groups[1])
  kit.box('silicon-chip', [1.12, .16, 1.04], [0, 0, 0], accent, groups[2])
  for (let i = 0; i < 9; i++) kit.box('silicon-cell', [.18, .018, .18], [((i % 3) - 1) * .27, .094, (Math.floor(i / 3) - 1) * .27], gold, groups[2])
  kit.box('heat-spreader', [1.5, .15, 1.4], [0, 0, 0], silver, groups[3])
  kit.box('heatsink-base', [1.65, .09, 1.6], [0, -.18, 0], silver, groups[4])
  for (let i = 0; i < 9; i++) kit.box('heatsink-fin', [.065, .42, 1.52], [-.68 + i * .17, .06, 0], silver, groups[4])
  kit.torus('cooling-fan-ring', .7, .06, [0, 0, 0], dark, groups[5]).rotation.x = Math.PI / 2
  const fan = kit.group('cooling-fan', groups[5])
  kit.cylinder('fan-hub', .16, .16, .11, [0, 0, 0], accent, fan)
  for (let i = 0; i < 7; i++) {
    const a = i * Math.PI * 2 / 7, blade = kit.box('fan-blade', [.51, .055, .19], [Math.cos(a) * .38, 0, Math.sin(a) * .38], dark, fan)
    blade.rotation.set(.12, -a + .35, 0)
  }
  return { groups, fan }
}

/** An orbiting miniature data center with a phased, exploded processor and visible cooling/data routes. */
export function buildDataAssembly(settings: MotionLabSettings): MotionLabHandle {
  const kit = new ScenicBuilder('motion-data-assembly'), machine = kit.group('data-center-tour')
  const charcoal = kit.material('#1b2738'), pcb = kit.material(settings.color, { roughness: .48 })
  const accent = kit.material(settings.secondaryColor, { metalness: .48 })
  const led = kit.material(settings.color, { emissive: settings.color, emissiveIntensity: 1.2 })
  const copper = kit.material('#c6a06f', { metalness: .7 }), pipe = kit.material('#729baa', { metalness: .55 })
  kit.box('data-center-plinth', [8.8, .3, 7.6], [0, .04, 0], charcoal)
  kit.box('raised-machine-floor', [8, .18, 6.8], [0, .25, 0], kit.material('#394758'), machine)
  for (const x of [-2.85, 2.85]) for (const z of [-2.1, 2.1]) rack(kit, machine, `server-rack-${x}-${z}`, x, z, led, pcb)
  for (const z of [-1.72, 1.72]) kit.box('horizontal-data-bus', [5.7, .025, .09], [0, .36, z], copper, machine)
  for (const x of [-2.85, 2.85]) kit.box('vertical-data-bus', [.09, .025, 3.53], [x, .36, 0], copper, machine)
  const { groups, fan } = chipLayers(kit, machine, pcb, accent)
  const baseY = [.48, .69, .88, 1.09, 1.4, 1.78]
  const radiator = kit.group('liquid-cooling-radiator', machine); radiator.position.set(1.9, .37, 0)
  kit.box('radiator-frame', [.48, 1.82, 1.44], [0, .91, 0], charcoal, radiator)
  for (let i = 0; i < 12; i++) kit.box('radiator-fin', [.62, .065, 1.34], [0, .12 + i * .14, 0], pipe, radiator)
  for (const side of [-1, 1]) {
    kit.beam('coolant-feed', [.8, .49, side * .55], [1.42, .49, side * .55], .065, pipe, machine)
    kit.beam('coolant-riser', [1.42, .49, side * .55], [1.42, 1.98, side * .55], .065, pipe, machine)
    kit.beam('coolant-return', [1.42, 1.98, side * .55], [1.92, 1.98, side * .55], .065, pipe, machine)
  }
  const flows = Array.from({ length: Math.min(56, Math.max(14, Math.round(settings.density / 50))) }, (_, i) => {
    const mesh = kit.ellipsoid('data-packet', [.065, .065, .065], [0, .41, 0], led, machine)
    return { mesh, phase: seeded(settings.seed, i) * 4 }
  })
  const coolant = Array.from({ length: 10 }, (_, i) => kit.ellipsoid('coolant-pulse', [.12, .12, .12], [1.42, .5, i % 2 ? -.55 : .55], accent, machine))
  const update = (seconds: number) => {
    const t = clock(seconds, settings.speed), phase = wrap(t, 32)
    const exploded = phase < 7 ? 1 - smooth(phase / 7) : phase < 15 ? 0 : phase < 23 ? smooth((phase - 15) / 8) : 1
    machine.rotation.y = t * Math.PI / 48
    groups.forEach((group, i) => { group.position.y = baseY[i] + exploded * i * .57; group.rotation.y = exploded * i * .075 })
    fan.rotation.y = t * (12 + (1 - exploded) * 12)
    led.emissiveIntensity = 1.05 + Math.sin(t * 2) * .18 * settings.amplitude
    for (const { mesh, phase: offset } of flows) {
      const point = wrap(t * .38 + offset, 4), edge = Math.floor(point), progress = point - edge
      if (edge === 0) mesh.position.set(-2.85 + progress * 5.7, .41, -1.72)
      else if (edge === 1) mesh.position.set(2.85, .41, -1.72 + progress * 3.44)
      else if (edge === 2) mesh.position.set(2.85 - progress * 5.7, .41, 1.72)
      else mesh.position.set(-2.85, .41, 1.72 - progress * 3.44)
    }
    coolant.forEach((mesh, i) => { mesh.position.y = .49 + wrap(t * .65 + i * .17, 1.49) })
    kit.root.userData.assemblyPhase = phase < 7 ? 'assembling' : phase < 15 ? 'running' : phase < 23 ? 'exploding' : 'inspection'
  }
  update(0)
  return { root: kit.root, update, dispose: kit.dispose }
}
