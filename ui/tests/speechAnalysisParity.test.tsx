import test from 'node:test'
import assert from 'node:assert/strict'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import { analyzeSceneSpeechDetailed, setupSpeechPhonemes } from '../src/api/scene3dSpeech'
import { SpeechAnalysisControls } from '../src/features/scene3d/speech/SpeechAnalysisControls'
import { defaultSpeech, type SpeechAnalysisSettings } from '../src/features/scene3d/speech/types'
import { parseSpeech } from '../src/features/scene3d/speech/track'
import { speechClips } from '../src/features/scene3d/speech/timeline'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement, HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('browser sends the same engine, literal transcript, language and isolation as MCP', async () => {
  const requests: { url: string; body: Record<string, unknown> }[] = []
  const previous = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), body: JSON.parse(options!.body as string) })
    return Response.json({ engine: 'phoneme', requestedEngine: 'phoneme', driver: 'phoneme-vocals',
      analysisSource: 'isolated-vocals', recognizer: 'wav2vec2-phoneme', duration: 1,
      mouthCues: [{ start: .1, end: 1, value: 'E' }] })
  }
  try {
    const data = await analyzeSceneSpeechDetailed(new Uint8Array([1, 2, 3]).buffer, {
      engine: 'phoneme', dialogue: '¡Four, one more!', language: 'en', isolateVocals: true,
    })
    assert.match(requests[0].url, /speech\/analyze\?isolate_vocals=true$/)
    assert.deepEqual(requests[0].body, { wavBase64: 'AQID', dialogue: '¡Four, one more!', language: 'en', engine: 'phoneme' })
    assert.equal(data.engine, 'phoneme')
  } finally { globalThis.fetch = previous }
})

test('native lip-sync engine, transcript and fallback survive a scene JSON round trip', () => {
  const value = { ...defaultSpeech(), driver: 'phoneme-vocals' as const, analysisEngine: 'auto' as const,
    language: 'en', text: 'Four', analysisFallback: null, morph: true,
    cues: [{ start: 18.3, end: 19.1, viseme: 'O' as const }], offset: 18.3 }
  assert.deepEqual(JSON.parse(JSON.stringify(parseSpeech(JSON.parse(JSON.stringify(value))))), value)
  const legacy = speechClips(value)[0]
  assert.equal(legacy.analysisEngine, 'auto')
  assert.equal(legacy.text, 'Four')
  assert.equal(legacy.language, 'en')
  assert.equal(legacy.analysisFallback, null)
  const clips = parseSpeech({ ...defaultSpeech(), clips: [{ id: 'sing', ...value }] })!.clips!
  assert.equal(clips[0].driver, 'phoneme-vocals')
  assert.equal(clips[0].analysisEngine, 'auto')
  assert.equal(clips[0].text, 'Four')
  for (const patch of [{ analysisEngine: 'unknown' }, { text: '\0' }, { language: 'x'.repeat(17) }]) {
    assert.throws(() => parseSpeech({ ...value, ...patch }))
  }
})

test('the visible engine selector preserves the transcript and never installs on mount', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const previous = globalThis.fetch
  const calls: string[] = []
  let saved: SpeechAnalysisSettings = { text: 'Four', language: 'en' }
  globalThis.fetch = async url => {
    calls.push(String(url))
    return Response.json({ phonemes: { installed: true, dependencies_available: true } })
  }
  function Harness() {
    const [settings, setSettings] = useState(saved)
    return <SpeechAnalysisControls settings={settings} disabled={false} onChange={value => { saved = value; setSettings(value) }} />
  }
  try {
    render(<Harness />)
    await waitFor(() => assert.ok(screen.getByText('Phoneme alignment is ready. Automatic uses it.')))
    fireEvent.change(screen.getByLabelText('Lip-sync engine'), { target: { value: 'phoneme' } })
    assert.deepEqual(saved, { analysisEngine: 'phoneme', text: 'Four', language: 'en' })
    assert.equal(calls.length, 1)
    assert.match(calls[0], /\/speech\/capabilities$/)
  } finally { cleanup(); globalThis.fetch = previous }
})

test('installer button, API and Wizard use the exact same explicit native setup command', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const previous = globalThis.fetch
  const commands: unknown[] = []
  globalThis.fetch = async (url, options) => {
    if (String(url).endsWith('/capabilities')) return Response.json({ phonemes: { installed: false, dependencies_available: true } })
    assert.match(String(url), /\/speech\/phonemes\/setup$/)
    commands.push(JSON.parse(options!.body as string))
    return Response.json({ version: 1, operation: 'audio.phonemes.setup', status: 'completed', result: { installed: true, device: 'cpu' } })
  }
  try {
    render(<SpeechAnalysisControls settings={{}} disabled={false} onChange={() => {}} />)
    await waitFor(() => assert.ok(screen.getByRole('button', { name: 'Install phoneme engine (1.26 GB)' })))
    assert.equal(commands.length, 0)
    fireEvent.click(screen.getByRole('button', { name: 'Install phoneme engine (1.26 GB)' }))
    await waitFor(() => assert.equal(commands.length, 1))
    await setupSpeechPhonemes(false)
    const { getCapability } = await import('../src/features/agent/capabilityRegistry')
    const wizard = getCapability('speech_analysis_engine')!
    const action = wizard.resolve({ type: 'speech_analysis_engine', install: true })!
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters')
    const result = await wizard.execute(action, { adapters: createDefaultApplicationAdapters() })
    assert.equal(result.metadata?.installed, true)
    assert.equal(result.metadata?.installRequested, true)
    assert.equal(wizard.resolve({ install: 1 }), null)
    assert.deepEqual(commands, [{ version: 1, input: { install: true } }, { version: 1, input: { install: false } }, { version: 1, input: { install: true } }])
    const schema = getCapability('prepare_programmatic_video')!.inputSchema as { properties: { scene_command: { description: string } } }
    assert.match(schema.properties.scene_command.description, /engine="auto"\|"phoneme"\|"rhubarb"/)
  } finally { cleanup(); globalThis.fetch = previous }
})
