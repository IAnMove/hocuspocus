import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { cameraEyeAtTime, cameraLookAtTime } from '../src/features/scene3d/camera.ts'
import {
  ACTION_CATEGORIES,
  ACTION_TEMPLATE_IDS,
  ACTION_TEMPLATES,
  applyActionTemplate,
  actionAliases,
  actionCard,
  actionTemplateDocument,
  isActionTemplateId,
  parseActionDocument,
} from '../src/features/scene3d/actionTemplates.ts'
import { ACTION_DRESSINGS, actionGroup, isActionDressing, paintActionSet } from '../src/features/scene3d/actionSets.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { parseDressing } from '../src/features/scene3d/documentSlot.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { filterScene3DTemplates, templateSetting } from '../src/features/scene3d/templateFilters.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'

const SOURCE = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../src/features/scene3d/actionTemplates.ts'), 'utf8')
const SETS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../src/features/scene3d/actionSets.ts'), 'utf8')
const audio = { workspaceId: 'demo', filename: 'vo.wav', url: '/api/v1/uploads/vo.wav' }

test('thirty-five action ids are native, catalogued and free of private cinema/GLB imports', () => {
  assert.equal(ACTION_TEMPLATE_IDS.length, 35)
  assert.equal(new Set(ACTION_TEMPLATE_IDS).size, 35)
  assert.doesNotMatch(SOURCE, /tools\/cinema/)
  assert.doesNotMatch(SOURCE, /from ['"][^'"]+\.glb['"]/)
  assert.doesNotMatch(SETS, /from ['"][^'"]+\.glb['"]/)
  for (const id of ACTION_TEMPLATE_IDS) {
    assert.equal(isActionTemplateId(id), true)
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    assert.ok(SCENE3D_TEMPLATES.some(item => item.id === id), id)
    assert.equal(TEMPLATE_CATEGORIES[id], 'action')
    assert.equal(ACTION_CATEGORIES[id], TEMPLATE_CATEGORIES[id])
    const card = actionCard(id, 'en')
    const es = actionCard(id, 'es')
    assert.ok(card && card.title && card.description && card.requirements.length >= 2, id)
    assert.ok(es && es.title && es.title !== card.title, id)
    assert.match(card.requirements.join(' '), /GLB|Imagen|Optional|opcional/)
  }
  assert.equal(applyActionTemplate('two-shot'), null)
  assert.equal(actionTemplateDocument('missing'), null)
})

test('apply, bind roles, optional audio/text and H/V variants reopen as native shots', () => {
  for (const id of ACTION_TEMPLATE_IDS) {
    const landscape = applyActionTemplate(id)
    assert.ok(landscape, id)
    const catalog = ACTION_TEMPLATES.find(item => item.id === id)
    assert.equal(landscape.templateId, id)
    assert.equal(landscape.duration, catalog?.duration)
    assert.equal(landscape.width, 1280)
    assert.equal(landscape.height, 720)
    assert.equal(landscape.slots.some(slot => /\.glb$/i.test(slot.sourceUrl) && !slot.sourceUrl.startsWith('/examples/')), false, id)
    assert.ok(landscape.dressing, id)
    assert.equal(parseDressing(landscape.dressing), landscape.dressing, id)
    const aliases = actionAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applyActionTemplate(id, {
      orientation: 'vertical',
      roles: { [lead]: '/api/v1/uploads/hero.glb', [aliases[lead]]: '/api/v1/uploads/other.glb' },
      audio,
      text: 'Literal overlay',
    })
    assert.ok(bound, id)
    assert.equal(bound.width, 720)
    assert.equal(bound.height, 1280)
    assert.notEqual(bound.camera.fov, landscape.camera.fov)
    assert.ok(bound.slots.some(slot => slot.sourceUrl === '/api/v1/uploads/hero.glb' || slot.sourceUrl === '/api/v1/uploads/other.glb'), id)
    assert.equal(bound.soundtrack?.[0]?.audio.url, audio.url)
    assert.equal(bound.texts?.[0]?.text, 'Literal overlay')
    const silent = applyActionTemplate(id, { text: false })
    assert.equal(silent?.texts, undefined)
    const raw = JSON.parse(JSON.stringify(bound))
    const parsed = parseActionDocument(raw)
    const native = parseScene3DDocument(raw)
    assert.equal(parsed?.templateId, id)
    assert.equal(native?.templateId, id)
    assert.equal(native?.camera.family, bound.camera.family)
    assert.deepEqual(native?.camera.eye, bound.camera.eye)
    assert.deepEqual(native?.camera.framing, bound.camera.framing)
    assert.equal(native?.slots.length, bound.slots.length)
    assert.deepEqual(native?.slots.map(slot => slot.motion?.to), bound.slots.map(slot => slot.motion?.to))
    assert.deepEqual(native?.slots.map(slot => slot.position), bound.slots.map(slot => slot.position))
    assert.equal(native?.worldSfx?.length ?? 0, bound.worldSfx?.length ?? 0)
    assert.equal(native?.soundtrack?.[0]?.audio.url, audio.url)
    assert.equal(native?.texts?.[0]?.text, 'Literal overlay')
    assert.equal(applyScene3DTemplate(id).templateId, id)
    assert.equal(applyScene3DTemplate(id).dressing, landscape.dressing)
  }
})

test('the thirty-five shots use distinct cameras and distinct in/out actions', () => {
  const cameras = new Set<string>()
  const actions = new Set<string>()
  const dressings = new Set<string>()
  for (const id of ACTION_TEMPLATE_IDS) {
    const doc = applyActionTemplate(id)!
    cameras.add(JSON.stringify({
      family: doc.camera.family,
      eye: doc.camera.eye,
      look: doc.camera.look,
      fov: doc.camera.fov,
      orbitRadius: doc.camera.orbitRadius,
      orbitHeight: doc.camera.orbitHeight,
      orbitTurns: doc.camera.orbitTurns,
      eyeOffset: doc.camera.eyeOffset,
      framing: doc.camera.framing,
    }))
    actions.add(JSON.stringify(doc.slots.map(slot => ({
      id: slot.id,
      slot: slot.slot,
      position: slot.position,
      motion: slot.motion,
      performance: slot.performance,
      appearance: slot.appearance,
      media: slot.media,
    }))))
    if (doc.dressing) dressings.add(doc.dressing)
    const moving = doc.slots.filter(slot => slot.motion)
    assert.ok(moving.length > 0, `${id} moves a role in/out`)
    assert.ok(moving.some(slot => slot.position.some((value, index) => value !== slot.motion!.to[index])), `${id} in ≠ out`)
    for (const phase of [0, 0.5, 1]) {
      const eye = cameraEyeAtTime(doc.camera, phase * doc.duration, doc.duration, doc.slots)
      const look = cameraLookAtTime(doc.camera, phase * doc.duration, doc.duration, doc.slots)
      assert.ok([...eye, ...look].every(Number.isFinite), id)
      assert.ok(Math.hypot(...eye.map((value, index) => value - look[index])) > 0.2, id)
    }
  }
  assert.equal(cameras.size, 35, 'cameras are not the same shot with another label')
  assert.equal(actions.size, 35, 'actions are not the same blocking with another label')
  assert.ok(dressings.has('open-sea') && dressings.has('lunar') && dressings.has('space-lane') && dressings.has('chase-street'))
  assert.ok(dressings.has('jungle') && dressings.has('snow') && dressings.has('casino'))
})

test('action dressings build named geometry without external media', () => {
  assert.equal(ACTION_DRESSINGS.length, 10)
  for (const kind of ACTION_DRESSINGS) {
    assert.equal(isActionDressing(kind), true)
    assert.equal(parseDressing(kind), kind)
    const root = actionGroup(kind)
    assert.equal(root.name, kind)
    assert.ok(root.children.length > 4, kind)
    paintActionSet(root, 1.25)
    paintActionSet(root, 4.5)
  }
  assert.equal(isActionDressing('citadel'), false)
  assert.equal(parseDressing('open-sea'), 'open-sea')
})

test('shot library filters by action category, set and search', () => {
  assert.equal(templateSetting('sea-deck'), 'sea')
  assert.equal(templateSetting('jungle-ambush'), 'jungle')
  assert.equal(templateSetting('casino-heist'), 'casino')
  const titleOf = (id: typeof ACTION_TEMPLATE_IDS[number]) => id
  const action = filterScene3DTemplates({ category: 'action', setting: 'all', query: '', locale: 'en', titleOf })
  assert.equal(action.length, 35)
  const sea = filterScene3DTemplates({ category: 'action', setting: 'sea', query: '', locale: 'en', titleOf })
  assert.ok(sea.some(item => item.id === 'sea-deck'))
  assert.ok(sea.every(item => templateSetting(item.id) === 'sea'))
  const lunar = filterScene3DTemplates({ category: 'action', setting: 'all', query: 'lunar', locale: 'en', titleOf })
  assert.ok(lunar.some(item => item.id === 'lunar-outpost'))
  assert.ok(!lunar.some(item => item.id === 'sea-deck'))
})
