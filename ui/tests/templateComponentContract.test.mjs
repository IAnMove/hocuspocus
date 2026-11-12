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
  templateSlotLabels,
} from '../src/features/sceneTemplates/componentContract.ts'
import { MUSIC_MOTION_TEMPLATES } from '../src/features/sceneTemplates/musicMotionCatalog.ts'

const keys = contract => contract.components.map(component => component.key)

test('resuelve las 48 fichas con un solo vocabulario de slots', () => {
  assert.equal(CANDIDATE_SCENE_TEMPLATES.length, 17)
  assert.equal(MUSIC_MOTION_TEMPLATES.length, 22)
  assert.equal(ALL_SCENE_TEMPLATES.length, 48)

  for (const template of ALL_SCENE_TEMPLATES) {
    assert.equal(getCandidateSceneTemplate(template.id).id, template.id)
    const contract = describeTemplateComponents(template.id)
    assert.equal(contract.schema, 'hocuspocus.template-components')
    assert.equal(contract.generationPolicy, 'provided_only')
    assert.equal(contract.status, (template.id.startsWith('walk-') || template.id === 'character-reaction') ? 'candidate' : 'approved')
    assert.equal(contract.catalogVersion, templateCatalogVersion(template))
    const labels = templateSlotLabels()
    for (const component of contract.components) assert.equal(component.label, labels[component.key], `${template.id}/${component.key} has a label`)
  }
})

test('versiona por pertenencia explícita al catálogo, no por el nombre de un slot', () => {
  for (const template of CANDIDATE_SCENE_TEMPLATES) {
    assert.equal(templateCatalogVersion(template), CATALOG_VERSION)
    assert.equal(describeTemplateComponents(template.id).catalogVersion, CATALOG_VERSION)
  }
  for (const template of MUSIC_MOTION_TEMPLATES) {
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
  const pass = describeTemplateComponents('music-crowd-surf')

  assert.ok(keys(duet).includes('subject_2'))
  assert.ok(!keys(duet).includes('prop_1'))
  assert.ok(keys(pass).includes('prop_1'))
  assert.ok(!keys(pass).includes('subject_2'))

  const subjectTwo = duet.components.find(component => component.key === 'subject_2')
  const propOne = pass.components.find(component => component.key === 'prop_1')
  assert.notEqual(subjectTwo?.label, propOne?.label)
  assert.notEqual(subjectTwo?.description, propOne?.description)
})

test('expone required, kinds y descripción en una plantilla original: la segunda persona es subject_2', () => {
  const contract = describeTemplateComponents('cinema-two-shot')
  const hero = contract.components.find(component => component.key === 'subject_1')
  const partner = contract.components.find(component => component.key === 'subject_2')
  const plate = contract.components.find(component => component.key === 'background')

  assert.deepEqual(keys(contract), ['subject_1', 'background', 'subject_2', 'foreground'])
  assert.deepEqual(hero?.kinds, ['image', 'model3d'])
  assert.equal(hero?.required, true)
  assert.equal(typeof hero?.description, 'string')
  assert.ok((hero?.description.length ?? 0) > 0)
  assert.deepEqual(plate?.kinds, ['image', 'video'])
  assert.equal(partner?.required, true)
  assert.deepEqual(partner?.kinds, ['image', 'model3d'])
  assert.ok((partner?.description.length ?? 0) > 0)
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
  const labels = templateSlotLabels()
  assert.equal(labels.subject_1, 'Subject 1')
  assert.equal(labels.subject_2, 'Subject 2')
  assert.equal(labels.background, 'Background')
  assert.equal(labels.prop_1, 'Prop 1')
  assert.equal(labels.prop_2, 'Prop 2')
  assert.equal(labels.foreground, 'Foreground')
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
  assert.match(parsed.instruction, /assetId y workspace/)
  assert.match(parsed.instruction, /no autoriza.*generación/i)
  assert.match(parsed.instruction, /No inventes archivos/i)
  assert.match(parsed.instruction, /cuerpo.*pose/i)
})
