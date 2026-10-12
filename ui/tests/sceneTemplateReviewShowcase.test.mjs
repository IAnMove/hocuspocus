import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import {
  MAX_SHOWCASE_INPUT_FILE_BYTES,
  MAX_SHOWCASE_INPUTS,
  isBuiltInShowcaseGraphic,
  prepareShowcase,
  registerShowcaseInputs,
} from '../scripts/sceneTemplateReview/showcase.mjs'
import { startReviewServer } from '../scripts/sceneTemplateReview/server.mjs'
import { atmosphere, effect } from '../src/features/sceneTemplates/sceneBuilders.ts'

const bytes = value => Buffer.from(value)
const sha256 = value => createHash('sha256').update(value).digest('hex')

const sceneBytes = (name = 'Editable showcase scene', generationPolicy = 'provided_only') => bytes(JSON.stringify({
  version: 1,
  name,
  generationPolicy,
  width: 1280,
  height: 720,
  fps: 30,
  duration: 4,
  layers: [],
  narrative: { templateId: 'showcase-test' },
}))

const reference = (name, content, sceneName) => ({
  url: `/scene-showcase/${name}`,
  sha256: sha256(content),
  bytes: content.length,
  ...(sceneName ? { sceneName } : {}),
})

const makeManifest = ({ video, poster, scene, items = undefined } = {}) => ({
  schema: 'hocuspocus.scene-showcase',
  version: 1,
  title: 'Portable showcase',
  description: 'A local, verified showcase package.',
  items: items || [{
    id: 'scene-one',
    title: 'Scene one',
    kind: 'scene',
    description: 'One editable scene.',
    effects: ['camera drift'],
    video,
    ...(poster ? { poster } : {}),
    scene,
    imageProvider: 'minimax',
    imageModel: 'image-01',
    approval: 'pending',
  }],
})

async function fixture() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hocus-showcase-package-test-'))
  const showcaseDir = path.join(directory, 'package')
  const uiDist = path.join(directory, 'ui')
  const outputDir = path.join(directory, 'output')
  await Promise.all([fs.mkdir(showcaseDir), fs.mkdir(uiDist), fs.mkdir(outputDir)])
  return { directory, showcaseDir, uiDist, outputDir }
}

async function writePackage({ showcaseDir, video = bytes('video'), poster = bytes('poster'), scene = sceneBytes(), inputs = {} }) {
  const manifest = makeManifest({
    video: reference('scene-one.mp4', video),
    poster: reference('scene-one.png', poster),
    scene: reference('scene-one.json', scene, JSON.parse(scene.toString()).name),
  })
  await fs.writeFile(path.join(showcaseDir, 'scene-one.mp4'), video)
  await fs.writeFile(path.join(showcaseDir, 'scene-one.png'), poster)
  await fs.writeFile(path.join(showcaseDir, 'scene-one.json'), scene)
  if (Object.keys(inputs).length) {
    await fs.mkdir(path.join(showcaseDir, 'inputs'))
    await Promise.all(Object.entries(inputs).map(([name, content]) => fs.writeFile(path.join(showcaseDir, 'inputs', name), content)))
  }
  await fs.writeFile(path.join(showcaseDir, 'manifest.json'), JSON.stringify(manifest))
  return { manifest, video, poster, scene }
}

test('validates, stages only referenced files, and registers canonical inputs', async t => {
  const paths = await fixture()
  t.after(() => fs.rm(paths.directory, { recursive: true, force: true }))
  const original = await writePackage({ showcaseDir: paths.showcaseDir, inputs: { 'nara.png': bytes('canonical-image') } })

  const preparation = await prepareShowcase(paths)
  assert.equal(preparation.referenceCount, 3)
  assert.equal(preparation.inputNames[0], 'nara.png')
  assert.deepEqual(JSON.parse(await fs.readFile(preparation.manifestPath, 'utf8')), original.manifest)
  assert.deepEqual(await fs.readFile(path.join(preparation.uiShowcaseDir, 'scene-one.mp4')), original.video)
  assert.deepEqual(await fs.readFile(path.join(preparation.uiShowcaseDir, 'scene-one.png')), original.poster)
  assert.deepEqual(await fs.readFile(path.join(preparation.uiShowcaseDir, 'scene-one.json')), original.scene)
  assert.deepEqual(await fs.readFile(path.join(paths.outputDir, 'inputs', 'nara.png')), bytes('canonical-image'))

  const calls = []
  const registered = await registerShowcaseInputs({ registerInput: async name => { calls.push(name); return { name } } }, preparation)
  assert.deepEqual(calls, ['nara.png'])
  assert.deepEqual(registered, [{ name: 'nara.png' }])
})

test('fails closed on bytes, SHA-256, scene identity and generation policy', async t => {
  const paths = await fixture()
  t.after(() => fs.rm(paths.directory, { recursive: true, force: true }))
  const scene = sceneBytes('Expected scene')
  const original = await writePackage({ showcaseDir: paths.showcaseDir, scene })
  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.mp4'), bytes('tampered'))
  await assert.rejects(() => prepareShowcase(paths), /SHA-256|bytes/i)
  assert.equal(await fs.access(path.join(paths.uiDist, 'scene-showcase')).then(() => true, () => false), false)

  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.mp4'), original.video)
  const wrongNameScene = sceneBytes('Actual scene')
  const wrongNameManifest = makeManifest({
    video: reference('scene-one.mp4', original.video),
    poster: reference('scene-one.png', original.poster),
    scene: reference('scene-one.json', wrongNameScene, 'Expected scene'),
  })
  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.json'), wrongNameScene)
  await fs.writeFile(path.join(paths.showcaseDir, 'manifest.json'), JSON.stringify(wrongNameManifest))
  await assert.rejects(() => prepareShowcase(paths), /sceneName|name does not match/i)

  const invalidPolicyScene = sceneBytes('Expected scene', 'auto')
  const invalidPolicyManifest = makeManifest({
    video: reference('scene-one.mp4', original.video),
    poster: reference('scene-one.png', original.poster),
    scene: reference('scene-one.json', invalidPolicyScene, 'Expected scene'),
  })
  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.json'), invalidPolicyScene)
  await fs.writeFile(path.join(paths.showcaseDir, 'manifest.json'), JSON.stringify(invalidPolicyManifest))
  await assert.rejects(() => prepareShowcase(paths), /provided_only/i)
})

test('rejects traversal, symlinked files, overwrite targets, and unsupported inputs', async t => {
  const paths = await fixture()
  t.after(() => fs.rm(paths.directory, { recursive: true, force: true }))
  const original = await writePackage({ showcaseDir: paths.showcaseDir })

  const traversal = makeManifest({
    video: { ...reference('scene-one.mp4', original.video), url: '/scene-showcase/../scene-one.mp4' },
    poster: reference('scene-one.png', original.poster),
    scene: reference('scene-one.json', original.scene, 'Editable showcase scene'),
  })
  await fs.writeFile(path.join(paths.showcaseDir, 'manifest.json'), JSON.stringify(traversal))
  await assert.rejects(() => prepareShowcase(paths), /URL relativa|relative|unsafe/i)

  await fs.writeFile(path.join(paths.showcaseDir, 'manifest.json'), JSON.stringify(original.manifest))
  await fs.rm(path.join(paths.showcaseDir, 'scene-one.mp4'))
  await fs.symlink(path.join(paths.directory, 'outside.mp4'), path.join(paths.showcaseDir, 'scene-one.mp4'))
  await fs.writeFile(path.join(paths.directory, 'outside.mp4'), original.video)
  await assert.rejects(() => prepareShowcase(paths), /non-symlink|symlink/i)
  await fs.rm(path.join(paths.showcaseDir, 'scene-one.mp4'))
  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.mp4'), original.video)

  await fs.mkdir(path.join(paths.uiDist, 'scene-showcase'))
  await assert.rejects(() => prepareShowcase(paths), /already exists|overwrite/i)

  await fs.rm(path.join(paths.uiDist, 'scene-showcase'), { recursive: true })
  await fs.mkdir(path.join(paths.showcaseDir, 'inputs'))
  await fs.writeFile(path.join(paths.showcaseDir, 'inputs', 'not-a-video.txt'), bytes('no'))
  await assert.rejects(() => prepareShowcase(paths), /safe JPG|basename|unsupported/i)
})

test('enforces finite canonical input count and per-file size', async t => {
  const paths = await fixture()
  t.after(() => fs.rm(paths.directory, { recursive: true, force: true }))
  await writePackage({ showcaseDir: paths.showcaseDir })
  await fs.mkdir(path.join(paths.showcaseDir, 'inputs'))
  const names = Array.from({ length: MAX_SHOWCASE_INPUTS + 1 }, (_, index) => `input-${index}.png`)
  await Promise.all(names.map(name => fs.writeFile(path.join(paths.showcaseDir, 'inputs', name), bytes(name))))
  await assert.rejects(() => prepareShowcase(paths), /more than 64|64 files/i)

  await fs.rm(path.join(paths.showcaseDir, 'inputs'), { recursive: true })
  await fs.mkdir(path.join(paths.showcaseDir, 'inputs'))
  await fs.writeFile(path.join(paths.showcaseDir, 'inputs', 'large.png'), Buffer.alloc(MAX_SHOWCASE_INPUT_FILE_BYTES + 1, 1))
  await assert.rejects(() => prepareShowcase(paths), /4 MiB|input limit/i)
})

test('requires every raster source to be a verified input and keeps the package silent', async t => {
  const paths = await fixture()
  t.after(() => fs.rm(paths.directory, { recursive: true, force: true }))
  const imageSource = '/api/v1/file/hero.png?workspace=procedural-showcase-v2'
  const scene = sceneBytes('Raster scene', 'provided_only')
  const parsedScene = JSON.parse(scene.toString())
  parsedScene.layers = [{ id: 'hero', name: 'hero', type: 'image', source: imageSource }]
  const rasterScene = bytes(JSON.stringify(parsedScene))
  await writePackage({ showcaseDir: paths.showcaseDir, scene: rasterScene, inputs: { 'hero.png': bytes('hero') } })
  await assert.doesNotReject(() => prepareShowcase(paths))

  await fs.rm(path.join(paths.showcaseDir, 'inputs'), { recursive: true })
  await assert.rejects(() => prepareShowcase(paths), /not present|verified inputs/i)

  await fs.mkdir(path.join(paths.showcaseDir, 'inputs'))
  await fs.writeFile(path.join(paths.showcaseDir, 'inputs', 'hero.png'), bytes('hero'))
  parsedScene.layers[0].source = 'https://evil.example/hero.png'
  const remoteScene = bytes(JSON.stringify(parsedScene))
  const remoteManifest = makeManifest({
    video: reference('scene-one.mp4', bytes('video')),
    poster: reference('scene-one.png', bytes('poster')),
    scene: reference('scene-one.json', remoteScene, 'Raster scene'),
  })
  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.json'), remoteScene)
  await fs.writeFile(path.join(paths.showcaseDir, 'manifest.json'), JSON.stringify(remoteManifest))
  await assert.rejects(() => prepareShowcase(paths), /local indexed|external|remote/i)

  parsedScene.layers[0].source = `/${String.fromCharCode(92)}evil.test/api/v1/file/hero.png`
  const backslashScene = bytes(JSON.stringify(parsedScene))
  const backslashManifest = makeManifest({
    video: reference('scene-one.mp4', bytes('video')),
    poster: reference('scene-one.png', bytes('poster')),
    scene: reference('scene-one.json', backslashScene, 'Raster scene'),
  })
  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.json'), backslashScene)
  await fs.writeFile(path.join(paths.showcaseDir, 'manifest.json'), JSON.stringify(backslashManifest))
  await assert.rejects(() => prepareShowcase(paths), /relative|external|unsafe/i)

  parsedScene.layers[0].source = imageSource
  parsedScene.audioTracks = [{ id: 'music' }]
  const audioScene = bytes(JSON.stringify(parsedScene))
  const audioManifest = makeManifest({
    video: reference('scene-one.mp4', bytes('video')),
    poster: reference('scene-one.png', bytes('poster')),
    scene: reference('scene-one.json', audioScene, 'Raster scene'),
  })
  await fs.writeFile(path.join(paths.showcaseDir, 'scene-one.json'), audioScene)
  await fs.writeFile(path.join(paths.showcaseDir, 'manifest.json'), JSON.stringify(audioManifest))
  await assert.rejects(() => prepareShowcase(paths), /silent|audioTracks/i)
})

test('accepts only the exact built-in compositor graphics', async t => {
  const paths = await fixture()
  t.after(() => fs.rm(paths.directory, { recursive: true, force: true }))
  const context = { duration: 4, bpm: 120, intensity: .5, bindings: {} }
  const kinds = ['beam', 'bolt', 'shield', 'burst', 'debris']
  const graphics = kinds.map(kind => effect(context, kind, `graphic-${kind}`, []).source)
  assert.deepEqual(graphics.map(isBuiltInShowcaseGraphic), [true, true, true, true, true], 'the broadside bolt too')
  const sceneObject = JSON.parse(sceneBytes('Built-in graphics').toString())
  sceneObject.layers = graphics.map((source, index) => ({
    ...effect(context, kinds[index], `graphic-${index}`, []),
    source,
  }))
  const scene = bytes(JSON.stringify(sceneObject))
  await writePackage({ showcaseDir: paths.showcaseDir, scene })
  await assert.doesNotReject(() => prepareShowcase(paths))

  const hostile = graphics[0].replace('%234deaff', '%234deafe')
  assert.equal(isBuiltInShowcaseGraphic(hostile), false)
  sceneObject.name = 'Hostile SVG'
  sceneObject.layers = [{ ...sceneObject.layers[0], source: hostile }]
  const hostileScene = bytes(JSON.stringify(sceneObject))
  await writePackage({ showcaseDir: paths.showcaseDir, scene: hostileScene })
  await assert.rejects(() => prepareShowcase(paths), /local indexed|external|data|verified/i)
})

test('allows only atmosphere effects whose source kind matches the 14 built-ins', async t => {
  const paths = await fixture()
  t.after(() => fs.rm(paths.directory, { recursive: true, force: true }))
  const kinds = ['rain', 'snow', 'dust', 'embers', 'fog', 'smoke', 'ash', 'fireflies', 'confetti', 'bokeh', 'sparkles', 'bubbles', 'speedlines', 'leaves']
  const context = { duration: 4, bpm: 120, intensity: .5, bindings: {} }
  const sceneObject = JSON.parse(sceneBytes('Atmosphere effects').toString())
  sceneObject.layers = kinds.map((kind, index) => ({
    ...atmosphere(context, kind),
    id: `atmosphere-${index}`,
    source: `maestro-effect:${kind}`,
  }))
  const scene = bytes(JSON.stringify(sceneObject))
  await writePackage({ showcaseDir: paths.showcaseDir, scene })
  await assert.doesNotReject(() => prepareShowcase(paths))

  sceneObject.name = 'Mismatched atmosphere effect'
  sceneObject.layers[0] = { ...sceneObject.layers[0], source: 'maestro-effect:snow' }
  const mismatch = bytes(JSON.stringify(sceneObject))
  await writePackage({ showcaseDir: paths.showcaseDir, scene: mismatch })
  await assert.rejects(() => prepareShowcase(paths), /unknown atmosphere|mismatched|external/i)
})

test('serves the staged manifest and registered inputs through the real sandbox', async t => {
  const paths = await fixture()
  const imageSource = '/api/v1/file/hero.png?workspace=procedural-showcase-v2'
  const sceneObject = JSON.parse(sceneBytes('HTTP scene').toString())
  sceneObject.layers = [{ id: 'hero', name: 'hero', type: 'image', source: imageSource }]
  const scene = bytes(JSON.stringify(sceneObject))
  await writePackage({ showcaseDir: paths.showcaseDir, scene, inputs: { 'hero.png': bytes('hero') } })
  const preparation = await prepareShowcase(paths)
  const server = await startReviewServer({ uiDist: paths.uiDist, outputDir: paths.outputDir, host: '127.0.0.1', port: 0 })
  t.after(async () => { await server.close(); await fs.rm(paths.directory, { recursive: true, force: true }) })
  await registerShowcaseInputs(server, preparation)

  const manifestResponse = await fetch(`${server.localOrigin}/scene-showcase/manifest.json`)
  assert.equal(manifestResponse.status, 200)
  assert.deepEqual(JSON.parse(await manifestResponse.text()), preparation.manifest)
  const inputResponse = await fetch(`${server.localOrigin}/api/v1/file/hero.png?workspace=default`)
  assert.equal(inputResponse.status, 200)
  assert.deepEqual(Buffer.from(await inputResponse.arrayBuffer()), bytes('hero'))
  const saved = await fetch(`${server.localOrigin}/api/v1/scenes`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ scene: sceneObject, preview: 'data:image/png;base64,iVBORw0KGgo=' }),
  })
  assert.equal(saved.status, 200)
})
