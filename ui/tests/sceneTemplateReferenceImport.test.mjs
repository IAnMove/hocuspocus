import assert from 'node:assert/strict'
import test from 'node:test'
import { APPROVED_REFERENCE_JSON } from '../src/features/sceneTemplates/approvedReferences.ts'
import { CANDIDATE_SCENE_TEMPLATES } from '../src/features/sceneTemplates/catalog.ts'
import { importApprovedReference, verifyReferenceBytes } from '../src/features/sceneTemplates/referenceImport.ts'

test('reference index pins exactly 24 JSON hashes/byte counts, not generated media', () => {
  assert.deepEqual(Object.keys(APPROVED_REFERENCE_JSON), CANDIDATE_SCENE_TEMPLATES.map(item => item.id))
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
  await assert.rejects(verifyReferenceBytes(buffer('ab'), expected), /size/)
})

test('rejects a non-matching download before reading bytes and never fetches remotely', async () => {
  let read = false
  await assert.rejects(importApprovedReference({ size: 0, arrayBuffer: async () => { read = true; return new ArrayBuffer(0) } }, CANDIDATE_SCENE_TEMPLATES[0]), /size/)
  assert.equal(read, false)
})

test('even a same-sized edited reference is rejected rather than compiled as a replacement', async () => {
  const template = CANDIDATE_SCENE_TEMPLATES[0]
  const { bytes } = APPROVED_REFERENCE_JSON[template.id]
  await assert.rejects(importApprovedReference({ size: bytes, arrayBuffer: async () => new ArrayBuffer(bytes) }, template), /JSON changed/)
})
