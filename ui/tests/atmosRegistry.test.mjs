import assert from 'node:assert/strict'
import test from 'node:test'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { ATMOS_SET_IDS, ATMOS_TEMPLATE_IDS } from '../src/features/scene3d/atmos/registryIds.ts'
import { ATMOS_SETS, installAtmosSet, isAtmosDressing, parseAtmosSettings } from '../src/features/scene3d/atmos/registry.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { parseDressing } from '../src/features/scene3d/documentSlot.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

test('shipped atmosphere ids match the typed catalog', () => {
  assert.deepEqual(ATMOS_SETS.map(set => set.id), [...ATMOS_SET_IDS])
  assert.deepEqual(ATMOS_SETS.flatMap(set => set.templates.map(item => item.id)), [...ATMOS_TEMPLATE_IDS])
})

test('forest templates keep the clearing document', () => {
  const wide = atmosTemplateDocument('atmos-clearing-wide')
  const back = atmosTemplateDocument('atmos-clearing-backlight')
  assert.ok(wide && back)
  for (const doc of [wide, back]) {
    assert.equal(doc.dressing, 'atmos-clearing')
    assert.equal(doc.atmos?.timeOfDay, 'golden')
    assert.equal(doc.atmos?.palette, 'green')
    assert.deepEqual([...doc.light.direction], [0.82, -0.55, 0.16])
    assert.equal(doc.light.intensity, 1.35)
    assert.equal(doc.light.color, '#ffd39a')
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
    assert.equal(doc.duration, 10)
    assert.equal(doc.width, 1920)
    assert.equal(doc.height, 1080)
    assert.equal(doc.fps, 24)
    assert.equal(doc.environment.bloom, 0.32)
    assert.equal(doc.environment.floorStyle, 'none')
  }
  assert.deepEqual([...wide.camera.eye], [0.08, 1.52, 2.9])
  assert.deepEqual([...wide.camera.look], [0.55, 0.42, -1.2])
  assert.equal(wide.camera.fov, 42)
  assert.deepEqual([...back.camera.eye], [1.55, 1.48, 3.15])
  assert.deepEqual([...back.camera.look], [-0.05, 0.38, -1.1])
  assert.equal(back.camera.fov, 40)
  const applied = applyScene3DTemplate('atmos-clearing-wide')
  assert.deepEqual([...applied.camera.eye], [...wide.camera.eye])
  assert.deepEqual([...applied.light.direction], [...wide.light.direction])
  assert.equal(settingFromDressing('atmos-clearing'), 'forest')
})

function probeSet() {
  return {
    id: 'atmos-probe',
    titleKey: 'template.atmos-clearing-wide.title',
    setting: 'forest',
    seed: 3,
    subject: [0, 0, 0],
    subjectYaw: 0,
    palettes: { moss: { fog: '#112233', ground: '#445566', accent: '#778899', sky: ['#112233', '#223344'] } },
    times: { noon: { sun: [0, -1, 0], sunColor: '#ffffff' } },
    defaults: { timeOfDay: 'noon', fogDensity: 0.2, wind: 0.2, motes: 0.2, palette: 'moss' },
    low: { shaftSteps: 1, grassBlades: 1, moteCount: 1 },
    high: { shaftSteps: 2, grassBlades: 2, moteCount: 2 },
    templates: [{ id: 'atmos-probe-wide', camera: 'establishment', eye: [0, 1, 4], look: [0, 1, 0], fov: 40, duration: 6 }],
    build() { throw new Error('probe is not built') },
    fallback() { return { sky: [1, 2, 3], ground: [4, 5, 6] } },
  }
}

test('a probe set is recognized without editing the typed catalog', () => {
  const uninstall = installAtmosSet(probeSet())
  try {
    assert.equal(isAtmosDressing('atmos-probe'), true)
    assert.equal(parseDressing('atmos-probe'), 'atmos-probe')
    assert.equal(settingFromDressing('atmos-probe'), 'forest')
    const doc = atmosTemplateDocument('atmos-probe-wide')
    assert.ok(doc)
    assert.equal(doc.atmos?.palette, 'moss')
    assert.equal(doc.camera.eye[2], 4)
    assert.equal(atmosFallbackLook(doc.atmos, doc.dressing).sky[0], 1)
    assert.equal(parseAtmosSettings({ palette: 'moss', timeOfDay: 'noon' }, 'atmos-probe')?.palette, 'moss')
    const round = parseScene3DDocument(JSON.parse(JSON.stringify({ ...doc, templateId: 'two-shot' })))
    assert.equal(round?.dressing, 'atmos-probe')
    assert.equal(round?.atmos?.palette, 'moss')
    assert.equal(round?.atmos?.timeOfDay, 'noon')
  } finally {
    uninstall()
  }
  assert.equal(parseDressing('atmos-probe'), undefined)
  assert.equal(isAtmosDressing('atmos-probe'), false)
  assert.equal(atmosTemplateDocument('atmos-probe-wide'), null)
})
