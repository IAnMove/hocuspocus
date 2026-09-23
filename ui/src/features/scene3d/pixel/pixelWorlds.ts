import { INDEX, layer, paintRange, paintReeds, paintSky, type IndexedLayer } from './pixelPaint'
import { paintCliff, paintDunes, paintFireflies, paintForest, paintMesas, paintSkyline, paintTrain, paintViaduct, paintVolcano, paintCars, paintGarden } from './pixelPaintWorlds'
import { bodySkyX, type PixelScene, type PixelWorldKind } from './pixelScene'

/** One painted plane of a world: where it stands (meters) and its art size. */
export type LayerSpec = {
  z: number; width: number; height: number; bottom: number; texture: [number, number]
  sky?: boolean
  /** Meters per second the plane travels along x, looping over `loop` meters. */
  drift?: { speed: number; loop: number }
  paint: (w: number, h: number) => IndexedLayer
}
export type WorldPlan = { layers: LayerSpec[]; ground: 'water' | 'sand' }

const SKY: Omit<LayerSpec, 'paint'> = { z: -62, width: 170, height: 52, bottom: -4, texture: [700, 214], sky: true }
const FAR: Omit<LayerSpec, 'paint'> = { z: -46, width: 130, height: 30, bottom: -1.5, texture: [680, 157] }
const NEAR: Omit<LayerSpec, 'paint'> = { z: -37, width: 110, height: 7, bottom: -1, texture: [720, 46] }
const far = { body: INDEX.far, rim: INDEX.farRim }
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
