import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  applyDialogueTemplate,
  dialogueAliases,
  dialogueCard,
  DIALOGUE_CATEGORIES,
  DIALOGUE_TEMPLATE_IDS,
  isDialogueTemplateId,
} from '../src/features/scene3d/dialogueTemplates.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { filterScene3DTemplates, templateTraitsOf } from '../src/features/scene3d/templateFilters.ts'
import { validFraming } from '../src/features/scene3d/framing.ts'
import { SCENE3D_TEMPLATE_IDS, type Scene3DDocument, type Vec3 } from '../src/features/scene3d/types.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, '../src/features/scene3d/dialogueTemplates.ts'), 'utf8')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const length = (v: Vec3) => Math.hypot(v[0], v[1], v[2])
const slotsOf = (doc: Scene3DDocument) => Object.fromEntries(doc.slots.map(slot => [slot.id, slot]))
const gap = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[2] - b[2])

test('six dialogue shots are registered as cinema, translated in both locales and free of project assets', () => {
  assert.equal(DIALOGUE_TEMPLATE_IDS.length, 6)
  assert.doesNotMatch(SOURCE, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of DIALOGUE_TEMPLATE_IDS) {
    assert.ok(isDialogueTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    assert.ok(SCENE3D_TEMPLATES.some(item => item.id === id), id)
    assert.equal(TEMPLATE_CATEGORIES[id], 'cinema')
    assert.equal(DIALOGUE_CATEGORIES[id], 'cinema')
    for (const [locale, catalog] of [['en', en], ['es', es]] as const) {
      const card = dialogueCard(id, locale)
      assert.equal(catalog.template[id]?.title, card?.title, `${locale} ${id}`)
      assert.equal(catalog.template[id]?.description, card?.description, `${locale} ${id}`)
      assert.ok((card?.requirements.length ?? 0) >= 3, `${locale} ${id}`)
    }
    assert.notEqual(dialogueCard(id, 'es')?.title, dialogueCard(id, 'en')?.title, id)
  }
  assert.equal(applyDialogueTemplate('two-shot'), null)
  assert.equal(dialogueCard('two-shot'), undefined)
  const titleOf = (id: string) => id
  const phone = filterScene3DTemplates({ category: 'cinema', setting: 'all', query: 'phone', locale: 'en', titleOf })
  assert.ok(phone.some(item => item.id === 'dialogue-phone-split'))
  const dialogue = filterScene3DTemplates({ category: 'all', setting: 'all', query: 'dialogue', locale: 'es', titleOf })
  for (const id of DIALOGUE_TEMPLATE_IDS) assert.ok(dialogue.some(item => item.id === id), id)
})

test('every dialogue shot builds for two models, reopens through the parser and moves', () => {
  for (const id of DIALOGUE_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(doc.width, 1280)
    assert.equal(doc.height, 720)
    assert.ok(doc.duration >= 5 && doc.duration <= 8, id)
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(reopened, id)
    assert.deepEqual(reopened.camera, doc.camera, id)
    const pose = (scene: Scene3DDocument) => scene.slots.map(slot => [slot.id, slot.slot, slot.media, slot.position, slot.rotationY, slot.scale, slot.motion?.to])
    assert.deepEqual(pose(reopened), pose(doc), id)
    assert.equal(doc.slots.find(slot => slot.id === 'background')?.surface, 'environment', `${id}: a painted set can take over`)
    const subjects = doc.slots.filter(slot => slot.slot === 'subject_1' || slot.slot === 'subject_2')
    assert.equal(subjects.length, 2, id)
    assert.ok(subjects.every(slot => slot.media === 'model3d' && slot.scale === 1), `${id}: authored for models`)
    const framing = doc.camera.framing
    if (framing) {
      assert.ok(validFraming(framing), id)
      assert.ok(doc.slots.some(slot => slot.id === framing.targetSlot), id)
      assert.equal(framing.anchor, 'head', id)
      assert.equal(framing.track, 'rest', `${id}: the camera never follows a clip's pose`)
      assert.equal(framing.relativeToFacing, false, id)
      assert.notEqual(doc.camera.family, 'fixed', `${id}: the fixed family ignores framing`)
    }
    const traits = templateTraitsOf(id)
    assert.equal(traits.still, false, id)
    assert.ok(traits.moves.length > 0, `${id}: the camera moves`)
    assert.ok(traits.uses.includes('dialogue'), `${id}: ${traits.uses}`)
    assert.equal(traits.subjects, 2, id)
    assert.notEqual(traits.shot, 'far', id)
    assert.equal(traits.authoredFor, 'model', id)
    const vertical = applyDialogueTemplate(id, { orientation: 'vertical' })!
    assert.equal(vertical.width, 720)
    assert.equal(vertical.height, 1280)
    assert.equal(vertical.camera.frameFormat, 'portrait')
  }
  const prints = DIALOGUE_TEMPLATE_IDS.map(id => {
    const doc = applyScene3DTemplate(id)
    return JSON.stringify([doc.camera, doc.slots])
  })
  assert.equal(new Set(prints).size, DIALOGUE_TEMPLATE_IDS.length, 'distinct compositions')
})

test('the over-the-shoulder pair mirrors the eyelines and the camera sides at the same distance', () => {
  const a = applyScene3DTemplate('dialogue-ots-a')
  const b = applyScene3DTemplate('dialogue-ots-b')
  for (const slots of [slotsOf(a), slotsOf(b)]) {
    assert.ok(slots.subject_1.position[0] < 0 && slots.subject_2.position[0] > 0, 'subject_1 left, subject_2 right')
    assert.ok(slots.subject_1.rotationY > 0, 'subject_1 looks right')
    assert.equal(slots.subject_2.rotationY, -slots.subject_1.rotationY, 'subject_2 looks left')
    const apart = gap(slots.subject_1.position, slots.subject_2.position)
    assert.ok(apart >= 1.6 && apart <= 1.8, `${apart} m apart`)
  }
  assert.deepEqual(b.slots.map(slot => [slot.position, slot.rotationY]), a.slots.map(slot => [slot.position, slot.rotationY]), 'the same blocking')
  const fa = a.camera.framing!, fb = b.camera.framing!
  assert.equal(fa.targetSlot, 'subject_2', 'A frames the right face')
  assert.equal(fb.targetSlot, 'subject_1', 'B frames the left face')
  assert.ok(fa.from[0] < 0 && fb.from[0] > 0, 'A behind the left shoulder, B behind the right')
  assert.deepEqual(fb.from, [-fa.from[0], fa.from[1], fa.from[2]])
  assert.deepEqual(fb.to, [-fa.to[0], fa.to[1], fa.to[2]])
  assert.deepEqual(fb.lookFrom, fa.lookFrom)
  assert.ok(Math.abs(length(fa.from) - length(fb.from)) < 1e-9, 'matching distances')
  const ratio = length(fa.to) / length(fa.from)
  assert.ok(ratio > 0.93 && ratio < 0.95, `a push of about 6 %: ${ratio}`)
  for (const id of ['dialogue-ots-a', 'dialogue-ots-b'] as const) {
    const traits = templateTraitsOf(id)
    assert.ok(traits.moves.includes('push'), id)
    assert.ok(traits.shot === 'close' || traits.shot === 'medium', `${id}: ${traits.shot}`)
    assert.ok(traits.uses.includes('talk'), id)
  }
  assert.match(dialogueCard('dialogue-ots-a', 'en')!.description, /B for the other/)
  assert.match(dialogueCard('dialogue-ots-a', 'es')!.description, /B para el otro/)
})

test('the table, the triangle, the embrace and the phone split carry their props and framings', () => {
  const table = applyScene3DTemplate('dialogue-table')
  const prop = slotsOf(table).table
  assert.equal(prop.slot, 'prop')
  assert.equal(prop.media, 'model3d')
  assert.equal(prop.grounded, true)
  assert.ok(Math.abs(table.camera.eye[1] - 1.15) < 1e-9, 'seated eye height')
  assert.ok(templateTraitsOf('dialogue-table').moves.includes('slide'))
  assert.match(dialogueCard('dialogue-table', 'en')!.description, /sit_down/)
  assert.match(dialogueCard('dialogue-table', 'es')!.description, /sit_down/)

  const triangle = applyScene3DTemplate('dialogue-triangle')
  const third = slotsOf(triangle).person_3
  assert.equal(third.slot, 'prop')
  assert.equal(third.media, 'model3d')
  assert.equal(third.scale, 1)
  assert.equal(third.grounded, true)
  const tri = templateTraitsOf('dialogue-triangle')
  assert.equal(tri.subjects, 2)
  assert.equal(tri.props, 1)
  assert.ok(tri.moves.includes('arc'))
  assert.equal(tri.shot, 'wide', 'a master')

  const embrace = applyScene3DTemplate('dialogue-embrace')
  assert.ok(gap(slotsOf(embrace).subject_1.position, slotsOf(embrace).subject_2.position) < 0.7, 'close together')
  const hug = templateTraitsOf('dialogue-embrace')
  assert.equal(hug.shot, 'close')
  assert.ok(hug.moves.includes('push') && hug.moves.includes('arc'))
  assert.ok(!hug.uses.includes('reaction'), 'two figures are not a reaction')

  const phone = applyScene3DTemplate('dialogue-phone-split')
  const { subject_1, subject_2, divider } = slotsOf(phone)
  assert.equal(divider.slot, 'prop')
  assert.equal(divider.media, 'screen')
  assert.equal(divider.screen?.style, 'frameless')
  assert.ok(divider.screen!.width < 0.1 && divider.screen!.height > 2, 'a thin tall plane')
  assert.equal(divider.position[0], 0)
  assert.equal(subject_1.rotationY, 0)
  assert.equal(subject_2.rotationY, 0)
  assert.equal(subject_1.position[0], -subject_2.position[0])
  assert.ok(subject_2.position[0] >= 1.2, 'far apart')
  assert.equal(phone.camera.framing!.lookFrom![0], (subject_2.position[0] - subject_1.position[0]) / 2, 'the look sits between the two halves')
  assert.deepEqual(phone.camera.framing!.lookTo, phone.camera.framing!.lookFrom, 'a symmetric push')
  const split = templateTraitsOf('dialogue-phone-split')
  assert.equal(split.subjects, 2)
  assert.equal(split.screens, 1)
  assert.equal(split.props, 0)
  assert.deepEqual(split.moves, ['push'])
  assert.equal(split.shot, 'medium')
  assert.equal(phone.environment?.floorStyle, 'none')
  assert.equal(phone.screenBackdrop?.sfx.length, 0)
  assert.equal(phone.dressing, undefined)
})

test('slots bind by id, alias, id family or role, and ship empty', () => {
  for (const id of DIALOGUE_TEMPLATE_IDS) {
    assert.ok(applyDialogueTemplate(id)!.slots.every(slot => slot.sourceUrl === ''), id)
    const aliases = dialogueAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applyDialogueTemplate(id, { roles: { [lead]: '/api/v1/file/a.glb?workspace=w' } })!
    assert.equal(bound.slots.find(slot => slot.id === aliases[lead])?.sourceUrl, '/api/v1/file/a.glb?workspace=w', id)
    assert.equal(bound.slots.find(slot => slot.id === 'background')?.sourceUrl, '', id)
  }
  const triangle = applyDialogueTemplate('dialogue-triangle', { roles: { prop: '/api/v1/file/p.glb?workspace=w', person: '/api/v1/file/x.glb?workspace=w' } })!
  assert.equal(triangle.slots.find(slot => slot.id === 'person_3')?.sourceUrl, '/api/v1/file/x.glb?workspace=w', 'the id family wins over the role')
  const table = applyDialogueTemplate('dialogue-table', { roles: { subject_2: '/api/v1/file/b.glb?workspace=w', prop: '/api/v1/file/t.glb?workspace=w' } })!
  assert.equal(table.slots.find(slot => slot.id === 'subject_2')?.sourceUrl, '/api/v1/file/b.glb?workspace=w')
  assert.equal(table.slots.find(slot => slot.id === 'table')?.sourceUrl, '/api/v1/file/t.glb?workspace=w')
})
