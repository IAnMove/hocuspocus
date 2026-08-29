import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit, emptyCharacterKitLibrary } from '../src/lib/characterKit.ts'
import { consumeFaceRigHandoff, isPersistentCharacterSource, kitFromFaceRigHandoff, queueFaceRigHandoff } from '../src/lib/characterKitHandoff.ts'

const memory = () => {
  const data = new Map()
  return {
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => { data.set(key, String(value)) },
    removeItem: key => { data.delete(key) },
  }
}

test('Face Rig handoff requires a persistent image and can be consumed once', () => {
  assert.equal(isPersistentCharacterSource('blob:temp'), false)
  const storage = memory()
  const queued = queueFaceRigHandoff({ name: 'Luma', source: '/api/v1/file/luma-front.png', workspace: 'default' }, storage)
  assert.equal(queued.source, '/api/v1/file/luma-front.png')
  assert.deepEqual(consumeFaceRigHandoff(storage), queued)
  assert.equal(consumeFaceRigHandoff(storage), null)
  assert.throws(() => queueFaceRigHandoff({ name: 'Luma', source: 'blob:temp', workspace: 'default' }, storage), /temporary browser image/)
})

test('Character Creator handoff reuses a kit with the same base and otherwise drafts a new one', () => {
  const existing = { ...createCharacterKit('Luma'), base: { id: 'luma-base', name: 'Luma', source: '/api/v1/file/luma-front.png', kind: 'image', alphaStatus: 'opaque', reviewState: 'approved' } }
  const library = { ...emptyCharacterKitLibrary(), kits: { [existing.id]: existing }, activeId: existing.id, revision: 2 }
  const reused = kitFromFaceRigHandoff({ name: 'Other', source: '/api/v1/file/luma-front.png', workspace: 'default' }, library)
  assert.equal(reused.id, existing.id)
  assert.equal(reused.name, 'Luma')
  const drafted = kitFromFaceRigHandoff({ name: 'Brin', source: '/api/v1/file/brin-front.png', workspace: 'default' }, library)
  assert.equal(drafted.name, 'Brin')
  assert.equal(drafted.base.source, '/api/v1/file/brin-front.png')
  assert.equal(drafted.base.reviewState, 'approved')
  assert.equal(drafted.provenance[0].method, 'character-creator-handoff')
  assert.equal(library.kits.brin, undefined)
})
