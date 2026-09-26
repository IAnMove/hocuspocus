import assert from 'node:assert/strict'
import test from 'node:test'
import {
  CATALOG_VERSION,
  CANDIDATE_SCENE_TEMPLATES,
  getCandidateSceneTemplate,
} from '../src/features/sceneTemplates/catalog.ts'

const EXPECTED_IDS = [
  'cinema-establishing',
  'cinema-reveal',
  'cinema-closeup',
  'cinema-two-shot',
  'cinema-detail',
  'cinema-hero',
  'cinema-isolation',
  'cinema-tracking',
  'music-pulse',
  'music-duet',
  'music-chorus',
  'music-orbit',
  'music-parallax',
  'music-stage',
  'music-product',
  'music-finale',
  'space-cruise',
  'space-orbit',
  'space-docking',
  'space-chase',
  'space-broadside',
  'space-shield',
  'space-explosion',
  'space-warp',
]

const slot = (template, id) => {
  const value = template.slots.find(candidate => candidate.id === id)
  assert.ok(value, `${template.id} declares ${id}`)
  return value
}

test('candidate catalog contains the exact 24 unique IDs', () => {
  assert.equal(CATALOG_VERSION, '2026-09-review-1')
  assert.equal(CANDIDATE_SCENE_TEMPLATES.length, 24)
  assert.equal(new Set(CANDIDATE_SCENE_TEMPLATES.map(template => template.id)).size, 24)
  assert.deepEqual(
    CANDIDATE_SCENE_TEMPLATES.map(template => template.id),
    EXPECTED_IDS,
  )
})

test('candidate catalog contains eight templates per family', () => {
  for (const family of ['cinema', 'music', 'space']) {
    assert.equal(
      CANDIDATE_SCENE_TEMPLATES.filter(template => template.family === family).length,
      8,
      `${family} has eight candidates`,
    )
  }
})

test('every candidate is version 1, remains unapproved, and has a four-second default', () => {
  for (const template of CANDIDATE_SCENE_TEMPLATES) {
    assert.equal(template.version, 1, `${template.id} is version 1`)
    assert.equal(template.status, 'candidate', `${template.id} remains a candidate`)
    assert.equal(template.defaultDuration, 4, `${template.id} defaults to four seconds`)
    assert.equal(getCandidateSceneTemplate(template.id), template)
    assert.match(template.promptExample, new RegExp(template.id.replaceAll('-', '\\-')))
  }
  assert.throws(
    () => getCandidateSceneTemplate('approved-or-unknown'),
    /Unknown candidate scene template: approved-or-unknown/,
  )
})

test('all candidates expose the shared required and optional slots with matching kinds', () => {
  for (const template of CANDIDATE_SCENE_TEMPLATES) {
    assert.equal(slot(template, 'hero').required, true, `${template.id}/hero is required`)
    assert.equal(slot(template, 'plate').required, true, `${template.id}/plate is required`)
    assert.deepEqual(slot(template, 'plate').kinds, ['image'], `${template.id}/plate is an image`)
    assert.deepEqual(slot(template, 'foreground').kinds, ['image'], `${template.id}/foreground is an image`)
    assert.equal(slot(template, 'foreground').required, false, `${template.id}/foreground is optional`)

    assert.deepEqual(
      slot(template, 'hero').kinds,
      template.family === 'space' ? ['model3d'] : ['image', 'model3d'],
      `${template.id}/hero matches its family`,
    )
  }
})

test('prop requirements and kinds match the candidate contract', () => {
  const requiredImageOrModel3d = new Set([
    'cinema-two-shot',
    'music-duet',
    'music-orbit',
    'space-orbit',
    'space-docking',
  ])
  const optionalImageOrModel3d = new Set(['music-product'])
  const requiredModel3d = new Set([
    'space-chase',
    'space-broadside',
    'space-shield',
    'space-explosion',
  ])

  for (const template of CANDIDATE_SCENE_TEMPLATES) {
    const expected = requiredImageOrModel3d.has(template.id)
      ? { required: true, kinds: ['image', 'model3d'] }
      : optionalImageOrModel3d.has(template.id)
        ? { required: false, kinds: ['image', 'model3d'] }
        : requiredModel3d.has(template.id)
          ? { required: true, kinds: ['model3d'] }
          : undefined
    const prop = template.slots.find(candidate => candidate.id === 'prop')

    if (!expected) {
      assert.equal(prop, undefined, `${template.id} has no unrequested prop slot`)
      continue
    }

    assert.ok(prop, `${template.id} declares prop`)
    assert.equal(prop.required, expected.required, `${template.id}/prop required flag`)
    assert.deepEqual(prop.kinds, expected.kinds, `${template.id}/prop kinds`)
  }
})

test('slot copy and prompt metadata explain the candidate limits in English', () => {
  for (const template of CANDIDATE_SCENE_TEMPLATES) {
    assert.ok(template.title.length > 0)
    assert.ok(template.description.length > 0)
    assert.ok(template.limits.length >= 6)
    assert.ok(template.limits.some(limit => /At most 2 GLB/.test(limit)), `${template.id} caps GLB use`)
    assert.ok(template.limits.some(limit => /supplied assets/.test(limit)), `${template.id} uses supplied assets`)
    assert.ok(template.limits.some(limit => /No AI-generated video/.test(limit)), `${template.id} rejects AI video`)
    assert.ok(template.limits.some(limit => /No dialogue included/.test(limit)), `${template.id} excludes dialogue`)
    assert.ok(template.limits.some(limit => /BPM/.test(limit)), `${template.id} documents preview audio limits`)
    for (const candidate of template.slots) {
      assert.ok(candidate.description.length > 20, `${template.id}/${candidate.id} explains its role`)
    }
  }
})
