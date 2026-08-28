import assert from 'node:assert/strict'
import test from 'node:test'
import { captureCharacterFaceAnchor, characterKitInventory, createCharacterKit, mountCharacterKitLayers } from '../src/lib/characterKit.ts'

const asset = (id, reviewState = 'approved') => ({ id, name: id, source: `${id}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState })

test('face anchors retain placement relative to a pose', () => {
  const pose = { transform: { x: 40, y: 55, scale: .5, opacity: 1, rotation: 5 } }
  const mouth = { transform: { x: 42, y: 49, scale: .1, opacity: 1, rotation: 2 } }
  assert.deepEqual(captureCharacterFaceAnchor(pose, mouth), { offsetX: 2, offsetY: -6, scale: .2, rotation: -3 })
})

test('mounting a reviewed kit creates isolated semantic face layers', () => {
  const kit = {
    ...createCharacterKit('Luma'),
    base: { ...asset('luma-base'), kind: 'image' },
    mouth: { closed: asset('closed'), wide: asset('wide'), round: asset('round', 'pending') },
    eyes: { blink: asset('blink') },
    anchors: { base: { mouth: { offsetX: 2, offsetY: -6, scale: .2, rotation: -3 }, eyes: { offsetX: 1, offsetY: -10, scale: .3, rotation: 0 } } },
  }
  const layers = mountCharacterKitLayers(kit)
  const pose = layers[0]
  assert.equal(layers.length, 4)
  assert.ok(layers.slice(1).every(layer => layer.relationship.targetLayerId === pose.id))
  assert.deepEqual(layers.find(layer => layer.id.endsWith('mouth-wide')).faceBinding, { poseLayerId: pose.id, role: 'mouth', state: 'wide' })
  assert.equal(layers.some(layer => layer.id.endsWith('mouth-round')), false)
  assert.equal(layers.find(layer => layer.id.endsWith('mouth-closed')).transform.x, 52)
})

test('inventory exposes only reviewed performance pieces to the LLM', () => {
  const kit = { ...createCharacterKit('Brin'), base: { ...asset('base'), kind: 'image' }, poses: { run: asset('run'), sad: asset('sad', 'rejected') }, mouth: { wide: asset('wide'), round: asset('round', 'pending') }, eyes: {} }
  const inventory = characterKitInventory({ version: 1, revision: 1, activeId: kit.id, kits: { [kit.id]: kit } })
  assert.deepEqual(inventory[0].poses, ['base', 'run'])
  assert.deepEqual(inventory[0].mouth, ['wide'])
})
