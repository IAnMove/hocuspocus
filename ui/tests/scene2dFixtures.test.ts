import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'scene2d')

function load(name: string) {
  return JSON.parse(fs.readFileSync(path.join(root, name, 'scene.json'), 'utf8'))
}

test('reference scenes normalize and keep the v1 text, effect and camera contracts', () => {
  const texts = normalizeScene2D(load('texts-v1'))
  assert.deepEqual(texts.texts?.map(cue => cue.preset), ['impact', 'rise', 'typewriter', 'wave'])
  assert.equal(texts.texts?.every(cue => cue.font === 'sans' || cue.font === 'mono'), true)
  assert.equal(texts.layers.some(layer => layer.atmosphere?.kind === 'dust'), true)

  const effects = normalizeScene2D(load('fx-atmosphere'))
  assert.deepEqual(effects.sfx?.map(cue => cue.kind), ['fireworks', 'portal', 'sparks'])
  assert.equal(effects.sfx?.every(cue => cue.sound === false), true)
  assert.deepEqual(effects.layers.map(layer => layer.atmosphere?.kind), ['rain', 'fog'])

  const camera = normalizeScene2D(load('camera-strips'))
  const follower = camera.layers.find(layer => layer.id === 'follower')
  assert.equal(camera.layers.some(layer => layer.type === 'camera' && layer.visible), true)
  assert.equal(follower?.relationship?.type, 'follow')
  assert.equal(follower?.relationship?.targetLayerId, 'anchor')
  assert.equal(follower?.strip?.enabled, true)
  assert.equal(follower?.strip?.seamOccluder.enabled, true)

  const demo = normalizeScene2D(load('fireworks-demo'))
  assert.equal(demo.sfx?.[0]?.kind, 'fireworks')
  assert.equal(demo.duration, 2)
})
