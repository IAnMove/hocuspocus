import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { parseArgs } from '../scripts/sceneTemplateReview/args.mjs'
import { assetKind, bindingsFor, canonicalSlot, cardAssets, readAssetPlan, selectCards, stageAssets } from '../scripts/sceneTemplateReview/assets.mjs'
import { contactSheet, indexRow, sheetTimes, writeReviewIndex } from '../scripts/sceneTemplateReview/outputs.mjs'
import { MAX_MEDIA_INPUT_FILE_BYTES, startReviewServer } from '../scripts/sceneTemplateReview/server.mjs'
import * as catalog from '../src/features/sceneTemplates/catalog.ts'
import { compileCandidateScene } from '../src/features/sceneTemplates/compile.ts'

const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'sceneTemplateReview')
const PLAN = path.join(FIXTURES, 'assets.json')
const solo = { id: 'solo', family: 'music', slots: [
  { id: 'subject_1', required: true, kinds: ['image', 'model3d'] },
  { id: 'background', required: true, kinds: ['image', 'video'] },
  { id: 'foreground', required: false, kinds: ['image'] },
] }
const legacy = { id: 'cinema-two-shot', family: 'cinema', slots: [
  { id: 'hero', required: true, kinds: ['image'] },
  { id: 'plate', required: true, kinds: ['image'] },
  { id: 'prop', required: true, kinds: ['image'] },
] }

async function writePlan(value) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hocus-review-plan-'))
  const file = path.join(directory, 'plan.json')
  await fs.writeFile(file, JSON.stringify(value))
  return file
}

async function sandbox() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hocus-review-assets-'))
  await fs.mkdir(path.join(directory, 'ui'))
  await fs.writeFile(path.join(directory, 'ui', 'index.html'), '<!doctype html><title>fixture</title>')
  return { directory, server: await startReviewServer({ uiDist: path.join(directory, 'ui'), outputDir: directory }) }
}

test('old slot names become the contract names once, prop by what the card holds', () => {
  assert.equal(canonicalSlot('cinema-establishing', 'hero'), 'subject_1')
  assert.equal(canonicalSlot('music-pulse', 'plate'), 'background')
  assert.equal(canonicalSlot('cinema-two-shot', 'prop'), 'subject_2')
  assert.equal(canonicalSlot('music-duet', 'prop'), 'subject_2')
  assert.equal(canonicalSlot('space-chase', 'prop'), 'prop_1')
  assert.equal(canonicalSlot('music-orbit', 'prop_2'), 'prop_2')
  assert.deepEqual(['a.PNG', 'b.jpeg', 'c.webp', 'd.glb', 'e.mp4', 'f.webm', 'g.svg'].map(assetKind), ['image', 'image', 'image', 'model3d', 'video', 'video', undefined])
})

test('a plan layers default, family and card, with controls, and resolves files next to the plan', async () => {
  const plan = await readAssetPlan(PLAN)
  const music = cardAssets(plan, 'music-pulse', { ...solo, id: 'music-pulse' })
  assert.deepEqual(music.assets.map(asset => [asset.slot, path.basename(asset.file), asset.type]), [['subject_1', 'subject.png', 'image'], ['background', 'plate.jpg', 'image']])
  assert.equal(path.dirname(music.assets[0].file), FIXTURES)
  assert.deepEqual(music.controls, { bpm: 96 })
  const space = cardAssets(plan, 'space-cruise', { ...solo, id: 'space-cruise', family: 'space' })
  assert.deepEqual(space.assets.map(asset => [path.basename(asset.file), asset.type]), [['ship.glb', 'model3d'], ['space.jpg', 'image']])
  const twoShot = cardAssets(plan, 'cinema-two-shot', legacy)
  assert.deepEqual(twoShot.assets.map(asset => [asset.slot, path.basename(asset.file)]), [['hero', 'subject.png'], ['plate', 'plate.jpg'], ['prop', 'partner.png']])
  const flat = await readAssetPlan(await writePlan({ hero: '/x/hero.png', plate: '/x/plate.webm' }))
  assert.deepEqual(cardAssets(flat, 'solo', solo).assets.map(asset => [asset.slot, asset.type]), [['subject_1', 'image'], ['background', 'video']])
})

test('a plan says what is wrong before anything renders', async () => {
  await assert.rejects(async () => readAssetPlan(await writePlan({ default: {}, extras: {} })), /unknown section/)
  await assert.rejects(async () => readAssetPlan(await writePlan({ hero: 'a.png', subject_1: 'b.png' })), /slot_alias_conflict/)
  await assert.rejects(async () => readAssetPlan(await writePlan({ villain: 'a.png' })), /unknown slot “villain”/)
  await assert.rejects(async () => readAssetPlan(await writePlan({ cards: { x: { controls: 3 } } })), /controls must be an object/)
  const plan = await readAssetPlan(await writePlan({ default: { subject_1: 'a.png' }, cards: { solo: { prop_1: 'p.png' } } }))
  assert.throws(() => cardAssets(plan, 'solo', solo), /has no slot prop_1/)
  const missing = await readAssetPlan(await writePlan({ subject_1: 'a.png' }))
  assert.throws(() => cardAssets(missing, 'solo', solo), /required slot\(s\) background/)
  const wrong = await readAssetPlan(await writePlan({ subject_1: 'a.png', background: 'b.png', foreground: 'f.glb' }))
  assert.throws(() => cardAssets(wrong, 'solo', solo), /foreground takes image, not model3d/)
})

test('cards come from the catalog at run time: every listed card by default, any resolvable ID on request', () => {
  assert.deepEqual(selectCards(catalog).map(card => card.id), catalog.ALL_SCENE_TEMPLATES.map(template => template.id))
  const first = catalog.ALL_SCENE_TEMPLATES[0].id
  assert.deepEqual(selectCards(catalog, [first, first]).map(card => card.id), [first])
  assert.throws(() => selectCards(catalog, ['no-such-card']), /Unknown scene template ID\(s\): no-such-card/)
})

test('the fixture plan compiles every catalog card through the public compile function', async () => {
  const plan = await readAssetPlan(PLAN)
  const served = new Map()
  for (const card of selectCards(catalog)) {
    const { assets, controls } = cardAssets(plan, card.id, card.template)
    for (const asset of assets) served.set(asset.file, { url: `/api/v1/file/${path.basename(asset.file)}?workspace=default` })
    const scene = compileCandidateScene(card.id, bindingsFor(assets, served), controls)
    const sources = scene.layers.map(layer => layer.source)
    // A slot that a control switches on (music-pinball's prop_1 with bouncer: prop) stays off at the card's defaults.
    const switched = new Set((card.template.slots ?? []).filter(slot => slot.requiredWhen).map(slot => slot.id))
    for (const asset of assets.filter(asset => !switched.has(asset.slot))) {
      assert.ok(sources.includes(served.get(asset.file).url), `${card.id} paints ${asset.slot}`)
    }
  }
})

test('staged assets are copied once, served by the sandbox byte for byte, and GLB and video names are accepted', async () => {
  const { directory, server } = await sandbox()
  try {
    const subject = path.join(FIXTURES, 'subject.png')
    const copy = path.join(directory, 'same-subject.png')
    await fs.copyFile(subject, copy)
    const staged = await stageAssets(server, [subject, copy, path.join(FIXTURES, 'plate.jpg')])
    assert.equal(staged.get(subject).name, staged.get(copy).name, 'the same bytes are one input')
    assert.match(staged.get(subject).name, /^asset-[0-9a-f]{16}\.png$/)
    const response = await fetch(`${server.localOrigin}${staged.get(subject).url}`)
    assert.equal(response.headers.get('content-type'), 'image/png')
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), await fs.readFile(subject))
    const status = await (await fetch(`${server.localOrigin}/api/v1/scene-template-review/status`)).json()
    assert.equal(status.inputCount, 2)
    await fs.writeFile(path.join(server.inputsDir, 'ship.glb'), Buffer.from('glTF'))
    await fs.writeFile(path.join(server.inputsDir, 'loop.webm'), Buffer.from('webm'))
    assert.equal((await server.registerInput('ship.glb')).name, 'ship.glb')
    const loop = await server.registerInput('loop.webm')
    assert.equal((await fetch(`${server.localOrigin}${loop.url}`)).headers.get('content-type'), 'video/webm')
    assert.equal(MAX_MEDIA_INPUT_FILE_BYTES, 32 * 1024 * 1024)
    await assert.rejects(() => stageAssets(server, [path.join(FIXTURES, 'missing.png')]), /not a regular file/)
  } finally {
    await server.close()
  }
})

test('the CLI takes --assets only with --render and resolves it from where npm was started', () => {
  const options = parseArgs(['--render', '--assets', 'plans/real.json', 'music-pulse'], { INIT_CWD: '/work/repo' })
  assert.equal(options.assetsFile, '/work/repo/plans/real.json')
  assert.deepEqual(options.templateIds, ['music-pulse'])
  assert.equal(parseArgs(['--render', '--assets=/abs/plan.json'], {}).assetsFile, '/abs/plan.json')
  assert.throws(() => parseArgs(['--assets', 'plan.json'], {}), /--assets requires --render/)
  assert.throws(() => parseArgs(['--render', '--assets'], {}), /needs a value/)
  assert.equal(parseArgs(['--render'], {}).assetsFile, null)
})

test('review.json rows name the files, the duration and the assets; the sheet takes frames from the middle of slices', async () => {
  assert.deepEqual(sheetTimes(6), [0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
  const row = indexRow({ id: 'music-stage', scene: { narrative: { templateId: 'music-pulse' } }, duration: 4.02, variant: 'assets',
    controls: { camera: 'sweep' }, assets: [{ slot: 'subject_1', type: 'image', file: '/x/subject.png', sha256: 'ab' }] })
  assert.deepEqual(row, { id: 'music-stage', templateId: 'music-pulse', status: 'rendered-not-approved', file: 'music-stage.mp4', sheet: 'music-stage.sheet.png',
    poster: 'music-stage.png', metadata: 'music-stage.json', duration: 4.02, variant: 'assets', controls: { camera: 'sweep' },
    assets: [{ slot: 'subject_1', type: 'image', file: '/x/subject.png', sha256: 'ab' }] })
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hocus-review-index-'))
  const file = await writeReviewIndex(directory, { assetsFile: PLAN, source: { headSha: 'x' }, rows: [row], failures: [] })
  const index = JSON.parse(await fs.readFile(file, 'utf8'))
  assert.equal(index.status, 'rendered-not-approved')
  assert.deepEqual(index.cards, [row])
  await assert.rejects(() => writeReviewIndex(directory, { rows: [], failures: [] }), /EEXIST/)
})

test('the contact sheet is a 3x2 tile of the rendered video', { skip: !hasFfmpeg() && 'ffmpeg is not on PATH' }, async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'hocus-review-sheet-'))
  const video = path.join(directory, 'clip.mp4')
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=30:duration=2', '-pix_fmt', 'yuv420p', video])
  const sheet = path.join(directory, 'clip.sheet.png')
  contactSheet(video, sheet, 2)
  const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_streams', '-of', 'json', sheet], { encoding: 'utf8' }))
  assert.equal(probe.streams[0].width, 426 * 3)
  assert.equal(probe.streams[0].height, 240 * 2)
})

function hasFfmpeg() {
  try {
    execFileSync('ffmpeg', ['-version'], { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}
