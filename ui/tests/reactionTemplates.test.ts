import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  applyReactionTemplate,
  isReactionTemplateId,
  reactionAliases,
  reactionAuthoredCueKinds,
  reactionCard,
  REACTION_CATEGORIES,
  REACTION_TEMPLATE_IDS,
} from '../src/features/scene3d/reactionTemplates.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { filterScene3DTemplates, templateTraitsOf } from '../src/features/scene3d/templateFilters.ts'
import { validFraming } from '../src/features/scene3d/framing.ts'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { SCENE3D_TEMPLATE_IDS, type Scene3DDocument, type Vec3 } from '../src/features/scene3d/types.ts'
import { FX_CATALOG } from '../src/features/sceneFx/types.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, '../src/features/scene3d/reactionTemplates.ts'), 'utf8')
const en = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/en/scene3dEditor.json'), 'utf8'))
const es = JSON.parse(readFileSync(join(HERE, '../src/i18n/locales/es/scene3dEditor.json'), 'utf8'))
const SCREEN_KINDS = new Set(FX_CATALOG.map(item => item.id))
const length = (v: Vec3) => Math.hypot(v[0], v[1], v[2])

test('five reaction shots are registered as cinema, translated in both locales and free of project assets', () => {
  assert.equal(REACTION_TEMPLATE_IDS.length, 5)
  assert.doesNotMatch(SOURCE, /\.glb['"]|\.png['"]|\/examples\//)
  for (const id of REACTION_TEMPLATE_IDS) {
    assert.ok(isReactionTemplateId(id))
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    assert.ok(SCENE3D_TEMPLATES.some(item => item.id === id), id)
    assert.equal(TEMPLATE_CATEGORIES[id], 'cinema')
    assert.equal(REACTION_CATEGORIES[id], 'cinema')
    for (const [locale, catalog] of [['en', en], ['es', es]] as const) {
      const card = reactionCard(id, locale)
      assert.equal(catalog.template[id]?.title, card?.title, `${locale} ${id}`)
      assert.equal(catalog.template[id]?.description, card?.description, `${locale} ${id}`)
      assert.ok((card?.requirements.length ?? 0) >= 2, `${locale} ${id}`)
    }
    assert.notEqual(reactionCard(id, 'es')?.title, reactionCard(id, 'en')?.title, id)
  }
  assert.equal(applyReactionTemplate('face-closeup'), null)
  assert.equal(reactionCard('face-closeup'), undefined)
  const found = filterScene3DTemplates({ category: 'cinema', setting: 'all', query: 'reaction', locale: 'en', titleOf: id => id })
  for (const id of REACTION_TEMPLATE_IDS) assert.ok(found.some(item => item.id === id), id)
})

test('every reaction shot holds one model close on the head, reopens through the parser and moves', () => {
  for (const id of REACTION_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    assert.equal(doc.templateId, id)
    assert.equal(doc.width, 1280)
    assert.equal(doc.height, 720)
    assert.ok(doc.duration >= 5 && doc.duration <= 8, id)
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(reopened, id)
    assert.deepEqual(reopened.camera, doc.camera, id)
    assert.deepEqual(reopened.sfx, doc.sfx, id)
    const pose = (scene: Scene3DDocument) => scene.slots.map(slot => [slot.id, slot.position, slot.rotationY, slot.motion?.to, slot.motion?.turnTo])
    assert.deepEqual(pose(reopened), pose(doc), id)
    const subjects = doc.slots.filter(slot => slot.slot === 'subject_1' || slot.slot === 'subject_2')
    assert.equal(subjects.length, 1, id)
    assert.equal(subjects[0].id, 'subject_1', id)
    assert.equal(subjects[0].media, 'model3d', `${id}: authored for models`)
    assert.equal(doc.slots.find(slot => slot.id === 'background')?.surface, 'environment', id)
    const framing = doc.camera.framing!
    assert.ok(validFraming(framing), id)
    assert.equal(framing.targetSlot, 'subject_1', id)
    assert.equal(framing.anchor, 'head', id)
    assert.equal(framing.track, 'rest', `${id}: the camera never follows a clip's pose`)
    assert.equal(framing.relativeToFacing, false, id)
    assert.notEqual(doc.camera.family, 'fixed', id)
    const traits = templateTraitsOf(id)
    assert.equal(traits.subjects, 1, id)
    assert.equal(traits.shot, 'close', `${id}: ${traits.shot}`)
    assert.ok(traits.uses.includes('reaction'), `${id}: ${traits.uses}`)
    assert.ok(traits.moves.includes('push') || traits.moves.includes('arc'), id)
    assert.equal(traits.still, false, id)
    const vertical = applyReactionTemplate(id, { orientation: 'vertical' })!
    assert.equal(vertical.width, 720)
    assert.equal(vertical.height, 1280)
    assert.equal(vertical.camera.frameFormat, 'portrait')
  }
  const prints = REACTION_TEMPLATE_IDS.map(id => {
    const doc = applyScene3DTemplate(id)
    return JSON.stringify([doc.camera, doc.slots, doc.sfx])
  })
  assert.equal(new Set(prints).size, REACTION_TEMPLATE_IDS.length, 'distinct compositions')
})

test('each reaction moves in its own way: push, arc, turn, rise, hit', () => {
  const push = applyScene3DTemplate('reaction-push-face').camera.framing!
  assert.equal(push.moveStart, 0.2, 'a short hold before the push')
  assert.ok(length(push.to) < length(push.from) * 0.7, 'from medium-close to close')
  assert.deepEqual(templateTraitsOf('reaction-push-face').moves, ['push'])

  const orbit = applyScene3DTemplate('reaction-orbit-face').camera.framing!
  assert.equal(orbit.orbitTurns, 0.12)
  assert.deepEqual(orbit.to, orbit.from, 'the arc keeps its distance')
  assert.deepEqual(templateTraitsOf('reaction-orbit-face').moves, ['arc'])

  const turn = applyScene3DTemplate('reaction-turn-to-camera')
  const figure = turn.slots.find(slot => slot.id === 'subject_1')!
  assert.deepEqual(figure.motion?.to, figure.position, 'a turn in place')
  assert.equal(figure.motion?.turnTo, 0, 'ends facing the camera')
  assert.ok(figure.rotationY > 1, 'starts in profile')
  assert.equal(slotPoseAtTime(figure, turn.duration, turn.duration).rotationY, 0)
  assert.deepEqual(slotPoseAtTime(figure, turn.duration / 2, turn.duration).position, figure.position)
  const tiny = turn.camera.framing!
  const ratio = length(tiny.to) / length(tiny.from)
  assert.ok(ratio > 0.88 && ratio < 0.95, `a tiny push: ${ratio}`)
  assert.ok(templateTraitsOf('reaction-turn-to-camera').moving.includes('subjects'))

  const lookUp = applyScene3DTemplate('reaction-look-up').camera.framing!
  assert.ok(lookUp.from[1] < -0.5, 'a low angle')
  assert.ok(lookUp.to[1] > lookUp.from[1], 'rises')
  assert.ok(lookUp.lookTo![1] > lookUp.lookFrom![1], 'tilts up to the face')
  const rise = templateTraitsOf('reaction-look-up')
  assert.ok(rise.moves.includes('rise') && rise.moves.includes('push'))
  assert.ok(!rise.uses.includes('reveal'), 'a tilt on a face is not a crane reveal')

  const impact = applyScene3DTemplate('reaction-impact')
  const flash = (impact.sfx ?? []).find(cue => cue.kind === 'impact_flash')!
  const frames = (flash.end - flash.start) * impact.fps
  assert.ok(frames > 1.99 && frames < 2.01, `two white frames, got ${frames}`)
  const shake = impact.camera.shake![0]
  assert.equal(shake.start, flash.start, 'the shake starts on the hit')
  assert.ok(shake.end - shake.start < 0.8, 'a short window')
  assert.ok(shake.end <= impact.duration && flash.end <= impact.duration)
  const snap = impact.camera.framing!
  assert.equal(snap.ease, 'snap')
  assert.ok(Math.abs(snap.moveStart! * impact.duration - flash.start) < 1e-9, 'the push snaps on the hit')
  const hit = templateTraitsOf('reaction-impact')
  assert.ok(hit.moves.includes('shake') && hit.moves.includes('push'))
  assert.ok(hit.uses.includes('action') && hit.uses.includes('reaction'))
  assert.ok(hit.moving.includes('effects'))
  assert.equal(impact.dressing, undefined, 'plain colours')
  assert.equal(impact.environment?.floorStyle, 'none')
  assert.equal(impact.screenBackdrop?.sfx.length, 0)
  assert.equal(impact.look?.toneMapping, 'neutral')
})

test('reaction cues are catalogued, kept and bound by alias or role', () => {
  for (const id of REACTION_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    const authored = reactionAuthoredCueKinds(id)
    for (const kind of authored) assert.ok(SCREEN_KINDS.has(kind), `${id}: ${kind}`)
    assert.equal(doc.sfx?.length ?? 0, authored.length, `${id}: no cue was dropped`)
    for (const cue of doc.sfx ?? []) assert.ok(cue.start >= 0 && cue.end <= doc.duration + 1e-9, `${id}: ${cue.id}`)
    assert.deepEqual(reactionAliases(id), { subject: 'subject_1', background: 'background' })
    const bound = applyReactionTemplate(id, { roles: { subject: '/api/v1/file/a.glb?workspace=w' } })!
    assert.equal(bound.slots.find(slot => slot.id === 'subject_1')?.sourceUrl, '/api/v1/file/a.glb?workspace=w', id)
    const byRole = applyReactionTemplate(id, { roles: { subject_1: '/api/v1/file/b.glb?workspace=w', background: '/api/v1/file/set.png?workspace=w' } })!
    assert.equal(byRole.slots.find(slot => slot.id === 'subject_1')?.sourceUrl, '/api/v1/file/b.glb?workspace=w', id)
    assert.equal(byRole.slots.find(slot => slot.id === 'background')?.sourceUrl, '/api/v1/file/set.png?workspace=w', id)
  }
})
