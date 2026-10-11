import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  TITLE_CATEGORIES,
  TITLE_TEMPLATE_IDS,
  applyTitleTemplate,
  isTitleTemplateId,
  titleAliases,
  titleAuthoredCueKinds,
  titleCard,
} from '../src/features/scene3d/titleTemplates.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { templateTraits } from '../src/features/scene3d/templateTraits.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import { FX_CATALOG } from '../src/features/sceneFx/types.ts'
import { TEXT_ENTERS, TEXT_EXITS } from '../src/lib/kineticText.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, '../src/features/scene3d/titleTemplates.ts'), 'utf8')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const SCREEN_KINDS = new Set(FX_CATALOG.map(item => item.id))
const traitsOf = (id: string) => {
  const doc = applyScene3DTemplate(id as (typeof SCENE3D_TEMPLATE_IDS)[number])
  return templateTraits(doc, { category: TEMPLATE_CATEGORIES[doc.templateId], family: doc.camera.family })
}

test('four title cards are registered under cinema, translated and free of project assets', () => {
  assert.equal(TITLE_TEMPLATE_IDS.length, 4)
  assert.doesNotMatch(SOURCE, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of TITLE_TEMPLATE_IDS) {
    assert.ok(isTitleTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    const row = SCENE3D_TEMPLATES.find(item => item.id === id)
    assert.ok(row, id)
    assert.equal(TEMPLATE_CATEGORIES[id], 'cinema')
    assert.equal(TITLE_CATEGORIES[id], 'cinema')
    assert.ok(en.template[id]?.title && en.template[id]?.description, id)
    assert.ok(es.template[id]?.title && es.template[id]?.description, id)
    assert.equal(en.template[id].title, titleCard(id, 'en')?.title)
    assert.equal(es.template[id].title, titleCard(id, 'es')?.title)
    assert.ok((titleCard(id, 'en')?.requirements.length ?? 0) >= 2, id)
  }
  assert.equal(applyTitleTemplate('two-shot'), null)
})

test('every title card is a 16:9 shot with kinetic texts and an optional cutout, and reopens with its texts', () => {
  for (const id of TITLE_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(doc.width, 1920)
    assert.equal(doc.height, 1080)
    assert.equal(doc.fps, 24)
    assert.ok(doc.duration >= 4 && doc.duration <= 6, `${id}: ${doc.duration}s`)
    assert.ok(doc.screenBackdrop, id)
    assert.ok(!doc.slots.some(slot => slot.slot === 'background'), `${id}: no background slot`)
    const subjects = doc.slots.filter(slot => slot.slot === 'subject_1')
    assert.equal(subjects.length, 1, id)
    assert.equal(subjects[0].surface, 'cutout')
    assert.ok((doc.texts?.length ?? 0) >= 2, `${id}: a main line and a second line`)
    for (const cue of doc.texts ?? []) {
      assert.ok(cue.start >= 0 && cue.end <= doc.duration + 1e-9, `${id}: ${cue.id}`)
      assert.ok(cue.text.trim().length > 0, `${id}: ${cue.id}`)
      if (cue.enter) assert.ok(TEXT_ENTERS.includes(cue.enter.preset), `${id}: ${cue.id} enter`)
      if (cue.exit) assert.ok(TEXT_EXITS.includes(cue.exit.preset), `${id}: ${cue.id} exit`)
    }
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(reopened, id)
    assert.deepEqual(reopened.texts, doc.texts, `${id}: every text field survives the parser`)
    assert.deepEqual(reopened.camera, doc.camera)
    assert.deepEqual(reopened.sfx, doc.sfx)
    assert.deepEqual(reopened.environment, doc.environment)
    const framing = doc.camera.framing!
    assert.ok(doc.slots.some(slot => slot.id === framing.targetSlot), id)
    assert.equal(framing.relativeToFacing, false, id)
    const vertical = applyTitleTemplate(id, { orientation: 'vertical' })!
    assert.equal(vertical.width, 1080)
    assert.equal(vertical.height, 1920)
    assert.equal(vertical.camera.frameFormat, 'portrait')
  }
})

test('title cards are distinct compositions', () => {
  const prints = TITLE_TEMPLATE_IDS.map(id => {
    const doc = applyScene3DTemplate(id)
    return JSON.stringify([doc.camera, doc.slots, doc.dressing, doc.sfx])
  })
  assert.equal(new Set(prints).size, TITLE_TEMPLATE_IDS.length)
})

test('title cards use only catalogued effects, keep every cue inside the shot and are never still', () => {
  for (const id of TITLE_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    const authored = titleAuthoredCueKinds(id)
    for (const kind of [...authored.sfx, ...authored.backdrop]) assert.ok(SCREEN_KINDS.has(kind), `${id}: ${kind}`)
    assert.equal(doc.sfx?.length ?? 0, authored.sfx.length, `${id}: no screen cue was dropped`)
    for (const cue of [...(doc.sfx ?? []), ...(doc.screenBackdrop?.sfx ?? [])]) assert.ok(cue.start >= 0 && cue.end <= doc.duration + 1e-9, `${id}: ${cue.id}`)
    const traits = traitsOf(id)
    assert.ok(traits.uses.includes('title'), `${id}: ${traits.uses}`)
    assert.equal(traits.still, false, id)
    assert.ok(traits.moving.includes('texts') && traits.moving.includes('camera'), `${id}: ${traits.moving}`)
    assert.ok(traits.moves.length > 0, `${id}: the camera moves on its own`)
    assert.equal(traits.subjects, 1, id)
    assert.equal(traits.authoredFor, 'cutout', id)
  }
  assert.deepEqual(traitsOf('title-lower-third').moves, ['push'])
  assert.deepEqual(traitsOf('title-kinetic-stage').moves, ['push'])
  assert.equal(traitsOf('title-kinetic-stage').floor, 'mirror')
  assert.deepEqual(traitsOf('title-chapter').moves, ['push'])
  assert.deepEqual(traitsOf('title-end-card').moves, ['slide'])
})

test('the lower third slides in from the left, holds and slides out', () => {
  const doc = applyScene3DTemplate('title-lower-third')
  const [name, role] = doc.texts!
  for (const cue of [name, role]) {
    assert.equal(cue.align, 'left')
    assert.ok(cue.x < 15, 'anchored at the left edge')
    assert.ok(cue.y > 70, 'in the lower third')
    assert.equal(cue.enter?.preset, 'slide-left')
    assert.equal(cue.exit?.preset, 'slide-left')
    assert.ok(cue.end - cue.start - cue.enter!.duration - cue.exit!.duration > 2, 'it holds')
  }
  assert.ok(name.size > role.size)
  assert.equal(name.box?.kind, 'bar')
  assert.equal(role.box?.kind, 'underline')
})

test('text and subtext replace the lines, and the kinetic stage lays one word per beat', () => {
  const third = applyTitleTemplate('title-lower-third', { text: 'MARÍA LÓPEZ', subtext: 'Director' })!
  assert.equal(third.texts![0].text, 'MARÍA LÓPEZ')
  assert.equal(third.texts![1].text, 'Director')
  const chapter = applyTitleTemplate('title-chapter', { text: 'THE RETURN', subtext: 'CHAPTER TWO' })!
  assert.equal(chapter.texts![0].text, 'THE RETURN')
  assert.equal(chapter.texts![1].text, 'CHAPTER TWO')
  assert.equal(chapter.texts![2].text, applyScene3DTemplate('title-chapter').texts![2].text, 'the rule is not a line of copy')
  assert.equal(chapter.texts![0].enter?.preset, 'wipe')
  assert.equal(chapter.texts![2].enter?.preset, 'wipe', 'the rule draws itself')
  const end = applyTitleTemplate('title-end-card', { subtext: 'FOLLOW FOR MORE' })!
  assert.equal(end.texts![0].text, applyScene3DTemplate('title-end-card').texts![0].text)
  assert.equal(end.texts![1].text, 'FOLLOW FOR MORE')
  assert.equal(end.texts![1].loop, 'pulse')

  const stage = applyScene3DTemplate('title-kinetic-stage')
  assert.deepEqual(stage.texts!.map(cue => cue.text), ['ONE', 'WORD', 'PER', 'BEAT'])
  for (let index = 1; index < stage.texts!.length; index += 1) {
    assert.ok(Math.abs(stage.texts![index].start - stage.texts![index - 1].end) < 1e-9, 'beats touch')
    assert.ok(Math.abs((stage.texts![index].end - stage.texts![index].start) - (stage.texts![0].end - stage.texts![0].start)) < 1e-9, 'beats are even')
  }
  const line = applyTitleTemplate('title-kinetic-stage', { text: '  hold   the line tonight ' })!
  assert.deepEqual(line.texts!.map(cue => cue.text), ['hold', 'the', 'line', 'tonight'])
  assert.equal(line.texts![0].start, stage.texts![0].start)
  assert.equal(line.texts![3].end, stage.texts![3].end)
  assert.ok(line.texts!.every(cue => cue.preset === 'impact' && cue.uppercase && cue.size === stage.texts![0].size))
  const many = applyTitleTemplate('title-kinetic-stage', { text: 'a b c d e f g h i j' })!
  assert.equal(many.texts!.length, 8, 'at most eight words')
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(many)))?.texts, many.texts)
  assert.ok(templateTraits(many, { category: 'cinema' }).uses.includes('title'))
})

test('cutouts bind by id, alias or role', () => {
  for (const id of TITLE_TEMPLATE_IDS) {
    const aliases = titleAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applyTitleTemplate(id, { roles: { [lead]: '/api/v1/file/a.png?workspace=w' } })!
    assert.ok(bound.slots.some(slot => slot.sourceUrl === '/api/v1/file/a.png?workspace=w'), id)
    const byRole = applyTitleTemplate(id, { roles: { subject_1: '/api/v1/file/b.png?workspace=w' } })!
    assert.equal(byRole.slots.find(slot => slot.slot === 'subject_1')?.sourceUrl, '/api/v1/file/b.png?workspace=w', id)
  }
})
