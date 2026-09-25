import test from 'node:test'
import assert from 'node:assert/strict'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import { defaultSpeech, type MouthCue, type Scene3DSpeech } from '../src/features/scene3d/speech/types'
import { parseMouthCues, parseSpeech } from '../src/features/scene3d/speech/track'
import { addSilence, moveCueBound, replaceCueInterval, setCueViseme, sourceToScene, waveformPeaks } from '../src/features/scene3d/speech/cueEdit'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement, HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLMediaElement: dom.window.HTMLMediaElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'play', { configurable: true, value: () => Promise.resolve() })
Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'pause', { configurable: true, value() {} })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const cues = (): MouthCue[] => [
  { start: 0, end: 0.4, viseme: 'A' },
  { start: 0.4, end: 0.8, viseme: 'E' },
  { start: 0.8, end: 1.2, viseme: 'M' },
]
const speechWith = (list: MouthCue[], extra: Partial<Scene3DSpeech> = {}): Scene3DSpeech => ({
  ...defaultSpeech(), start: 3, offset: 0.2, cues: list,
  audio: { workspaceId: 'one', filename: 'line.wav', url: '/api/v1/file/line.wav?workspace=one' }, ...extra,
})

test('source, offset and scene clocks stay distinct', () => {
  assert.equal(sourceToScene(0.7, { start: 3, offset: 0.2 }), 3.5)
  assert.deepEqual(waveformPeaks(new Float32Array([0, 1, -1, 0]), 2), [1, 1])
})

test('manual viseme and bound edits survive JSON reopen and stay identified', () => {
  let next = setCueViseme(cues(), 0, 'O')
  next = moveCueBound(next, 1, 'end', 0.7)
  const speech = parseSpeech(JSON.parse(JSON.stringify(speechWith(next))))!
  assert.equal(speech.cues[0].viseme, 'O')
  assert.equal(speech.cues[0].manual, true)
  assert.equal(speech.cues[1].end, 0.7)
  assert.equal(speech.cues[1].manual, true)
  assert.equal(speech.cues[2].viseme, 'M')
  assert.equal(speech.cues[2].manual, undefined)
  assert.deepEqual(parseMouthCues(speech.cues), speech.cues)
})

test('reanalyze replaces only the interval and keeps outside corrections', () => {
  const edited = setCueViseme(cues(), 0, 'U')
  const replaced = replaceCueInterval(edited, 0.4, 0.8, [{ start: 0.4, end: 0.8, viseme: 'F' }])
  assert.equal(replaced[0].viseme, 'U')
  assert.equal(replaced[0].manual, true)
  assert.equal(replaced[1].viseme, 'F')
  assert.equal(replaced[1].manual, undefined)
  assert.equal(replaced[2].viseme, 'M')
  const silent = addSilence(replaced, 0.8, 1.2)
  assert.equal(silent[2].viseme, 'rest')
  assert.equal(silent[2].manual, true)
  assert.equal(silent[0].viseme, 'U')
})

test('timeline can select an interval, retarget a viseme, add silence and loop', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { CueTimeline } = await import('../src/features/scene3d/speech/CueTimeline')
  globalThis.fetch = async () => new Response(new Uint8Array(32))
  class FakeOfflineAudioContext {
    decodeAudioData() {
      return { duration: 1.2, sampleRate: 8, getChannelData: () => new Float32Array(10) }
    }
  }
  Object.defineProperty(globalThis, 'OfflineAudioContext', { configurable: true, value: FakeOfflineAudioContext })
  function Harness() {
    const [speech, setSpeech] = useState(speechWith(cues()))
    return <CueTimeline speech={speech} disabled={false} onChange={setSpeech} onReanalyze={() => {}} />
  }
  try {
    render(<Harness />)
    assert.match(screen.getByTestId('speech-cue-clocks').textContent ?? '', /Source/)
    assert.match(screen.getByTestId('speech-cue-clocks').textContent ?? '', /Scene/)
    assert.match(screen.getByTestId('speech-cue-clocks').textContent ?? '', /offset/)
    fireEvent.click(screen.getByTestId('speech-cue-0'))
    fireEvent.change(screen.getByLabelText('Viseme'), { target: { value: 'O' } })
    assert.equal(screen.getByTestId('speech-cue-0').getAttribute('data-manual'), 'true')
    fireEvent.change(screen.getByLabelText('Selection start (source s)'), { target: { value: '0.4' } })
    fireEvent.change(screen.getByLabelText('Selection end (source s)'), { target: { value: '0.8' } })
    assert.ok(screen.getByTestId('speech-cue-selection'))
    fireEvent.click(screen.getByRole('button', { name: 'Add silence' }))
    assert.match(screen.getByTestId('speech-cue-1').textContent ?? '', /rest|Manual/)
    fireEvent.change(screen.getByLabelText('Zoom'), { target: { value: '2' } })
    assert.ok(screen.getByRole('button', { name: 'Loop selection' }))
    fireEvent.change(screen.getByLabelText('Cue start (source s)'), { target: { value: '0.05' } })
    assert.match(screen.getByTestId('speech-cue-0').getAttribute('aria-label') ?? '', /0\.05/)
  } finally { cleanup() }
})
