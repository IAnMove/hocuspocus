import assert from 'node:assert/strict'
import test from 'node:test'
import { appliedCharacterFaceTransform, captureCharacterFaceAnchor, characterKitInventory, characterKitRecipeInventory, createCharacterKit, emptyCharacterKitLibrary, mountCharacterKitLayers, parseCharacterKitPoseLayerId, syncMountedCharacterKitLayers, syncSceneCharacterKits } from '../src/lib/characterKit.ts'

const asset = (id, reviewState = 'approved') => ({ id, name: id, source: `${id}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState })

test('face anchors retain placement relative to a pose', () => {
  const pose = { transform: { x: 40, y: 55, scale: .5, opacity: 1, rotation: 5 } }
  const mouth = { transform: { x: 42, y: 49, scale: .1, opacity: 1, rotation: 2 } }
  assert.deepEqual(captureCharacterFaceAnchor(pose, mouth), { offsetX: 4, offsetY: -12, scale: .2, rotation: -3 })
})

test('applied face transform scales pose-local anchors with the character', () => {
  const pose = { x: 40, y: 60, scale: .5, opacity: 1, rotation: 0 }
  const anchor = { offsetX: 4, offsetY: -12, scale: .2, rotation: 0 }
  assert.deepEqual(appliedCharacterFaceTransform(pose, anchor), { x: 42, y: 54, scale: .1, opacity: 1, rotation: 0 })
  const larger = appliedCharacterFaceTransform({ ...pose, scale: 1 }, anchor)
  assert.equal(larger.x, 44)
  assert.equal(larger.y, 48)
  assert.equal(larger.scale, .2)
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
  const closed = layers.find(layer => layer.id.endsWith('mouth-closed'))
  const wide = layers.find(layer => layer.id.endsWith('mouth-wide'))
  assert.equal(closed.transform.x, 50 + 2 * .72)
  assert.equal(closed.transform.y, 55 + (-6) * .72)
  assert.equal(closed.transform.scale, .72 * .2)
  assert.equal(closed.transform.opacity, 1)
  assert.equal(closed.animation.start.opacity, 1)
  assert.equal(wide.transform.opacity, 0)
  assert.equal(wide.animation.start.opacity, 0)
})

test('open eyes stay visible at rest and blink starts hidden', () => {
  const kit = {
    ...createCharacterKit('Luma'),
    base: { ...asset('luma-base'), kind: 'image' },
    mouth: { closed: asset('closed') },
    eyes: { open: asset('open'), blink: asset('blink') },
    anchors: { base: { mouth: { offsetX: 0, offsetY: -18, scale: .05, rotation: 0 }, eyes: { offsetX: 0, offsetY: -28, scale: .12, rotation: 0 } } },
  }
  const layers = mountCharacterKitLayers(kit)
  const open = layers.find(layer => layer.id.endsWith('eyes-open'))
  const blink = layers.find(layer => layer.id.endsWith('eyes-blink'))
  assert.equal(open.transform.opacity, 1)
  assert.equal(open.faceBinding.role, 'eyes')
  assert.equal(blink.transform.opacity, 0)
  assert.equal(blink.z > open.z, true)
})

test('syncing a mounted kit moves the existing mouth without duplicating it', () => {
  const kit = {
    ...createCharacterKit('Luma'),
    base: { ...asset('luma-base'), kind: 'image' },
    mouth: { closed: asset('closed'), wide: asset('wide') },
    eyes: {},
    anchors: { base: { mouth: { offsetX: 0, offsetY: -10, scale: .05, rotation: 0 } } },
  }
  const mounted = mountCharacterKitLayers(kit)
  const moved = {
    ...kit,
    anchors: { base: { mouth: { offsetX: 0, offsetY: -22, scale: .05, rotation: 0 } } },
  }
  const synced = syncMountedCharacterKitLayers(mounted, moved)
  assert.equal(synced.filter(layer => layer.id.endsWith('mouth-closed')).length, 1)
  assert.ok(synced.find(layer => layer.id.endsWith('mouth-closed')).transform.y < mounted.find(layer => layer.id.endsWith('mouth-closed')).transform.y)
})

test('playing a saved scene re-reads live kit anchors instead of the original snapshot', () => {
  const kit = {
    ...createCharacterKit('Luma'),
    base: { ...asset('luma-base'), kind: 'image' },
    mouth: { closed: asset('closed'), wide: asset('wide') },
    eyes: {},
    anchors: { base: { mouth: { offsetX: 0, offsetY: -10, scale: .05, rotation: 0 } } },
  }
  const snapshot = mountCharacterKitLayers(kit)
  const closed = snapshot.find(layer => layer.id.endsWith('mouth-closed'))
  const frozen = snapshot.map(layer => layer.id.endsWith('mouth-closed') || layer.id.endsWith('mouth-wide')
    ? {
      ...layer,
      transform: { ...layer.transform, y: 40 },
      animation: {
        ...layer.animation,
        start: { ...layer.animation.start, y: 40 },
        end: { ...layer.animation.end, y: 40 },
        keyframes: [
          { id: `${layer.id}-0`, time: 0, x: layer.transform.x, y: 40, scale: layer.transform.scale, opacity: layer.transform.opacity, rotation: 0, curve: 'hold' },
          { id: `${layer.id}-1`, time: 1, x: layer.transform.x, y: 40, scale: layer.transform.scale, opacity: layer.id.endsWith('wide') ? 1 : 0, rotation: 0, curve: 'hold' },
        ],
      },
    }
    : layer)
  const live = {
    ...kit,
    anchors: { base: { mouth: { offsetX: 0, offsetY: -24, scale: .05, rotation: 0 } } },
  }
  const library = { ...emptyCharacterKitLibrary(), revision: 11, activeId: live.id, kits: { [live.id]: live } }
  assert.deepEqual(parseCharacterKitPoseLayerId(snapshot[0].id), { kitId: 'luma', poseId: 'base' })
  const synced = syncSceneCharacterKits(frozen, library)
  const updated = synced.find(layer => layer.id.endsWith('mouth-closed'))
  assert.ok(updated.transform.y < closed.transform.y)
  assert.ok(updated.animation.keyframes.every(frame => frame.y === updated.transform.y))
  assert.equal(updated.animation.keyframes[1].opacity, 0)
})

test('mounting uses a per-state mouth anchor and keeps the legacy fallback', () => {
  const kit = {
    ...createCharacterKit('Anchored'),
    base: { ...asset('base'), kind: 'image' },
    mouth: { closed: asset('closed'), wide: asset('wide'), round: asset('round') },
    eyes: {},
    anchors: {
      base: {
        mouth: { offsetX: 2, offsetY: -6, scale: .2, rotation: -3 },
        mouthStates: { wide: { offsetX: 8, offsetY: -4, scale: .25, rotation: 1 } },
      },
    },
  }
  const layers = mountCharacterKitLayers(kit)
  const poseScale = .72
  assert.deepEqual(layers.find(layer => layer.id.endsWith('mouth-wide')).transform, {
    x: 50 + 8 * poseScale,
    y: 55 + (-4) * poseScale,
    scale: poseScale * .25,
    opacity: 0,
    rotation: 1,
  })
  assert.equal(layers.find(layer => layer.id.endsWith('mouth-closed')).transform.x, 50 + 2 * poseScale)
  assert.equal(layers.find(layer => layer.id.endsWith('mouth-round')).transform.x, 50 + 2 * poseScale)
})

test('capture then mount keeps pose-local mouth offset at two scene scales', () => {
  const kit = {
    ...createCharacterKit('Luma'),
    base: { ...asset('luma-base'), kind: 'image' },
    mouth: { closed: asset('closed') },
    eyes: {},
    anchors: { base: { mouth: { offsetX: 4, offsetY: -12, scale: .2, rotation: 0 } } },
  }
  const smallPose = { x: 40, y: 60, scale: .5, opacity: 1, rotation: 0 }
  const largePose = { x: 40, y: 60, scale: 1, opacity: 1, rotation: 0 }
  const small = mountCharacterKitLayers(kit, 'base', smallPose)
  const large = mountCharacterKitLayers(kit, 'base', largePose)
  const recapture = layers => captureCharacterFaceAnchor(
    layers[0],
    layers.find(layer => layer.id.endsWith('mouth-closed')),
  )
  const smallAnchor = recapture(small)
  const largeAnchor = recapture(large)
  assert.equal(smallAnchor.offsetX, 4)
  assert.equal(smallAnchor.offsetY, -12)
  assert.equal(smallAnchor.scale, .2)
  assert.deepEqual(smallAnchor, largeAnchor)
  const smallMouth = small.find(layer => layer.id.endsWith('mouth-closed'))
  const largeMouth = large.find(layer => layer.id.endsWith('mouth-closed'))
  assert.equal(smallMouth.transform.y, 60 + (-12) * .5)
  assert.equal(largeMouth.transform.y, 60 + (-12) * 1)
  assert.notEqual(smallMouth.transform.y, largeMouth.transform.y)
})

test('inventory exposes only reviewed performance pieces to the LLM', () => {
  const kit = { ...createCharacterKit('Brin'), base: { ...asset('base'), kind: 'image' }, poses: { run: asset('run'), sad: asset('sad', 'rejected') }, mouth: { wide: asset('wide'), round: asset('round', 'pending') }, eyes: {} }
  const inventory = characterKitInventory({ version: 1, revision: 1, activeId: kit.id, kits: { [kit.id]: kit } })
  assert.deepEqual(inventory[0].poses, ['base', 'run'])
  assert.deepEqual(inventory[0].mouth, ['wide'])
  const recipeInventory = characterKitRecipeInventory({ version: 1, revision: 1, activeId: kit.id, kits: { [kit.id]: kit } })
  assert.deepEqual(recipeInventory.map(item => item.name), ['brin/base', 'brin/pose/run', 'brin/mouth/wide'])
  assert.ok(recipeInventory.every(item => item.description.includes('APPROVED_CHARACTER_KIT id=brin')))
})
