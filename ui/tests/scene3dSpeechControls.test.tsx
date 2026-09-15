import test from 'node:test'
import assert from 'node:assert/strict'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import { defaultSpeech, type Scene3DSpeech } from '../src/features/scene3d/speech/types'
import type { Scene3DSlot } from '../src/features/scene3d/types'

function installDom(url = 'http://localhost/') {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement, HTMLSelectElement: dom.window.HTMLSelectElement,
    HTMLMediaElement: dom.window.HTMLMediaElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'play', { configurable: true, value: () => Promise.resolve() })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'pause', { configurable: true, value() {} })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  return dom
}
installDom()

const slot = (speech: Scene3DSpeech, sourceUrl = '/api/v1/file/mira.glb?workspace=one'): Scene3DSlot => ({
  id: 'subject_1', slot: 'subject_1', position: [0, 0, 0], rotationY: 0, scale: 1, sourceUrl, media: 'model3d', clip: null, speech,
})
const voiced = (): Scene3DSpeech => ({
  ...defaultSpeech(), start: 1, offset: 0.2,
  audio: { workspaceId: 'one', filename: 'line.wav', url: '/api/v1/file/line.wav?workspace=one' },
  cues: [{ start: 0, end: 0.4, viseme: 'A', manual: true }, { start: 0.4, end: 0.8, viseme: 'E' }, { start: 0.8, end: 1.2, viseme: 'M' }],
})

function fakeAudio() {
  class FakeOfflineAudioContext {
    constructor(channels = 1, length = 1, sampleRate = 48000) { this.sampleRate = sampleRate; this.length = length; this.numberOfChannels = channels }
    sampleRate: number; length: number; numberOfChannels: number
    destination = {}
    decodeAudioData() {
      const samples = new Float32Array(32000)
      return { duration: 2, sampleRate: 16000, length: samples.length, numberOfChannels: 1, getChannelData: () => samples }
    }
    createBufferSource() { return { buffer: null as AudioBuffer | null, connect() {}, start() {} } }
    startRendering() { return { getChannelData: () => new Float32Array(this.length || 16000) } }
  }
  Object.defineProperty(globalThis, 'OfflineAudioContext', { configurable: true, value: FakeOfflineAudioContext })
}

test('insecure HTTP shows a microphone alternative and the interval editor', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DSpeechControls } = await import('../src/features/scene3d/speech/Scene3DSpeechControls')
  fakeAudio()
  Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false })
  globalThis.fetch = async (url) => {
    const value = String(url)
    if (value.includes('/outputs')) return Response.json({ outputs: [], total: 0 })
    if (value.includes('/capabilities')) return Response.json({ rhubarb: true, vocalIsolation: { available: false } })
    return new Response('ok')
  }
  try {
    render(<Scene3DSpeechControls slot={slot(voiced())} workspace="one" disabled={false} calibrate={() => undefined}
      onChange={() => {}} onImport={() => {}} onFit={() => {}} />)
    assert.match(screen.getByRole('note').textContent ?? '', /HTTPS or localhost/)
    assert.ok(screen.getByTestId('speech-cue-timeline'))
    fireEvent.click(screen.getByTestId('speech-cue-0'))
    assert.equal(screen.getByTestId('speech-cue-0').getAttribute('data-manual'), 'true')
  } finally { cleanup() }
})

test('reanalyze of a later interval keeps earlier manual corrections', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DSpeechControls } = await import('../src/features/scene3d/speech/Scene3DSpeechControls')
  fakeAudio()
  let next: Scene3DSpeech | undefined
  globalThis.fetch = async (url, init) => {
    const value = String(url)
    if (value.includes('/outputs')) return Response.json({ outputs: [], total: 0 })
    if (value.includes('/capabilities')) return Response.json({ rhubarb: true, vocalIsolation: { available: false } })
    if (value.includes('/analyze')) {
      const size = (init?.body as ArrayBuffer | undefined)?.byteLength ?? 0
      assert.ok(size > 44)
      return Response.json({ mouthCues: [{ start: 0, end: 0.4, value: 'G' }], recognizer: 'phonetic', duration: 0.4 })
    }
    return new Response(new Uint8Array(1000))
  }
  try {
    function Harness() {
      const [speech, setSpeech] = useState(voiced())
      return <Scene3DSpeechControls slot={slot(speech)} workspace="one" disabled={false} calibrate={() => undefined}
        onChange={value => { next = value; setSpeech(value) }} onImport={() => {}} onFit={() => {}} />
    }
    render(<Harness />)
    await waitFor(() => assert.ok(screen.getByLabelText('Waveform')))
    fireEvent.change(screen.getByLabelText('Selection start (source s)'), { target: { value: '0.4' } })
    fireEvent.change(screen.getByLabelText('Selection end (source s)'), { target: { value: '0.8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Recalculate selection' }))
    await waitFor(() => assert.equal(next?.cues.some(cue => cue.viseme === 'F' && !cue.manual), true))
    assert.equal(next!.cues[0].viseme, 'A')
    assert.equal(next!.cues[0].manual, true)
  } finally { cleanup() }
})

test('a late analysis after the character changes does not commit another calibration', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DSpeechControls } = await import('../src/features/scene3d/speech/Scene3DSpeechControls')
  fakeAudio()
  let finish: ((response: Response) => void) | undefined, commits = 0
  globalThis.fetch = async (url) => {
    const value = String(url)
    if (value.includes('/outputs')) return Response.json({ outputs: [], total: 0 })
    if (value.includes('/capabilities')) return Response.json({ rhubarb: true, vocalIsolation: { available: false } })
    if (value.includes('/analyze')) return new Promise<Response>(resolve => { finish = resolve })
    return new Response(new Uint8Array(1000))
  }
  try {
    function Harness({ sourceUrl }: { sourceUrl: string }) {
      const [speech, setSpeech] = useState(voiced())
      return <Scene3DSpeechControls slot={slot(speech, sourceUrl)} workspace="one" disabled={false} calibrate={() => undefined}
        onChange={next => { commits++; setSpeech(next) }} onImport={() => {}} onFit={() => {}} />
    }
    const view = render(<Harness sourceUrl="/api/v1/file/mira.glb?workspace=one" />)
    fireEvent.click(screen.getByRole('button', { name: 'Calculate gestures with Rhubarb (local)' }))
    await waitFor(() => assert.ok(finish))
    view.rerender(<Harness sourceUrl="/api/v1/file/other.glb?workspace=one" />)
    finish!(Response.json({ mouthCues: [{ start: 0, end: 0.4, value: 'F' }], recognizer: 'phonetic', duration: 0.4 }))
    await waitFor(() => assert.equal(screen.getByRole('button', { name: 'Calculate gestures with Rhubarb (local)' }).hasAttribute('disabled'), false))
    assert.equal(commits, 0)
  } finally { cleanup() }
})
