import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  SPEED_CATEGORIES,
  SPEED_TEMPLATE_IDS,
  applySpeedTemplate,
  isSpeedTemplateId,
  speedAliases,
  speedAuthoredCueKinds,
  speedCard,
} from '../src/features/scene3d/speedTemplates.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { templateTraits } from '../src/features/scene3d/templateTraits.ts'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import { FX_CATALOG } from '../src/features/sceneFx/types.ts'
import { WORLD_SFX_KINDS } from '../src/features/sceneFx/world.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, '../src/features/scene3d/speedTemplates.ts'), 'utf8')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const SCREEN_KINDS = new Set(FX_CATALOG.map(item => item.id))
const traitsOf = (id: string) => {
  const doc = applyScene3DTemplate(id as (typeof SCENE3D_TEMPLATE_IDS)[number])
  return templateTraits(doc, { category: TEMPLATE_CATEGORIES[doc.templateId], family: doc.camera.family })
}

test('five speed shots are registered under action, translated and free of project assets', () => {
  assert.equal(SPEED_TEMPLATE_IDS.length, 5)
  assert.doesNotMatch(SOURCE, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of SPEED_TEMPLATE_IDS) {
    assert.ok(isSpeedTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    const row = SCENE3D_TEMPLATES.find(item => item.id === id)
    assert.ok(row, id)
    assert.equal(row.tags, undefined, `${id}: speed shots carry no tag`)
    assert.equal(TEMPLATE_CATEGORIES[id], 'action')
    assert.equal(SPEED_CATEGORIES[id], 'action')
    assert.ok(en.template[id]?.title && en.template[id]?.description, id)
    assert.ok(es.template[id]?.title && es.template[id]?.description, id)
    assert.equal(en.template[id].title, speedCard(id, 'en')?.title)
    assert.equal(es.template[id].title, speedCard(id, 'es')?.title)
    assert.ok((speedCard(id, 'en')?.requirements.length ?? 0) >= 2, id)
  }
  assert.equal(applySpeedTemplate('two-shot'), null)
  assert.match(speedCard('speed-run-toward', 'en')!.description, /clip: run/)
  assert.match(speedCard('speed-run-toward', 'es')!.description, /clip: run/)
})

test('every speed shot is a 16:9 shot for GLB subjects over an environment plate and reopens unchanged', () => {
  for (const id of SPEED_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(doc.width, 1920)
    assert.equal(doc.height, 1080)
    assert.equal(doc.fps, 24)
    assert.ok(doc.duration >= 5 && doc.duration <= 8, `${id}: ${doc.duration}s`)
    assert.ok(doc.screenBackdrop, id)
    const background = doc.slots.find(slot => slot.slot === 'background')
    assert.equal(background?.media, 'image', id)
    assert.equal(background?.surface, 'environment', `${id}: the plate sits under the backdrop effects`)
    for (const slot of doc.slots.filter(item => item.slot === 'subject_1' || item.slot === 'subject_2' || item.slot === 'prop')) {
      assert.equal(slot.media, 'model3d', `${id}: ${slot.id}`)
    }
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(reopened, id)
    assert.deepEqual(reopened.camera, doc.camera)
    // The parser spells out optional slot fields as undefined; the authored placement, media and motion must come back as written.
    const placed = (slots: typeof doc.slots) => JSON.parse(JSON.stringify(slots.map(({ id, slot, media, surface, position, rotationY, scale, motion }) => ({ id, slot, media, surface, position, rotationY, scale, motion }))))
    assert.deepEqual(placed(reopened.slots), placed(doc.slots))
    assert.deepEqual(reopened.screenBackdrop, doc.screenBackdrop)
    assert.deepEqual(reopened.sfx, doc.sfx)
    assert.equal(reopened.worldSfx?.length ?? 0, doc.worldSfx?.length ?? 0)
    assert.equal(reopened.dressing, doc.dressing)
    const framing = doc.camera.framing
    if (framing) {
      assert.ok(doc.slots.some(slot => slot.id === framing.targetSlot), id)
      assert.equal(framing.relativeToFacing, false, id)
      assert.notEqual(doc.camera.family, 'fixed', `${id}: the fixed family ignores framing`)
    }
    const vertical = applySpeedTemplate(id, { orientation: 'vertical' })!
    assert.equal(vertical.width, 1080)
    assert.equal(vertical.height, 1920)
    assert.equal(vertical.camera.frameFormat, 'portrait')
  }
})

test('speed shots are distinct compositions', () => {
  const prints = SPEED_TEMPLATE_IDS.map(id => {
    const doc = applyScene3DTemplate(id)
    return JSON.stringify([doc.camera, doc.slots, doc.dressing, doc.sfx])
  })
  assert.equal(new Set(prints).size, SPEED_TEMPLATE_IDS.length)
})

test('speed shots use only catalogued effects and keep every cue inside the shot', () => {
  for (const id of SPEED_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    const authored = speedAuthoredCueKinds(id)
    for (const kind of [...authored.sfx, ...authored.backdrop]) assert.ok(SCREEN_KINDS.has(kind), `${id}: ${kind}`)
    for (const kind of authored.worldSfx) assert.ok(WORLD_SFX_KINDS.includes(kind), `${id}: ${kind}`)
    assert.equal(doc.sfx?.length ?? 0, authored.sfx.length, `${id}: no screen cue was dropped`)
    assert.equal(doc.worldSfx?.length ?? 0, authored.worldSfx.length, `${id}: no world cue was dropped`)
    assert.equal(doc.screenBackdrop?.sfx.length, authored.backdrop.length, `${id}: no backdrop cue was dropped`)
    const cues = [...(doc.sfx ?? []), ...(doc.worldSfx ?? []), ...(doc.screenBackdrop?.sfx ?? [])]
    for (const cue of cues) assert.ok(cue.start >= 0 && cue.end <= doc.duration + 1e-9, `${id}: ${cue.id}`)
    for (const shake of doc.camera.shake ?? []) assert.ok(shake.start >= 0 && shake.end <= doc.duration + 1e-9, `${id}: shake`)
    for (const cue of doc.worldSfx ?? []) if (cue.anchor) assert.ok(doc.slots.some(slot => slot.id === cue.anchor!.slotId), `${id}: ${cue.id} anchors to a slot`)
  }
})

test('every speed shot moves: a travelling subject, or a push or slide, with the moves it was authored with', () => {
  for (const id of SPEED_TEMPLATE_IDS) {
    const traits = traitsOf(id)
    assert.equal(traits.still, false, id)
    assert.ok(traits.uses.includes('action'), `${id}: ${traits.uses}`)
    assert.ok(traits.moving.includes('camera'), `${id}: the camera moves`)
    assert.equal(traits.authoredFor, 'model', id)
    const travels = applyScene3DTemplate(id).slots.some(slot => (slot.slot === 'subject_1' || slot.slot === 'subject_2') && slot.motion)
    assert.ok(travels || traits.moves.includes('push') || traits.moves.includes('slide'), `${id}: ${traits.moves}`)
  }
  const run = traitsOf('speed-run-toward')
  assert.deepEqual(run.moves, ['push'])
  assert.ok(run.moving.includes('backdrop') && run.moving.includes('effects'))
  assert.equal(run.floor, 'none')
  const chase = traitsOf('speed-foot-chase')
  assert.equal(chase.subjects, 2)
  assert.ok(chase.moves.includes('track') && chase.moves.includes('shake'), `${chase.moves}`)
  assert.ok(chase.moving.includes('subjects'))
  const flyby = traitsOf('speed-flyby')
  assert.deepEqual(flyby.moves, ['slide'])
  assert.ok(flyby.moving.includes('props'))
  assert.equal(flyby.props, 1)
  const rush = traitsOf('speed-rush-lines')
  assert.deepEqual(rush.moves, ['push', 'shake'])
  assert.equal(rush.shot, 'close')
  const dash = traitsOf('speed-side-dash')
  assert.deepEqual(dash.moves, ['slide', 'track'])
  assert.ok(dash.moving.includes('subjects'))
})

test('the treadmill runner stands still on a low lens while the chase, the dash and the fly-by cross the set', () => {
  const run = applyScene3DTemplate('speed-run-toward')
  assert.equal(run.dressing, 'treadmill')
  const runner = run.slots.find(slot => slot.slot === 'subject_1')!
  assert.equal(runner.motion, undefined, 'the clip runs on the spot')
  assert.equal(runner.clip, null, 'the template bakes no clip; the cast brings clip: run')
  assert.ok(run.camera.framing!.from[1] < -0.8, 'the lens sits well below the head')
  assert.ok(run.screenBackdrop!.sfx.every(cue => cue.kind === 'speedlines' && cue.intensity < 1), 'faint lines')

  const chase = applyScene3DTemplate('speed-foot-chase')
  assert.equal(chase.dressing, 'chase-street')
  assert.equal(chase.camera.family, 'follow')
  const [runnerSlot, chaserSlot] = ['subject_1', 'subject_2'].map(role => chase.slots.find(slot => slot.slot === role)!)
  for (const slot of [runnerSlot, chaserSlot]) {
    assert.ok(slot.motion?.faceTravel && slot.motion.to[0] > slot.position[0] + 10, `${slot.id} crosses the set`)
    assert.equal(slot.motion!.to[2], slot.position[2], `${slot.id} keeps its lane`)
  }
  assert.notEqual(runnerSlot.position[2], chaserSlot.position[2], 'parallel lanes')
  assert.ok(chase.camera.shake!.every(window => window.amplitude <= 0.04), 'a light shake')

  const flyby = applyScene3DTemplate('speed-flyby')
  const craft = flyby.slots.find(slot => slot.slot === 'prop')!
  assert.equal(craft.position[0], -16)
  assert.equal(craft.motion!.to[0], 16)
  assert.equal(craft.motion!.faceTravel, true)
  assert.ok(Math.abs(slotPoseAtTime(craft, 3, 6).position[0]) < 1e-9, 'centred at mid-shot')
  const framing = flyby.camera.framing!
  assert.ok(framing.lookFrom![0] < -3 && framing.lookTo![0] > 3, 'the look pans with the craft')

  const dash = applyScene3DTemplate('speed-side-dash')
  assert.equal(dash.camera.family, 'side')
  const dasher = dash.slots.find(slot => slot.slot === 'subject_1')!
  assert.ok(dasher.motion?.faceTravel && dasher.motion.to[0] - dasher.position[0] >= 10)
  assert.ok(Math.abs(dash.camera.framing!.to[0] - dash.camera.framing!.from[0]) >= 3, 'a fast slide across the figure')
})

test('model slots bind by id, alias or role', () => {
  for (const id of SPEED_TEMPLATE_IDS) {
    const aliases = speedAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applySpeedTemplate(id, { roles: { [lead]: '/api/v1/file/a.glb?workspace=w' } })!
    assert.ok(bound.slots.some(slot => slot.sourceUrl === '/api/v1/file/a.glb?workspace=w'), id)
    const byRole = applySpeedTemplate(id, { roles: { background: '/api/v1/file/set.png?workspace=w' } })!
    assert.equal(byRole.slots.find(slot => slot.slot === 'background')?.sourceUrl, '/api/v1/file/set.png?workspace=w', id)
  }
  const chase = applySpeedTemplate('speed-foot-chase', { roles: { runner: '/api/v1/file/r.glb?workspace=w', chaser: '/api/v1/file/c.glb?workspace=w' } })!
  assert.equal(chase.slots.find(slot => slot.id === 'runner')?.sourceUrl, '/api/v1/file/r.glb?workspace=w')
  assert.equal(chase.slots.find(slot => slot.id === 'chaser')?.sourceUrl, '/api/v1/file/c.glb?workspace=w')
})
