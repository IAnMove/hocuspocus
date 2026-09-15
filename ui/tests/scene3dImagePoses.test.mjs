import test from 'node:test'
import assert from 'node:assert/strict'
import { imagePoseAtTime, imagePoseBounds, imagePoseRect, parseImagePoses } from '../src/features/scene3d/imagePoseSequence.ts'
import { defaultMediaScreen, parseMediaScreen, mediaScreenMountKey } from '../src/features/scene3d/mediaScreen.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { slotMountKey } from '../src/features/scene3d/backdrop.ts'
import { worldAssetsReady } from '../src/features/scene3d/gpu.ts'
import { cameraEyeAtTime, cameraLookAtTime } from '../src/features/scene3d/camera.ts'
import { createUserTemplate, remountUserTemplate } from '../src/features/scene3d/userTemplates.ts'

const poses = () => parseImagePoses([
  { sourceUrl: '/examples/standing.png', duration: 1, height: .9 },
  { sourceUrl: '/examples/kneeling.png', duration: 2, height: .6 },
  { sourceUrl: '/examples/bracing.png', duration: 1, height: .4 },
])

test('fixed cameras keep their eye and target while character and media clocks advance', () => {
  const doc = applyScene3DTemplate('dark-living-black-tide')
  doc.camera = { ...doc.camera, family: 'fixed', framing: undefined }
  assert.equal(parseScene3DDocument(doc).camera.family, 'fixed')
  for (const t of [0, .5, 3, 6]) {
    assert.deepEqual(cameraEyeAtTime(doc.camera, t, 6, doc.slots), doc.camera.eye)
    assert.deepEqual(cameraLookAtTime(doc.camera, t, 6, doc.slots), doc.camera.look)
  }
})

test('held poses preserve exact boundaries, final hold, trim, speed and backward seeking', () => {
  const p = poses(), clock = { start: 0, speed: 1, loop: false }
  assert.deepEqual([0, .999, 1, 2.99, 3, 4, 50, .5].map(t => imagePoseAtTime(p, t, clock)), [0, 0, 1, 1, 2, 2, 2, 0])
  assert.equal(imagePoseAtTime(p, 4, { ...clock, loop: true }), 0)
  assert.equal(imagePoseAtTime(p, .5, { ...clock, start: 2, speed: 2 }), 2)
  assert.equal(imagePoseAtTime([], 1, clock), -1)
})

test('transparent padding is excluded from pose alignment while crouching stays grounded', () => {
  const data = new Uint8ClampedArray(8 * 10 * 4)
  for (let y = 2; y <= 8; y++) for (let x = 1; x <= 5; x++) data[(y * 8 + x) * 4 + 3] = 255
  const bounds = imagePoseBounds(data, 8, 10)
  assert.deepEqual(bounds, { x: 1, y: 2, width: 5, height: 7 })
  const standing = imagePoseRect(poses()[0], bounds, 720, 1280)
  const kneeling = imagePoseRect(poses()[1], bounds, 720, 1280)
  assert.equal(standing.y + standing.height, kneeling.y + kneeling.height)
  assert.ok(kneeling.height < standing.height)
  assert.throws(() => imagePoseBounds(new Uint8ClampedArray(4), 1, 1), /empty-image/)
})

test('pose sequences reject missing durable frames and bound memory and timing inputs', () => {
  assert.throws(() => parseImagePoses([{ sourceUrl: 'blob:expired' }]), /missing-image/)
  assert.throws(() => parseImagePoses(Array(25).fill(poses()[0])), /too-long/)
  const [p] = parseImagePoses([{ sourceUrl: '/test.png', duration: 0, height: Infinity, x: -99, lift: 4 }])
  assert.equal(p.duration, 1 / 60); assert.equal(p.height, .9); assert.equal(p.x, -1); assert.equal(p.lift, 1)
})

test('pose sources, durations, placement and alpha survive native scene reopening', () => {
  const doc = applyScene3DTemplate('dark-living-black-tide')
  const slot = doc.slots.find(s => s.slot === 'subject_1')
  slot.screen = parseMediaScreen({ ...defaultMediaScreen(), sourceUrl: poses()[0].sourceUrl, poseSequence: poses(), transparent: true, loop: false })
  const restored = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.deepEqual(restored.slots.find(s => s.id === slot.id).screen, slot.screen)
  const changed = { ...slot.screen, poseSequence: poses().map((p, i) => i === 1 ? { ...p, sourceUrl: '/new.png' } : p) }
  assert.notEqual(mediaScreenMountKey(slot.screen), mediaScreenMountKey(changed))
  const gpu = { mountKey: slotMountKey(slot), loaded: true, screen: { ready: false } }
  const world = { dressingReady: true, slots: new Map([[slot.id, gpu]]) }
  assert.equal(worldAssetsReady(world, [slot]), false)
  gpu.screen.ready = true; assert.equal(worldAssetsReady(world, [slot]), true)
  assert.equal(worldAssetsReady(world, [{ ...slot, screen: changed }]), false)
  gpu.screenError = new Error('pose-sequence-load-timeout')
  assert.throws(() => worldAssetsReady(world, [slot]), /pose-sequence-load-timeout/)
})

test('a layout-only scenario still exposes pose media after the still is stripped', () => {
  const pack = createUserTemplate({
    document: applyScene3DTemplate('dark-still-time-wounds'),
    title: 'Wounds layout',
    includeAssets: false,
    id: 'user-wounds',
  })
  assert.ok(pack)
  const hero = pack.document.slots.find(slot => slot.id === 'hero')
  assert.equal(hero.sourceUrl, '')
  assert.equal(hero.screen.sourceUrl, '/examples/dark-stillness/wounded-knight.png')
  assert.equal(hero.screen.poseSequence.length, 7)
  const applied = remountUserTemplate(pack, createDefaultScene3DDocument(), false)
  const live = applied.slots.find(slot => slot.id === 'hero')
  assert.equal(live.sourceUrl, '')
  assert.ok(live.screen.sourceUrl)
  assert.equal(live.screen.poseSequence.length, 7)
  const gpu = { mountKey: slotMountKey(live), loaded: true }
  const world = { dressingReady: true, slots: new Map([[live.id, gpu]]) }
  assert.equal(worldAssetsReady(world, [live]), false)
  gpu.screen = { ready: true }
  assert.equal(worldAssetsReady(world, [live]), true)
})
