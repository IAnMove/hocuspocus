import assert from 'node:assert/strict'
import test from 'node:test'
import { GROUND_Y, integerScale, playtestScene, stepBody, WORLD_WIDTH, type PlaySprite } from '../src/features/game-assets/playtestScene.ts'
import {
  anchorPivot, applyKey, cameraFor, clipFrameIndex, heroAction, layerOffsets, sheetClip, spriteBox, tilesetCells, type PlayKeys,
} from '../src/features/game-assets/playtestSprites.ts'
import type { Game, GameAsset, GameAttempt } from '../src/features/game-assets/types.ts'

function attempt(id: string, files: Record<string, string>, patch: Partial<GameAttempt> = {}): GameAttempt {
  return { id, status: 'ok', files, ...patch }
}

/** An approved asset whose approved attempt is its first one, unless ``attempts``/``approvedAttemptId`` say otherwise. */
function asset(partial: Partial<GameAsset> & Pick<GameAsset, 'id' | 'kind'>): GameAsset {
  const attempts = partial.attempts || [attempt(`${partial.id}-a`, { main: `${partial.id}/main.png`, preview: `${partial.id}/preview.png` })]
  return {
    name: partial.name || partial.id,
    description: '',
    status: 'approved',
    tags: [],
    spec: {},
    dependsOn: [],
    candidates: 1,
    locked: false,
    approvedAttemptId: attempts[0]?.id || null,
    ...partial,
    attempts,
  }
}

function sheet(id: string, action: string, extra: Partial<GameAsset> = {}): GameAsset {
  return asset({
    id, kind: 'animation', spec: { character: 'hero', action, loop: action !== 'jump' && action !== 'attack' }, dependsOn: ['hero'],
    attempts: [attempt(`${id}-a`, { main: `${id}/sheet.png`, sheet: `${id}/sheet.png`, atlas: `${id}/sheet.json`, preview: `${id}/preview.gif` })],
    ...extra,
  })
}

function game(assets: GameAsset[]): Game {
  return {
    id: 'bosque', title: 'Bosque', revision: 1, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [],
    style: {
      revision: 1, approval: 'approved', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
    assets,
  }
}

function fullGame(): Game {
  return game([
    asset({ id: 'hero', kind: 'character', spec: { role: 'player' } }),
    asset({ id: 'slime', kind: 'character', name: 'Slime', spec: { role: 'enemy' } }),
    asset({ id: 'baker', kind: 'character', name: 'Baker', spec: { role: 'npc' } }),
    sheet('idle', 'idle'), sheet('walk', 'walk'), sheet('run', 'run'), sheet('jump', 'jump'), sheet('attack', 'attack'),
    asset({ id: 'grass', kind: 'tile' }),
    asset({ id: 'ground', kind: 'tileset', attempts: [attempt('ts', { main: 'ground/tileset.png', tiles: 'ground/tiles.json' })] }),
    asset({
      id: 'woods', kind: 'background', spec: { loopX: false },
      attempts: [
        attempt('bg-a1', { 'layer-0.png': 'bg/a1/layer-0.png', 'layer-1.png': 'bg/a1/layer-1.png', parallax: 'bg/a1/parallax.json' }),
        attempt('bg-a2', { 'layer-1.png': 'bg/a2/layer-1.png', 'layer-0.png': 'bg/a2/layer-0.png', parallax: 'bg/a2/parallax.json' }, {
          metrics: { layers: [{ file: 'layer-0.png', factor: 0.1 }, { file: 'layer-1.png', factor: 1 }] },
        }),
      ],
      approvedAttemptId: 'bg-a2',
    }),
    asset({
      id: 'theme', kind: 'music',
      attempts: [attempt('m', { wav: 'theme/take.wav', ogg: 'theme/take.ogg' }, { metrics: { loopStart: 1000, loopEnd: 95999 } })],
    }),
    asset({ id: 'salto', kind: 'sfx', spec: { trigger: 'salto' }, attempts: [attempt('s', { 0: 'jump/0.wav', 1: 'jump/1.wav' })] }),
    asset({ id: 'moneda', kind: 'sfx', name: 'moneda', attempts: [attempt('c', { wav: 'coin.wav' })] }),
    asset({ id: 'golpe', kind: 'sfx', name: 'golpe', attempts: [attempt('h', { wav: 'hit.wav' })] }),
    asset({ id: 'coin', kind: 'item', name: 'Coin' }),
    asset({ id: 'spark', kind: 'vfx', spec: { blend: 'add' }, attempts: [attempt('v', { main: 'spark/sheet.png', sheet: 'spark/sheet.png', atlas: 'spark/sheet.json' })] }),
  ])
}

test('a full approved game fills the playtest from the approved media only', () => {
  const scene = playtestScene(fullGame())
  assert.equal(scene.hero?.id, 'hero')
  assert.deepEqual(Object.keys(scene.hero?.clips || {}).sort(), ['attack', 'idle', 'jump', 'run', 'walk'])
  // The sheet and its atlas, not the GIF preview (one frame on a canvas).
  assert.deepEqual(scene.hero?.clips.walk, { file: 'walk/sheet.png', atlas: 'walk/sheet.json', tag: 'walk', loop: true, anchor: 'bottom' })
  assert.equal(scene.hero?.clips.jump?.loop, false)
  // ``main`` is the approved sprite; ``preview`` is the 4× review copy.
  assert.equal(scene.hero?.sprite?.file, 'hero/main.png')
  assert.deepEqual(scene.ground, { name: 'ground', file: 'ground/tileset.png', tiles: 'ground/tiles.json' })
  assert.equal(scene.loopX, false)
  assert.deepEqual(scene.music, { file: 'theme/take.wav', loop: { start: 1000, end: 95999 } })
  assert.deepEqual(scene.sfx, { jump: ['jump/0.wav', 'jump/1.wav'], coin: ['coin.wav'], hit: ['hit.wav'] })
  assert.deepEqual(scene.missing, [])
  assert.equal(scene.items[0]?.name, 'Coin')
  assert.equal(scene.vfx?.anchor, 'center')
  assert.equal(scene.vfx?.additive, true)
})

test('the playtest uses the approved candidate and never a newer or unapproved attempt', () => {
  const scene = playtestScene(fullGame())
  // Candidate a2 is approved: its own layers, far first, with the factors of its own metrics.
  assert.deepEqual(scene.layers, [{ file: 'bg/a2/layer-0.png', factor: 0.1 }, { file: 'bg/a2/layer-1.png', factor: 1 }])

  const unapproved = playtestScene(game([
    asset({ id: 'hero', kind: 'character', status: 'review', approvedAttemptId: null }),
    asset({ id: 'rejected', kind: 'character', attempts: [attempt('r', { main: 'r.png' }, { decision: 'rejected' })] }),
    asset({ id: 'failed', kind: 'music', attempts: [attempt('f', { wav: 'f.wav' }, { status: 'failed' })] }),
    asset({ id: 'newer', kind: 'tile', attempts: [attempt('t-a1', { main: 'old.png' }), attempt('t-a2', { main: 'new.png' })], approvedAttemptId: 't-a1' }),
  ]))
  assert.equal(unapproved.hero, null)
  assert.equal(unapproved.music, null)
  assert.equal(unapproved.ground?.file, 'old.png')
  assert.deepEqual(unapproved.missing.map(item => item.code), ['hero', 'background', 'music', 'sfx', 'sfx', 'sfx'])
})

test('only enemies and bosses are enemies; missing clips and sounds are named entries', () => {
  const scene = playtestScene(game([
    asset({ id: 'hero', kind: 'character', spec: { role: 'player' } }),
    asset({ id: 'twin', kind: 'character', spec: { role: 'player' } }),
    asset({ id: 'baker', kind: 'character', spec: { role: 'npc' } }),
    asset({ id: 'ogre', kind: 'character', spec: { role: 'boss' } }),
    sheet('walk', 'walk'),
  ]))
  assert.deepEqual(scene.enemies.map(item => item.id), ['ogre'])
  assert.deepEqual(scene.missing.filter(item => item.code === 'animation').map(item => item.name), ['idle', 'run', 'jump', 'attack'])
  assert.deepEqual(scene.missing.filter(item => item.code === 'sfx').map(item => item.name), ['jump', 'coin', 'hit'])
  assert.ok(scene.missing.every(item => !item.name.includes(':')))
})

const ATLAS = {
  frames: {
    walk_0: { frame: { x: 0, y: 0, w: 20, h: 30 }, duration: 100 },
    walk_1: { frame: { x: 20, y: 0, w: 20, h: 30 }, duration: 50 },
    walk_2: { frame: { x: 40, y: 0, w: 20, h: 30 }, duration: 200 },
    jump_0: { frame: { x: 0, y: 30, w: 20, h: 30 }, duration: 80 },
    jump_1: { frame: { x: 20, y: 30, w: 20, h: 30 }, duration: 80 },
  },
  meta: {
    frameTags: [{ name: 'walk', from: 0, to: 2 }, { name: 'jump', from: 3, to: 4 }],
    pivot: { x: 10, y: 29 }, mirror: false, loop: { walk: true, jump: false },
  },
}

function sprite(tag: string, patch: Partial<PlaySprite> = {}): PlaySprite {
  return { file: 's.png', atlas: 's.json', tag, loop: true, anchor: 'bottom', ...patch }
}

test('a clip follows its tag, frame durations, per-tag loop, mirror flag and pivot', () => {
  const walk = sheetClip(ATLAS, sprite('walk'))
  assert.ok(walk)
  assert.deepEqual(walk.frames.map(frame => frame.duration), [100, 50, 200])
  assert.equal(walk.mirror, false)
  assert.deepEqual(walk.pivot, { x: 10, y: 29 })
  assert.deepEqual([0, 99, 100, 149, 150, 349, 350, 360].map(ms => clipFrameIndex(walk, ms)), [0, 0, 1, 1, 2, 2, 0, 0])
  // ``meta.loop.jump`` is false even though the sprite asked for a loop: it plays once and holds.
  const jump = sheetClip(ATLAS, sprite('jump', { loop: true }))
  assert.ok(jump)
  assert.equal(jump.loop, false)
  assert.deepEqual([0, 80, 159, 160, 5000].map(ms => clipFrameIndex(jump, ms)), [0, 1, 1, 1, 1])
  // An effect atlas without a pivot falls back to its centre, a character to its feet.
  const bare = { frames: { fx_0: { frame: { x: 0, y: 0, w: 64, h: 64 }, duration: 55 } }, meta: {} }
  assert.deepEqual(sheetClip(bare, sprite('fx', { anchor: 'center' }))?.pivot, { x: 32, y: 32 })
  assert.deepEqual(anchorPivot(20, 30, 'bottom'), { x: 10, y: 29 })
  assert.equal(sheetClip({ frames: {} }, sprite('walk')), null)
})

test('a mirrored sprite flips around its pivot so the feet stay put', () => {
  for (const width of [20, 21]) {
    const pivot = anchorPivot(width, 30, 'bottom')
    const plain = spriteBox(100, GROUND_Y - 1, pivot, width, false)
    const flipped = spriteBox(100, GROUND_Y - 1, pivot, width, true)
    assert.equal(plain.left + pivot.x, 100)
    assert.equal(plain.top + pivot.y, GROUND_Y - 1)
    // Mirrored, column c lands on left + width - 1 - c; the pivot column lands on x.
    assert.equal(flipped.left + width - 1 - pivot.x, 100)
    assert.equal(flipped.top, plain.top)
  }
  // An effect is centred on its pivot, not stood on it.
  const fx = spriteBox(200, 150, anchorPivot(64, 64, 'center'), 64, false)
  assert.deepEqual(fx, { left: 168, top: 118 })
})

test('parallax layers move by their factor; a layer without loopX never wraps', () => {
  const looped = layerOffsets(1000, 0.3, 640, true)
  assert.equal(looped[0], -(300 % 640))
  assert.ok(looped[0] <= 0 && looped[looped.length - 1] + 640 >= 640, 'the copies cover the view')
  assert.deepEqual(layerOffsets(0, 1, 640, true), [0])
  assert.deepEqual(layerOffsets(500, 0.5, 800, false), [-160])
  assert.deepEqual(layerOffsets(5000, 1, 800, false), [-160], 'clamped at the right edge, no seam shown')
  assert.deepEqual(layerOffsets(900, 1, 640, false), [0], 'a screen-wide layer that does not loop stays put')
  assert.equal(cameraFor(10), 0)
  assert.equal(cameraFor(WORLD_WIDTH), WORLD_WIDTH - 640)
})

test('keys the game does not use are left alone; in the air the hero shows its jump', () => {
  const keys: PlayKeys = { left: false, right: false, run: false, jump: false, attack: false }
  assert.equal(applyKey(keys, 'a', true), false)
  assert.equal(applyKey(keys, 'Tab', true), false)
  assert.equal(applyKey(keys, 'ArrowRight', true), true)
  assert.equal(keys.right, true)
  const has = (names: string[]) => (name: string) => names.includes(name)
  const ground = { x: 0, y: GROUND_Y, vx: 0, vy: 0, onGround: true }
  const rising = { ...ground, y: GROUND_Y - 30, vy: -100, onGround: false }
  const falling = { ...rising, vy: 100 }
  assert.equal(heroAction(rising, keys, false, has(['jump'])), 'jump')
  assert.equal(heroAction(falling, keys, false, has(['jump'])), 'jump', 'fall falls back to jump')
  assert.equal(heroAction(falling, keys, false, has(['jump', 'fall'])), 'fall')
  assert.equal(heroAction(ground, { ...keys, run: true }, false, has(['walk'])), 'walk', 'run falls back to walk')
  assert.equal(heroAction(ground, keys, true, has([])), 'attack')
})

test('a 3×3 tileset draws its top edge over its centre', () => {
  const tiles = { sizePx: 16, tiles: ['tl', 't', 'tr', 'l', 'c', 'r', 'bl', 'b', 'br'].map((name, index) => ({ name, x: (index % 3) * 16, y: Math.floor(index / 3) * 16, w: 16, h: 16 })) }
  assert.deepEqual(tilesetCells(tiles), { top: { x: 16, y: 0, w: 16, h: 16 }, fill: { x: 16, y: 16, w: 16, h: 16 } })
  assert.equal(tilesetCells({}), null)
})

test('a jump leaves the ground and lands on it again; the hero stays inside the level', () => {
  let body = stepBody(
    { x: 10, y: GROUND_Y, vx: 0, vy: 0, onGround: true },
    { left: false, right: false, run: false, jump: true },
    1 / 60,
  )
  assert.equal(body.onGround, false)
  assert.ok(body.y < GROUND_Y)
  let guard = 0
  while (!body.onGround && guard < 400) {
    body = stepBody(body, { left: false, right: false, run: false, jump: false }, 1 / 60)
    guard += 1
  }
  assert.equal(body.onGround, true)
  assert.equal(body.y, GROUND_Y)
  assert.ok(guard < 400)
  for (let index = 0; index < 50; index += 1) body = stepBody(body, { left: true, right: false, run: true, jump: false }, 0.05)
  assert.equal(body.x, 16)
})

test('integer scale fits a phone and caps a wide view', () => {
  assert.equal(integerScale(390), 1)
  assert.equal(integerScale(1280), 2)
  assert.equal(integerScale(2560), 4)
})
