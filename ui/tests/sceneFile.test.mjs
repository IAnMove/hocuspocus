import assert from 'node:assert/strict'
import test from 'node:test'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile.ts'

const valid = {
  version: 1,
  name: 'Shot',
  width: 1280,
  height: 720,
  duration: 4,
  fps: 30,
  layers: [
    { id: 'cam', name: 'Camera', type: 'camera', source: '', visible: true, z: 0, transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 }, animation: { start: {}, end: {}, duration: 4, curve: 'linear' } },
  ],
}

test('parseSceneFile round-trips a serialized scene', () => {
  const parsed = parseSceneFile(serializeSceneFile(valid))
  assert.equal(parsed.version, 1)
  assert.equal(parsed.layers[0].id, 'cam')
  assert.equal(parsed.fps, 30)
})

test('parseSceneFile fills missing size/duration and rejects broken layers', () => {
  const parsed = parseSceneFile(JSON.stringify({
    version: 1,
    layers: [{ id: 'hero', type: 'image', source: 'hero.png', name: 'Hero', visible: true, z: 1, transform: {}, animation: { start: {}, end: {}, duration: 1, curve: 'linear' } }],
  }))
  assert.equal(parsed.width, 1280)
  assert.equal(parsed.height, 720)
  assert.equal(parsed.duration, 1)
  assert.throws(() => parseSceneFile(JSON.stringify({ version: 1, layers: [{}] })), /valid id/)
  assert.throws(() => parseSceneFile(JSON.stringify({
    version: 1,
    layers: [
      { id: 'a', type: 'image', source: '', name: 'A', visible: true, z: 0, transform: {}, animation: { start: {}, end: {}, duration: 1, curve: 'linear' } },
      { id: 'a', type: 'overlay', source: '', name: 'B', visible: true, z: 1, transform: {}, animation: { start: {}, end: {}, duration: 1, curve: 'linear' } },
    ],
  })), /unique id/)
  assert.throws(() => parseSceneFile(JSON.stringify({
    version: 1,
    layers: [{ id: 'ship', type: 'teleport', source: '', name: 'Ship', visible: true, z: 0, transform: {}, animation: { start: {}, end: {}, duration: 1, curve: 'linear' } }],
  })), /Unsupported scene layer type/)
})
