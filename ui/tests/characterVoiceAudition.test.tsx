import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { CharacterVoice } from '../src/lib/characterVoice'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
const voice: CharacterVoice = { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'ryan', instructions: 'Warm storyteller' }
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })

test('voice origin and an explicit Spanish audition are available before saving a character or setting up mouths', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CharacterVoiceFields } = await import('../src/features/characters/CharacterVoiceFields')
  const original = globalThis.fetch, requests: Record<string, unknown>[] = [], changes: unknown[] = []
  globalThis.fetch = async (input, init) => {
    if (String(input).endsWith('/generate')) { requests.push(JSON.parse(String(init?.body))); return json({ job_id: 'audition', status: 'queued' }) }
    return json({ job_id: 'audition', status: 'completed', output_files: ['spanish-sample.wav'] })
  }
  t.after(() => { cleanup(); globalThis.fetch = original })
  const view = render(<CharacterVoiceFields workspace="my-studio" value={voice} onChange={value => changes.push(value)} />)
  assert.ok(view.getByRole('option', { name: 'Ryan · English' }))
  assert.ok(view.getByRole('option', { name: 'Eric · Chinese · Sichuan' }))
  assert.equal(requests.length, 0)
  fireEvent.change(view.getByLabelText('Sample sentence language'), { target: { value: 'es' } })
  assert.equal(requests.length, 0)
  fireEvent.click(view.getByRole('button', { name: 'Generate voice sample' }))
  await waitFor(() => assert.ok(view.getByLabelText('Selected voice sample').getAttribute('src')?.includes('spanish-sample.wav')))
  assert.equal(requests.length, 1)
  assert.equal(requests[0].workspace, 'my-studio')
  assert.equal(requests[0].model_mode, 'ryan')
  assert.equal(requests[0].alt_prompt, voice.instructions)
  assert.match(String(requests[0].prompt), /historia en español/)
  assert.deepEqual(changes, [])
  const audio = view.getByLabelText('Selected voice sample') as HTMLAudioElement
  let stopped = 0
  Object.defineProperty(audio, 'paused', { value: false, configurable: true })
  audio.pause = () => { stopped++; Object.defineProperty(audio, 'paused', { value: true }) }
  fireEvent.change(view.getByLabelText('Sample sentence language'), { target: { value: 'en' } })
  assert.equal(stopped, 1)
  assert.equal(view.queryByLabelText('Selected voice sample'), null)
})

test('switching voices cancels only the owned audition and never exposes its late audio under the new voice', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CharacterVoiceFields } = await import('../src/features/characters/CharacterVoiceFields')
  const original = globalThis.fetch, cancelled: string[] = []
  let release!: (response: Response) => void, pending = false, count = 0
  globalThis.fetch = async input => {
    const path = String(input)
    if (path.endsWith('/generate')) return json({ job_id: ++count === 1 ? 'old-voice' : 'new-voice', status: 'queued' })
    if (path.includes('/cancel/')) { cancelled.push(path); return json({}) }
    if (path.endsWith('/status/old-voice')) { pending = true; return new Promise<Response>(resolve => { release = resolve }) }
    return json({ job_id: 'new-voice', status: 'completed', output_files: ['new-voice.wav'] })
  }
  t.after(() => { cleanup(); globalThis.fetch = original })
  const view = render(<CharacterVoiceFields workspace="default" value={voice} onChange={() => {}} />)
  fireEvent.click(view.getByRole('button', { name: 'Generate voice sample' }))
  await waitFor(() => assert.ok(pending))
  view.rerender(<CharacterVoiceFields workspace="default" value={{ ...voice, voiceId: 'aiden' }} onChange={() => {}} />)
  await waitFor(() => assert.deepEqual(cancelled, ['/api/v1/cancel/old-voice']))
  release(json({ job_id: 'old-voice', status: 'completed', output_files: ['wrong-voice.wav'] }))
  assert.equal(view.queryByLabelText('Selected voice sample'), null)
  fireEvent.click(view.getByRole('button', { name: 'Generate voice sample' }))
  await waitFor(() => assert.match(view.getByLabelText('Selected voice sample').getAttribute('src')!, /new-voice.wav/))
  assert.deepEqual(cancelled, ['/api/v1/cancel/old-voice'])
})
