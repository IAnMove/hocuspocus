import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ALL_SCENE_TEMPLATES,
  CATALOG_VERSION,
  CANDIDATE_SCENE_TEMPLATES,
  EXPANDED_CATALOG_VERSION,
  getCandidateSceneTemplate,
  templateCatalogVersion,
} from '../src/features/sceneTemplates/catalog.ts'
import {
  describeTemplateComponents,
  templateComponentPrompt,
  TEMPLATE_SLOT_LABELS,
} from '../src/features/sceneTemplates/componentContract.ts'
import { MUSIC_MOTION_TEMPLATES } from '../src/features/sceneTemplates/musicMotionCatalog.ts'

const keys = contract => contract.components.map(component => component.key)

test('resuelve las 24 plantillas legacy y las 24 musicales sin mezclar roles', () => {
  assert.equal(CANDIDATE_SCENE_TEMPLATES.length, 24)
  assert.equal(MUSIC_MOTION_TEMPLATES.length, 24)
  assert.equal(ALL_SCENE_TEMPLATES.length, 48)

  for (const template of ALL_SCENE_TEMPLATES) {
    assert.equal(getCandidateSceneTemplate(template.id).id, template.id)
    const contract = describeTemplateComponents(template.id)
    assert.equal(contract.schema, 'hocuspocus.template-components')
    assert.equal(contract.generationPolicy, 'provided_only')
    assert.equal(contract.status, 'candidate')
    assert.equal(contract.catalogVersion, templateCatalogVersion(template))
  }
})

test('versiona por pertenencia explícita al catálogo, no por el nombre de un slot', () => {
  for (const template of CANDIDATE_SCENE_TEMPLATES) {
    assert.equal(templateCatalogVersion(template), CATALOG_VERSION)
    assert.equal(describeTemplateComponents(template.id).catalogVersion, CATALOG_VERSION)
  }
  for (const template of ALL_SCENE_TEMPLATES.slice(CANDIDATE_SCENE_TEMPLATES.length)) {
    assert.equal(templateCatalogVersion(template), EXPANDED_CATALOG_VERSION)
    assert.equal(describeTemplateComponents(template.id).catalogVersion, EXPANDED_CATALOG_VERSION)
  }

  const legacyWithMusicRole = {
    ...CANDIDATE_SCENE_TEMPLATES[0],
    slots: [...CANDIDATE_SCENE_TEMPLATES[0].slots, {
      id: 'subject_1', required: false, kinds: ['image'], description: 'test',
    }],
  }
  assert.equal(templateCatalogVersion(legacyWithMusicRole), CATALOG_VERSION)
})

test('mantiene subject_2 separado de prop_1', () => {
  const duet = describeTemplateComponents('music-orbit-duel')
  const pass = describeTemplateComponents('music-ricochet-pass')

  assert.ok(keys(duet).includes('subject_2'))
  assert.ok(!keys(duet).includes('prop_1'))
  assert.ok(keys(pass).includes('prop_1'))
  assert.ok(!keys(pass).includes('subject_2'))

  const subjectTwo = duet.components.find(component => component.key === 'subject_2')
  const propOne = pass.components.find(component => component.key === 'prop_1')
  assert.notEqual(subjectTwo?.label, propOne?.label)
  assert.notEqual(subjectTwo?.description, propOne?.description)
})

test('expone required, kinds y descripción en una plantilla legacy', () => {
  const contract = describeTemplateComponents('cinema-two-shot')
  const hero = contract.components.find(component => component.key === 'hero')
  const prop = contract.components.find(component => component.key === 'prop')
  const plate = contract.components.find(component => component.key === 'plate')

  assert.deepEqual(hero?.kinds, ['image', 'model3d'])
  assert.equal(hero?.required, true)
  assert.equal(typeof hero?.description, 'string')
  assert.ok((hero?.description.length ?? 0) > 0)
  assert.deepEqual(plate?.kinds, ['image'])
  assert.equal(prop?.required, true)
  assert.deepEqual(prop?.kinds, ['image', 'model3d'])
  assert.ok((prop?.description.length ?? 0) > 0)
  assert.deepEqual(contract.limits, [...contract.limits])
})

test('devuelve objetos frescos y no permite mutar el catálogo mediante el contrato', () => {
  const first = describeTemplateComponents('music-high-five')
  const second = describeTemplateComponents('music-high-five')
  assert.notEqual(first, second)
  assert.notEqual(first.components, second.components)
  assert.notEqual(first.components[0], second.components[0])
  assert.notEqual(first.limits, second.limits)

  first.components[0].description = 'mutated locally'
  first.components[0].kinds.push('model3d')
  first.limits.push('mutated locally')

  const fresh = describeTemplateComponents('music-high-five')
  assert.notEqual(fresh.components[0].description, 'mutated locally')
  assert.deepEqual(fresh.components[0].kinds, ['image'])
  assert.ok(!fresh.limits.includes('mutated locally'))
  assert.equal(TEMPLATE_SLOT_LABELS.subject_2, 'Subject 2')
  assert.equal(TEMPLATE_SLOT_LABELS.prop_1, 'Prop 1')
})

test('rechaza una plantilla desconocida y el prompt no intenta generar ni inventar archivos', () => {
  assert.throws(
    () => describeTemplateComponents('unknown-template'),
    /Unknown candidate scene template: unknown-template/,
  )

  const parsed = JSON.parse(templateComponentPrompt('music-orbit-duel'))
  assert.equal(parsed.schema, 'hocuspocus.template-components')
  assert.equal(parsed.generationPolicy, 'provided_only')
  assert.equal(typeof parsed.instruction, 'string')
  assert.match(parsed.instruction, /assetId and workspace/)
  assert.match(parsed.instruction, /does not authorize.*generation/i)
  assert.match(parsed.instruction, /Do not invent files/i)
  assert.match(parsed.instruction, /body.*pose/i)
})
