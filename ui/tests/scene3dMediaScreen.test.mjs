import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultMediaScreen, mediaScreenTime, mediaScreenRect, parseMediaScreen } from '../src/features/scene3d/mediaScreen.ts'
import { applyScene3DTemplate, remountScene3DTemplate, SCENE3D_TEMPLATES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { MEDIA_TEMPLATE_IDS } from '../src/features/scene3d/mediaTemplateIds.ts'
import { slotMountKey } from '../src/features/scene3d/backdrop.ts'
import { worldAssetsReady } from '../src/features/scene3d/gpu.ts'

test('video screen clock respects trim, speed, looping and backward seeking', () => {
  const screen = { ...defaultMediaScreen(), start: 1, speed: 2 }
  assert.equal(mediaScreenTime(1, 5, screen), 3)
  assert.equal(mediaScreenTime(3, 5, screen), 2)
  assert.equal(mediaScreenTime(0, 5, screen), 1)
  assert.equal(mediaScreenTime(3, 5, { ...screen, loop: false }), 4.999)
  assert.equal(mediaScreenTime(1, Infinity, screen), 0)
})

test('wide screenshots fit a 4:3 monitor without stretching or unintended crop', () => {
  assert.deepEqual(mediaScreenRect(1200, 900, 1920, 1080, 'contain'), { x: 0, y: 112.5, width: 1200, height: 675 })
  const cover = mediaScreenRect(1200, 900, 1920, 1080, 'cover')
  assert.equal(cover.height, 900); assert.ok(cover.x < 0); assert.ok(cover.width > 1200)
})

test('screen source identity, mesh, video trim and style survive JSON reopening', () => {
  const doc = applyScene3DTemplate('desk-presenter'), slot = doc.slots.find(s => s.id === 'computer')
  slot.screen = { ...defaultMediaScreen(), sourceUrl: '/api/v1/uploads/demo.mp4', sourceRef: { workspaceId: 'promo', filename: 'demo.mp4', url: '/api/v1/uploads/demo.mp4', assetId: 'screen-video' }, media: 'video', start: 2.5, speed: .5, loop: false, flipY: true }
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.deepEqual(reopened.slots.find(s => s.id === 'computer').screen, slot.screen)
  assert.equal(reopened.dressing, 'retro-lab')
})

test('transient screen uploads cannot masquerade as durable restored assets', () => {
  const parsed = parseMediaScreen({ sourceUrl: 'blob:expired', sourceRef: { workspaceId: 'promo', filename: 'lost.png', url: 'blob:expired' }, width: Infinity, height: -20, speed: NaN })
  assert.equal(parsed.sourceUrl, ''); assert.equal(parsed.sourceRef, undefined)
  assert.equal(parsed.width, 4); assert.equal(parsed.height, .02); assert.equal(parsed.speed, 1)
  assert.equal(parsed.mode, 'mesh')
})

test('all product templates reopen and keep unique world objects; corridor travels', () => {
  for (const id of MEDIA_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id), reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.equal(reopened?.templateId, id)
    assert.equal(new Set(doc.slots.map(s => s.id)).size, doc.slots.length)
    assert.ok(doc.slots.some(s => s.screen))
  }
  const lead = applyScene3DTemplate('screen-corridor').slots[0]
  assert.notDeepEqual(lead.position, lead.motion.to)
  const tv = applyScene3DTemplate('tv-head-walk')
  assert.equal(tv.slots[0].sourceUrl, '/examples/tv-head-humanoid.glb')
  assert.equal(tv.slots[0].screen.mode, 'plane')
  assert.equal(tv.slots[0].screen.anchor, 'headfront')
  assert.equal(tv.slots[0].clip.name, 'Walking')
  const catalog = SCENE3D_TEMPLATES.find(item => item.id === tv.templateId)
  assert.equal(catalog.duration, tv.duration)
  assert.deepEqual(catalog.slots, tv.slots.map(slot => slot.slot))
})

test('changing template can retain selected screen content without copying its geometry', () => {
  const doc = applyScene3DTemplate('monitor-reveal'), screen = doc.slots.find(s => s.screen)
  screen.screen.sourceUrl = '/api/v1/uploads/show.mp4'; screen.screen.media = 'video'
  const next = remountScene3DTemplate('billboard-plaza', doc)
  assert.equal(next.slots[1].screen.sourceUrl, screen.screen.sourceUrl)
  assert.equal(next.slots[1].screen.style, 'billboard')
  assert.equal(next.slots[1].screen.media, 'video')
})

test('keep-objects assigns each control-room wall once when IDs change', () => {
  const room = applyScene3DTemplate('control-room')
  const walls = room.slots.filter(slot => slot.media === 'screen')
  walls.forEach((slot, index) => {
    slot.screen.sourceUrl = `/api/v1/uploads/wall-${index}.mp4`
    slot.screen.media = 'video'
  })
  const next = remountScene3DTemplate('topic-travelling', room)
  const kept = next.slots.filter(slot => slot.media === 'screen').map(slot => slot.screen.sourceUrl)
  assert.deepEqual(kept, [
    '/api/v1/uploads/wall-0.mp4',
    '/api/v1/uploads/wall-1.mp4',
    '/api/v1/uploads/wall-2.mp4',
  ])
  assert.equal(new Set(kept).size, 3)
})

test('export readiness rejects pending, stale and failed screen bindings', () => {
  const slot = applyScene3DTemplate('monitor-detail').slots[0]
  slot.screen.sourceUrl = '/api/v1/uploads/show.mp4'
  const gpu = { mountKey: slotMountKey(slot), loaded: true, screen: { ready: false } }
  const world = { dressingReady: true, slots: new Map([[slot.id, gpu]]) }
  assert.equal(worldAssetsReady(world, [slot]), false)
  gpu.screen.ready = true; assert.equal(worldAssetsReady(world, [slot]), true)
  assert.equal(worldAssetsReady(world, [{ ...slot, screen: { ...slot.screen, sourceUrl: '/different.mp4' } }]), false)
  gpu.screenError = new Error('missing mesh'); assert.throws(() => worldAssetsReady(world, [slot]), /missing mesh/)
})
