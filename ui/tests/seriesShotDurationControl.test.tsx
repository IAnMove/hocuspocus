import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('editing dialogue recalculates and displays the authoritative requested clip duration', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SeriesShotDurationControl } = await import('../src/features/series/SeriesShotDurationControl.tsx')
  const calls: unknown[] = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body || '{}'))
    calls.push(body)
    return new Response(JSON.stringify({
      ...body.shot,
      durationSeconds: 6.583,
      dialogueDuration: {
        model: 'minimax_h3', durationMode: 'frame_lattice', wordCount: 28,
        syllableCount: 28, secondsPerSyllable: 0.22, segmentCount: 1,
        spokenSeconds: 6.16, estimatedVoiceSeconds: 6.51,
        requestedClipSeconds: 6.583, minimumLimited: false, requiresSplit: false,
        modelMinimumSeconds: 5.167, modelMaximumSeconds: 14.375,
        fps: 24, calculatedFrames: 158, effectiveFrames: 158, frameLattice: '17n+5',
      },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch

  const initial = {
    id: 'shot-1', sceneId: 'scene-1', order: 1, durationSeconds: 5.167,
    framing: 'medium', camera: 'locked', action: 'Talks', prompt: 'Talks', negativePrompt: '',
    dialogueBeats: [{ id: 'line-1', characterId: 'char-1', text: 'Hola', emotion: '', delivery: '' }],
    dialogueDuration: {
      model: 'minimax_h3', durationMode: 'frame_lattice' as const, wordCount: 1,
      syllableCount: 2, secondsPerSyllable: 0.22, segmentCount: 1,
      spokenSeconds: 0.44, estimatedVoiceSeconds: 0.79,
      requestedClipSeconds: 5.167, minimumLimited: true, requiresSplit: false,
      modelMinimumSeconds: 5.167, modelMaximumSeconds: 14.375,
      fps: 24, calculatedFrames: 22, effectiveFrames: 124, frameLattice: '17n+5',
    },
    visibleCharacterIds: ['char-1'], speakingCharacterIds: ['char-1'],
    wardrobeByCharacterId: {}, propIds: [], emotionalStateByCharacterId: {},
    renderStrategy: 'direct' as const,
    referencePolicy: { mode: 'automatic' as const, manualIncludeAssetIds: [], manualExcludeAssetIds: [] },
    attempts: [],
  }
  const series = {
    id: 'series-1', spokenLanguage: 'Español de España', language: 'Español',
    provider: { videoModel: 'minimax_h3' },
  }

  function Harness() {
    const [shot, setShot] = useState(initial)
    return <>
      <textarea aria-label="Dialogue" value={shot.dialogueBeats[0].text} onChange={event => setShot(current => ({
        ...current,
        dialogueBeats: [{ ...current.dialogueBeats[0], text: event.target.value }],
      }))} />
      <SeriesShotDurationControl workspace="default" series={series} shot={shot} onChange={setShot} />
    </>
  }

  try {
    render(<Harness />)
    assert.match(screen.getByText(/Requested clip:/).textContent || '', /5\.167 s/)
    fireEvent.change(screen.getByRole('textbox', { name: 'Dialogue' }), {
      target: { value: 'sol '.repeat(28).trim() },
    })
    await waitFor(() => {
      assert.match(screen.getByText(/Requested clip:/).textContent || '', /6\.583 s/)
    }, { timeout: 2000 })
    assert.equal(calls.length, 1)
    assert.equal((calls[0] as { workspace: string }).workspace, 'default')
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
  }
})

test('a failed duration preview does not freeze the signature', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SeriesShotDurationControl } = await import('../src/features/series/SeriesShotDurationControl.tsx')
  const originalFetch = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    calls += 1
    const body = JSON.parse(String(init?.body || '{}'))
    if (calls === 1) {
      return new Response(JSON.stringify({ detail: 'preview failed' }), {
        status: 500, headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({
      ...body.shot,
      durationSeconds: 8,
      dialogueDuration: {
        model: 'minimax_h3', durationMode: 'frame_lattice', wordCount: 3,
        syllableCount: 3, secondsPerSyllable: 0.22, segmentCount: 1,
        spokenSeconds: 0.66, estimatedVoiceSeconds: 1,
        requestedClipSeconds: 8, minimumLimited: false, requiresSplit: false,
        modelMinimumSeconds: 5.167, modelMaximumSeconds: 14.375,
        fps: 24, calculatedFrames: 192, effectiveFrames: 192, frameLattice: '17n+5',
      },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch

  const initial = {
    id: 'shot-1', sceneId: 'scene-1', order: 1, durationSeconds: 5.167,
    framing: 'medium', camera: 'locked', action: 'Talks', prompt: 'Talks', negativePrompt: '',
    dialogueBeats: [{ id: 'line-1', characterId: 'char-1', text: 'Hola', emotion: '', delivery: '' }],
    visibleCharacterIds: ['char-1'], speakingCharacterIds: ['char-1'],
    wardrobeByCharacterId: {}, propIds: [], emotionalStateByCharacterId: {},
    renderStrategy: 'direct' as const,
    referencePolicy: { mode: 'automatic' as const, manualIncludeAssetIds: [], manualExcludeAssetIds: [] },
    attempts: [],
  }
  const series = {
    id: 'series-1', spokenLanguage: 'Español de España', language: 'Español',
    provider: { videoModel: 'minimax_h3' },
  }

  function Harness() {
    const [shot, setShot] = useState(initial)
    return <>
      <textarea aria-label="Dialogue" value={shot.dialogueBeats[0].text} onChange={event => setShot(current => ({
        ...current,
        dialogueBeats: [{ ...current.dialogueBeats[0], text: event.target.value }],
      }))} />
      <SeriesShotDurationControl workspace="default" series={series} shot={shot} onChange={setShot} />
    </>
  }

  try {
    render(<Harness />)
    await waitFor(() => assert.match(screen.getByText(/Could not calculate|preview failed|failed/i).textContent || '', /./), { timeout: 2000 }).catch(() => undefined)
    fireEvent.change(screen.getByRole('textbox', { name: 'Dialogue' }), {
      target: { value: 'Hola otra vez' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Dialogue' }), {
      target: { value: 'Hola' },
    })
    await waitFor(() => assert.ok(calls >= 2), { timeout: 2000 })
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
  }
})
