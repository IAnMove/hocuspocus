import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  TRANSITION_CATEGORIES,
  TRANSITION_TEMPLATE_IDS,
  applyTransitionTemplate,
  isTransitionTemplateId,
  transitionAliases,
  transitionAuthoredCueKinds,
  transitionCard,
} from '../src/features/scene3d/transitionTemplates.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { filterScene3DTemplates } from '../src/features/scene3d/templateFilters.ts'
import { templateTraits, type TemplateCameraMove } from '../src/features/scene3d/templateTraits.ts'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import { FX_CATALOG } from '../src/features/sceneFx/types.ts'
import { WORLD_SFX_KINDS } from '../src/features/sceneFx/world.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, '../src/features/scene3d/transitionTemplates.ts'), 'utf8')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const SCREEN_KINDS = new Set(FX_CATALOG.map(item => item.id))
const traitsOf = (id: string) => {
  const doc = applyScene3DTemplate(id as (typeof SCENE3D_TEMPLATE_IDS)[number])
  return templateTraits(doc, { category: TEMPLATE_CATEGORIES[doc.templateId], family: doc.camera.family })
}

test('eight transitions are registered under cinema with the transition tag, translated and free of project assets', () => {
  assert.equal(TRANSITION_TEMPLATE_IDS.length, 8)
  assert.doesNotMatch(SOURCE, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of TRANSITION_TEMPLATE_IDS) {
    assert.ok(isTransitionTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    const row = SCENE3D_TEMPLATES.find(item => item.id === id)
    assert.deepEqual(row?.tags, ['transition'], id)
    assert.equal(TEMPLATE_CATEGORIES[id], 'cinema')
    assert.equal(TRANSITION_CATEGORIES[id], 'cinema')
    assert.ok(en.template[id]?.title && en.template[id]?.description, id)
    assert.ok(es.template[id]?.title && es.template[id]?.description, id)
    assert.equal(en.template[id].title, transitionCard(id, 'en')?.title)
    assert.equal(es.template[id].title, transitionCard(id, 'es')?.title)
    assert.ok((transitionCard(id, 'en')?.requirements.length ?? 0) >= 2, id)
  }
  assert.equal(en.category.transition, 'Transitions')
  assert.equal(es.category.transition, 'Transiciones')
  assert.equal(applyTransitionTemplate('two-shot'), null)
  const found = filterScene3DTemplates({ category: 'transition', setting: 'all', query: '', locale: 'en', titleOf: id => id })
  assert.deepEqual(found.map(item => item.id), [...TRANSITION_TEMPLATE_IDS])
})

test('every transition is a short 16:9 cut piece on a flat backdrop with one optional cutout and no background slot', () => {
  for (const id of TRANSITION_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(doc.width, 1920)
    assert.equal(doc.height, 1080)
    assert.equal(doc.fps, 24)
    assert.ok(doc.duration >= 0.6 && doc.duration <= 2.5, `${id}: ${doc.duration}s`)
    assert.equal(doc.environment?.floorStyle, 'none')
    assert.ok(doc.screenBackdrop, id)
    assert.ok(!doc.slots.some(slot => slot.slot === 'background'), `${id}: no background slot`)
    const subjects = doc.slots.filter(slot => slot.slot === 'subject_1')
    assert.equal(subjects.length, 1, id)
    assert.equal(subjects[0].media, 'image')
    assert.equal(subjects[0].surface, 'cutout')
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(reopened, id)
    assert.deepEqual(reopened.camera, doc.camera)
    assert.deepEqual(reopened.screenBackdrop, doc.screenBackdrop)
    assert.deepEqual(reopened.sfx, doc.sfx)
    assert.equal(reopened.worldSfx?.length ?? 0, doc.worldSfx?.length ?? 0)
    const framing = doc.camera.framing
    if (framing) {
      assert.ok(doc.slots.some(slot => slot.id === framing.targetSlot), id)
      assert.equal(framing.relativeToFacing, false, id)
      assert.notEqual(doc.camera.family, 'fixed', `${id}: the fixed family ignores framing`)
    }
    const vertical = applyTransitionTemplate(id, { orientation: 'vertical' })!
    assert.equal(vertical.width, 1080)
    assert.equal(vertical.height, 1920)
    assert.equal(vertical.camera.frameFormat, 'portrait')
  }
})

test('transitions are distinct compositions', () => {
  const prints = TRANSITION_TEMPLATE_IDS.map(id => {
    const doc = applyScene3DTemplate(id)
    return JSON.stringify([doc.camera, doc.slots, doc.dressing, doc.sfx])
  })
  assert.equal(new Set(prints).size, TRANSITION_TEMPLATE_IDS.length)
})

test('transitions use only catalogued effects, keep every cue inside the shot and count flashes in frames', () => {
  for (const id of TRANSITION_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    const authored = transitionAuthoredCueKinds(id)
    for (const kind of [...authored.sfx, ...authored.backdrop]) assert.ok(SCREEN_KINDS.has(kind), `${id}: ${kind}`)
    for (const kind of authored.worldSfx) assert.ok(WORLD_SFX_KINDS.includes(kind), `${id}: ${kind}`)
    assert.equal(doc.sfx?.length ?? 0, authored.sfx.length, `${id}: no screen cue was dropped`)
    assert.equal(doc.worldSfx?.length ?? 0, authored.worldSfx.length, `${id}: no world cue was dropped`)
    assert.equal(doc.screenBackdrop?.sfx.length, authored.backdrop.length, `${id}: no backdrop cue was dropped`)
    const cues = [...(doc.sfx ?? []), ...(doc.worldSfx ?? []), ...(doc.screenBackdrop?.sfx ?? [])]
    assert.ok(cues.length > 0, `${id}: a transition is carried by its effects`)
    for (const cue of cues) assert.ok(cue.start >= 0 && cue.end <= doc.duration + 1e-9, `${id}: ${cue.id}`)
    for (const shake of doc.camera.shake ?? []) assert.ok(shake.start >= 0 && shake.end <= doc.duration + 1e-9, `${id}: shake`)
    for (const flash of (doc.sfx ?? []).filter(cue => cue.kind === 'impact_flash' || cue.kind === 'impact_invert')) {
      const frames = (flash.end - flash.start) * doc.fps
      assert.ok(frames > 1.99 && frames < 4.01, `${id}: ${flash.id} lasts ${frames} frames`)
    }
  }
})

test('every transition comes out of the traits as a moving transition with the moves it was authored with', () => {
  const expected: Record<(typeof TRANSITION_TEMPLATE_IDS)[number], { moves: TemplateCameraMove[]; moving: string[] }> = {
    'transition-whip-pan': { moves: ['slide', 'roll', 'shake'], moving: ['camera', 'effects'] },
    'transition-iris-in': { moves: ['push'], moving: ['camera', 'effects'] },
    'transition-flash-white': { moves: ['push'], moving: ['camera', 'effects'] },
    'transition-wipe-prop': { moves: [], moving: ['props', 'effects'] },
    'transition-match-shape': { moves: ['pull'], moving: ['camera', 'effects'] },
    'transition-eyecatch': { moves: [], moving: ['subjects', 'effects'] },
    'transition-smash-in': { moves: ['push', 'shake'], moving: ['camera', 'effects'] },
    'transition-rise-off': { moves: ['rise'], moving: ['camera', 'effects'] },
  }
  for (const id of TRANSITION_TEMPLATE_IDS) {
    const traits = traitsOf(id)
    assert.ok(traits.uses.includes('transition'), `${id}: ${traits.uses}`)
    assert.equal(traits.still, false, id)
    assert.equal(traits.subjects, 1, id)
    assert.equal(traits.authoredFor, 'cutout', id)
    assert.notEqual(traits.shot, 'plate', id)
    for (const move of expected[id].moves) assert.ok(traits.moves.includes(move), `${id}: ${move} in ${traits.moves}`)
    for (const part of expected[id].moving) assert.ok(traits.moving.includes(part), `${id}: ${part} in ${traits.moving}`)
  }
  assert.equal(traitsOf('transition-smash-in').uses.includes('action'), true, 'the smash lands with a beat')
  assert.equal(traitsOf('transition-eyecatch').shot, 'wide')
  assert.equal(traitsOf('transition-wipe-prop').props, 1)
})

test('the wipe prop crosses the whole frame and covers the lens at mid-shot', () => {
  const doc = applyScene3DTemplate('transition-wipe-prop')
  const prop = doc.slots.find(slot => slot.slot === 'prop')!
  assert.equal(prop.media, 'model3d')
  assert.ok(prop.position[0] < -3 && prop.motion!.to[0] > 3, 'it starts and ends off frame')
  assert.ok(Math.abs(slotPoseAtTime(prop, doc.duration / 2, doc.duration).position[0]) < 1e-9, 'it is centred at mid-shot')
  const eye = doc.camera.eye
  assert.ok(eye[2] - prop.position[2] > 0.5 && eye[2] - prop.position[2] < 1, 'it passes close in front of the lens')
  assert.equal(doc.camera.family, 'fixed')
})

test('cutouts bind by id, alias or role, and only the eyecatch draws an optional title', () => {
  for (const id of TRANSITION_TEMPLATE_IDS) {
    const aliases = transitionAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applyTransitionTemplate(id, { roles: { [lead]: '/api/v1/file/a.png?workspace=w' } })!
    assert.ok(bound.slots.some(slot => slot.sourceUrl === '/api/v1/file/a.png?workspace=w'), id)
    const byRole = applyTransitionTemplate(id, { roles: { subject_1: '/api/v1/file/b.png?workspace=w' } })!
    assert.equal(byRole.slots.find(slot => slot.slot === 'subject_1')?.sourceUrl, '/api/v1/file/b.png?workspace=w', id)
    assert.equal(applyTransitionTemplate(id)?.texts, undefined, `${id}: no placeholder text by default`)
  }
  const titled = applyTransitionTemplate('transition-eyecatch', { text: 'PART TWO' })!
  assert.equal(titled.texts?.length, 1)
  assert.equal(titled.texts?.[0].text, 'PART TWO')
  assert.ok(titled.texts![0].end <= titled.duration + 1e-9)
  assert.ok(templateTraits(titled, { category: 'cinema' }).uses.includes('title'))
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(titled)))?.texts, titled.texts)
  assert.equal(applyTransitionTemplate('transition-whip-pan', { text: 'PART TWO' })?.texts, undefined)
})
