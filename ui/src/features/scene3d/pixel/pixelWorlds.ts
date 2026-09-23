import { INDEX, layer, paintRange, paintReeds, paintSky, type IndexedLayer } from './pixelPaint'
import { paintCliff, paintDunes, paintFireflies, paintForest, paintMesas, paintSkyline, paintTrain, paintViaduct, paintVolcano, paintCars, paintGarden, paintReef, paintSchool, paintSeaLight, paintMist, paintBalloon, paintWheel, paintStand, paintCabin, paintTents, paintVillage, paintSkater, paintFalls, paintNebula, paintPlanetLimb, paintStation, paintAsteroid, paintWindmills, paintFacade, paintCastle, paintBeach, paintLanterns } from './pixelPaintWorlds'
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
  /** Lies flat on the ground instead of standing, centred at `z`. */
  floor?: boolean
  /** Radians per second it turns about its own centre. */
  spin?: number
  /** Goes round a centre (x, y) at `radius`, staying upright, like a gondola. */
  orbit?: { x: number; y: number; radius: number; speed: number; phase: number }
  paint: (w: number, h: number) => IndexedLayer
}
export type WorldPlan = { layers: LayerSpec[]; ground: 'water' | 'sand' | 'field' | 'none'; /** Height of the floor, meters. */ groundY?: number; /** Fireworks burst in the sky. */ fireworks?: boolean }

const SKY: Omit<LayerSpec, 'paint'> = { z: -62, width: 170, height: 52, bottom: -4, texture: [700, 214], sky: true }
const FAR: Omit<LayerSpec, 'paint'> = { z: -46, width: 130, height: 30, bottom: -1.5, texture: [680, 157] }
const NEAR: Omit<LayerSpec, 'paint'> = { z: -37, width: 110, height: 7, bottom: -1, texture: [720, 46] }
const far = { body: INDEX.far, rim: INDEX.farRim }
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
      orbit: { x: 0, y: WHEEL.y, radius: WHEEL.radius, speed: -.12, phase: i / 8 * Math.PI * 2 },
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
    return { ground: 'none', layers: [
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
