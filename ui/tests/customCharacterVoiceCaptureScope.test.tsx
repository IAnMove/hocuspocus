import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { createHash } from 'node:crypto'
import { JSDOM } from 'jsdom'
import { createCharacterKit } from '../src/lib/characterKit'
import type { CustomCharacterVoice } from '../src/lib/characterVoice'
import { buildSpeechProduction } from '../src/features/scene3d/speech/production'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
dom.window.HTMLMediaElement.prototype.pause = () => {}
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })

test('applying a saved character cannot replace a reference voice while its recording is uploading', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CharacterDefinitionEditor } = await import('../src/features/characters/CharacterDefinitionEditor')
  const stored: CustomCharacterVoice = { provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference',
    name: 'Saved voice', referenceAudio: '/api/v1/uploads/stored.wav', transcript: 'The saved recording.', language: 'auto' }
  const model = { workspaceId: 'studio', filename: 'actor.glb', url: '/unit-capture-scope.glb' }
  const kit = { ...createCharacterKit('Actor'), id: 'actor', voice: stored,
    speech3d: { model, digest: createHash('sha256').update('model-bytes').digest('hex') } }
  const doc = buildSpeechProduction({ kind: 'dialogue', title: 'Scope test', workspace: 'studio', duration: 5, offset: 0,
    cast: [{ id: 'actor', name: 'Actor', model }] })
  const slot = { ...doc.slots[0], character: { id: 'actor', name: 'Actor', kitRef: { id: 'actor', workspace: 'studio' }, voice: stored } }
  const originalFetch = globalThis.fetch, originalAudio = globalThis.OfflineAudioContext
  let releaseUpload!: (response: Response) => void, uploadStarted = false
  const changes: unknown[] = []
  globalThis.OfflineAudioContext = class {
    destination = {}
    async decodeAudioData() { return { duration: 6 } }
    createBufferSource() { return { connect() {}, start() {} } }
    async startRendering() { return { getChannelData: () => new Float32Array(6 * 16000).fill(.1) } }
  } as unknown as typeof OfflineAudioContext
  globalThis.fetch = async url => {
    if (String(url).includes('/character-kits/library')) return json({ version: 1, revision: 1, kits: { actor: kit } })
    if (String(url).endsWith('/upload-audio')) {
      uploadStarted = true
      return new Promise<Response>(resolve => { releaseUpload = resolve })
    }
    if (String(url) === model.url) return new Response('model-bytes')
    throw new Error(`Unexpected request: ${String(url)}`)
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch; globalThis.OfflineAudioContext = originalAudio })
  const view = render(<CharacterDefinitionEditor workspace="studio" slot={slot} onApply={patch => changes.push(patch)} />)
  await waitFor(() => assert.equal(view.getByTestId('character-voice').matches(':disabled'), false))
  fireEvent.change(view.getByLabelText('Voice name'), { target: { value: 'Replacement voice' } })
  changes.length = 0
  fireEvent.change(view.getByLabelText('Import audio sample'), { target: { files: [new File(['audio'], 'replacement.mp3', { type: 'audio/mpeg' })] } })
  await waitFor(() => assert.equal(uploadStarted, true))
  const apply = view.getByTestId('apply-character')
  assert.equal(apply.matches(':disabled'), true, 'applying a saved voice must not race its pending replacement upload')
  fireEvent.click(apply)
  assert.deepEqual(changes, [])
  releaseUpload(json({ filename: 'replacement.wav', url: '/api/v1/uploads/replacement.wav', path: '/private/replacement.wav' }))
  await waitFor(() => assert.equal(view.getByLabelText('Original voice sample').getAttribute('src'), '/api/v1/uploads/replacement.wav'))
  assert.equal((view.getByLabelText('Voice name') as HTMLInputElement).value, 'Replacement voice')
  assert.equal((view.getByLabelText('Exact sample transcript') as HTMLTextAreaElement).value, '')
})
