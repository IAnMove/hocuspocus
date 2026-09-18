import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FX_CATALOG, parseSceneFx } from '../src/features/sceneFx/types'
import { parseWorldSfx, worldSfxAudioCues, WORLD_SFX_KINDS } from '../src/features/sceneFx/world'
import { worldSfxDepthDocument, worldSfxDuelDocument, worldSfxMixedDocument } from '../src/features/sceneFx/worldDemo'
import { fxSamples } from '../src/features/sceneFx/audio'
import { adoptPreparedSceneDocument, isFxShowcaseDocument, sceneHasAuthoredContent, withFxShowcase } from '../src/features/sceneFx/showcase'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document'
import { applyScene3DTemplate } from '../src/features/scene3d/templates'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile'
import { getSceneLayerTiming } from '../src/lib/sceneTimeline'

test('2D and 3D preserve all effects and audio settings through save/reopen', () => {
  const world = withFxShowcase(createDefaultScene3DDocument())
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(world)))?.sfx, world.sfx)
  const scene = withFxShowcase({ version: 1 as const, name: 'FX', layers: [], width: 640, height: 360, duration: 3 })
  assert.deepEqual(parseSceneFile(serializeSceneFile(scene)).sfx, scene.sfx)
  assert.equal(scene.duration, FX_CATALOG.length * 3)
  assert.deepEqual(scene.sfx.map(cue => cue.kind), FX_CATALOG.map(cue => cue.id))
})

test('invalid/duplicate effects cannot create unbounded or NaN render state', () => {
  const result = parseSceneFx([{ id: 'a', kind: 'sparks', size: Infinity, seed: -5 }, { id: 'a', kind: 'rain' }, { kind: 'unknown' }, { kind: 'snow', start: 3, end: 2 }, null])
  assert.equal(result.length, 1)
  assert.equal(result[0].size, 65)
  assert.equal(result[0].seed, 1)
  assert.equal(parseSceneFx(Array.from({ length: 100 }, (_, i) => ({ id: String(i), kind: 'rain' }))).length, 64)
})

test('every sound has repeatable finite PCM, a non-silent body and silent edges', () => {
  for (const preset of FX_CATALOG) {
    const cue = parseSceneFx([{ kind: preset.id, start: 0, end: 1, sound: true }])[0]
    const first = fxSamples(cue, 16000)
    assert.deepEqual(first, fxSamples(cue, 16000))
    assert.equal(first.length, 16000)
    assert.ok(first.every(value => Number.isFinite(value) && Math.abs(value) <= 1))
    assert.ok(first.some(value => Math.abs(value) > .005), preset.id)
    assert.equal(Math.abs(first[0]), 0)
    assert.ok(Math.abs(first.at(-1)!) < .001)
  }
})


test('anime showcase preserves the scene and supports oriented energy beams', () => {
  const source = createDefaultScene3DDocument()
  const next = withFxShowcase(source, 'anime')
  assert.equal(next.duration, 36)
  assert.equal(next.sfx.length, 12)
  assert.equal(next.slots, source.slots)
  assert.ok(next.sfx.some(cue => cue.kind === 'energy_beam'))
  const rotated = parseSceneFx([{ ...next.sfx[0], rotation: -45 }])
  assert.equal(rotated[0].rotation, -45)
  assert.equal(parseScene3DDocument({ ...next, sfx: rotated })?.sfx?.[0].rotation, -45)
  assert.equal(source.sfx, undefined)
})

test('world SFX stay in meters and do not rewrite screen overlays', () => {
  const demo = worldSfxDepthDocument()
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(demo)))
  assert.equal(reopened?.worldSfx?.length, 2)
  assert.equal(reopened?.worldSfx?.[0].kind, 'portal')
  assert.equal(reopened?.worldSfx?.[0].position.z, -1.55)
  assert.equal(reopened?.sfx?.[0].kind, 'speedlines')
  assert.equal(parseWorldSfx([{ kind: 'confetti', start: 0, end: 1 }]).length, 0)
  assert.equal(parseWorldSfx([{ id: 'a', kind: 'portal', start: 3, end: 2 }]).length, 0)
  const audio = worldSfxAudioCues(demo.worldSfx)
  assert.equal(audio.every(cue => (WORLD_SFX_KINDS as readonly string[]).includes(cue.kind)), true)
  assert.equal(parseScene3DDocument({ ...createDefaultScene3DDocument(), worldSfx: demo.worldSfx })?.sfx?.length ?? 0, 0)
  const duel = parseScene3DDocument(JSON.parse(JSON.stringify(worldSfxDuelDocument())))
  assert.equal(duel?.worldSfx?.some(cue => cue.kind === 'energy_beam' && cue.anchor?.slotId === 'subject_1' && cue.target?.slotId === 'subject_2'), true)
  const mixed = parseScene3DDocument(JSON.parse(JSON.stringify(worldSfxMixedDocument())))
  assert.equal(mixed?.sfx?.some(cue => cue.kind === 'speedlines'), true)
  assert.equal(mixed?.worldSfx?.some(cue => cue.kind === 'lightning'), true)
})

test('2D showcase background matches the requested collection after reopening', () => {
  for (const [collection, seconds] of [['anime', 36], ['retro', 30], ['all', FX_CATALOG.length * 3]] as const) {
    const next = withFxShowcase({ version: 1 as const, name: 'FX', layers: [], width: 640, height: 360, duration: 3 }, collection)
    const reopened = parseSceneFile(serializeSceneFile(next))
    assert.equal(reopened.duration, seconds)
    assert.equal(getSceneLayerTiming(reopened.layers[0]).span, seconds)
    const authored = { ...reopened, duration: 120 }
    assert.equal(withFxShowcase(authored, collection).layers, authored.layers)
  }
})

test('Wizard showcase without a document keeps an authored 2D scene and its local assets', () => {
  const current = {
    version: 1 as const,
    name: 'Hero shot',
    width: 1280,
    height: 720,
    duration: 8,
    layers: [{
      id: 'hero',
      type: 'image' as const,
      source: 'blob:http://localhost/user-cutout',
      name: 'Hero',
      visible: true,
      transform: { x: 40, y: 50, scale: 1, opacity: 1, rotation: 0 },
      animation: { start: { x: 40, y: 50, scale: 1, opacity: 1, rotation: 0 }, end: { x: 40, y: 50, scale: 1, opacity: 1, rotation: 0 }, duration: 8, curve: 'linear' as const },
    }],
  }
  const incoming = withFxShowcase({ version: 1 as const, name: 'SFX showcase', layers: [], width: 1280, height: 720, duration: 4 }, 'anime')
  assert.equal(isFxShowcaseDocument(incoming), true)
  assert.equal(sceneHasAuthoredContent(current), true)
  const adopted = adoptPreparedSceneDocument(current, incoming)
  assert.equal(adopted.mode, 'retain')
  assert.equal(adopted.document.layers, current.layers)
  assert.equal(adopted.document.layers[0].source, 'blob:http://localhost/user-cutout')
  assert.equal(adopted.document.name, 'Hero shot')
  assert.equal(adopted.document.duration, 36)
  assert.equal(adopted.document.sfx.length, 12)
})

test('Wizard showcase without a document keeps placed 3D speakers', () => {
  const current = createDefaultScene3DDocument()
  current.slots[0].sourceUrl = '/api/v1/file/hero.glb?workspace=client-a'
  const incoming = withFxShowcase(createDefaultScene3DDocument(), 'all')
  const adopted = adoptPreparedSceneDocument(current, incoming)
  assert.equal(adopted.mode, 'retain')
  assert.equal(adopted.document.slots, current.slots)
  assert.equal(adopted.document.slots[0].sourceUrl, '/api/v1/file/hero.glb?workspace=client-a')
  assert.equal(adopted.document.sfx.length, FX_CATALOG.length)
})

test('Wizard showcase without a document keeps authored world SFX on an empty Video3D stage', () => {
  const current = createDefaultScene3DDocument()
  current.worldSfx = parseWorldSfx([{ id: 'portal-1', kind: 'portal', start: 0, end: 4, position: { x: 0, y: 1.2, z: -1.5 } }])
  const incoming = withFxShowcase(createDefaultScene3DDocument(), 'anime')
  assert.equal(sceneHasAuthoredContent(current), true)
  const adopted = adoptPreparedSceneDocument(current, incoming)
  assert.equal(adopted.mode, 'retain')
  assert.equal(adopted.document.slots, current.slots)
  assert.equal(adopted.document.worldSfx, current.worldSfx)
  assert.equal(adopted.document.worldSfx?.[0].id, 'portal-1')
  assert.equal(adopted.document.sfx.length, 12)
})

test('Wizard showcase without a document keeps authored screen media on a monitor-only stage', () => {
  const current = applyScene3DTemplate('monitor-detail')
  const screen = current.slots[0]
  assert.equal(screen.media, 'screen')
  assert.equal(screen.sourceUrl, '')
  screen.screen = { ...screen.screen!, sourceUrl: '/api/v1/uploads/show.mp4', media: 'video' }
  const incoming = withFxShowcase(createDefaultScene3DDocument(), 'all')
  assert.equal(sceneHasAuthoredContent(current), true)
  const adopted = adoptPreparedSceneDocument(current, incoming)
  assert.equal(adopted.mode, 'retain')
  assert.equal(adopted.document.slots, current.slots)
  assert.equal(adopted.document.slots[0].screen?.sourceUrl, '/api/v1/uploads/show.mp4')
  assert.equal(adopted.document.templateId, 'monitor-detail')
  assert.ok(adopted.document.sfx.length >= 12)
})

test('an empty editor still opens the stock showcase, and apply/speech documents still replace', () => {
  const empty2d = { version: 1 as const, name: 'Untitled scene', layers: [] as [], width: 1280, height: 720, duration: 5 }
  const showcase = withFxShowcase({ version: 1 as const, name: 'SFX showcase', layers: [], width: 1280, height: 720, duration: 4 })
  assert.equal(sceneHasAuthoredContent(empty2d), false)
  assert.equal(adoptPreparedSceneDocument(empty2d, showcase).mode, 'replace')
  const current = createDefaultScene3DDocument()
  current.slots[0].sourceUrl = '/files/hero.glb'
  const preparedApply = { ...createDefaultScene3DDocument(), duration: 6, sfx: [{ id: 'spark-1', kind: 'sparks', start: 0, end: 1 }] }
  assert.equal(isFxShowcaseDocument(preparedApply), false)
  assert.equal(adoptPreparedSceneDocument(current, preparedApply as typeof current).mode, 'replace')
})
