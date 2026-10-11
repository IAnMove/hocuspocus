import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  applyGroupTemplate,
  groupAliases,
  groupCard,
  GROUP_CATEGORIES,
  GROUP_TEMPLATE_IDS,
  isGroupTemplateId,
} from '../src/features/scene3d/groupTemplates.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { filterScene3DTemplates, templateTraitsOf } from '../src/features/scene3d/templateFilters.ts'
import { validFraming } from '../src/features/scene3d/framing.ts'
import { SCENE3D_TEMPLATE_IDS, type Scene3DDocument, type Scene3DSlot } from '../src/features/scene3d/types.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, '../src/features/scene3d/groupTemplates.ts'), 'utf8')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const persons = (doc: Scene3DDocument) => doc.slots.filter(slot => /^person_\d+$/.test(slot.id))
const slotsOf = (doc: Scene3DDocument) => Object.fromEntries(doc.slots.map(slot => [slot.id, slot]))
const url = (name: string) => `/api/v1/file/${name}?workspace=w`

test('four group shots are registered, translated in both locales and free of project assets', () => {
  assert.equal(GROUP_TEMPLATE_IDS.length, 4)
  assert.doesNotMatch(SOURCE, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of GROUP_TEMPLATE_IDS) {
    assert.ok(isGroupTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    assert.ok(SCENE3D_TEMPLATES.some(item => item.id === id), id)
    assert.equal(TEMPLATE_CATEGORIES[id], id === 'group-audience' ? 'music' : 'cinema')
    assert.equal(GROUP_CATEGORIES[id], TEMPLATE_CATEGORIES[id])
    for (const [locale, catalog] of [['en', en], ['es', es]] as const) {
      const card = groupCard(id, locale)
      assert.equal(catalog.template[id]?.title, card?.title, `${locale} ${id}`)
      assert.equal(catalog.template[id]?.description, card?.description, `${locale} ${id}`)
      assert.ok((card?.requirements.length ?? 0) >= 3, `${locale} ${id}`)
    }
    assert.notEqual(groupCard(id, 'es')?.title, groupCard(id, 'en')?.title, id)
  }
  assert.equal(applyGroupTemplate('wide-tableau'), null)
  assert.equal(groupCard('wide-tableau'), undefined)
  const crowd = filterScene3DTemplates({ category: 'music', setting: 'all', query: 'crowd', locale: 'es', titleOf: id => id })
  assert.ok(crowd.some(item => item.id === 'group-audience'))
})

test('every group shot is a wide figure shot of models that reopens, moves and binds person props by family', () => {
  for (const id of GROUP_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(doc.width, 1280)
    assert.equal(doc.height, 720)
    assert.ok(doc.duration >= 5 && doc.duration <= 8, id)
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(reopened, id)
    assert.deepEqual(reopened.camera, doc.camera, id)
    const pose = (scene: Scene3DDocument) => scene.slots.map(slot => [slot.id, slot.slot, slot.media, slot.position, slot.rotationY, slot.scale, Boolean(slot.grounded)])
    assert.deepEqual(pose(reopened), pose(doc), id)
    assert.equal(doc.slots.find(slot => slot.id === 'background')?.surface, 'environment', id)
    assert.ok(doc.slots.filter(slot => slot.slot === 'subject_1' || slot.slot === 'subject_2').every(slot => slot.media === 'model3d'), `${id}: authored for models`)
    for (const slot of persons(doc)) {
      assert.equal(slot.slot, 'prop', slot.id)
      assert.equal(slot.media, 'model3d', slot.id)
      assert.equal(slot.scale, 1, slot.id)
      assert.equal(slot.grounded, true, slot.id)
      assert.match(groupCard(id, 'en')!.description, /person_/, `${id}: the copy lists the person slots`)
      assert.match(groupCard(id, 'es')!.description, /person_/, `${id}: the copy lists the person slots`)
    }
    const framing = doc.camera.framing!
    assert.ok(validFraming(framing), id)
    assert.equal(framing.targetSlot, 'subject_1', id)
    assert.equal(framing.anchor, 'head', id)
    assert.equal(framing.track, 'rest', `${id}: the camera never follows a clip's pose`)
    assert.equal(framing.relativeToFacing, false, id)
    const traits = templateTraitsOf(id)
    assert.equal(traits.shot, 'wide', `${id}: ${traits.shot}`)
    assert.ok(traits.uses.includes('figure'), `${id}: ${traits.uses}`)
    assert.equal(traits.still, false, id)
    assert.ok(traits.moves.length > 0, id)
    assert.equal(traits.authoredFor, 'model', id)
    if (persons(doc).length) {
      const bound = applyGroupTemplate(id, { roles: { person: url('extra.glb') } })!
      assert.ok(persons(bound).every(slot => slot.sourceUrl === url('extra.glb')), `${id}: one GLB fills every person_N`)
      assert.equal(bound.slots.find(slot => slot.id === 'subject_1')?.sourceUrl, '', id)
    }
    const lead = Object.keys(groupAliases(id))[0]
    const byAlias = applyGroupTemplate(id, { roles: { [lead]: url('lead.glb') } })!
    assert.equal(byAlias.slots.find(slot => slot.id === 'subject_1')?.sourceUrl, url('lead.glb'), id)
    const vertical = applyGroupTemplate(id, { orientation: 'vertical' })!
    assert.equal(vertical.width, 720)
    assert.equal(vertical.height, 1280)
    assert.equal(vertical.camera.frameFormat, 'portrait')
  }
  const prints = GROUP_TEMPLATE_IDS.map(id => {
    const doc = applyScene3DTemplate(id)
    return JSON.stringify([doc.camera, doc.slots])
  })
  assert.equal(new Set(prints).size, GROUP_TEMPLATE_IDS.length, 'distinct blockings')
})

test('the arc, the line, the audience and the circle carry the right counts and blockings', () => {
  const arc = applyScene3DTemplate('group-arc-five')
  assert.deepEqual(persons(arc).map(slot => slot.id), ['person_2', 'person_3', 'person_4', 'person_5'])
  const front = slotsOf(arc).subject_1
  assert.ok(persons(arc).every(slot => slot.position[2] < front.position[2]), 'the four stand behind the lead')
  assert.equal(templateTraitsOf('group-arc-five').props, 4)
  assert.equal(templateTraitsOf('group-arc-five').subjects, 1)
  assert.deepEqual(templateTraitsOf('group-arc-five').moves, ['push'])

  const line = applyScene3DTemplate('group-line-four')
  const figures = line.slots.filter(slot => slot.media === 'model3d')
  assert.deepEqual(figures.map(slot => slot.id), ['person_3', 'subject_1', 'subject_2', 'person_4'], 'ordered left to right')
  assert.ok(figures.every((slot, index) => index === 0 || slot.position[0] > figures[index - 1].position[0]))
  assert.ok(figures.every(slot => slot.position[2] === figures[0].position[2]), 'one line')
  const truck = line.camera.framing!
  assert.equal(truck.lookTo![0] - truck.lookFrom![0], truck.to[0] - truck.from[0], 'the look slides with the eye')
  assert.deepEqual(templateTraitsOf('group-line-four').moves, ['slide'])
  assert.equal(templateTraitsOf('group-line-four').props, 2)
  assert.equal(templateTraitsOf('group-line-four').subjects, 2)

  const audience = applyScene3DTemplate('group-audience')
  assert.equal(audience.environment?.platform, true, 'a low platform')
  const performer = slotsOf(audience).subject_1
  assert.ok(performer.position[1] > 0.2 && performer.grounded, 'the performer stands on the platform')
  const crowd = audience.slots.filter(slot => /^crowd_\d+$/.test(slot.id))
  assert.equal(crowd.length, 6)
  for (const slot of crowd) {
    assert.equal(slot.slot, 'prop', slot.id)
    assert.equal(slot.media, 'image', slot.id)
    assert.equal(slot.surface, 'cutout', slot.id)
    assert.equal(slot.rotationY, Math.PI, `${slot.id} faces the stage`)
    assert.ok(slot.position[2] > 0 && slot.position[2] < audience.camera.framing!.from[2], `${slot.id} stands between the camera and the stage`)
  }
  const crowdTraits = templateTraitsOf('group-audience')
  assert.equal(crowdTraits.props, 6)
  assert.ok(crowdTraits.uses.includes('music') && crowdTraits.uses.includes('figure'))
  assert.ok(crowdTraits.moves.includes('rise'), 'a crane up')
  for (const locale of ['en', 'es'] as const) {
    const card = groupCard('group-audience', locale)!
    assert.match(card.description, /crowd/, locale)
    assert.match(card.requirements.join(' '), /crowd/, locale)
  }
  const filled = applyGroupTemplate('group-audience', { roles: { crowd: url('back.png') } })!
  assert.ok(filled.slots.filter(slot => slot.id.startsWith('crowd_')).every(slot => slot.sourceUrl === url('back.png')), 'one picture fills the crowd')

  const circle = applyScene3DTemplate('group-circle')
  const ring = circle.slots.filter(slot => slot.media === 'model3d')
  assert.deepEqual(ring.map(slot => slot.id), ['subject_1', 'subject_2', 'person_3', 'person_4', 'person_5'])
  const facing = (slot: Scene3DSlot) => Math.atan2(-slot.position[0], -slot.position[2])
  for (const slot of ring) {
    assert.ok(Math.abs(Math.hypot(slot.position[0], slot.position[2]) - 1.5) < 0.02, `${slot.id} on the circle`)
    assert.ok(Math.abs(slot.rotationY - facing(slot)) < 0.02, `${slot.id} faces the centre`)
  }
  assert.ok(circle.camera.framing!.from[1] > 2, 'the camera is above')
  assert.deepEqual(templateTraitsOf('group-circle').moves, ['arc'])
  assert.equal(templateTraitsOf('group-circle').props, 3)
  assert.equal(templateTraitsOf('group-circle').subjects, 2)
})
