import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { cameraEyeAtTime, cameraLookAtTime } from '../src/features/scene3d/camera.ts'
import {
  CAMPAIGN_CATEGORIES,
  CAMPAIGN_TEMPLATE_IDS,
  CAMPAIGN_TEMPLATES,
  applyCampaignTemplate,
  campaignAliases,
  campaignCard,
  campaignTemplateDocument,
  isCampaignTemplateId,
  parseCampaignDocument,
} from '../src/features/scene3d/campaignTemplates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'

const SOURCE = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../src/features/scene3d/campaignTemplates.ts'), 'utf8')
const audio = { workspaceId: 'demo', filename: 'vo.wav', url: '/api/v1/uploads/vo.wav' }

test('eight campaign ids are native, catalogued and free of private cinema/GLB imports', () => {
  assert.equal(CAMPAIGN_TEMPLATE_IDS.length, 8)
  assert.equal(new Set(CAMPAIGN_TEMPLATE_IDS).size, 8)
  assert.doesNotMatch(SOURCE, /tools\/cinema/)
  assert.doesNotMatch(SOURCE, /from ['"][^'"]+\.glb['"]/)
  for (const id of CAMPAIGN_TEMPLATE_IDS) {
    assert.equal(isCampaignTemplateId(id), true)
    assert.ok((SCENE3D_TEMPLATE_IDS as readonly string[]).includes(id), id)
    assert.ok(SCENE3D_TEMPLATES.some(item => item.id === id), id)
    assert.ok(TEMPLATE_CATEGORIES[id])
    assert.equal(CAMPAIGN_CATEGORIES[id], TEMPLATE_CATEGORIES[id])
    const card = campaignCard(id, 'en')
    const es = campaignCard(id, 'es')
    assert.ok(card && card.title && card.description && card.requirements.length >= 2, id)
    assert.ok(es && es.title && es.title !== card.title, id)
    assert.match(card.requirements.join(' '), /GLB|Imagen|Optional|opcional/)
  }
  assert.equal(applyCampaignTemplate('two-shot'), null)
  assert.equal(campaignTemplateDocument('missing'), null)
})

test('apply, bind roles, optional audio/text and H/V variants reopen as native shots', () => {
  for (const id of CAMPAIGN_TEMPLATE_IDS) {
    const landscape = applyCampaignTemplate(id)
    assert.ok(landscape, id)
    const catalog = CAMPAIGN_TEMPLATES.find(item => item.id === id)
    assert.equal(landscape.templateId, id)
    assert.equal(landscape.duration, catalog?.duration)
    assert.equal(landscape.width, 1280)
    assert.equal(landscape.height, 720)
    assert.equal(landscape.slots.some(slot => /\.glb$/i.test(slot.sourceUrl)), false, id)
    const aliases = campaignAliases(id)
    const lead = Object.keys(aliases)[0]
    const bound = applyCampaignTemplate(id, {
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
    const silent = applyCampaignTemplate(id, { text: false })
    assert.equal(silent?.texts, undefined)
    const raw = JSON.parse(JSON.stringify(bound))
    const parsed = parseCampaignDocument(raw)
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
  }
})

test('campaign display roles bind the board URL onto screen.sourceUrl', () => {
  const bound = applyCampaignTemplate('screen-alert', {
    roles: {
      operator: '/api/v1/uploads/hero.glb',
      display: '/api/v1/uploads/alert.mp4',
    },
  })
  assert.ok(bound)
  const board = bound.slots.find(slot => slot.id === 'alert-screen')
  const operator = bound.slots.find(slot => slot.id === 'subject_1')
  assert.equal(operator?.sourceUrl, '/api/v1/uploads/hero.glb')
  assert.equal(board?.media, 'screen')
  assert.equal(board?.sourceUrl, '')
  assert.equal(board?.screen?.sourceUrl, '/api/v1/uploads/alert.mp4')
  assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(bound)))?.slots.find(slot => slot.id === 'alert-screen')?.screen?.sourceUrl, '/api/v1/uploads/alert.mp4')
})

test('the eight shots use distinct cameras and distinct in/out actions', () => {
  const families = new Set<string>()
  const cameras = new Set<string>()
  const actions = new Set<string>()
  for (const id of CAMPAIGN_TEMPLATE_IDS) {
    const doc = applyCampaignTemplate(id)!
    families.add(doc.camera.family)
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
  assert.equal(families.size, 8, 'eight different camera families')
  assert.equal(cameras.size, 8, 'cameras are not the same shot with another label')
  assert.equal(actions.size, 8, 'actions are not the same blocking with another label')
})
