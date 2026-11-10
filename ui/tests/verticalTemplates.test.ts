import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  applyVerticalTemplate,
  isVerticalTemplateId,
  verticalAliases,
  verticalCard,
  VERTICAL_CATEGORIES,
  VERTICAL_TEMPLATE_IDS,
} from '../src/features/scene3d/verticalTemplates.ts'
import { VERTICAL_DIALOGUE_IDS, VERTICAL_TALK_IDS } from '../src/features/scene3d/verticalTemplateIds.ts'
import { applyScene3DTemplate, remountScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { filterScene3DTemplates, templateTraitsOf } from '../src/features/scene3d/templateFilters.ts'
import { framingPose, validFraming } from '../src/features/scene3d/framing.ts'
import { projectPoint } from '../src/features/scene3d/camera.ts'
import { SCENE3D_TEMPLATE_IDS, type Scene3DDocument, type Scene3DSlot, type Vec3 } from '../src/features/scene3d/types.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCES = ['verticalTemplates.ts', 'verticalDialogueSpecs.ts', 'verticalTalkSpecs.ts']
  .map(name => readFileSync(join(HERE, '../src/features/scene3d', name), 'utf8')).join('\n')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const slotsOf = (doc: Scene3DDocument) => Object.fromEntries(doc.slots.map(slot => [slot.id, slot]))
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const mirror = (v: Vec3): Vec3 => [-v[0], v[1], v[2]]
const isDialogue = (id: string) => (VERTICAL_DIALOGUE_IDS as readonly string[]).includes(id)

/** A rigged 1.7 m figure at rest, measured on the CPU renders of this pack: the head anchor, the eyes 8.5 cm above it,
 * the crown 23 cm above it and the chin 2 cm under it. */
const ANCHOR = 1.48
const HEAD = { eye: 0.085, crown: 0.23, chin: -0.02 }
/** The seated card frames the feet; a sit_down hold puts the head about here. */
const SEATED_ANCHOR = 1.1

type Frame = { eye: Vec3; look: Vec3; fov: number }
function framesOf(doc: Scene3DDocument): Frame[] {
  const framing = doc.camera.framing!
  const target = doc.slots.find(slot => slot.id === framing.targetSlot)!
  const anchor: Vec3 = framing.anchor === 'feet' ? [...target.position] as Vec3 : add(target.position, [0, ANCHOR, 0])
  return [0, doc.duration / 2, doc.duration].map(seconds => ({ ...framingPose(framing, anchor, target, seconds, doc.duration), fov: doc.camera.fov }))
}
/** Where a head point of a slot lands in the 9:16 frame (x and y from the top-left, 0 to 1). */
function headAt(doc: Scene3DDocument, slot: Scene3DSlot, frame: Frame, part: keyof typeof HEAD) {
  const seated = doc.camera.framing!.anchor === 'feet'
  const point = add(slot.position, [0, (seated ? SEATED_ANCHOR : ANCHOR) + HEAD[part], 0])
  return projectPoint(point, frame.eye, frame.look, frame.fov, doc.width / doc.height)
}

test('eighteen vertical shots are registered as cinema, translated in both locales and free of project assets', () => {
  assert.equal(VERTICAL_DIALOGUE_IDS.length, 12)
  assert.equal(VERTICAL_TALK_IDS.length, 6)
  assert.equal(VERTICAL_TEMPLATE_IDS.length, 18)
  assert.doesNotMatch(SOURCES, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of VERTICAL_TEMPLATE_IDS) {
    assert.ok(isVerticalTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    assert.equal(SCENE3D_TEMPLATES.find(item => item.id === id)?.frameFormat, 'portrait', `${id}: the row keeps the frame`)
    assert.equal(TEMPLATE_CATEGORIES[id], 'cinema')
    assert.equal(VERTICAL_CATEGORIES[id], 'cinema')
    for (const [locale, catalog] of [['en', en], ['es', es]] as const) {
      const card = verticalCard(id, locale)
      assert.equal(catalog.template[id]?.title, card?.title, `${locale} ${id}`)
      assert.equal(catalog.template[id]?.description, card?.description, `${locale} ${id}`)
      assert.ok((card?.requirements.length ?? 0) >= (isDialogue(id) ? 3 : 2), `${locale} ${id}`)
      assert.ok((card?.description.length ?? 0) <= 240, `${locale} ${id}: one catalogue line`)
    }
    assert.match(verticalCard(id, 'en')!.title, /^Portrait /, `${id}: «portrait» is a literal title word`)
    assert.match(verticalCard(id, 'es')!.title, /vertical/i, id)
    assert.match(verticalCard(id, 'en')!.description, /9:16/, id)
    assert.match(verticalCard(id, 'es')!.description, /9:16/, id)
  }
  assert.equal(applyVerticalTemplate('two-shot'), null)
  assert.equal(verticalCard('two-shot'), undefined)
  const titleOf = (id: string) => id
  for (const [locale, query] of [['en', 'portrait'], ['es', 'vertical']] as const) {
    const found = filterScene3DTemplates({ category: 'all', setting: 'all', query, locale, titleOf })
    for (const id of VERTICAL_TEMPLATE_IDS) assert.ok(found.some(item => item.id === id), `${locale} ${query} ${id}`)
  }
})

test('every vertical shot builds at 720x1280 for models, reopens through the parser and moves', () => {
  for (const id of VERTICAL_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.deepEqual([doc.width, doc.height], [720, 1280], id)
    assert.equal(doc.camera.frameFormat, 'portrait', `${id}: drawn for 9:16, never adapted again`)
    assert.ok(doc.duration >= 5 && doc.duration <= 8, id)
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!
    assert.ok(reopened, id)
    assert.deepEqual(reopened.camera, doc.camera, id)
    const pose = (scene: Scene3DDocument) => scene.slots.map(slot => [slot.id, slot.slot, slot.media, slot.position, slot.rotationY, slot.scale, slot.motion?.to])
    assert.deepEqual(pose(reopened), pose(doc), id)
    assert.equal(doc.slots.find(slot => slot.id === 'background')?.surface, 'environment', `${id}: a world or a painted set can take over`)
    const subjects = doc.slots.filter(slot => slot.slot === 'subject_1' || slot.slot === 'subject_2')
    assert.equal(subjects.length, isDialogue(id) ? 2 : 1, id)
    assert.ok(subjects.every(slot => slot.media === 'model3d' && slot.scale === 1 && slot.sourceUrl === ''), `${id}: authored for models, shipped empty`)
    const framing = doc.camera.framing!
    assert.ok(framing && validFraming(framing), id)
    assert.equal(framing.anchor, id === 'vertical-dialogue-table' ? 'feet' : 'head', id)
    assert.equal(framing.track, 'rest', `${id}: the camera never follows a clip's pose`)
    assert.equal(framing.relativeToFacing, false, id)
    assert.notEqual(doc.camera.family, 'fixed', `${id}: the fixed family ignores framing`)
    const traits = templateTraitsOf(id)
    assert.equal(traits.still, false, id)
    assert.equal(traits.kind, 'scene', id)
    assert.equal(traits.authoredFor, 'model', id)
    assert.notEqual(traits.shot, 'far', id)
    assert.ok(traits.uses.includes('talk'), `${id}: ${traits.uses}`)
    assert.equal(traits.uses.includes('dialogue'), isDialogue(id), `${id}: ${traits.uses}`)
    assert.ok(!traits.uses.includes('reveal') && !traits.uses.includes('impact') && !traits.uses.includes('speed'), `${id}: ${traits.uses}`)
    if (id === 'vertical-dialogue-locked') {
      assert.deepEqual(traits.moves, [], 'a locked tripod')
      assert.deepEqual(traits.moving, ['effects'], 'the dust keeps it alive')
    } else assert.ok(traits.moves.length > 0, `${id}: the camera moves`)
  }
  const prints = VERTICAL_TEMPLATE_IDS.map(id => JSON.stringify([applyScene3DTemplate(id).camera, applyScene3DTemplate(id).slots]))
  assert.equal(new Set(prints).size, VERTICAL_TEMPLATE_IDS.length, 'distinct compositions')
})

/** The faces a card is about, when they are not the framing target: the target of these is seen from behind. */
const FACES: Partial<Record<string, string[]>> = {
  'vertical-dialogue-high': ['subject_2'], 'vertical-dialogue-trio': ['subject_2', 'person_3'], 'vertical-dialogue-table': ['subject_2'],
}

test('faces sit on the upper third with the crown in frame and the lower third left for captions', () => {
  for (const id of VERTICAL_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    const faces = (FACES[id] ?? [doc.camera.framing!.targetSlot]).map(name => doc.slots.find(slot => slot.id === name)!)
    for (const frame of framesOf(doc)) {
      for (const face of faces) {
        const eye = headAt(doc, face, frame, 'eye')!, crown = headAt(doc, face, frame, 'crown')!, chin = headAt(doc, face, frame, 'chin')!
        assert.ok(eye.y > 0.12 && eye.y < 0.45, `${id}: ${face.id} eyes at ${eye.y.toFixed(2)}`)
        assert.ok(crown.y > 0.04, `${id}: ${face.id} crown at ${crown.y.toFixed(2)} leaves headroom`)
        assert.ok(chin.y < 0.6, `${id}: ${face.id} chin at ${chin.y.toFixed(2)} stays above the caption third`)
        assert.ok(eye.x > 0.1 && eye.x < 0.9, `${id}: ${face.id} face at x ${eye.x.toFixed(2)}`)
      }
    }
  }
})

test('the second face is in frame where the card shows two, and off frame in the singles', () => {
  const shown = ['vertical-dialogue-stack', 'vertical-dialogue-walk', 'vertical-dialogue-table', 'vertical-dialogue-trio',
    'vertical-dialogue-listener', 'vertical-dialogue-low', 'vertical-dialogue-high', 'vertical-dialogue-locked']
  for (const id of VERTICAL_DIALOGUE_IDS) {
    const doc = applyScene3DTemplate(id)
    const target = doc.camera.framing!.targetSlot
    const others = doc.slots.filter(slot => slot.id !== target && slot.media === 'model3d' && slot.id !== 'table')
    for (const frame of framesOf(doc)) {
      for (const other of others) {
        const eye = headAt(doc, other, frame, 'eye')
        const inside = Boolean(eye && eye.x > 0.03 && eye.x < 0.97 && eye.y > 0.05 && eye.y < 0.6)
        if (shown.includes(id)) assert.ok(inside, `${id}: ${other.id} at ${eye?.x.toFixed(2)}, ${eye?.y.toFixed(2)}`)
        if (id.includes('-single-')) assert.ok(!inside, `${id}: ${other.id} stays out of the clean single`)
      }
    }
  }
})

test('the A and B pairs mirror each other with matching eyelines from one side of the line', () => {
  for (const [a, b] of [['vertical-dialogue-ots-a', 'vertical-dialogue-ots-b'], ['vertical-dialogue-single-a', 'vertical-dialogue-single-b']] as const) {
    const da = applyScene3DTemplate(a), db = applyScene3DTemplate(b)
    assert.deepEqual(db.slots.map(slot => [slot.position, slot.rotationY]), da.slots.map(slot => [slot.position, slot.rotationY]), 'the same blocking')
    const { subject_1, subject_2 } = slotsOf(da)
    assert.ok(subject_1.position[0] < 0 && subject_2.position[0] > 0 && subject_1.rotationY > 0 && subject_2.rotationY === -subject_1.rotationY)
    const fa = da.camera.framing!, fb = db.camera.framing!
    assert.notEqual(fa.targetSlot, fb.targetSlot)
    assert.deepEqual(fb.from, mirror(fa.from))
    assert.deepEqual(fb.to, mirror(fa.to))
    assert.ok(fa.from[2] > 0 && fb.from[2] > 0, `${a}: both cameras on the same side of the line`)
  }
  const ots = applyScene3DTemplate('vertical-dialogue-ots-a'), single = applyScene3DTemplate('vertical-dialogue-single-b')
  assert.equal(ots.camera.framing!.targetSlot, single.camera.framing!.targetSlot, 'ots A and single B frame the same face')
})

test('the walk strolls toward the camera, the seated card carries its table and the trio its third figure', () => {
  const walk = applyScene3DTemplate('vertical-dialogue-walk')
  const walkers = walk.slots.filter(slot => slot.motion)
  assert.equal(walkers.length, 2)
  const steps = walkers.map(slot => sub(slot.motion!.to, slot.position))
  assert.deepEqual(steps[0], steps[1], 'side by side the whole way')
  assert.ok(steps[0][2] > 2 && Math.hypot(...steps[0]) / walk.duration < 1, 'toward the camera, under a run')
  assert.ok(walkers.every(slot => slot.motion!.faceTravel))
  const walkTraits = templateTraitsOf('vertical-dialogue-walk')
  assert.ok(walkTraits.travel && walkTraits.moves.includes('track') && walkTraits.uses.includes('dialogue'))

  const table = slotsOf(applyScene3DTemplate('vertical-dialogue-table')).table
  assert.deepEqual([table.slot, table.media, table.grounded], ['prop', 'model3d', true])
  assert.match(verticalCard('vertical-dialogue-table', 'en')!.description, /sit_down/)
  assert.match(verticalCard('vertical-dialogue-table', 'es')!.description, /sit_down/)

  const third = slotsOf(applyScene3DTemplate('vertical-dialogue-trio')).person_3
  assert.deepEqual([third.slot, third.media, third.scale, third.grounded], ['prop', 'model3d', 1, true])
  assert.equal(templateTraitsOf('vertical-dialogue-trio').props, 1)
  assert.deepEqual(applyScene3DTemplate('vertical-dialogue-locked').worldSfx?.map(cue => cue.kind), ['dust'])
})

test('a vertical card keeps its frame when the editor switches to it, and builds landscape when asked', () => {
  const landscape = applyScene3DTemplate('two-shot')
  for (const id of ['vertical-dialogue-ots-a', 'vertical-talk-bust'] as const) {
    const next = remountScene3DTemplate(id, landscape)
    assert.deepEqual([next.width, next.height], [720, 1280], id)
    assert.deepEqual(next.camera, applyScene3DTemplate(id).camera, `${id}: the authored camera, not an adapted one`)
    const wide = applyVerticalTemplate(id, { orientation: 'horizontal' })!
    assert.deepEqual([wide.width, wide.height], [1280, 720], id)
    assert.equal(wide.camera.frameFormat, undefined, `${id}: the portrait scales are undone`)
    assert.ok(wide.camera.fov < applyScene3DTemplate(id).camera.fov, id)
  }
})

test('slots bind by id, alias or role, and ship empty', () => {
  for (const id of VERTICAL_TEMPLATE_IDS) {
    const aliases = verticalAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applyVerticalTemplate(id, { roles: { [lead]: '/api/v1/file/a.glb?workspace=w' } })!
    assert.equal(bound.slots.find(slot => slot.id === aliases[lead])?.sourceUrl, '/api/v1/file/a.glb?workspace=w', id)
    assert.equal(bound.slots.find(slot => slot.id === 'background')?.sourceUrl, '', id)
  }
  const trio = applyVerticalTemplate('vertical-dialogue-trio', { roles: { person: '/api/v1/file/x.glb?workspace=w' } })!
  assert.equal(trio.slots.find(slot => slot.id === 'person_3')?.sourceUrl, '/api/v1/file/x.glb?workspace=w', 'the id family')
})
