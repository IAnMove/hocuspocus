import { INDEX, layer, paintMoon, paintRange, paintReeds, paintSky, type IndexedLayer } from './pixelPaint'
import { paintCliff, paintDunes, paintFireflies, paintForest, paintMesas, paintSkyline, paintTrain, paintViaduct, paintVolcano, paintCars, paintGarden, paintReef, paintSchool, paintSeaLight, paintMist, paintBalloon, paintWheel, paintStand, paintCabin, paintTents, paintVillage, paintSkater, paintFalls, paintNebula, paintPlanetLimb, paintStation, paintAsteroid, paintWindmills, paintFacade, paintCastle, paintBeach, paintLanterns, paintRoom, paintLoopRange, paintPoles, paintCarriage, dustSnow, paintOrchard, paintNaveWall, paintArcade, paintFlagstones, paintPond, paintLilies, paintKoi, paintCaravan, paintGrid, paintPalms, paintMurmuration, paintLaunchTower, paintRocket, paintExhaust, paintCaveMouth, paintGrotto } from './pixelPaintWorlds'
import { bodySkyX, type PixelScene, type PixelWorldKind } from './pixelScene'

/** One painted plane of a world: where it stands (meters) and its art size. */
export type LayerSpec = {
  z: number; width: number; height: number; bottom: number; texture: [number, number]
  sky?: boolean
  /** Meters per second the plane travels along x, looping over `loop` meters. */
  drift?: { speed: number; loop: number; offset?: number; /** Meters it bobs up and down. */ bob?: number; /** Travels up instead of across, swaying. */ rise?: boolean }
  /** Where it stands across x (meters) and how it is turned about y, for walls. */
  x?: number
  turn?: number
  /** Texels per second its painting slides past, wrapping (painted to loop). */
  scroll?: number
  /** The same along its height: a floor flowing toward the camera. */
  scrollY?: number
  /** Lies flat on the ground instead of standing, centred at `z`. */
  floor?: boolean
  /** Radians per second it turns about its own centre. */
  spin?: number
  /** Goes round a centre (x, y) at `radius`, staying upright, like a gondola. */
  orbit?: { x: number; y: number; radius: number; speed: number; phase: number; /** Hangs this far below its point, like a gondola. */ drop?: number; /** Vertical radius, for a flattened arc. */ ry?: number; /** Circles on the ground (y is then z), facing where it goes. */ flat?: boolean }
  /** The sun or moon on its arc: the key light follows whichever is higher. */
  celestial?: 'sun' | 'moon'
  /** Paints frame `frame` of `frames` when the layer is a sprite animation. */
  paint: (w: number, h: number, frame?: number) => IndexedLayer
  /** Lifts off once at `at` seconds and climbs with `accel` m/s²; an
   *  `ignite` layer (the flame) only shows from just before liftoff. */
  launch?: { at: number; accel: number; ignite?: boolean }
  /** A sprite animation: this many frames, shown at `fps`. */
  frames?: { count: number; fps: number }
}
/** A shaft of coloured light from a window to the floor, in meters. */
export type Beam = { from: [number, number, number]; to: [number, number, number]; width: number; hue: number }
export type WorldPlan = { beams?: Beam[]; layers: LayerSpec[]; ground: 'water' | 'sand' | 'field' | 'none'; /** Height of the floor, meters. */ groundY?: number; /** Fireworks burst in the sky. */ fireworks?: boolean; /** No aurora ever hangs here. */ clearSky?: boolean; /** Raindrops ring the water, 0..1. */ rain?: number; /** The world's light breathes in this colour. */ pulse?: string }

const SKY: Omit<LayerSpec, 'paint'> = { z: -62, width: 170, height: 52, bottom: -4, texture: [700, 214], sky: true }
const FAR: Omit<LayerSpec, 'paint'> = { z: -46, width: 130, height: 30, bottom: -1.5, texture: [680, 157] }
const NEAR: Omit<LayerSpec, 'paint'> = { z: -37, width: 110, height: 7, bottom: -1, texture: [720, 46] }
const far = { body: INDEX.far, rim: INDEX.farRim }
/** The eclipse: where the discs hang, how fast the moon crosses and its
 *  size in texels (on a 24 m, 96 texel plate). */
export const ECLIPSE = { y: 20, speed: 2, start: -20, texels: 11, meters: 11 * 24 / 96 }

/** How dark the eclipse makes the day at `seconds`, 0 to 1: the share of the
 *  sun the moon covers, eased so totality is brief and deep. */
export function eclipseShade(seconds: number) {
  const apart = Math.abs(ECLIPSE.start + ECLIPSE.speed * seconds)
  const cover = Math.max(0, Math.min(1, (2 * ECLIPSE.meters - apart) / (1.8 * ECLIPSE.meters)))
  return cover * cover
}

/** Koi: path radii, speed (radians/s, sign is the way round), start and length. */
const KOI: [number, number, number, number, number][] = [[4.6, 3.1, .35, 0, 1.3], [3.4, 2.4, -.45, 1.7, 1.1], [2.2, 1.6, .6, 3.2, .9], [4, 2.2, -.3, 4.4, 1.2], [1.4, 1.2, -.7, .9, .8], [3, 2.8, .4, 5.3, 1]]

/** The launch: where the rocket stands, when it lifts off and how hard. */
export const LAUNCH = { x: 4, pad: .3, at: 6, accel: 1.6 }

/** How brightly the engines light the coast at `seconds`: they flare at
 *  ignition, blaze at liftoff and fade as the rocket climbs away. */
export function launchGlow(seconds: number) {
  const since = seconds - LAUNCH.at
  if (since < -1.2) return 0
  return Math.min(1, (since + 1.2) / .5) * Math.exp(-Math.max(0, since) * .3)
}

/** A day in the day-cycle world lasts as long as its template's clip. */
export const DAY_SECONDS = 24

/** Lantern flocks: depth, plane width and height, rise speed, lantern count. */
const LANTERNS: [number, number, number, number, number][] = [[-40, 70, 26, .35, 60], [-28, 44, 18, .5, 34], [-18, 26, 12, .7, 18], [-10, 14, 8, .9, 8]]

/** The Ferris wheel's hub height and radius, meters (centred on x = 0). */
const WHEEL = { y: 8.6, radius: 7.2 }

/** The village plane; its chimneys are mapped into the world for smoke. */
export const VILLAGE: Omit<LayerSpec, 'paint'> = { z: -26, width: 70, height: 9, bottom: -.6, texture: [560, 72] }

/** Balloons: depth, size, height, drift speed, start and two cloth colours. */
const BALLOONS: [number, number, number, number, number, number, number][] = [
  [-40, 5, 11, .5, 60, 0, 3], [-30, 3.6, 6.5, .7, 88, 2, 3], [-22, 2.6, 8.5, .9, 52, 1, 0], [-14, 1.9, 4.6, 1.1, 70, 3, 2], [-34, 3, 14, .6, 104, 1, 3],
]

/** Where the volcano's crater stands across its plane, for the smoke above it. */
export const VOLCANO_CENTER = .56
const near = { body: INDEX.near, rim: INDEX.nearRim }

function sky(scene: PixelScene): LayerSpec {
  return { ...SKY, paint: (w, h) => {
    const horizonRow = Math.round(h * .92)
    return paintSky(w, h, {
      seed: scene.seed, horizonRow, stars: Math.round(scene.stars * 560),
      moon: scene.body === 'none' ? null : {
        kind: scene.body, x: bodySkyX(scene), y: horizonRow * (1 - .8 * scene.bodyY) / h, radius: 11 * scene.bodySize, crescent: scene.crescent,
      },
    })
  } }
}

/** The distant range: mountain height, roughness and snow in meters. */
function range(scene: PixelScene): LayerSpec {
  return { ...FAR, paint: (w, h) => {
    const rows = h / FAR.height
    return paintRange(w, h, {
      ...far, seed: scene.seed + 1, shade: INDEX.farShade, lightFrom: bodySkyX(scene), mist: true,
      base: h - (3 + 4 * scene.mountains) * rows, rough: 8 * scene.roughness * rows, peaks: 3 + Math.round(scene.mountains * 3),
      // Past the midpoint peaks grow more slowly, so the tallest still leave sky above them.
      peakLift: (scene.mountains <= .5 ? 16 * scene.mountains : 8 + 6 * (scene.mountains - .5)) * rows, snow: scene.snow * 63,
    })
  } }
}

function hills(scene: PixelScene, trees: boolean): LayerSpec {
  return { ...NEAR, paint: (w, h) => paintRange(w, h, {
    ...near, seed: scene.seed + 2, lightFrom: bodySkyX(scene), base: h * (.85 - .7 * scene.hills), rough: h * .25,
    peaks: 2, peakLift: h * .5 * scene.hills, trees: trees && scene.trees > 0, treeDensity: scene.trees * 1.17,
  }) }
}

function reeds(scene: PixelScene, fireflies = 0): LayerSpec[] {
  if (!scene.reeds && !fireflies) return []
  return [{ z: 4.5, width: 7, height: 1.15, bottom: -.02, texture: [480, 80], paint: (w, h) => {
    const painted = scene.reeds ? paintReeds(w, h, scene.seed + 3) : layer(w, h)
    return fireflies ? paintFireflies(painted, scene.seed + 8, fireflies, .1) : painted
  } }]
}

const WORLDS: Record<PixelWorldKind, (scene: PixelScene) => WorldPlan> = {
  'pixel-lake': scene => ({ ground: 'water', layers: [sky(scene), range(scene), hills(scene, true), ...reeds(scene)] }),
  'pixel-peaks': scene => ({ ground: 'water', layers: [sky(scene), range(scene), hills(scene, false), ...reeds(scene)] }),
  'pixel-city': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { z: -44, width: 124, height: 16, bottom: -1, texture: [700, 90], paint: (w, h) => paintSkyline(w, h, { ...far, seed: scene.seed + 11, lightFrom: bodySkyX(scene), tall: scene.city, windows: scene.windows * .7 }) },
    { z: -36, width: 106, height: 11, bottom: -1, texture: [720, 75], paint: (w, h) => paintSkyline(w, h, { ...near, seed: scene.seed + 12, lightFrom: bodySkyX(scene), tall: scene.city * .8, windows: scene.windows }) },
    ...reeds(scene),
  ] }),
  'pixel-desert': scene => ({ ground: 'sand', layers: [
    sky(scene),
    { ...FAR, paint: (w, h) => paintMesas(w, h, { ...far, seed: scene.seed + 1, lightFrom: bodySkyX(scene), tall: .15 + scene.mountains * .5, count: 3 + Math.round(scene.roughness * 5) }) },
    { z: -30, width: 96, height: 5, bottom: -.6, texture: [720, 38], paint: (w, h) => paintDunes(w, h, { ...near, seed: scene.seed + 2, lightFrom: bodySkyX(scene), tall: .3 + scene.hills * .7 }) },
    ...reeds(scene),
  ] }),
  'pixel-coast': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { z: -28, width: 90, height: 16, bottom: -1, texture: [640, 114], paint: (w, h) => paintCliff(w, h, { ...near, seed: scene.seed + 2, lightFrom: bodySkyX(scene), tall: .4 + scene.hills * .6, trees: scene.trees }) },
    ...reeds(scene),
  ] }),
  'pixel-viaduct': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene), hills(scene, true),
    { z: -24, width: 96, height: 6, bottom: -.5, texture: [768, 48], paint: (w, h) => paintViaduct(w, h, { ...near, seed: scene.seed + 4, lightFrom: bodySkyX(scene) }) },
    // The train rides the deck, crossing the whole bridge and coming round again.
    { z: -23.8, width: 26, height: 1.25, bottom: 4.78, texture: [208, 10], drift: { speed: 5.5, loop: 130 }, paint: (w, h) => paintTrain(w, h, { seed: scene.seed, carriages: 5 }) },
    ...reeds(scene),
  ] }),
  'pixel-volcano': scene => ({ ground: 'water', layers: [
    sky(scene),
    { ...FAR, paint: (w, h) => paintVolcano(w, h, { ...far, seed: scene.seed + 1, lightFrom: bodySkyX(scene), peak: .45 + scene.mountains * .3, center: VOLCANO_CENTER }) },
    hills(scene, true), ...reeds(scene),
  ] }),
  'pixel-drivein': scene => ({ ground: 'sand', layers: [
    sky(scene),
    { ...FAR, paint: (w, h) => paintMesas(w, h, { ...far, seed: scene.seed + 1, lightFrom: bodySkyX(scene), tall: .12 + scene.mountains * .4, count: 3 }) },
    { z: -2.5, width: 16, height: 1.5, bottom: 0, texture: [256, 24], paint: (w, h) => paintCars(w, h, { seed: scene.seed + 3, count: 7, ...near }) },
    { z: 1.5, width: 11, height: 1.3, bottom: 0, texture: [176, 21], paint: (w, h) => paintCars(w, h, { seed: scene.seed + 4, count: 4, body: INDEX.trees, rim: INDEX.near }) },
  ] }),
  'pixel-garden': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { z: -30, width: 92, height: 12, bottom: -.8, texture: [736, 96], paint: (w, h) => paintGarden(w, h, { ...near, seed: scene.seed + 2, lightFrom: bodySkyX(scene), trees: Math.round(4 + scene.trees * 10), pagoda: true, lanterns: 0, size: 9 }) },
    { z: -9, width: 30, height: 4.2, bottom: -.3, texture: [360, 50], paint: (w, h) => paintGarden(w, h, { body: INDEX.trees, rim: INDEX.near, seed: scene.seed + 3, lightFrom: bodySkyX(scene), trees: Math.round(2 + scene.trees * 3), pagoda: false, lanterns: 3, size: 11 }) },
    ...reeds(scene),
  ] }),
  'pixel-reef': scene => {
    const water = sky(scene)
    // The seabed lies below the corals, which stand on it rather than in it.
    return { ground: 'sand', groundY: -2.6, layers: [
      { ...water, paint: (w, h) => paintSeaLight(water.paint(w, h), scene.seed) },
      { ...FAR, bottom: -2.8, height: 31, paint: (w, h) => paintReef(w, h, { ...far, seed: scene.seed + 1, lightFrom: .5, kelp: scene.trees * .6, tall: .5 + scene.mountains * .5 }) },
      // Two schools cross at different depths, in opposite directions.
      { z: -30, width: 10, height: 3.4, bottom: 5.5, texture: [66, 22], drift: { speed: 1.6, loop: 110, offset: 48 }, paint: (w, h) => paintSchool(w, h, scene.seed + 7, 16) },
      { z: -9, width: 4, height: 1.6, bottom: 2.4, texture: [40, 16], drift: { speed: -2.3, loop: 70, offset: 40 }, paint: (w, h) => paintSchool(w, h, scene.seed + 9, 10) },
      { z: -13, width: 62, height: 9, bottom: -2.8, texture: [620, 90], paint: (w, h) => paintReef(w, h, { ...near, seed: scene.seed + 2, lightFrom: .5, kelp: scene.trees, tall: .4 + scene.hills * .6 }) },
      // Coral close to the lens, darkest of all, frames the view.
      { z: -3, width: 22, height: 3.6, bottom: -3.2, texture: [440, 72], paint: (w, h) => paintReef(w, h, { body: INDEX.trees, rim: INDEX.near, seed: scene.seed + 3, lightFrom: .5, kelp: scene.trees * .7, tall: 1.7 }) },
    ] }
  },
  'pixel-valley': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { z: -41, width: 124, height: 4, bottom: 1.2, texture: [640, 22], paint: (w, h) => paintMist(w, h, scene.seed, .8) },
    { ...NEAR, z: -38, paint: hills(scene, true).paint },
    { z: -35, width: 104, height: 1.2, bottom: -.3, texture: [620, 8], paint: (w, h) => paintMist(w, h, scene.seed + 1, .45) },
    ...BALLOONS.map(([z, size, y, speed, offset, a, b]) => ({
      z, width: size * .8, height: size, bottom: y, texture: [Math.round(size * 7.2), Math.round(size * 9)] as [number, number],
      drift: { speed, loop: 150, offset, bob: size * .08 },
      paint: (w: number, h: number) => paintBalloon(w, h, { colors: [INDEX.balloon + a, INDEX.balloon + b] as [number, number], lightFrom: bodySkyX(scene) }),
    })),
    ...reeds(scene),
  ] }),
  'pixel-fair': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { z: -44, width: 124, height: 16, bottom: -1, texture: [700, 90], paint: (w, h) => paintSkyline(w, h, { ...far, seed: scene.seed + 11, lightFrom: bodySkyX(scene), tall: scene.city, windows: scene.windows * .6 }) },
    { z: -22.2, width: 12, height: 9.6, bottom: -.3, texture: [80, 64], paint: (w, h) => paintStand(w, h, { body: INDEX.far, rim: INDEX.farRim }) },
    { z: -22, width: WHEEL.radius * 2.15, height: WHEEL.radius * 2.15, bottom: WHEEL.y - WHEEL.radius * 1.075, texture: [104, 104], spin: -.12, paint: w => paintWheel(w, { body: INDEX.far, rim: INDEX.farRim }) },
    ...Array.from({ length: 8 }, (_, i) => ({
      z: -21.8, width: 1.4, height: 1.4, bottom: 0, texture: [14, 14] as [number, number],
      orbit: { x: 0, y: WHEEL.y, radius: WHEEL.radius, speed: -.12, phase: i / 8 * Math.PI * 2, drop: .7 },
      paint: (w: number, h: number) => paintCabin(w, h, INDEX.balloon + (i % 3)),
    })),
    { z: -16, width: 44, height: 3.2, bottom: -.2, texture: [300, 22], paint: (w, h) => paintTents(w, h, scene.seed + 5, 6) },
    ...reeds(scene),
  ] }),
  'pixel-village': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene), hills(scene, true),
    { ...VILLAGE, paint: (w, h) => paintVillage(w, h, { ...near, seed: scene.seed + 6, lightFrom: bodySkyX(scene), houses: 9 }) },
    ...[[-11, 1.4, 20], [-8, -1.8, 44], [-14, 1.1, 8]].map(([z, speed, offset], i) => ({
      z, width: .8, height: 1, bottom: 0, texture: [8, 10] as [number, number], drift: { speed, loop: 36, offset },
      paint: (w: number, h: number) => paintSkater(w, h, scene.seed + i),
    })),
    ...reeds(scene),
  ] }),
  'pixel-falls': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { z: -34, width: 76, height: 16, bottom: -.8, texture: [608, 128], paint: (w, h) => paintFalls(w, h, { ...far, seed: scene.seed + 4, lightFrom: bodySkyX(scene), wide: scene.hills }) },
    { z: -17, width: 44, height: 5, bottom: -.6, texture: [440, 50], paint: (w, h) => paintForest(w, h, { seed: scene.seed + 6, tall: .35, density: scene.trees, body: INDEX.near }) },
    ...reeds(scene),
  ] }),
  'pixel-orbit': scene => {
    const stars = sky(scene)
    return { ground: 'none', clearSky: true, layers: [
      { ...stars, bottom: -30, height: 82, texture: [700, 336], paint: (w, h) => paintNebula(stars.paint(w, h), scene.seed) },
      { z: -40, width: 150, height: 30, bottom: -24, texture: [700, 140], paint: (w, h) => paintPlanetLimb(w, h, { seed: scene.seed + 3, curve: 1.6 + scene.mountains * 3, lightFrom: bodySkyX(scene) }) },
      { z: -24, width: 15, height: 6, bottom: 5, texture: [120, 48], drift: { speed: .45, loop: 70, offset: 30, bob: .25 }, paint: (w, h) => paintStation(w, h, scene.seed) },
      ...[[-18, 1.2, 2.5, -.7, 20], [-12, .7, 5.5, .5, 44], [-30, 2, 9, -.3, 60]].map(([z, size, y, speed, offset], i) => ({
        z, width: size, height: size, bottom: y, texture: [Math.round(size * 12), Math.round(size * 12)] as [number, number],
        drift: { speed, loop: 60, offset, bob: .3 }, spin: (i % 2 ? .3 : -.2),
        paint: (w: number) => paintAsteroid(w, w, scene.seed + i),
      })),
    ] }
  },
  'pixel-tulips': scene => ({ ground: 'field', layers: [
    sky(scene), range(scene), hills(scene, true),
    { z: -28, width: 80, height: 12, bottom: -.6, texture: [640, 96], paint: (w, h) => paintWindmills(w, h, { ...near, seed: scene.seed + 4, lightFrom: bodySkyX(scene), count: 3 }) },
  ] }),
  'pixel-alley': scene => ({ ground: 'water', layers: [
    sky(scene),
    { z: -44, width: 60, height: 18, bottom: -1, texture: [480, 144], paint: (w, h) => paintSkyline(w, h, { ...far, seed: scene.seed + 11, lightFrom: bodySkyX(scene), tall: scene.city, windows: scene.windows }) },
    // The street's two walls run away from the camera on either side.
    { z: -14, x: -4.2, turn: Math.PI / 2, width: 46, height: 15, bottom: -.2, texture: [460, 150], paint: (w, h) => paintFacade(w, h, { ...near, seed: scene.seed + 21, lightFrom: .9 }) },
    { z: -14, x: 4.2, turn: -Math.PI / 2, width: 46, height: 15, bottom: -.2, texture: [460, 150], paint: (w, h) => paintFacade(w, h, { ...near, seed: scene.seed + 22, lightFrom: .1 }) },
  ] }),
  'pixel-castle': scene => ({ ground: 'water', fireworks: true, layers: [
    sky(scene), range(scene),
    { z: -26, width: 56, height: 17, bottom: -.8, texture: [448, 136], paint: (w, h) => paintCastle(w, h, { body: INDEX.near, rim: INDEX.farRim, seed: scene.seed + 4, lightFrom: bodySkyX(scene) }) },
    ...reeds(scene),
  ] }),
  'pixel-beach': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene), hills(scene, true),
    // The shore lies just above the sea, its waterline toward the horizon.
    { z: 6.5, width: 64, height: 10, bottom: .03, floor: true, texture: [512, 110], paint: (w, h) => paintBeach(w, h, scene.seed) },
  ] }),
  'pixel-lanterns': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene), hills(scene, true),
    // Flocks of lanterns at four depths rise at their own pace, the near ones faster.
    // Two copies of each flock, half a cycle apart, so the sky is never empty.
    ...LANTERNS.flatMap(([z, width, height, speed, count], i) => [0, 1].map(copy => ({
      z: z + copy * .1, width, height, bottom: 0, texture: [Math.round(width * 8), Math.round(height * 8)] as [number, number],
      drift: { speed, loop: height * 2, offset: i * 7 + copy * height, bob: width * .02, rise: true },
      paint: (w: number, h: number) => paintLanterns(w, h, scene.seed + i * 17 + copy * 5, count),
    }))),
    ...reeds(scene),
  ] }),
  'pixel-window': scene => {
    const city = WORLDS['pixel-city'](scene)
    // The room wall stands just in front of the camera; its panes are open.
    return { ...city, layers: [...city.layers, { z: 6, width: 5.4, height: 3.1, bottom: .15, texture: [324, 186], paint: (w, h) => paintRoom(w, h, scene.seed) }] }
  },
  'pixel-express': scene => ({ ground: 'water', layers: [
    sky(scene),
    // Farther layers slide by slower: parallax from a moving train.
    { ...FAR, texture: [720, 157], scroll: 4, paint: (w, h) => paintLoopRange(w, h, { ...far, seed: scene.seed + 1, lightFrom: bodySkyX(scene), base: h * .7, amp: h * .18 * (.4 + scene.mountains), trees: 0 }) },
    { ...NEAR, z: -30, height: 8, texture: [720, 64], scroll: 18, paint: (w, h) => paintLoopRange(w, h, { ...near, seed: scene.seed + 2, lightFrom: bodySkyX(scene), base: h * .72, amp: h * .12, trees: scene.trees }) },
    { z: -7, width: 22, height: 6, bottom: -.3, texture: [480, 130], scroll: 150, paint: (w, h) => paintPoles(w, h, 160) },
    { z: 6, width: 5.4, height: 3.1, bottom: .15, texture: [324, 186], paint: (w, h) => paintCarriage(w, h) },
  ] }),
  'pixel-daycycle': scene => ({ ground: 'water', layers: [
    sky({ ...scene, body: 'none' }), range(scene), hills(scene, true), ...reeds(scene),
    // One full turn per day: the sun rises in the east as the moon sets.
    ...(['sun', 'moon'] as const).map((kind, i) => ({
      z: -60, width: 24, height: 24, bottom: 0, texture: [96, 96] as [number, number], celestial: kind,
      orbit: { x: 0, y: -1, radius: 46, ry: 25, speed: -Math.PI * 2 / DAY_SECONDS, phase: Math.PI - i * Math.PI },
      paint: (w: number, h: number) => { const disc = layer(w, h); paintMoon(disc, scene.seed, { kind, x: .5, y: .5, radius: kind === 'sun' ? 11 : 9, crescent: kind === 'sun' ? 0 : scene.crescent }); return disc },
    })),
  ] }),
  'pixel-eclipse': scene => {
    const desert = WORLDS['pixel-desert']({ ...scene, body: 'none' })
    const disc = (kind: 'sun' | 'moon') => (w: number, h: number) => {
      const plate = layer(w, h)
      if (kind === 'sun') paintMoon(plate, scene.seed, { kind: 'sun', x: .5, y: .5, radius: ECLIPSE.texels, crescent: 0 })
      else for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (Math.hypot(x + .5 - w / 2, y + .5 - h / 2) <= ECLIPSE.texels + .5) plate.data[y * w + x] = INDEX.umbra
      return plate
    }
    const plate = { width: 24, height: 24, bottom: ECLIPSE.y - 12, texture: [96, 96] as [number, number] }
    return { ...desert, clearSky: true, layers: [...desert.layers,
      { ...plate, z: -60, paint: disc('sun') },
      // The moon slides across the sun on the clock, darkest at mid-clip.
      { ...plate, z: -59.5, drift: { speed: ECLIPSE.speed, loop: 200, offset: ECLIPSE.start + 100 }, paint: disc('moon') },
    ] }
  },
  'pixel-seasons': scene => {
    const mountains = range(scene)
    return { ground: 'water', layers: [
      sky(scene),
      { ...mountains, paint: (w, h) => dustSnow(mountains.paint(w, h), 14, INDEX.snowFar, scene.seed) },
      { z: -30, width: 96, height: 10, bottom: -.8, texture: [640, 70], paint: (w, h) => paintOrchard(w, h, { ...near, seed: scene.seed + 3, lightFrom: bodySkyX(scene), trees: Math.round(6 + scene.trees * 22) }) },
      ...reeds(scene),
    ] }
  },
  'pixel-cathedral': scene => ({ ground: 'none', layers: [
    { z: -20, width: 30, height: 22, bottom: 0, texture: [360, 264], paint: w => paintNaveWall(w, 264) },
    { z: -6, x: -7, turn: Math.PI / 2, width: 28, height: 22, bottom: 0, texture: [336, 264], paint: (w, h) => paintArcade(w, h) },
    { z: -6, x: 7, turn: -Math.PI / 2, width: 28, height: 22, bottom: 0, texture: [336, 264], paint: (w, h) => paintArcade(w, h) },
    { z: -6, width: 14, height: 28, bottom: 0, floor: true, texture: [168, 336], paint: (w, h) => paintFlagstones(w, h, scene.seed) },
  ], beams: [
    // Light from the rose window and the lancets falls across the floor.
    ...[0, 1, 2, 3, 4, 5].map(hue => ({ from: [(hue - 2.5) * .7, 15.4 - Math.abs(hue - 2.5) * .3, -19.8] as [number, number, number], to: [(hue - 2.5) * 1.6 + 1.5, 0, -4 + hue * .8] as [number, number, number], width: 1.1, hue })),
    { from: [-4.2, 6, -19.8], to: [-2.5, 0, -12], width: 1.4, hue: 1 },
    { from: [4.2, 6, -19.8], to: [3, 0, -11], width: 1.4, hue: 4 },
  ] }),
  'pixel-koi': scene => ({ ground: 'none', layers: [
    { z: 0, width: 32, height: 22, bottom: 0, floor: true, texture: [512, 352], paint: (w, h) => paintPond(w, h, scene.seed) },
    // Koi circle at their own pace and size, some each way, under the lily pads.
    ...KOI.map(([radius, ry, speed, phase, size], i) => ({
      z: 0, width: size, height: size * .36, bottom: .02, floor: true, texture: [16, 6] as [number, number],
      orbit: { x: 0, y: 0, radius, ry, speed, phase, flat: true },
      paint: (w: number, h: number) => paintKoi(w, h, i),
    })),
    { z: 0, width: 32, height: 22, bottom: .05, floor: true, texture: [512, 352], paint: (w, h) => paintLilies(w, h, scene.seed + 5, Math.round(6 + scene.trees * 8)) },
  ] }),
  'pixel-caravan': scene => ({ ground: 'sand', layers: [
    sky(scene),
    { ...FAR, paint: (w, h) => paintMesas(w, h, { ...far, seed: scene.seed + 1, lightFrom: bodySkyX(scene), tall: .1 + scene.mountains * .3, count: 3 }) },
    // A long dune crest, and the caravan walking along it against the moon.
    { z: -24, width: 90, height: 4, bottom: -.6, texture: [900, 40], paint: (w, h) => paintLoopRange(w, h, { ...near, seed: scene.seed + 2, lightFrom: bodySkyX(scene), base: h * .4, amp: h * .06, trees: 0 }) },
    { z: -24.2, width: 14, height: 2.2, bottom: 1.75, texture: [280, 44], frames: { count: 4, fps: 5 },
      drift: { speed: .6, loop: 60, offset: 23.5 }, paint: (w, h, frame = 0) => paintCaravan(w, h, frame, 4) },
  ] }),
  'pixel-synthwave': scene => ({ ground: 'none', clearSky: true, layers: [
    sky(scene), range(scene),
    // The grid runs from the horizon to the lens and flows toward it.
    { z: -20, width: 150, height: 60, bottom: 0, floor: true, texture: [600, 240], scrollY: 30, paint: (w, h) => paintGrid(w, h, 20) },
    { z: -6, width: 26, height: 9, bottom: 0, texture: [520, 180], paint: (w, h) => paintPalms(w, h, scene.seed) },
  ] }),
  'pixel-monsoon': scene => ({ ground: 'water', rain: 1, layers: [
    sky(scene), range(scene), hills(scene, true),
    { z: -9, width: 26, height: 9, bottom: -.2, texture: [520, 180], paint: (w, h) => paintPalms(w, h, scene.seed) },
    ...reeds(scene),
  ] }),
  'pixel-marsh': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene), hills(scene, true),
    // Thousands of starlings, drifting slowly across as the flock folds.
    { z: -42, width: 56, height: 20, bottom: 7, texture: [420, 150], frames: { count: 24, fps: 8 },
      drift: { speed: .7, loop: 120, offset: 54, bob: 1.2 }, paint: (w, h, frame = 0) => paintMurmuration(w, h, frame, 24, scene.seed, 2600) },
    ...reeds(scene),
  ] }),
  'pixel-launch': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { ...NEAR, z: -31, paint: (w, h) => paintRange(w, h, { ...near, seed: scene.seed + 2, lightFrom: bodySkyX(scene), base: h * .8, rough: h * .08, peaks: 1, peakLift: h * .1 }) },
    { z: -30, x: LAUNCH.x + 2.2, width: 7, height: 14, bottom: -.3, texture: [120, 240], paint: (w, h) => paintLaunchTower(w, h) },
    { z: -29.8, x: LAUNCH.x, width: 1.4, height: 9, bottom: LAUNCH.pad, texture: [28, 180], launch: { at: LAUNCH.at, accel: LAUNCH.accel }, paint: (w, h) => paintRocket(w, h) },
    { z: -29.7, x: LAUNCH.x, width: 1.6, height: 3.4, bottom: LAUNCH.pad - 3.2, texture: [32, 68], launch: { at: LAUNCH.at, accel: LAUNCH.accel, ignite: true }, paint: (w, h) => paintExhaust(w, h, scene.seed) },
  ] }),
  'pixel-grotto': scene => ({ ground: 'water', rain: .25, pulse: '#7af0ff', layers: [
    { z: -26, width: 64, height: 26, bottom: -1, texture: [512, 208], paint: (w, h) => paintGrotto(w, h, scene.seed) },
    { z: 5.6, width: 7.2, height: 4.2, bottom: -.4, texture: [360, 210], paint: (w, h) => paintCaveMouth(w, h, scene.seed + 3) },
  ] }),
  'pixel-forest': scene => ({ ground: 'water', layers: [
    sky(scene), range(scene),
    { z: -42, width: 120, height: 14, bottom: -1, texture: [640, 75], paint: (w, h) => paintForest(w, h, { seed: scene.seed + 5, tall: scene.hills * .6, density: .6 + scene.trees * .4, body: INDEX.far }) },
    { z: -33, width: 100, height: 9, bottom: -1, texture: [700, 63], paint: (w, h) => paintFireflies(paintForest(w, h, { seed: scene.seed + 6, tall: scene.hills, density: scene.trees, body: INDEX.near }), scene.seed + 7, 160, .25) },
    ...reeds(scene, 60),
  ] }),
}

export function worldPlan(kind: PixelWorldKind, scene: PixelScene): WorldPlan {
  return WORLDS[kind](scene)
}
