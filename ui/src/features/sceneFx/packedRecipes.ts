import type { EnergySurface } from './energyShaders'

export type PackedSheet = {
  s: EnergySurface
  w: number
  h: number
  x?: number
  y?: number
  z?: number
  rx?: number
  bb?: boolean
  seed?: number
  kind?: string
}
export type PackedPoints = { m: string; n: number; sp: number; ht: number; sz: number; c?: string }
export type PackedRecipe = {
  id: string
  color: string
  sound: string
  sheets?: PackedSheet[]
  pts?: PackedPoints
  dome?: boolean
}

const S = (
  s: EnergySurface, w: number, h: number,
  extra: Partial<PackedSheet> = {},
): PackedSheet => ({ s, w, h, bb: extra.bb ?? true, ...extra })

export const PACKED_FX = [
  { id: 'torch', color: '#ff7a28', sound: 'crackle', sheets: [S('fire', .55, 1.15, { y: .4 }), S('fire', .4, .9, { x: .06, y: .35, seed: 4 })], pts: { m: 'rise', n: 40, sp: .2, ht: .15, sz: .03, c: '#ffcc77' } },
  { id: 'fire_jet', color: '#ff5a14', sound: 'whoosh', sheets: [S('fire', 1.1, 2.4, { y: .9 }), S('fireball', .7, .7, { y: .2 })], pts: { m: 'jet', n: 80, sp: .25, ht: .4, sz: .04 } },
  { id: 'magma', color: '#ff4d12', sound: 'crackle', sheets: [S('magma', 3.4, 2.2, { y: .02, rx: -1.57, bb: false })], pts: { m: 'rise', n: 50, sp: 1.4, ht: .2, sz: .05, c: '#ffb040' } },
  { id: 'lava_burst', color: '#ff3b00', sound: 'impact', sheets: [S('fireball', 1.6, 1.6, { y: .5 }), S('magma', 2.4, 1.6, { y: .05, rx: -1.57, bb: false })], pts: { m: 'burst', n: 120, sp: .25, ht: .25, sz: .05 } },
  { id: 'ember_storm', color: '#ff8a3a', sound: 'crackle', sheets: [S('mist', 2.8, 1.4, { y: .4, seed: 2 })], pts: { m: 'flutter', n: 220, sp: 2.6, ht: 2.2, sz: .045 } },
  { id: 'dragon_breath', color: '#ff6a22', sound: 'whoosh', sheets: [S('fire', 1.8, 1.3, { y: .7, z: .4 }), S('fire', 2.2, 1.1, { y: .55, z: .9, seed: 8 })], pts: { m: 'jet', n: 90, sp: .4, ht: .3, sz: .04 } },
  { id: 'solar_flare', color: '#ffd060', sound: 'power', sheets: [S('sunshaft', 2.4, 3.2, { y: 1.2 }), S('flash', 1.3, 1.3, { y: .6 })], pts: { m: 'rise', n: 70, sp: .5, ht: .4, sz: .04 } },
  { id: 'molten_ground', color: '#e14a10', sound: 'crackle', sheets: [S('magma', 4.2, 2.8, { rx: -1.57, bb: false }), S('blastRing', 3.4, 3.4, { y: .03, rx: -1.57, bb: false })] },
  { id: 'waterfall', color: '#8fd4ff', sound: 'rain', sheets: [S('waterfall', 1.6, 3.2, { y: 1.3 }), S('splash', 1.8, 1.2, { y: .15 })], pts: { m: 'fall', n: 140, sp: .7, ht: 2.8, sz: .04 } },
  { id: 'steam', color: '#d5e4ee', sound: 'wind', sheets: [S('steam', 1.4, 2.4, { y: .9 }), S('steam', 1.1, 2, { x: .15, y: .8, seed: 5 })], pts: { m: 'rise', n: 40, sp: .4, ht: .3, sz: .05 } },
  { id: 'geyser', color: '#bfefff', sound: 'impact', sheets: [S('waterfall', .9, 2.8, { y: 1.2 }), S('splash', 2.2, 2.2, { y: .2 })], pts: { m: 'jet', n: 110, sp: .3, ht: .6, sz: .045 } },
  { id: 'ripple', color: '#7ecfff', sound: 'whoosh', sheets: [S('blastRing', 3.2, 3.2, { y: .03, rx: -1.57, bb: false }), S('blastRing', 4.4, 4.4, { y: .04, rx: -1.57, bb: false, seed: 3 })] },
  { id: 'ocean_spray', color: '#c8f2ff', sound: 'wind', sheets: [S('steam', 2.2, 1.6, { y: .5 }), S('splash', 2.6, 1.8, { y: .25 })], pts: { m: 'flutter', n: 130, sp: 1.6, ht: 1.1, sz: .04 } },
  { id: 'bubble_column', color: '#9ceeff', sound: 'pop', sheets: [S('heal', .8, 2.2, { y: .9 })], pts: { m: 'rise', n: 90, sp: .45, ht: 1.6, sz: .06 } },
  { id: 'whirlpool', color: '#4aa7d8', sound: 'wind', sheets: [S('tornado', 2.4, 1.2, { y: .15, rx: -1.2, bb: false }), S('hole', 1.8, 1.8, { y: .08, rx: -1.57, bb: false })], pts: { m: 'spin', n: 100, sp: 1.3, ht: .15, sz: .04 } },
  { id: 'heavy_rain', color: '#9bb8d4', sound: 'rain', pts: { m: 'dart', n: 640, sp: 3.8, ht: 3.6, sz: .08 } },
  { id: 'blizzard', color: '#e8f4ff', sound: 'wind', sheets: [S('frost', 3, 2, { y: .8 })], pts: { m: 'flutter', n: 360, sp: 3.4, ht: 2.8, sz: .055 } },
  { id: 'hail', color: '#d5e8f8', sound: 'impact', pts: { m: 'dart', n: 280, sp: 3, ht: 3.2, sz: .07 } },
  { id: 'sandstorm', color: '#d2b07a', sound: 'wind', sheets: [S('mist', 3.6, 1.8, { y: .5 }), S('mist', 3.2, 1.5, { y: .9, seed: 6 })], pts: { m: 'drift', n: 240, sp: 3.2, ht: 1.6, sz: .05 } },
  { id: 'ash_fall', color: '#8a8178', sound: 'wind', sheets: [S('mist', 3, 1.6, { y: 1.1 })], pts: { m: 'sink', n: 260, sp: 3, ht: 2.8, sz: .05 } },
  { id: 'thunderhead', color: '#6d7c99', sound: 'thunder', sheets: [S('mist', 3.4, 1.7, { y: 1.6 }), S('mist', 2.8, 1.3, { y: 2, seed: 4 })], pts: { m: 'drift', n: 80, sp: 2, ht: .4, sz: .04, c: '#cfe6ff' } },
  { id: 'ball_lightning', color: '#b9e7ff', sound: 'crackle', sheets: [S('plasma', 1.5, 1.5, { y: 1.1 })], pts: { m: 'orbit', n: 70, sp: .9, ht: .2, sz: .04 } },
  { id: 'aurora_curtain', color: '#66ffc8', sound: 'rise', sheets: [S('sunshaft', 2.8, 3.4, { y: 1.5 }), S('heal', 2.2, 3, { x: .3, y: 1.4, seed: 7 })] },
  { id: 'heat_haze', color: '#ffb070', sound: 'wind', sheets: [S('steam', 2.6, 2, { y: .7 }), S('steam', 2.2, 1.7, { x: .2, y: .55, seed: 3 })] },
  { id: 'plasma', color: '#7af0ff', sound: 'power', sheets: [S('plasma', 1.8, 1.8, { y: 1 }), S('orb', 1.1, 1.1, { y: 1 })], pts: { m: 'spin', n: 60, sp: .8, ht: .2, sz: .035 } },
  { id: 'nova', color: '#ffe08a', sound: 'impact', sheets: [S('flash', 2.2, 2.2, { y: .8 }), S('blastRing', 5, 5, { y: .04, rx: -1.57, bb: false }), S('sunshaft', 2, 2.6, { y: 1 })], pts: { m: 'burst', n: 160, sp: .3, ht: .3, sz: .05 } },
  { id: 'emp', color: '#8ecbff', sound: 'scan', sheets: [S('blastRing', 4.2, 4.2, { y: .5, bb: true }), S('hologram', 2.4, 2.4, { y: 1 })], pts: { m: 'burst', n: 90, sp: .4, ht: .1, sz: .04 } },
  { id: 'hologram', color: '#5ce8ff', sound: 'scan', sheets: [S('hologram', 1.6, 2.6, { y: 1.1 })] },
  { id: 'glitch', color: '#ff4ad2', sound: 'scan', sheets: [S('hologram', 1.7, 2.2, { y: 1 }), S('slash', 1.8, .8, { y: 1, seed: 9 })] },
  { id: 'tractor_beam', color: '#86f0c8', sound: 'power', sheets: [S('sunshaft', 1.4, 3.4, { y: 1.4 }), S('heal', 1.1, 3, { y: 1.3 })] },
  { id: 'force_push', color: '#c5ddff', sound: 'whoosh', sheets: [S('blastRing', 3.6, 3.6, { y: .8 }), S('shock', 4.2, 4.2, { y: .05, rx: -1.57, bb: false })] },
  { id: 'gravity_well', color: '#8a6cff', sound: 'power', sheets: [S('hole', 2.2, 2.2, { y: 1 }), S('voidShade', 2.6, 2.6, { y: 1 })], pts: { m: 'spin', n: 90, sp: 1.2, ht: .3, sz: .035 } },
  { id: 'wormhole', color: '#7a5cff', sound: 'rise', sheets: [S('portal', 2, 2.4, { y: 1.15, bb: false }), S('hole', 1.6, 1.9, { y: 1.15, z: -.04, bb: false })] },
  { id: 'teleport', color: '#9dfff0', sound: 'magic', sheets: [S('heal', 1.4, 2.6, { y: 1.1 }), S('flash', 1.2, 1.2, { y: .9 })], pts: { m: 'rise', n: 80, sp: .5, ht: .8, sz: .04 } },
  { id: 'nanites', color: '#b7c4c8', sound: 'scan', pts: { m: 'orbit', n: 180, sp: 1.1, ht: 1.2, sz: .03 } },
  { id: 'pulse_wave', color: '#7ad0ff', sound: 'whoosh', sheets: [S('blastRing', 2.8, 2.8, { y: .9 }), S('blastRing', 4, 4, { y: .9, seed: 4 })] },
  { id: 'heal', color: '#b6ff9a', sound: 'chime', sheets: [S('heal', 1.5, 2.6, { y: 1.1 })], pts: { m: 'rise', n: 90, sp: .55, ht: .9, sz: .04, c: '#f5ffd2' } },
  { id: 'holy_light', color: '#fff4b0', sound: 'chime', sheets: [S('sunshaft', 2.2, 3.4, { y: 1.5 }), S('heal', 1.6, 2.8, { y: 1.2 })], pts: { m: 'rise', n: 60, sp: .4, ht: .5, sz: .04 } },
  { id: 'curse', color: '#6b2d88', sound: 'magic', sheets: [S('voidShade', 2.2, 2.4, { y: 1 }), S('poison', 1.8, 1.8, { y: .7 })], pts: { m: 'sink', n: 70, sp: .8, ht: .8, sz: .04 } },
  { id: 'poison_cloud', color: '#7dff4a', sound: 'wind', sheets: [S('poison', 2.8, 2.2, { y: .8 }), S('mist', 3, 1.6, { y: .5, seed: 5 })] },
  { id: 'fairy_dust', color: '#ffc6f3', sound: 'chime', pts: { m: 'flutter', n: 200, sp: 1.8, ht: 1.8, sz: .04, c: '#ffe9a8' } },
  { id: 'runes', color: '#ffd27a', sound: 'magic', sheets: [S('circle', 2.6, 2.6, { y: .03, rx: -1.57, bb: false }), S('heal', 1.4, 1.8, { y: .8 })] },
  { id: 'hex', color: '#c46bff', sound: 'magic', sheets: [S('circle', 2.4, 2.4, { y: .03, rx: -1.57, bb: false }), S('voidShade', 1.8, 1.8, { y: .9 })] },
  { id: 'souls', color: '#c8f6ff', sound: 'rise', sheets: [S('heal', 1.2, 2, { y: 1 })], pts: { m: 'flutter', n: 70, sp: 1.2, ht: 1.6, sz: .05 } },
  { id: 'mana_burst', color: '#6ad0ff', sound: 'power', sheets: [S('plasma', 1.6, 1.6, { y: .9 }), S('flash', 1.1, 1.1, { y: .9 })], pts: { m: 'burst', n: 110, sp: .22, ht: .22, sz: .045 } },
  { id: 'enchant', color: '#ffe38a', sound: 'magic', sheets: [S('aura', 1.6, 2.2, { y: 1 })], pts: { m: 'orbit', n: 80, sp: .7, ht: 1, sz: .035 } },
  { id: 'slash_wave', color: '#ffe9d2', sound: 'slash', sheets: [S('slash', 3.2, 1.4, { y: 1.1 })] },
  { id: 'impact_debris', color: '#c4a078', sound: 'impact', sheets: [S('mist', 1.8, 1, { y: .2 })], pts: { m: 'burst', n: 180, sp: .3, ht: .25, sz: .06 } },
  { id: 'muzzle_flash', color: '#ffe7a0', sound: 'impact', sheets: [S('flash', 1.4, 1.4, { y: 1.2, z: .4 }), S('fire', .8, .6, { y: 1.15, z: .55 })] },
  { id: 'ground_crack', color: '#ff7a3a', sound: 'thunder', sheets: [S('magma', 3.6, 2.2, { rx: -1.57, bb: false }), S('blastRing', 3, 3, { y: .03, rx: -1.57, bb: false })] },
  { id: 'shock_stun', color: '#f4ff7a', sound: 'crackle', sheets: [S('plasma', 1.5, 1.5, { y: 1.1 })], pts: { m: 'orbit', n: 50, sp: .6, ht: .4, sz: .04 } },
  { id: 'parry', color: '#fff1c8', sound: 'slash', sheets: [S('slash', 2.4, 1.2, { y: 1.2 }), S('flash', 1, 1, { y: 1.2 })] },
  { id: 'fireflies', color: '#ffe36a', sound: 'chime', pts: { m: 'flutter', n: 90, sp: 2.2, ht: 1.8, sz: .05 } },
  { id: 'petals', color: '#ff9ab8', sound: 'wind', pts: { m: 'flutter', n: 160, sp: 2.4, ht: 2.2, sz: .055 } },
  { id: 'leaves', color: '#8fbf4a', sound: 'wind', pts: { m: 'flutter', n: 140, sp: 2.6, ht: 2, sz: .06 } },
  { id: 'pollen', color: '#ffe08a', sound: 'wind', pts: { m: 'drift', n: 180, sp: 2.4, ht: 1.5, sz: .035 } },
  { id: 'spores', color: '#c7e86a', sound: 'wind', sheets: [S('poison', 2, 1.6, { y: .7 })], pts: { m: 'drift', n: 120, sp: 1.8, ht: 1.2, sz: .04 } },
  { id: 'sparkle', color: '#fff6c4', sound: 'chime', pts: { m: 'orbit', n: 110, sp: 1, ht: 1.2, sz: .04 } },
  { id: 'sunshafts', color: '#ffe2a3', sound: 'rise', sheets: [S('sunshaft', 2.6, 3.6, { y: 1.5 }), S('sunshaft', 1.8, 3.2, { x: .4, y: 1.4, seed: 8 })] },
  { id: 'frost_aura', color: '#cfefff', sound: 'wind', sheets: [S('frost', 2.2, 2.4, { y: 1 }), S('aura', 1.6, 2.1, { y: 1 })], pts: { m: 'orbit', n: 50, sp: .7, ht: .8, sz: .035 } },
  { id: 'ice_wall', color: '#b7e9ff', sound: 'slash', sheets: [S('ice', 2.4, 2.8, { y: 1.1, bb: false }), S('frost', 2.6, 2.4, { y: 1 })] },
  { id: 'freeze', color: '#9adcff', sound: 'magic', sheets: [S('ice', 2.2, 2.2, { y: .9 }), S('frost', 2.8, 2, { y: .5 })], pts: { m: 'burst', n: 80, sp: .2, ht: .2, sz: .04 } },
  { id: 'crystal_rain', color: '#d7f4ff', sound: 'chime', pts: { m: 'dart', n: 220, sp: 2.6, ht: 3, sz: .05 } },
  { id: 'void_rift', color: '#7a4dff', sound: 'power', sheets: [S('voidShade', 2.4, 2.8, { y: 1.1, bb: false }), S('portal', 1.8, 2.2, { y: 1.1, bb: false })] },
  { id: 'shadow_tendrils', color: '#3b2458', sound: 'wind', sheets: [S('voidShade', 2.6, 2.8, { y: 1 }), S('voidShade', 2.2, 2.4, { x: .2, y: .9, seed: 6 })] },
  { id: 'bats', color: '#2c2438', sound: 'whoosh', pts: { m: 'flutter', n: 70, sp: 2.4, ht: 1.8, sz: .07 } },
  { id: 'dark_pulse', color: '#5b2d88', sound: 'power', sheets: [S('voidShade', 2.2, 2.2, { y: .9 }), S('blastRing', 3.4, 3.4, { y: .04, rx: -1.57, bb: false })] },
  { id: 'eclipse', color: '#ffb060', sound: 'rise', sheets: [S('hole', 2.4, 2.4, { y: 1.3 }), S('sunshaft', 2.8, 2.2, { y: 1.3 })] },
  { id: 'confetti_burst', color: '#66ddff', sound: 'pop', pts: { m: 'burst', n: 220, sp: .35, ht: .4, sz: .05 } },
  { id: 'fireworks_burst', color: '#ff88dd', sound: 'impact', sheets: [S('flash', 1.2, 1.2, { y: 1.6 })], pts: { m: 'burst', n: 200, sp: .4, ht: .5, sz: .05 } },
  { id: 'starfield', color: '#fff1aa', sound: 'chime', pts: { m: 'drift', n: 260, sp: 3.4, ht: 2.6, sz: .035 } },
  { id: 'bubble_field', color: '#88eeff', sound: 'pop', pts: { m: 'rise', n: 90, sp: 1.8, ht: 1.8, sz: .07 } },
  { id: 'meteor', color: '#ff9548', sound: 'thunder', sheets: [S('fireball', 1.2, 1.2, { y: 1.8, z: -.6 }), S('fire', 1.6, .8, { y: 1.4, z: -.2 })], pts: { m: 'jet', n: 70, sp: .2, ht: .2, sz: .04 } },
  { id: 'comet', color: '#ffe0a0', sound: 'whoosh', sheets: [S('orb', .8, .8, { y: 1.7, z: -.8 }), S('sunshaft', 2.4, 1.1, { y: 1.4, z: 0 })], pts: { m: 'jet', n: 80, sp: .25, ht: .15, sz: .04 } },
  { id: 'rainbow', color: '#ff9ad6', sound: 'chime', sheets: [S('heal', 2.8, 1.6, { y: 1.4 }), S('sunshaft', 2.6, 1.8, { y: 1.5, seed: 2 })] },
  { id: 'acid', color: '#b6ff3a', sound: 'wind', sheets: [S('acid', 2.6, 1.8, { y: .2, rx: -1.2, bb: false }), S('poison', 2, 1.4, { y: .4 })], pts: { m: 'rise', n: 40, sp: .8, ht: .3, sz: .04 } },
  { id: 'sonic_boom', color: '#d7f3ff', sound: 'whoosh', sheets: [S('blastRing', 3.2, 3.2, { y: 1 }), S('blastRing', 4.6, 4.6, { y: 1, seed: 5 }), S('shock', 5, 5, { y: .04, rx: -1.57, bb: false })] },
  { id: 'afterimage', color: '#9ad4ff', sound: 'whoosh', sheets: [S('hologram', 1.4, 2.2, { y: 1 }), S('slash', 1.8, .7, { y: 1 })] },
  { id: 'magnetic', color: '#8ab6ff', sound: 'scan', sheets: [S('plasma', 1.4, 1.4, { y: 1 })], pts: { m: 'orbit', n: 120, sp: 1.3, ht: .8, sz: .03 } },
  { id: 'oil_fire', color: '#ff6a18', sound: 'crackle', sheets: [S('fire', 1.6, 1.5, { y: .55 }), S('mist', 2.4, 1.2, { y: .7 })], pts: { m: 'rise', n: 50, sp: .7, ht: .3, sz: .04, c: '#3a2a22' } },
  { id: 'phoenix', color: '#ff7a32', sound: 'power', sheets: [S('fire', 1.8, 2.4, { y: 1.1 }), S('aura', 1.7, 2.2, { y: 1.1 }), S('flash', 1, 1, { y: 1.2 })], pts: { m: 'rise', n: 90, sp: .6, ht: .6, sz: .04 } },
  { id: 'spirit_flame', color: '#7ad7ff', sound: 'magic', sheets: [S('fire', 1.1, 1.8, { y: .8 }), S('heal', 1.2, 1.9, { y: .85 })], pts: { m: 'rise', n: 50, sp: .35, ht: .4, sz: .035 } },
  { id: 'crimson_mist', color: '#c43b4a', sound: 'wind', sheets: [S('mist', 3, 1.7, { y: .6 }), S('poison', 2.4, 1.6, { y: .5 })] },
  { id: 'lightning_orb', color: '#d7f0ff', sound: 'crackle', sheets: [S('plasma', 1.5, 1.5, { y: 1.1 }), S('orb', 1, 1, { y: 1.1 })], pts: { m: 'orbit', n: 40, sp: .55, ht: .2, sz: .04 } },
  { id: 'chain_spark', color: '#cfe9ff', sound: 'crackle', sheets: [S('slash', 2.8, .9, { y: 1.1 }), S('plasma', .8, .8, { y: 1.1 })], pts: { m: 'orbit', n: 30, sp: 1.1, ht: .2, sz: .04 } },
  { id: 'time_rift', color: '#c9a5ff', sound: 'rise', sheets: [S('portal', 1.9, 2.3, { y: 1.15, bb: false }), S('hologram', 1.6, 2, { y: 1.15, z: -.05, bb: false })] },
  { id: 'ink', color: '#2a2a38', sound: 'whoosh', sheets: [S('voidShade', 2.4, 2.2, { y: .8 }), S('mist', 2.6, 1.5, { y: .5 })], pts: { m: 'burst', n: 80, sp: .25, ht: .2, sz: .05 } },
  { id: 'cherry_blossom', color: '#ffb3c9', sound: 'wind', pts: { m: 'flutter', n: 180, sp: 2.5, ht: 2.2, sz: .055 } },
  { id: 'gold_spark', color: '#ffd36a', sound: 'chime', pts: { m: 'orbit', n: 140, sp: .9, ht: 1.1, sz: .04 } },
  { id: 'smoke_ring', color: '#b1a4bd', sound: 'wind', sheets: [S('blastRing', 2.6, 2.6, { y: .8 }), S('mist', 2.2, 1.2, { y: .8 })] },
] as const satisfies readonly PackedRecipe[]

export const PACKED_FX_IDS = PACKED_FX.map(item => item.id)
export const PACKED_BY_ID = Object.fromEntries(PACKED_FX.map(item => [item.id, item])) as Record<string, PackedRecipe>
