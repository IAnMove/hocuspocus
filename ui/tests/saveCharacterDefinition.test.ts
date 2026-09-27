import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createCharacterKit, type CharacterKit } from '../src/lib/characterKit'
import { clearSpeechDraft, readSpeechDraft, writeSpeechDraft } from '../src/lib/characterSpeechDraft'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, sessionStorage: dom.window.sessionStorage })

function image(id: string, source: string) {
  return { id, name: id, source, kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const }
}

test('saving a new character does not consume the general workshop draft or overwrite that kit', async t => {
  const { saveCharacterDefinition } = await import('../src/features/characters/saveCharacterDefinition')
  const alice = createCharacterKit('Alice')
  alice.id = 'alice-kit'
  alice.base = image('alice-base', '/alice.png')
  alice.mouth = { wide: { ...image('alice-mouth', '/alice-mouth.png'), kind: 'overlay' } }
  writeSpeechDraft('studio', { baseRevision: 7, kit: alice })
  const library = { version: 1 as const, revision: 7, activeId: alice.id, kits: { [alice.id]: { ...alice } } }
  const writes: Array<{ id: string; name: string; mouth: CharacterKit['mouth'] }> = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url.includes('/character-kits/library/kits/') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      writes.push({ id: body.kit.id, name: body.kit.name, mouth: body.kit.mouth })
      return new Response(JSON.stringify({
        version: 1, revision: 8, activeId: body.kit.id,
        kits: { ...library.kits, [body.kit.id]: body.kit },
      }))
    }
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${url}`)
  }
  t.after(() => { globalThis.fetch = originalFetch; clearSpeechDraft('studio'); clearSpeechDraft('studio', alice.id) })
  const saved = await saveCharacterDefinition({
    workspace: 'studio', library, id: '', kit: undefined, workshop: null,
    update: async current => {
      const previous = current ?? { ...createCharacterKit('Bob'), id: 'new-bob-id' }
      return { ...previous, name: 'Bob', voice: { voiceId: 'serena' } }
    },
    isCurrent: () => true,
  })
  assert.deepEqual(writes, [{ id: 'new-bob-id', name: 'Bob', mouth: {} }])
  assert.equal(saved.kit.id, 'new-bob-id')
  assert.equal(saved.kit.name, 'Bob')
  assert.equal(readSpeechDraft('studio')?.kit.id, 'alice-kit')
  assert.deepEqual(readSpeechDraft('studio')?.kit.mouth, alice.mouth)
})

test('saving a linked character still merges its scoped mouth recovery', async t => {
  const { saveCharacterDefinition } = await import('../src/features/characters/saveCharacterDefinition')
  const kit = createCharacterKit('Linked')
  kit.id = 'linked-kit'
  kit.base = image('linked-base', '/linked.png')
  const edited = { ...kit, mouth: { wide: { ...image('linked-mouth', '/linked-mouth.png'), kind: 'overlay' as const } } }
  writeSpeechDraft('studio', { baseRevision: 3, kit: edited }, kit.id)
  const library = { version: 1 as const, revision: 3, activeId: kit.id, kits: { [kit.id]: kit } }
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    if (String(input).includes('/character-kits/library/kits/') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      return new Response(JSON.stringify({
        version: 1, revision: 4, activeId: body.kit.id, kits: { [body.kit.id]: body.kit },
      }))
    }
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${input}`)
  }
  t.after(() => { globalThis.fetch = originalFetch; clearSpeechDraft('studio', kit.id) })
  const saved = await saveCharacterDefinition({
    workspace: 'studio', library, id: kit.id, kit, workshop: null,
    update: async current => ({ ...current!, name: 'Linked', voice: { voiceId: 'serena' } }),
    isCurrent: () => true,
  })
  assert.equal(saved.kit.id, kit.id)
  assert.deepEqual(saved.kit.mouth, edited.mouth)
  assert.equal(readSpeechDraft('studio', kit.id), null)
})
