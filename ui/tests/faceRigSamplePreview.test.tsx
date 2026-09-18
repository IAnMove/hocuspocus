import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { createCharacterKit } from '../src/lib/characterKit'
import { sampleMouthCues } from '../src/features/characters/sampleMouthCues'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const cues = JSON.parse(readFileSync(new URL('../public/speech-examples/english-preview.json', import.meta.url), 'utf8'))
const kit = createCharacterKit('Sample')
for (const state of ['closed', 'small', 'wide', 'round'] as const) kit.mouth[state] = {
  id: state, name: state, source: `/${state}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState: 'pending',
}

test('included recording drives all four pending mouth shapes and stops without a generation request', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { FaceRigSamplePreview } = await import('../src/features/characters/FaceRigSamplePreview')
  const { FaceRigStatePicker } = await import('../src/features/characters/FaceRigStatePicker')
  const originalFetch = globalThis.fetch
  const requests: string[] = [], states: Array<string | undefined> = []
  let frame: FrameRequestCallback | undefined, plays = 0, pauses = 0
  globalThis.requestAnimationFrame = next => { frame = next; return 1 }
  globalThis.cancelAnimationFrame = () => { frame = undefined }
  dom.window.HTMLMediaElement.prototype.play = async function () { plays++; Object.defineProperty(this, 'paused', { configurable: true, value: false }) }
  dom.window.HTMLMediaElement.prototype.pause = function () { pauses++; Object.defineProperty(this, 'paused', { configurable: true, value: true }) }
  globalThis.fetch = async (input, init) => {
    assert.equal(init?.method ?? 'GET', 'GET')
    assert.equal(String(input), '/speech-examples/english-preview.json')
    requests.push(String(input)); return new Response(JSON.stringify(cues))
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch })
  const stopRef = { current: null as (() => void) | null }
  const view = render(<><FaceRigSamplePreview kit={kit} disabled={false} onStart={() => {}} onViseme={cue => states.push(cue?.sourceState)} stopRef={stopRef} />
    <FaceRigStatePicker kit={kit} selected="wide" disabled={false} onSelect={() => {}} /></>)
  assert.equal(requests.length, 0, 'mounting must not fetch audio or start a job')
  assert.equal(view.queryByRole('button', { name: /Blink/ }), null, 'eyes start collapsed and optional')
  const eyes = view.getByText('Eyes and blinking (optional)').closest('details')!
  fireEvent.click(view.getByRole('button', { name: 'Play included voice sample' }))
  await waitFor(() => assert.equal(plays, 1))
  const audio = view.container.querySelector('audio')!
  assert.equal(audio.getAttribute('src'), '/speech-examples/english-preview.mp3')
  const timeline = sampleMouthCues(cues, kit)
  for (const state of ['closed', 'small', 'wide', 'round']) {
    const cue = timeline.find(item => item.state === state)!
    audio.currentTime = (cue.start + cue.end) / 2
    frame!(0)
    assert.equal(states.at(-1), state)
  }
  fireEvent.click(view.getByRole('button', { name: 'Stop sample' }))
  assert.equal(pauses, 1); assert.equal(states.at(-1), undefined); assert.equal(frame, undefined)
  eyes.open = true
  assert.equal(view.getAllByText('Use the original drawing').length, 2)
  assert.equal(requests.length, 1)
  view.unmount(); assert.equal(stopRef.current, null)
})

test('sample mouth cues use an available shape when a draft pack is incomplete', () => {
  const partial = { ...kit, mouth: { wide: kit.mouth.wide } }
  assert.ok(sampleMouthCues(cues, partial).every(cue => cue.sourceState === 'wide'))
})
