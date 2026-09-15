import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import {
  WORLD3D_TEMPLATE_KIND,
  USER_TEMPLATE_STORAGE_KEY,
  createUserTemplate,
  downloadUserTemplate,
  isWorld3DTemplateRaw,
  parseUserTemplate,
  readStoredUserTemplates,
  remountUserTemplate,
  removeUserTemplate,
  saveUserTemplate,
  scenarioDocumentFromShot,
  templateFileTooLarge,
  writeStoredUserTemplates,
} from '../src/features/scene3d/userTemplates.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, Storage: dom.window.Storage })

const gallery = { workspaceId: 'demo', filename: 'hero.glb', url: '/api/v1/uploads/hero.glb' }

test('export strips clip identity, production and blob URLs from a scenario pack', () => {
  const document = applyScene3DTemplate('two-shot')
  document.clipNumber = 17
  document.playbackSpeed = 2
  document.dressing = applyScene3DTemplate('cafe-dance').dressing
  document.production = { kind: 'song', title: 'Clip 17', workspace: 'demo' }
  document.slots[0].sourceUrl = 'blob:http://localhost/secret'
  document.slots[0].sourceRef = { ...gallery, url: 'blob:http://localhost/secret' }
  document.slots[1].sourceUrl = gallery.url
  document.slots[1].sourceRef = gallery
  const pack = createUserTemplate({ document, title: 'My tavern', description: 'Cafe layout', includeAssets: true, id: 'user-tavern' })
  assert.ok(pack)
  assert.equal(pack.kind, WORLD3D_TEMPLATE_KIND)
  assert.equal(pack.title, 'My tavern')
  assert.equal(pack.document.clipNumber, undefined)
  assert.equal(pack.document.production, undefined)
  assert.equal(pack.document.templateId, 'two-shot')
  assert.equal(pack.document.dressing, 'cafe')
  assert.equal(pack.document.slots[0].sourceUrl, '')
  assert.equal(pack.document.slots[1].sourceUrl, gallery.url)
  assert.equal(pack.document.slots[0].speech, undefined)
})

test('export without assets clears durable URLs too', () => {
  const document = createDefaultScene3DDocument()
  document.slots[0].sourceUrl = gallery.url
  const stripped = scenarioDocumentFromShot(document, false)
  assert.equal(stripped.slots[0].sourceUrl, '')
  assert.equal(createUserTemplate({ document, title: '  ' }), undefined)
})

test('import accepts a pack and wraps a raw shot JSON as a scenario', () => {
  const shot = createDefaultScene3DDocument()
  shot.clipNumber = 4
  shot.slots[0].sourceUrl = gallery.url
  const wrapped = parseUserTemplate(shot)
  assert.ok(wrapped)
  assert.equal(wrapped.kind, WORLD3D_TEMPLATE_KIND)
  assert.equal(wrapped.document.clipNumber, undefined)
  assert.equal(wrapped.document.slots[0].sourceUrl, gallery.url)
  assert.equal(parseUserTemplate({ kind: WORLD3D_TEMPLATE_KIND, version: 2, id: 'x', title: 'x', document: shot }), undefined)
  assert.equal(isWorld3DTemplateRaw({ kind: WORLD3D_TEMPLATE_KIND }), true)
  assert.equal(isWorld3DTemplateRaw(shot), false)
})

const villain = { id: 'villain-1', name: 'Villain', kitRef: { id: 'villain-1', workspace: 'demo' } }
const hero = { id: 'hero-1', name: 'Hero', kitRef: { id: 'hero-1', workspace: 'demo' } }

test('export without assets strips character identity so keep-objects cannot graft it onto another GLB', () => {
  const document = applyScene3DTemplate('speech-portrait')
  document.slots[0].sourceUrl = gallery.url
  document.slots[0].sourceRef = gallery
  document.slots[0].character = villain
  document.slots[0].speech = { version: 1, enabled: true, cues: [], driver: 'imported', start: 0, offset: 0, gain: 1, strength: .85, clean: true, style: 'soft', lip: '#874d47', expression: 'neutral', blink: true, eyes: true }
  const pack = createUserTemplate({ document, title: 'Talking cafe', includeAssets: false, id: 'user-talk' })
  assert.ok(pack)
  assert.equal(pack.document.slots[0].sourceUrl, '')
  assert.equal(pack.document.slots[0].character, undefined)
  assert.equal(pack.document.slots[0].speech, undefined)

  const previous = applyScene3DTemplate('speech-portrait')
  previous.slots[0].sourceUrl = '/api/v1/uploads/current-hero.glb'
  previous.slots[0].sourceRef = { workspaceId: 'demo', filename: 'current-hero.glb', url: '/api/v1/uploads/current-hero.glb' }
  previous.slots[0].character = hero
  previous.slots[0].clip = { index: 0, name: 'Idle' }
  const kept = remountUserTemplate(pack, previous, true)
  assert.equal(kept.slots[0].sourceUrl, previous.slots[0].sourceUrl)
  assert.equal(kept.slots[0].character.id, 'hero-1')
  assert.equal(kept.slots[0].clip.name, 'Idle')

  const leftover = {
    kind: WORLD3D_TEMPLATE_KIND, version: 1, id: 'user-leftover', title: 'Leftover villain', includeAssets: false,
    document: { ...document, clipNumber: undefined, production: undefined },
  }
  const imported = parseUserTemplate(leftover)
  assert.ok(imported)
  assert.equal(imported.document.slots[0].character, undefined)
  assert.equal(imported.document.slots[0].sourceUrl, '')
})

test('keep-objects does not attach the current character or speech onto a template that brought its own GLB', () => {
  const document = applyScene3DTemplate('speech-portrait')
  document.slots[0].sourceUrl = gallery.url
  document.slots[0].sourceRef = gallery
  document.slots[0].character = villain
  const pack = createUserTemplate({ document, title: 'Cast cafe', includeAssets: true, id: 'user-cast' })
  assert.equal(pack.document.slots[0].character.id, 'villain-1')
  const previous = applyScene3DTemplate('speech-portrait')
  previous.slots[0].sourceUrl = '/api/v1/uploads/current-hero.glb'
  previous.slots[0].character = hero
  previous.slots[0].speech = { version: 1, enabled: true, cues: [], driver: 'imported', start: 0, offset: 0, gain: 1, strength: .85, clean: true, style: 'soft', lip: '#874d47', expression: 'neutral', blink: true, eyes: true }
  const kept = remountUserTemplate(pack, previous, true)
  assert.equal(kept.slots[0].sourceUrl, gallery.url)
  assert.equal(kept.slots[0].character.id, 'villain-1')
  assert.equal(kept.slots[0].speech, undefined)
})

test('keep-objects restores standalone screen media that export stripped', () => {
  const document = applyScene3DTemplate('billboard-plaza')
  const screen = document.slots.find(slot => slot.media === 'screen')
  assert.ok(screen?.screen)
  screen.screen.sourceUrl = '/api/v1/uploads/ad.mp4'
  screen.screen.sourceRef = { workspaceId: 'demo', filename: 'ad.mp4', url: '/api/v1/uploads/ad.mp4' }
  screen.screen.media = 'video'
  document.slots[0].sourceUrl = gallery.url
  document.slots[0].sourceRef = gallery

  const pack = createUserTemplate({ document, title: 'Night plaza', includeAssets: false, id: 'user-plaza' })
  assert.ok(pack)
  const packedScreen = pack.document.slots.find(slot => slot.media === 'screen')
  assert.equal(packedScreen.screen.sourceUrl, '')
  assert.equal(packedScreen.screen.sourceRef, undefined)
  assert.equal(pack.document.slots[0].sourceUrl, '')

  const kept = remountUserTemplate(pack, document, true)
  const keptScreen = kept.slots.find(slot => slot.id === screen.id)
  assert.equal(keptScreen.screen.sourceUrl, '/api/v1/uploads/ad.mp4')
  assert.equal(keptScreen.screen.sourceRef.filename, 'ad.mp4')
  assert.equal(keptScreen.screen.media, 'video')
  assert.equal(kept.slots[0].sourceUrl, gallery.url)
})

test('keep-objects does not clone the first wall onto every destination screen', () => {
  const room = applyScene3DTemplate('control-room')
  room.slots.filter(slot => slot.media === 'screen').forEach((slot, index) => {
    slot.screen.sourceUrl = `/api/v1/uploads/wall-${index}.mp4`
    slot.screen.media = 'video'
  })
  const pack = createUserTemplate({ document: applyScene3DTemplate('topic-travelling'), title: 'Topics', includeAssets: false, id: 'user-topics' })
  const kept = remountUserTemplate(pack, room, true)
  const urls = kept.slots.filter(slot => slot.media === 'screen').map(slot => slot.screen.sourceUrl)
  assert.deepEqual(urls, [
    '/api/v1/uploads/wall-0.mp4',
    '/api/v1/uploads/wall-1.mp4',
    '/api/v1/uploads/wall-2.mp4',
  ])
})

test('keep-objects restores each control-room screen by slot id', () => {
  const document = applyScene3DTemplate('control-room')
  const screens = document.slots.filter(slot => slot.media === 'screen')
  assert.equal(screens.length, 6)
  screens.forEach((slot, index) => {
    slot.screen.sourceUrl = `/api/v1/uploads/wall-${index}.mp4`
    slot.screen.sourceRef = { workspaceId: 'demo', filename: `wall-${index}.mp4`, url: slot.screen.sourceUrl }
    slot.screen.media = 'video'
  })
  const pack = createUserTemplate({ document, title: 'Walls', includeAssets: false, id: 'user-walls' })
  const kept = remountUserTemplate(pack, document, true)
  for (const slot of screens) {
    const next = kept.slots.find(item => item.id === slot.id)
    assert.equal(next.screen.sourceUrl, slot.screen.sourceUrl)
  }
})

test('wrapping a screen-only shot keeps the durable screen URL', () => {
  const shot = applyScene3DTemplate('monitor-detail')
  shot.slots[0].screen.sourceUrl = '/api/v1/uploads/spot.mp4'
  shot.slots[0].screen.sourceRef = { workspaceId: 'demo', filename: 'spot.mp4', url: '/api/v1/uploads/spot.mp4' }
  shot.slots[0].screen.media = 'video'
  const wrapped = parseUserTemplate(shot)
  assert.ok(wrapped)
  assert.equal(wrapped.includeAssets, true)
  assert.equal(wrapped.document.slots[0].screen.sourceUrl, '/api/v1/uploads/spot.mp4')
})

test('applying a scenario keeps clip size and can reuse the current GLBs', () => {
  const previous = createDefaultScene3DDocument()
  previous.clipNumber = 8
  previous.width = 1920
  previous.height = 1080
  previous.fps = 60
  previous.playbackSpeed = 0.5
  previous.slots[0].sourceUrl = gallery.url
  previous.slots[0].sourceRef = gallery
  previous.slots[0].clip = { index: 0, name: 'Walk' }
  const pack = createUserTemplate({ document: applyScene3DTemplate('hero-push'), title: 'Hero', id: 'user-hero' })
  const kept = remountUserTemplate(pack, previous, true)
  assert.equal(kept.clipNumber, 8)
  assert.equal(kept.width, 1920)
  assert.equal(kept.templateId, 'hero-push')
  assert.equal(kept.slots[0].sourceUrl, gallery.url)
  assert.equal(kept.slots[0].clip.name, 'Walk')
  const fresh = remountUserTemplate(pack, previous, false)
  assert.equal(fresh.slots[0].sourceUrl, '')
  assert.equal(fresh.clipNumber, 8)
})

test('browser library stores at most 24 scenarios and rejects oversized files', () => {
  window.localStorage.clear()
  for (let index = 0; index < 26; index++) {
    const pack = createUserTemplate({ document: createDefaultScene3DDocument(), title: `Scene ${index}`, id: `user-${index}` })
    saveUserTemplate(pack)
  }
  const stored = readStoredUserTemplates()
  assert.equal(stored.length, 24)
  assert.equal(stored[0].id, 'user-25')
  assert.equal(stored.at(-1).id, 'user-2')
  assert.equal(removeUserTemplate('user-25').length, 23)
  assert.equal(templateFileTooLarge(1.5 * 1024 * 1024 + 1), true)
  assert.equal(templateFileTooLarge(1024), false)
  const original = Storage.prototype.setItem
  Storage.prototype.setItem = () => { throw new Error('full') }
  try {
    assert.throws(() => writeStoredUserTemplates([]), /quota/)
  } finally { Storage.prototype.setItem = original }
})

test('download uses a shareable scenario filename', () => {
  const clicks = []
  const original = URL.createObjectURL
  URL.createObjectURL = () => 'blob:template'
  URL.revokeObjectURL = () => {}
  const proto = window.HTMLAnchorElement.prototype
  const click = proto.click
  proto.click = function clickSpy() { clicks.push(this.download) }
  try {
    downloadUserTemplate(createUserTemplate({ document: createDefaultScene3DDocument(), title: 'Night Cafe!', id: 'user-night' }))
    assert.deepEqual(clicks, ['night-cafe.world3d.template.json'])
  } finally {
    proto.click = click
    URL.createObjectURL = original
  }
})
