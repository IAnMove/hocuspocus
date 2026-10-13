import assert from 'node:assert/strict'
import test from 'node:test'
import { APPROVED_REFERENCE_JSON } from '../src/features/sceneTemplates/approvedReferences.ts'
import { CANDIDATE_SCENE_TEMPLATES, SCENE_TEMPLATE_ALIASES, resolveSceneTemplate } from '../src/features/sceneTemplates/catalog.ts'
import { importApprovedReference, verifyReferenceBytes } from '../src/features/sceneTemplates/referenceImport.ts'

// The 24 «coral v1» originals the owner approved by eye. Seven were merged into other cards on 2026-10-12; their
// published hashes stay as a historical record and each id still compiles, as an alias of its card.
const CORAL_V1 = [
  'cinema-establishing', 'cinema-reveal', 'cinema-closeup', 'cinema-two-shot', 'cinema-detail', 'cinema-hero', 'cinema-isolation', 'cinema-tracking',
  'music-pulse', 'music-duet', 'music-chorus', 'music-orbit', 'music-parallax', 'music-stage', 'music-product', 'music-finale',
  'space-cruise', 'space-orbit', 'space-docking', 'space-chase', 'space-broadside', 'space-shield', 'space-explosion', 'space-warp',
]

test('reference index keeps the 24 coral v1 hashes/byte counts as history, not generated media', () => {
  assert.deepEqual(Object.keys(APPROVED_REFERENCE_JSON), CORAL_V1)
  const merged = CORAL_V1.filter(id => id in SCENE_TEMPLATE_ALIASES)
  assert.deepEqual(merged, ['cinema-isolation', 'music-chorus', 'music-parallax', 'music-stage', 'music-finale', 'space-shield', 'space-explosion'])
  assert.deepEqual(CORAL_V1.filter(id => !merged.includes(id)), CANDIDATE_SCENE_TEMPLATES.map(item => item.id).filter(id => !id.startsWith('walk-') && id !== 'character-reaction'))
  for (const id of CORAL_V1) assert.ok(resolveSceneTemplate(id).template, `${id} still compiles`)
  for (const reference of Object.values(APPROVED_REFERENCE_JSON)) {
    assert.deepEqual(Object.keys(reference).sort(), ['bytes', 'sha256'])
    assert.match(reference.sha256, /^[a-f0-9]{64}$/)
    assert.ok(reference.bytes > 0 && reference.bytes < 4_000_000)
  }
})

test('verifies actual SHA-256 bytes with the known abc vector; changed bytes fail', async () => {
  const expected = { bytes: 3, sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' }
  const buffer = text => new TextEncoder().encode(text).buffer
  await verifyReferenceBytes(buffer('abc'), expected)
  await assert.rejects(verifyReferenceBytes(buffer('abd'), expected), /JSON changed/)
  await assert.rejects(verifyReferenceBytes(buffer('ab'), expected), /size does not match/)
})

test('rejects a non-matching download before reading bytes and never fetches remotely', async () => {
  let read = false
  await assert.rejects(importApprovedReference({ size: 0, arrayBuffer: async () => { read = true; return new ArrayBuffer(0) } }, CANDIDATE_SCENE_TEMPLATES[0]), /size does not match/)
  assert.equal(read, false)
})

test('even a same-sized edited reference is rejected rather than compiled as a replacement', async () => {
  const template = CANDIDATE_SCENE_TEMPLATES[0]
  const { bytes } = APPROVED_REFERENCE_JSON[template.id]
  await assert.rejects(importApprovedReference({ size: bytes, arrayBuffer: async () => new ArrayBuffer(bytes) }, template), /JSON changed/)
})
