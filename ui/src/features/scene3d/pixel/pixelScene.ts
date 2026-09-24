/** What a pixel world is made of, so it can be reimagined: where the sun or
 *  moon hangs (and so where the light comes from), how tall and rough the
 *  ranges are, how much snow, trees, stars, water ripple and city light. */

export type PixelWorldKind = 'pixel-lake' | 'pixel-peaks' | 'pixel-city' | 'pixel-desert' | 'pixel-coast' | 'pixel-forest' | 'pixel-viaduct' | 'pixel-volcano' | 'pixel-drivein' | 'pixel-garden' | 'pixel-reef' | 'pixel-valley' | 'pixel-fair' | 'pixel-village' | 'pixel-falls' | 'pixel-orbit' | 'pixel-tulips' | 'pixel-alley' | 'pixel-castle' | 'pixel-beach' | 'pixel-lanterns' | 'pixel-window' | 'pixel-express' | 'pixel-daycycle' | 'pixel-eclipse' | 'pixel-seasons' | 'pixel-cathedral' | 'pixel-koi' | 'pixel-caravan' | 'pixel-synthwave' | 'pixel-monsoon' | 'pixel-marsh' | 'pixel-launch' | 'pixel-grotto' | 'pixel-starry' | 'pixel-dawnmist' | 'pixel-motel'
export type PixelBody = 'moon' | 'sun' | 'planet' | 'none'
export type MeteorDirection = 'left' | 'right' | 'both'

export type PixelScene = {
  /** Layout of ridges, trees, stars and buildings; change it to reimagine. */
  seed: number
  body: PixelBody
  /** Across the sky, 0 left to 1 right. The light comes from here. */
  bodyX: number
  /** From the horizon (0) to high in the sky (1). */
  bodyY: number
  /** 0.4 small to 2.5 huge. */
  bodySize: number
  /** Moon phase shadow, 0 full to 1 thin crescent. */
  crescent: number
  mountains: number
  roughness: number
  snow: number
  hills: number
  trees: number
  stars: number
  auroraHeight: number
  reeds: boolean
  /** Water waves, 0 mirror calm to 1 choppy. */
  ripple: number
  meteorDirection: MeteorDirection
  /** Skyline height and density (city worlds). */
  city: number
  /** Share of lit windows (city worlds). */
  windows: number
}

const BASE: PixelScene = {
  seed: 97, body: 'moon', bodyX: .65, bodyY: .46, bodySize: 1, crescent: .25,
  mountains: .5, roughness: .45, snow: 0, hills: .5, trees: .7, stars: .6, auroraHeight: .5,
  reeds: true, ripple: .5, meteorDirection: 'both', city: 0, windows: 0,
}

export const PIXEL_SCENE_DEFAULTS: Record<PixelWorldKind, PixelScene> = {
  'pixel-lake': BASE,
  'pixel-peaks': { ...BASE, seed: 311, bodyX: .27, bodyY: .7, mountains: .8, roughness: .5, snow: .6, trees: 0, stars: .5, ripple: .22 },
  'pixel-city': { ...BASE, seed: 41, bodyX: .83, bodyY: .45, bodySize: .8, mountains: .25, trees: 0, hills: .2, stars: .3, reeds: false, city: .7, windows: .55, ripple: .45 },
  'pixel-desert': { ...BASE, seed: 23, body: 'sun', bodyX: .37, bodyY: .16, bodySize: 1.9, crescent: 0, mountains: .35, roughness: .2, trees: 0, hills: .6, stars: .25, reeds: false, ripple: 0 },
  'pixel-coast': { ...BASE, seed: 67, bodyX: .13, bodyY: .55, mountains: .15, roughness: .3, trees: .15, hills: .7, stars: .45, reeds: false, ripple: .85 },
  'pixel-viaduct': { ...BASE, seed: 58, bodyX: .25, bodyY: .62, bodySize: .9, mountains: .4, hills: .45, trees: .6, stars: .7, ripple: .55 },
  'pixel-volcano': { ...BASE, seed: 73, bodyX: .12, bodyY: .72, bodySize: .8, mountains: .5, hills: .35, trees: .35, stars: .5, ripple: .6, reeds: false },
  'pixel-drivein': { ...BASE, seed: 17, bodyX: .1, bodyY: .78, bodySize: .7, mountains: .3, hills: .3, trees: 0, stars: .8, ripple: 0, reeds: false },
  'pixel-garden': { ...BASE, seed: 88, bodyX: .72, bodyY: .5, bodySize: 1.2, crescent: .08, mountains: .7, roughness: .15, snow: .8, trees: .6, stars: .35, ripple: .35, reeds: false },
  'pixel-reef': { ...BASE, seed: 29, body: 'none', mountains: .45, roughness: .7, hills: .55, trees: .8, stars: .3, ripple: 0, reeds: false },
  'pixel-valley': { ...BASE, seed: 142, body: 'sun', bodyX: .32, bodyY: .32, bodySize: 1.5, crescent: 0, mountains: .45, roughness: .35, hills: .55, trees: .75, stars: .1, ripple: .3, reeds: true },
  'pixel-fair': { ...BASE, seed: 64, bodyX: .85, bodyY: .7, bodySize: .8, mountains: .3, hills: .3, trees: 0, stars: .5, ripple: .5, reeds: false, city: .45, windows: .4 },
  'pixel-village': { ...BASE, seed: 211, bodyX: .8, bodyY: .62, bodySize: .9, crescent: .3, mountains: .6, roughness: .4, snow: .9, hills: .45, trees: .8, stars: .6, ripple: 0, reeds: false },
  'pixel-falls': { ...BASE, seed: 97, body: 'sun', bodyX: .78, bodyY: .82, bodySize: .8, crescent: 0, mountains: .55, roughness: .5, hills: .5, trees: .7, stars: .15, ripple: .75, reeds: true },
  'pixel-orbit': { ...BASE, seed: 404, bodyX: .82, bodyY: .8, bodySize: 1.3, crescent: .55, mountains: .5, stars: 1, reeds: false, ripple: 0, trees: 0 },
  'pixel-tulips': { ...BASE, seed: 55, body: 'sun', bodyX: .7, bodyY: .22, bodySize: 1.5, crescent: 0, mountains: .12, roughness: .2, hills: .3, trees: .5, stars: .1, ripple: 0, reeds: false },
  'pixel-alley': { ...BASE, seed: 313, body: 'none', stars: .15, ripple: .35, reeds: false, city: .8, windows: .5 },
  'pixel-castle': { ...BASE, seed: 77, bodyX: .12, bodyY: .7, bodySize: .7, crescent: .5, mountains: .35, roughness: .5, hills: .3, trees: .5, stars: .55, ripple: .4, reeds: true },
  'pixel-beach': { ...BASE, seed: 36, bodyX: .35, bodyY: .45, bodySize: 1.1, crescent: .15, mountains: .25, roughness: .5, hills: .6, trees: .5, stars: .8, ripple: .6, reeds: false },
  'pixel-lanterns': { ...BASE, seed: 18, bodyX: .8, bodyY: .5, bodySize: .8, crescent: .6, mountains: .45, roughness: .4, hills: .45, trees: .8, stars: .6, ripple: .15, reeds: true },
  'pixel-window': { ...BASE, seed: 51, bodyX: .7, bodyY: .6, bodySize: .8, crescent: .4, mountains: .2, trees: 0, hills: .2, stars: .35, reeds: false, city: .75, windows: .6, ripple: .5 },
  'pixel-express': { ...BASE, seed: 144, bodyX: .6, bodyY: .62, bodySize: .9, crescent: .2, mountains: .6, trees: .8, stars: .6, reeds: false, ripple: .4 },
  'pixel-daycycle': { ...BASE, seed: 240, crescent: .15, mountains: .55, roughness: .45, hills: .5, trees: .7, stars: .3, ripple: .35, reeds: true },
  'pixel-eclipse': { ...BASE, seed: 23, body: 'none', crescent: 0, mountains: .45, roughness: .3, trees: 0, hills: .6, stars: .8, reeds: false, ripple: 0 },
  'pixel-seasons': { ...BASE, seed: 402, body: 'sun', bodyX: .7, bodyY: .5, bodySize: 1, crescent: 0, mountains: .55, roughness: .5, hills: .5, trees: .7, stars: .15, ripple: .3, reeds: true },
  'pixel-cathedral': { ...BASE, seed: 700, body: 'none', stars: 0, reeds: false, ripple: 0, trees: 0 },
  'pixel-koi': { ...BASE, seed: 81, body: 'none', stars: 0, trees: .6, reeds: false, ripple: 0 },
  'pixel-caravan': { ...BASE, seed: 19, bodyX: .52, bodyY: .06, bodySize: 2.5, crescent: 0, mountains: .35, roughness: .3, trees: 0, hills: .5, stars: .7, reeds: false, ripple: 0 },
  'pixel-synthwave': { ...BASE, seed: 1984, body: 'sun', bodyX: .5, bodyY: .42, bodySize: 2.3, crescent: 0, mountains: .3, roughness: .7, trees: 0, stars: .6, reeds: false, ripple: 0 },
  'pixel-monsoon': { ...BASE, seed: 612, body: 'none', mountains: .5, roughness: .55, hills: .6, trees: .9, stars: 0, reeds: true, ripple: .35 },
  'pixel-marsh': { ...BASE, seed: 333, body: 'sun', bodyX: .7, bodyY: .2, bodySize: 1.4, crescent: 0, mountains: .2, roughness: .3, hills: .3, trees: .5, stars: .3, reeds: true, ripple: .2 },
  'pixel-launch': { ...BASE, seed: 1969, bodyX: .15, bodyY: .55, bodySize: .7, crescent: .5, mountains: .2, roughness: .3, hills: .2, trees: 0, stars: .7, reeds: false, ripple: .4 },
  'pixel-grotto': { ...BASE, seed: 505, body: 'none', stars: 0, trees: 0, reeds: false, ripple: .1 },
  'pixel-starry': { ...BASE, seed: 1889, bodyX: .9, bodyY: .82, bodySize: 1.1, crescent: .45, mountains: .45, roughness: .6, hills: .4, trees: .3, stars: .2, reeds: false, ripple: 0 },
  'pixel-dawnmist': { ...BASE, seed: 707, body: 'sun', bodyX: .35, bodyY: .3, bodySize: 1.2, crescent: 0, mountains: .55, roughness: .4, hills: .5, trees: .8, stars: .1, reeds: true, ripple: .15 },
  'pixel-motel': { ...BASE, seed: 66, bodyX: .85, bodyY: .7, bodySize: .7, crescent: .3, mountains: .3, trees: 0, stars: .8, reeds: false, ripple: 0 },
  'pixel-forest': { ...BASE, seed: 131, bodyX: .5, bodyY: .72, bodySize: .8, mountains: .45, trees: 1, hills: .8, stars: .55, ripple: .3 },
}

export const PIXEL_WORLD_KINDS = Object.keys(PIXEL_SCENE_DEFAULTS) as PixelWorldKind[]
export function isPixelWorldKind(kind: unknown): kind is PixelWorldKind {
  return typeof kind === 'string' && kind in PIXEL_SCENE_DEFAULTS
}

const unit = (value: unknown, fallback: number, min = 0, max = 1) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback

const BODIES: PixelBody[] = ['moon', 'sun', 'planet', 'none']
const DIRECTIONS: MeteorDirection[] = ['left', 'right', 'both']

/** The authored changes over a world's defaults; unknown keys are dropped. */
export function parsePixelScene(raw: unknown): Partial<PixelScene> | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const value = raw as Record<string, unknown>, out: Partial<PixelScene> = {}
  for (const key of ['bodyX', 'bodyY', 'crescent', 'mountains', 'roughness', 'snow', 'hills', 'trees', 'stars', 'auroraHeight', 'ripple', 'city', 'windows'] as const) {
    if (key in value) out[key] = unit(value[key], BASE[key])
  }
  if ('bodySize' in value) out.bodySize = unit(value.bodySize, 1, .4, 2.5)
  if ('seed' in value) out.seed = Math.round(unit(value.seed, BASE.seed, 1, 999999))
  if (BODIES.includes(value.body as PixelBody)) out.body = value.body as PixelBody
  if (DIRECTIONS.includes(value.meteorDirection as MeteorDirection)) out.meteorDirection = value.meteorDirection as MeteorDirection
  if (typeof value.reeds === 'boolean') out.reeds = value.reeds
  return Object.keys(out).length ? out : undefined
}

/** Where the sun or moon sits across the painted sky, which is wider than
 *  the view: 0..1 spans the part the camera sees. */
export function bodySkyX(scene: Pick<PixelScene, 'bodyX'>) {
  return .2 + .6 * scene.bodyX
}

export function resolvePixelScene(kind: PixelWorldKind, authored: Partial<PixelScene> | undefined): PixelScene {
  return { ...PIXEL_SCENE_DEFAULTS[kind], ...authored }
}

/** Where the sun or moon hangs, as a direction from the viewer: its light
 *  falls from there onto actors and props. */
export function bodyDirection(scene: Pick<PixelScene, 'bodyX' | 'bodyY'>): [number, number, number] {
  const azimuth = (scene.bodyX - .5) * 1.7, elevation = .1 + scene.bodyY * 1.05
  return [Math.sin(azimuth) * Math.cos(elevation), Math.sin(elevation), -Math.cos(azimuth) * Math.cos(elevation)]
}
