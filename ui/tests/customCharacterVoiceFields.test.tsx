import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import type { CharacterVoice, CustomCharacterVoice } from '../src/lib/characterVoice'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
dom.window.HTMLMediaElement.prototype.pause = () => {}
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
const saved: CustomCharacterVoice = { provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference', name: 'My narrator',
  referenceAudio: '/api/v1/uploads/narrator.wav', transcript: 'This is my own voice.', language: 'auto' }

function mockDecode(t: test.TestContext, duration = 6) {
  const original = globalThis.OfflineAudioContext
  const samples = new Float32Array(6 * 16000).fill(.1)
  globalThis.OfflineAudioContext = class {
    destination = {}
    async decodeAudioData() { return { duration } }
    createBufferSource() { return { connect() {}, start() {} } }
    async startRendering() { return { getChannelData: () => samples } }
  } as unknown as typeof OfflineAudioContext
  t.after(() => { globalThis.OfflineAudioContext = original })
}

test('imported recording becomes a reusable voice only with name and transcript; saved voices can be selected for another character', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CharacterVoiceFields } = await import('../src/features/characters/CharacterVoiceFields')
  const { createCharacterKit } = await import('../src/lib/characterKit')
  mockDecode(t)
  const original = globalThis.fetch; let uploads = 0, current: CharacterVoice | undefined
  globalThis.fetch = async (url, init) => {
    assert.ok(String(url).endsWith('/upload-audio'))
    const audio = (init?.body as FormData).get('file') as File
    assert.equal(audio.type, 'audio/wav'); assert.ok(audio.size > 44)
    uploads++
    return json({ filename: 'recording.wav', url: '/api/v1/uploads/recording.wav', path: '/server/private/recording.wav' })
  }
  t.after(() => { cleanup(); globalThis.fetch = original })
  function Editor() {
    const [value, setValue] = useState<CharacterVoice>()
    return <CharacterVoiceFields workspace="characters" value={value} onChange={next => { current = next; setValue(next) }}
      savedKits={[{ ...createCharacterKit('Other actor'), id: 'other', voice: saved }]} />
  }
  const view = render(<Editor />)
  fireEvent.change(view.getByTestId('character-voice'), { target: { value: 'new-reference' } })
  assert.equal(view.queryByRole('button', { name: 'Generate voice sample' }), null)
  fireEvent.change(view.getByLabelText('Voice name'), { target: { value: 'Imported actor' } })
  fireEvent.change(view.getByLabelText('Import audio sample'), { target: { files: [new File(['audio'], 'test.mp3', { type: 'audio/mpeg' })] } })
  await waitFor(() => assert.ok(view.getByLabelText('Original voice sample')))
  assert.equal(view.queryByRole('button', { name: 'Generate voice sample' }), null)
  fireEvent.change(view.getByLabelText('Exact sample transcript'), { target: { value: 'These are the words I recorded.' } })
  assert.ok(view.getByRole('button', { name: 'Generate voice sample' }))
  assert.equal(current?.model, 'qwen3_tts_base')
  assert.equal((current as CustomCharacterVoice).referenceAudio, '/api/v1/uploads/recording.wav')
  assert.ok(!JSON.stringify(current).includes('/server/private'))
  fireEvent.change(view.getByTestId('character-voice'), { target: { value: 'saved:other' } })
  assert.deepEqual(current, saved)
  assert.equal(uploads, 1, 'selecting a saved voice neither uploads nor generates')
})

test('invalid duration leaves the previous voice intact and does not upload a silently cropped recording', async t => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { CustomCharacterVoiceFields } = await import('../src/features/characters/CustomCharacterVoiceFields')
  mockDecode(t, 31)
  const original = globalThis.fetch; let requests = 0
  globalThis.fetch = async () => { requests++; throw new Error('Must not upload') }
  t.after(() => { cleanup(); globalThis.fetch = original })
  const changes: unknown[] = []
  const view = render(<CustomCharacterVoiceFields value={saved} onChange={value => changes.push(value)} />)
  fireEvent.change(view.getByLabelText('Import audio sample'), { target: { files: [new File(['audio'], 'long.wav', { type: 'audio/wav' })] } })
  await view.findByText(/The sample must last 3–30 seconds/)
  assert.deepEqual(changes, []); assert.equal(requests, 0)
  assert.equal(view.getByLabelText('Original voice sample').getAttribute('src'), saved.referenceAudio)
})

test('cancelling microphone permission disposes a late stream without replacing the saved voice', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CustomCharacterVoiceFields } = await import('../src/features/characters/CustomCharacterVoiceFields')
  let grant!: (stream: MediaStream) => void, stopped = 0
  const originalRecorder = globalThis.MediaRecorder
  Object.defineProperty(dom.window, 'isSecureContext', { value: true, configurable: true })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: () => new Promise<MediaStream>(resolve => { grant = resolve }) } })
  globalThis.MediaRecorder = class { constructor() { throw new Error('Cancelled permission must not start recording') } } as unknown as typeof MediaRecorder
  t.after(() => { cleanup(); globalThis.MediaRecorder = originalRecorder; Reflect.deleteProperty(navigator, 'mediaDevices') })
  const changes: unknown[] = []
  const view = render(<CustomCharacterVoiceFields value={saved} onChange={value => changes.push(value)} />)
  fireEvent.click(view.getByRole('button', { name: 'Record with microphone' }))
  await view.findByText(/Allow microphone access/)
  fireEvent.click(view.getByRole('button', { name: 'Cancel recording' }))
  grant({ getTracks: () => [{ stop: () => stopped++ }] } as unknown as MediaStream)
  await waitFor(() => assert.equal(stopped, 1))
  assert.deepEqual(changes, [])
})

test('recording a new reference stops microphone tracks, uploads WAV and requires its new transcript', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CustomCharacterVoiceFields } = await import('../src/features/characters/CustomCharacterVoiceFields')
  mockDecode(t)
  const originalRecorder = globalThis.MediaRecorder, originalFetch = globalThis.fetch
  let stopped = 0, uploads = 0
  Object.defineProperty(dom.window, 'isSecureContext', { value: true, configurable: true })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
    getUserMedia: async () => ({ getTracks: () => [{ stop: () => stopped++ }] }),
  } })
  globalThis.MediaRecorder = class {
    state = 'inactive'; mimeType = 'audio/webm'
    ondataavailable?: (event: { data: Blob }) => void
    onstop?: () => void
    start() { this.state = 'recording' }
    stop() { this.state = 'inactive'; this.ondataavailable?.({ data: new Blob(['recorded audio']) }); this.onstop?.() }
  } as unknown as typeof MediaRecorder
  globalThis.fetch = async (url, init) => {
    assert.ok(String(url).endsWith('/upload-audio')); uploads++
    assert.equal(((init?.body as FormData).get('file') as File).type, 'audio/wav')
    return json({ filename: 'new.wav', url: '/api/v1/uploads/new.wav', path: '/private/new.wav' })
  }
  t.after(() => { cleanup(); globalThis.MediaRecorder = originalRecorder; globalThis.fetch = originalFetch; Reflect.deleteProperty(navigator, 'mediaDevices') })
  const changes: CustomCharacterVoice[] = []
  const view = render(<CustomCharacterVoiceFields value={saved} onChange={value => changes.push(value)} />)
  fireEvent.click(view.getByRole('button', { name: 'Record with microphone' }))
  await view.findByText(/Recording · 30 seconds/)
  fireEvent.click(view.getByRole('button', { name: 'Stop recording' }))
  await waitFor(() => assert.equal(changes.length, 1))
  assert.equal(stopped, 1); assert.equal(uploads, 1)
  assert.equal(changes[0].referenceAudio, '/api/v1/uploads/new.wav')
  assert.equal(changes[0].transcript, '', 'never apply an old transcript to a replacement recording')
  assert.equal(changes[0].name, saved.name)
})
