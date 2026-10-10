import { seeded } from './resources'
import { clock, ScenicBuilder, smooth } from './scenicShared'
import type { MotionLabHandle, MotionLabSettings } from './types'

function lighthouseKeeper(kit: ScenicBuilder, color: string) {
  const keeper = kit.group('lighthouse-keeper'), coat = kit.material(color), dark = kit.material('#25384b')
  const skin = kit.material('#d9aa81'), cream = kit.material('#fff1c5')
  kit.cylinder('keeper-coat', .14, .19, .32, [0, .46, 0], coat, keeper)
  kit.ellipsoid('keeper-head', [.23, .26, .22], [0, .75, 0], skin, keeper)
  kit.ellipsoid('keeper-nose', [.08, .07, .08], [0, .73, .12], skin, keeper)
  kit.cylinder('keeper-cap', .15, .16, .075, [0, .89, 0], dark, keeper)
  kit.box('keeper-cap-peak', [.24, .035, .16], [0, .85, .13], dark, keeper)
  kit.box('keeper-scarf', [.3, .07, .24], [0, .63, 0], cream, keeper)
  const limbs = [-1, 1].map(side => {
    const leg = kit.group(`keeper-leg-${side}`, keeper); leg.position.set(side * .09, .32, 0)
    kit.cylinder('trouser-leg', .055, .05, .24, [0, -.12, 0], dark, leg)
    kit.ellipsoid('boot', [.13, .09, .23], [0, -.27, .04], dark, leg)
    const arm = kit.group(`keeper-arm-${side}`, keeper); arm.position.set(side * .17, .58, 0)
    kit.cylinder('coat-sleeve', .05, .055, .24, [0, -.12, 0], coat, arm)
    kit.ellipsoid('keeper-hand', [.085, .1, .09], [0, -.27, 0], skin, arm)
    return { arm, leg, side }
  })
  return { keeper, limbs }
}

/** A miniature island story: the keeper climbs the exterior spiral before the lantern begins its sweep. */
export function buildLighthouseStory(settings: MotionLabSettings): MotionLabHandle {
  const kit = new ScenicBuilder('motion-lighthouse-story'), stone = kit.material('#667980'), rock = kit.material('#596973')
  const ivory = kit.material('#efe6d1'), stripe = kit.material(settings.color), brass = kit.material('#d5ac62', { metalness: .65 })
  const wood = kit.material('#685144'), dark = kit.material('#273f49'), roof = kit.material(settings.secondaryColor)
  kit.box('open-sea', [96, .6, 96], [0, -1.05, 0], kit.material('#244e68', { roughness: .36, metalness: .28 }))
  kit.cylinder('island', 2.65, 3.3, 1.1, [0, -.43, 0], stone)
  for (let i = 0; i < 17; i++) {
    const a = i * Math.PI * 2 / 17, radius = 2.5 + seeded(settings.seed, i) * .45
    const mesh = kit.ellipsoid('coastal-rock', [.65 + seeded(settings.seed + 1, i) * .65, .55, .75], [Math.cos(a) * radius, -.23, Math.sin(a) * radius], rock)
    mesh.rotation.y = a
  }
  kit.cylinder('tower-foundation', 1.12, 1.22, .24, [0, .18, 0], dark)
  for (let i = 0; i < 5; i++) kit.cylinder('tower-masonry', .98 - (i + 1) * .085, .98 - i * .085, 1.1, [0, .84 + i * 1.1, 0], i % 2 ? stripe : ivory)
  for (const y of [1.2, 2.7, 4.2]) {
    const z = .99 - (y / 5.5) * .425
    kit.cylinder('porthole-glass', .12, .12, .035, [0, y, z], dark).rotation.x = Math.PI / 2
    kit.torus('porthole-rim', .14, .026, [0, y, z + .025], brass)
  }
  kit.cylinder('lantern-balcony', 1.72, 1.72, .16, [0, 5.86, 0], dark)
  const glass = kit.material('#95c5bd', { transparent: true, opacity: .2, depthWrite: false, roughness: .14 })
  kit.cylinder('lantern-glass', .57, .57, .85, [0, 6.33, 0], glass)
  for (let i = 0; i < 10; i++) {
    const a = i * Math.PI / 5
    kit.cylinder('balcony-baluster', .024, .024, .52, [1.64 * Math.cos(a), 6.13, 1.64 * Math.sin(a)], brass)
    if (i % 2 === 0) kit.cylinder('lantern-frame', .035, .035, .87, [.59 * Math.cos(a), 6.34, .59 * Math.sin(a)], dark)
  }
  kit.torus('balcony-rail', 1.64, .033, [0, 6.4, 0], brass).rotation.x = Math.PI / 2
  kit.cylinder('lantern-roof', .12, .83, .5, [0, 7, 0], roof)
  kit.cylinder('weather-mast', .026, .026, .55, [0, 7.45, 0], brass)
  kit.box('weather-vane', [.52, .12, .05], [.12, 7.65, 0], brass)
  const stepCount = 32, startAngle = Math.PI * .45, sweep = Math.PI * 3.6
  for (let i = 0; i < stepCount; i++) {
    const a = startAngle + sweep * i / (stepCount - 1), y = .25 + i * 5.64 / (stepCount - 1)
    const step = kit.box('spiral-stair-tread', [.67, .09, .54], [1.27 * Math.cos(a), y, 1.27 * Math.sin(a)], wood)
    step.rotation.y = -a
    if (i % 2 === 0) kit.cylinder('stair-rail-post', .022, .022, .6, [1.57 * Math.cos(a), y + .3, 1.57 * Math.sin(a)], brass)
    if (i > 0) {
      const before = startAngle + sweep * (i - 1) / (stepCount - 1)
      kit.beam('spiral-handrail', [1.57 * Math.cos(before), y + .42, 1.57 * Math.sin(before)],
        [1.57 * Math.cos(a), y + .6, 1.57 * Math.sin(a)], .028, brass)
    }
  }
  kit.box('keepers-cottage', [1.45, 1.1, 1.35], [-1.98, .67, .56], ivory)
  for (const side of [-1, 1]) {
    const panel = kit.box('cottage-roof', [1.65, .12, .95], [-1.98, 1.4, .56 + side * .34], roof)
    panel.rotation.x = side * .55
  }
  kit.box('cottage-door', [.34, .69, .07], [-1.98, .51, 1.27], dark)
  kit.box('cottage-window', [.27, .3, .06], [-2.46, .83, 1.27], kit.material('#ffcb87', { emissive: '#e29849', emissiveIntensity: .4 }))
  kit.box('cottage-chimney', [.23, .65, .27], [-2.4, 1.65, .24], stone)
  const { keeper, limbs } = lighthouseKeeper(kit, settings.secondaryColor)
  const beacon = kit.group('rotating-beacon'); beacon.position.y = 6.31
  const lens = kit.material('#fff3b6', { emissive: '#ffdd81', emissiveIntensity: 0 })
  kit.ellipsoid('beacon-lens', [.4, .45, .4], [0, 0, 0], lens, beacon)
  const beamMaterial = kit.material('#fff1a5', { emissive: '#f8d374', emissiveIntensity: .8, transparent: true, opacity: 0, depthWrite: false })
  const beam = kit.cylinder('lighthouse-light-volume', 1.05, .09, 7, [3.5, 0, 0], beamMaterial, beacon)
  beam.rotation.z = -Math.PI / 2; beam.castShadow = false
  const waveMaterial = kit.material('#a5c9c8', { transparent: true, opacity: .36, depthWrite: false })
  const waves = Array.from({ length: 7 }, (_, i) => {
    const mesh = kit.torus('ocean-wave', 3.5 + i * .65, .025, [0, -.72, 0], waveMaterial)
    mesh.rotation.x = Math.PI / 2; return mesh
  })
  const update = (seconds: number) => {
    const t = clock(seconds, settings.speed), climb = smooth((t - 2) / 16), a = startAngle + sweep * climb
    keeper.position.set(1.27 * Math.cos(a), .3 + 5.64 * climb, 1.27 * Math.sin(a)); keeper.rotation.y = -a
    const walking = t > 2 && t < 18 ? Math.sin(climb * (stepCount - 1) * Math.PI) * .35 : 0
    for (const { arm, leg, side } of limbs) { leg.rotation.x = side * walking; arm.rotation.x = -side * walking }
    const light = smooth((t - 20) / 1.5)
    beacon.rotation.y = Math.max(0, t - 20) * .55
    lens.emissiveIntensity = light * 2.5; beamMaterial.opacity = light * .12; beam.visible = light > 0
    waves.forEach((wave, i) => { wave.position.y = -.72 + Math.sin(t * .65 + i) * .018 * settings.amplitude; wave.scale.setScalar(1 + Math.sin(t * .4 + i) * .018) })
    kit.root.userData.storyPhase = t < 2 ? 'arrival' : t < 18 ? 'climbing' : t < 20 ? 'lighting' : 'beacon'
  }
  update(0)
  return { root: kit.root, update, dispose: kit.dispose }
}
