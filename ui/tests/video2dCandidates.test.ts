import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import { FINISH_PRESETS } from '../src/lib/scene2d/finish.ts'
import { COMPOSER_SCENE_TEMPLATES, VIDEO2D_SCENE_TEMPLATES, getCandidateSceneTemplate } from '../src/features/sceneTemplates/catalog.ts'
import { compileCandidateScene } from '../src/features/sceneTemplates/compile.ts'
import { candidateDemoBindings } from '../src/features/sceneTemplates/demoScenes.ts'
import type { Scene } from '../src/types/index.ts'

const ASSETS = {
  subject_1: { type: 'image' as const, source: '/api/v1/file/photo.png' },
  background: { type: 'image' as const, source: '/api/v1/file/plate.png' },
  foreground: { type: 'image' as const, source: '/api/v1/file/dust.png' },
}
const layersOf = (scene: Scene) => Object.fromEntries(scene.layers.map(layer => [layer.id, layer]))
const travel = (scene: Scene, id: string) => {
  const frames = layersOf(scene)[id]?.animation.keyframes ?? []
  return { x: frames.at(-1)!.x - frames[0].x, scale: frames.at(-1)!.scale - frames[0].scale }
}

test('the two titled cards are composer cards that compile through the one entry and normalize', () => {
  assert.deepEqual(VIDEO2D_SCENE_TEMPLATES.map(template => template.id), ['documentary-history', 'city-postcard'])
  for (const template of VIDEO2D_SCENE_TEMPLATES) {
    assert.ok(COMPOSER_SCENE_TEMPLATES.includes(template))
    const scene = normalizeScene2D(compileCandidateScene(template.id, candidateDemoBindings(template.id)))
    assert.equal(scene.version, 1)
    assert.equal(scene.duration, 6)
    assert.equal(scene.width, 1920)
    assert.ok(scene.texts?.length && scene.finish)
  }
})

test('documentary-history pushes the plate with parallax and writes the caption and years it is given', () => {
  const scene = compileCandidateScene('documentary-history', ASSETS, { caption: 'El puerto en 1931', yearFrom: '1925', yearTo: '1931', yearLabel: 'Año' })
  const layers = layersOf(scene)
  assert.deepEqual(scene.layers.map(layer => layer.id), ['background', 'subject_1', 'foreground', 'atmosphere-dust'])
  assert.equal(layers.background.source, ASSETS.background.source)
  assert.equal(layers.subject_1.source, ASSETS.subject_1.source)
  const plate = travel(scene, 'background')
  const fore = travel(scene, 'foreground')
  assert.ok(plate.scale > 0 && plate.x !== 0, 'the plate pushes and slides')
  assert.ok(Math.abs(fore.x) > Math.abs(plate.x), 'the foreground passes faster than the plate')
  const cues = Object.fromEntries((scene.texts ?? []).map(cue => [cue.id, cue.text]))
  assert.equal(cues.caption, 'El puerto en 1931')
  assert.equal(cues.date, '1931')
  assert.equal(cues.label, 'Año')
  assert.deepEqual(scene.finish, FINISH_PRESETS.oldDoc)
  const quiet = compileCandidateScene('documentary-history', ASSETS, { caption: '', yearFrom: '', yearTo: '' })
  assert.deepEqual(quiet.texts, [], 'empty fields add no titles')
  const decade = compileCandidateScene('documentary-history', ASSETS, { caption: '', yearTo: 'Años 20' })
  assert.deepEqual(decade.texts?.map(cue => [cue.id, cue.text]), [['date', 'Años 20']], 'a year that is not a number dates the shot without a counter')
})

test('city-postcard drifts the city sideways, carries the banner text and says it has no birds', () => {
  const scene = compileCandidateScene('city-postcard', ASSETS, { banner: 'Sal en las ventanas' })
  assert.ok(travel(scene, 'background').x < 0, 'the city drifts sideways')
  assert.ok(Math.abs(travel(scene, 'foreground').x) > Math.abs(travel(scene, 'background').x))
  assert.ok((layersOf(scene)['atmosphere-leaves'].animation.path?.points.length ?? 0) >= 2)
  assert.equal(scene.texts?.[0].text, 'Sal en las ventanas')
  assert.ok(getCandidateSceneTemplate('city-postcard').limits.some(limit => /pájaros/.test(limit)))
  assert.deepEqual(compileCandidateScene('city-postcard', ASSETS, { banner: '' }).texts, [])
})

test('a longer titled shot travels further at the same speed, and portrait frames lay out the titles', () => {
  const short = compileCandidateScene('documentary-history', ASSETS, { duration: 6 })
  const long = compileCandidateScene('documentary-history', ASSETS, { duration: 12 })
  assert.ok(Math.abs(travel(long, 'background').scale - 2 * travel(short, 'background').scale) < 1e-9)
  const tall = compileCandidateScene('documentary-history', ASSETS, {}, { width: 1080, height: 1920 })
  assert.equal(tall.height, 1920)
  assert.deepEqual(Object.fromEntries((tall.texts ?? []).map(cue => [cue.id, cue.y])), { date: 64, caption: 72, count: 42, label: 62 })
})

test('the titled cards take pictures only', () => {
  assert.throws(() => compileCandidateScene('documentary-history', { ...ASSETS, subject_1: { type: 'model3d', source: '/api/v1/file/a.glb' } }), /no admite model3d/)
  assert.throws(() => compileCandidateScene('city-postcard', { ...ASSETS, background: { type: 'video', source: '/api/v1/file/loop.mp4' } }), /no admite video/)
})
