import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createCharacterKit } from '../src/lib/characterKit'
import { parseCharacterVoice } from '../src/lib/characterVoice'
import { generateSceneSpeechClip } from '../src/lib/sceneSpeech'
import { characterSlotPatch, characterFromSlot, speechCastIsReady } from '../src/features/scene3d/speech/characterBinding'
import { defaultSpeech } from '../src/features/scene3d/speech/types'
import { normalizeStoryCharacter } from '../src/features/stories/model'
import { normalizeScene3DSlot } from '../src/features/scene3d/documentSlot'
import { buildSpeechProduction } from '../src/features/scene3d/speech/production'

const voice = { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'serena', instructions: 'Warm and calm' } as const
const face = { meshIndex: 0, center: [0, 1, 0] as const, size: [.1, .1] as const, skin: [.5, .4, .3] as const,
  eyes: { left: [-.1, 1.2, 0] as const, right: [.1, 1.2, 0] as const, size: [.1, .1] as const, skinLeft: [.5, .4, .3] as const, skinRight: [.5, .4, .3] as const } }
const model = { workspaceId: 'one', filename: 'alice.glb', url: '/unit-character.glb' }
test('Video 3D speech submit ignores a 2D Story kit until a GLB or speech3d kit is present', () => {
  const paper = { ...createCharacterKit('Nilo'), id: 'nilo' }
  const talker = {
    ...createCharacterKit('Alice'),
    id: 'alice',
    speech3d: { model, digest: 'a'.repeat(64) },
  }
  const cast = [{ id: 'nilo', name: 'Nilo', characterKitRef: { id: 'nilo', workspace: 'one' } }]
  assert.equal(speechCastIsReady(cast, {}, {}, [paper, talker]), false)
  assert.equal(speechCastIsReady(cast, {}, {}, [talker]), false)
  assert.equal(speechCastIsReady(
    [{ id: 'alice', name: 'Alice', characterKitRef: { id: 'alice', workspace: 'one' } }],
    {}, {}, [talker],
  ), true)
  assert.equal(speechCastIsReady(cast, { nilo: { name: 'nilo.glb' } }, {}, [talker]), true)
  assert.equal(speechCastIsReady(cast, {}, { nilo: { id: 'alice', workspace: 'one' } }, [talker]), true)
})

test('public voice whitelist rejects secrets and unsupported providers', () => {
  assert.deepEqual(parseCharacterVoice(voice), voice)
  for (const patch of [{ apiKey: 'fake' }, { provider: 'remote' }, { model: 'wrong' }, { voiceId: 'unknown' }]) assert.throws(() => parseCharacterVoice({ ...voice, ...patch }))
})
test('canonical model identity is verified; applying keeps scene turns and old 2D kit assets', async () => {
  const fetch = globalThis.fetch
  globalThis.fetch = async () => new Response('model-bytes')
  try {
    const kit = { ...createCharacterKit('Alice'), voice, provenance: [{ method: 'old-2d' }],
      speech3d: { model, digest: createHash('sha256').update('model-bytes').digest('hex'), settings: { ...defaultSpeech(), face } } }
    const doc = buildSpeechProduction({ kind: 'dialogue', title: 'Text-only', workspace: 'one', duration: 4, offset: 0, cast: [{ id: 'instance-a', name: 'A', model }] })
    const patch = await characterSlotPatch(kit, 'one', 7, doc.slots[0])
    assert.equal(patch.character?.id, 'instance-a')
    assert.equal(patch.character?.kitRef?.id, kit.id)
    assert.deepEqual(patch.speech?.clips, doc.slots[0].speech?.clips)
    assert.equal(patch.speech?.audio, undefined)
    const saved = await characterFromSlot(kit, { ...doc.slots[0], ...patch })
    assert.deepEqual(saved.provenance, kit.provenance)
    assert.deepEqual(saved.poses, kit.poses)
    assert.equal((saved.speech3d?.settings as Record<string, unknown>).clips, undefined)
    await assert.rejects(characterSlotPatch({ ...kit, speech3d: { ...kit.speech3d, digest: 'a'.repeat(64) } }, 'one', 8), /model changed/)
    const reopened = normalizeScene3DSlot({ ...doc.slots[0], ...patch })
    assert.deepEqual(reopened.character, patch.character)
    assert.deepEqual(normalizeStoryCharacter({ id: 'story-alice', characterKitRef: patch.character?.kitRef }, 0).characterKitRef, patch.character?.kitRef)
  } finally { globalThis.fetch = fetch }
})
test('explicit generation sends literal text and voice parameters to the existing job API once', async () => {
  const requests: Record<string, unknown>[] = []
  const result = await generateSceneSpeechClip({ model: voice.model, voice, prompt: 'Hello, Alice.', durationSeconds: 3, workspace: 'one' }, {
    submitGeneration: async params => { requests.push(params); return { job_id: 'owned', status: 'queued' } },
    fetchJobStatus: async () => ({ status: 'completed', output_files: ['clip.wav'] } as never),
  })
  assert.equal(requests.length, 1)
  assert.equal(requests[0].prompt, 'Hello, Alice.')
  assert.equal(requests[0].model_mode, 'serena')
  assert.equal(requests[0].alt_prompt, 'Warm and calm')
  assert.equal(requests[0].workspace, 'one')
  assert.equal(result.filename, 'clip.wav')
})

test('an uncalibrated replacement clears old facial artwork without merging actor identities or turns', async () => {
  const fetch = globalThis.fetch
  globalThis.fetch = async () => new Response('replacement-bytes')
  try {
    const kit = { ...createCharacterKit('New character'), speech3d: {
      model: { ...model, url: '/uncalibrated-replacement.glb' }, digest: createHash('sha256').update('replacement-bytes').digest('hex') } }
    const doc = buildSpeechProduction({ kind: 'dialogue', title: 'Two actors', workspace: 'one', duration: 4, offset: 0,
      cast: [{ id: 'actor-a', name: 'A', model }, { id: 'actor-b', name: 'B', model }] })
    const patches = await Promise.all(doc.slots.map(slot => characterSlotPatch(kit, 'one', 1, { ...slot, character: undefined,
      speech: { ...slot.speech!, face, atlas: { ...model, filename: 'old.png', url: '/old.png' }, style: 'pixel', expression: 'angry' } })))
    assert.notEqual(patches[0].character?.id, patches[1].character?.id)
    for (const [i, patch] of patches.entries()) {
      assert.equal(patch.character?.id, doc.slots[i].id)
      assert.equal(patch.character?.kitRef?.id, kit.id)
      assert.equal(patch.speech?.face, undefined)
      assert.equal(patch.speech?.atlas, undefined)
      assert.equal(patch.speech?.style, defaultSpeech().style)
      assert.equal(patch.speech?.expression, 'neutral')
      assert.deepEqual(patch.speech?.clips, doc.slots[i].speech?.clips)
    }
  } finally { globalThis.fetch = fetch }
})
test('aborting after submit cancels only this request and never submits a replacement', async () => {
  const abort = new AbortController(), cancelled: string[] = []
  await assert.rejects(generateSceneSpeechClip({ model: voice.model, voice, prompt: 'Hello', durationSeconds: 3, signal: abort.signal }, {
    submitGeneration: async () => { abort.abort(); return { job_id: 'owned-only', status: 'queued' } },
    fetchJobStatus: async () => { throw new Error('Must not poll') },
    cancelJob: async id => { cancelled.push(id) },
  }), /abort/i)
  assert.deepEqual(cancelled, ['owned-only'])
})
