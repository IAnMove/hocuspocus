import assert from 'node:assert/strict'
import test from 'node:test'
import { GROUND_Y, integerScale, playtestScene, stepBody } from '../src/features/game-assets/playtestScene.ts'
import type { Game, GameAsset, GameAttempt } from '../src/features/game-assets/types.ts'

function attempt(file: string, metrics?: Record<string, unknown>): GameAttempt {
  return { id: 'a1', status: 'ok', files: file.endsWith('.ogg') || file.endsWith('.wav') ? { ogg: file, wav: file } : { preview: file, main: file }, metrics }
}

function asset(partial: Partial<GameAsset> & Pick<GameAsset, 'id' | 'kind'>): GameAsset {
  return {
    name: partial.name || partial.id,
    description: '',
    status: partial.status || 'approved',
    tags: [],
    spec: partial.spec || {},
    dependsOn: partial.dependsOn || [],
    candidates: 1,
    locked: false,
    attempts: partial.attempts || [attempt(`${partial.id}.png`)],
    approvedAttemptId: null,
    ...partial,
  }
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

test('a synthetic approved game fills the playtest and keeps the parallax factor', () => {
  const scene = playtestScene(game([
    asset({ id: 'hero', kind: 'character', spec: { role: 'player' } }),
    asset({ id: 'slime', kind: 'character', name: 'Slime' }),
    asset({ id: 'idle', kind: 'animation', spec: { action: 'idle' }, dependsOn: ['hero'] }),
    asset({ id: 'walk', kind: 'animation', spec: { action: 'andar' }, dependsOn: ['hero'] }),
    asset({ id: 'run', kind: 'animation', spec: { action: 'run' }, dependsOn: ['hero'] }),
    asset({ id: 'jump', kind: 'animation', spec: { action: 'saltar' }, dependsOn: ['hero'] }),
    asset({ id: 'attack', kind: 'animation', spec: { action: 'attack' }, dependsOn: ['hero'] }),
    asset({ id: 'grass', kind: 'tile' }),
    asset({ id: 'ground', kind: 'tileset' }),
    asset({
      id: 'woods', kind: 'background',
      attempts: [{
        id: 'bg', status: 'ok',
        files: { 'layer-0.png': 'far.png', 'layer-1.png': 'near.png', parallax: 'parallax.json' },
        metrics: { layers: [{ file: 'layer-0.png', factor: 0.1 }, { file: 'layer-1.png', factor: 1 }] },
      }],
    }),
    asset({ id: 'theme', kind: 'music', attempts: [attempt('theme.ogg')] }),
    asset({ id: 'salto', kind: 'sfx', spec: { trigger: 'salto' }, attempts: [attempt('jump.wav')] }),
    asset({ id: 'moneda', kind: 'sfx', name: 'moneda', attempts: [attempt('coin.wav')] }),
    asset({ id: 'golpe', kind: 'sfx', name: 'golpe', attempts: [attempt('hit.wav')] }),
    asset({ id: 'coin', kind: 'item', name: 'Coin' }),
  ]))
  assert.equal(scene.hero?.id, 'hero')
  assert.deepEqual(Object.keys(scene.hero?.sheets || {}), ['idle', 'walk', 'run', 'jump', 'attack'])
  assert.deepEqual(scene.tiles.map(item => item.id), ['ground'])
  assert.deepEqual(scene.layers.map(layer => layer.factor), [0.1, 1])
  assert.equal(scene.enemies[0]?.id, 'slime')
  assert.equal(scene.music, 'theme.ogg')
  assert.equal(scene.sfxByTrigger.jump, 'jump.wav')
  assert.equal(scene.sfxByTrigger.coin, 'coin.wav')
  assert.equal(scene.sfxByTrigger.hit, 'hit.wav')
  assert.deepEqual(scene.missing, [])
  assert.equal(scene.items[0]?.name, 'Coin')
})

test('nothing approved is listed as missing', () => {
  const scene = playtestScene(game([
    asset({ id: 'hero', kind: 'character', status: 'review', spec: { role: 'player' } }),
    asset({ id: 'grass', kind: 'tile', status: 'pending' }),
  ]))
  assert.equal(scene.hero, null)
  for (const item of ['hero', 'tile', 'background', 'music', 'sfx:jump', 'sfx:coin', 'sfx:hit']) {
    assert.ok(scene.missing.includes(item), item)
  }
})

test('a jump leaves the ground and lands on it again', () => {
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
})

test('integer scale fits a phone and caps a wide view', () => {
  assert.equal(integerScale(390), 1)
  assert.equal(integerScale(1280), 2)
  assert.equal(integerScale(2560), 4)
})
