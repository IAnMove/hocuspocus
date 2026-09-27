import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit } from '../src/lib/characterKit'
import { CHARACTER_MOUTH_STATES } from '../src/lib/characterMouthStates'
import { createCharacterSpeechPreview, type characterSpeechPreviewServices } from '../src/lib/characterSpeechPreview'
import { faceRigVisemeAt, previewFaceRigDialogueFromCues } from '../src/lib/characterKitFaceRig'

const actor = () => ({ ...createCharacterKit('Actor'), mouth: Object.fromEntries(CHARACTER_MOUTH_STATES.map(state =>
  [state, { id: state, name: state, source: `/${state}.png`, kind: 'overlay' as const,
    alphaStatus: 'transparent' as const, reviewState: 'approved' as const }])) })

test('voice preview uses the full isolated recording, script and all nine phonetic shapes', async () => {
  const kit = actor(), before = structuredClone(kit), controller = new AbortController()
  const text = 'Esta frase dura bastante más de tres segundos, y necesitamos escucharla hasta el final.'
  const buffer = { duration: 7.5 } as AudioBuffer, wav = new ArrayBuffer(8)
  const result = await createCharacterSpeechPreview({ kit, text, model: 'speech', workspace: 'other', language: 'es', signal: controller.signal }, {
    generate: async options => {
      assert.ok(options.durationSeconds > 3); assert.equal(options.prompt, text)
      assert.equal(options.workspace, 'other'); assert.equal(options.signal, controller.signal)
      return { filename: 'isolated.wav', jobId: 'job', model: 'speech', prompt: text }
    },
    decode: async (url, signal) => { assert.match(url, /isolated\.wav.*workspace=other/); assert.equal(signal, controller.signal); return buffer },
    wav: async actual => { assert.equal(actual, buffer); return wav },
    analyze: async (bytes, options) => {
      assert.equal(bytes, wav); assert.equal(options?.dialogue, text); assert.equal(options?.language, 'es')
      assert.equal(options?.signal, controller.signal)
      return { recognizer: 'phonetic', duration: 7.5,
        mouthCues: ['X', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'].map((value, i) => ({ start: i * .7, end: i * .7 + .5, value })) }
    },
  })
  assert.equal(result.preview.end, 7.5)
  assert.deepEqual(new Set(result.preview.visemes.map(cue => cue.state)), new Set(CHARACTER_MOUTH_STATES))
  assert.ok(result.preview.visemes.every(cue => !cue.fallback))
  assert.equal(faceRigVisemeAt(result.preview, .6)?.state, 'closed', 'gaps close the mouth')
  assert.equal(faceRigVisemeAt(result.preview, 7.4)?.state, 'closed', 'the silent tail closes the mouth')
  assert.equal(faceRigVisemeAt(result.preview, 7.6), undefined)
  assert.deepEqual(kit, before, 'preview never approves or saves a kit')
})

test('a failed or cancelled analysis never returns an apparently successful text-timed preview', async () => {
  const options = { kit: actor(), text: 'Hola', model: 'speech', workspace: 'default', language: 'es', signal: new AbortController().signal }
  const services: typeof characterSpeechPreviewServices = {
    generate: async () => ({ filename: 'voice.wav', jobId: 'job', model: 'speech', prompt: 'Hola' }),
    decode: async () => ({ duration: 4 }) as AudioBuffer,
    wav: async () => new ArrayBuffer(8),
    analyze: async () => { throw new Error('Phonetic analysis unavailable') },
  }
  await assert.rejects(createCharacterSpeechPreview(options, services), /Phonetic analysis unavailable/)
  const abort = new AbortController()
  await assert.rejects(createCharacterSpeechPreview({ ...options, signal: abort.signal }, { ...services,
    analyze: async () => { abort.abort(); return { recognizer: 'phonetic', duration: 4, mouthCues: [] } },
  }), { name: 'AbortError' })
})

test('legacy previews retain defined fallback shapes and reject out-of-range analysis', () => {
  const kit = actor()
  for (const state of CHARACTER_MOUTH_STATES.slice(4)) delete kit.mouth[state]
  const preview = previewFaceRigDialogueFromCues(kit, 'Hola', { mouthCues: [
    { start: 0, end: .2, value: 'A' }, { start: .2, end: .4, value: 'C' }, { start: .4, end: .6, value: 'F' },
  ] }, 1)
  assert.deepEqual(preview.visemes.slice(0, 3).map(cue => cue.sourceState), ['closed', 'wide', 'round'])
  assert.throws(() => previewFaceRigDialogueFromCues(kit, 'Hola', [{ start: 0, end: 2, viseme: 'A' }], 1), /exceed/)
})
