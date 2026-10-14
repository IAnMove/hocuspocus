// The Mixer/SFX sub-tabs render the LoRA selector for the virtual MMAudio model. That model has no LoRA
// endpoint: the server answered 404 "Unknown model: mmaudio_v2" for the list and the details, on every visit.
import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
class ObserverStub { observe() {} disconnect() {} }
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MouseEvent: dom.window.MouseEvent, MutationObserver: dom.window.MutationObserver,
  ResizeObserver: ObserverStub, IntersectionObserver: ObserverStub, React,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
window.matchMedia = (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia

async function loraRequests(modelType: string): Promise<string[]> {
  const { render, cleanup } = await import('@testing-library/react')
  const { LoraSelector } = await import('../src/components/SettingsDrawer/LoraSelector.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const before = useStore.getState(), beforeFetch = globalThis.fetch
  const urls: string[] = []
  try {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      urls.push(String(input))
      return new Response(JSON.stringify({ loras: [], guidance_max_phases: 1 }), { headers: { 'content-type': 'application/json' } })
    }) as typeof fetch
    useStore.setState({ params: { ...before.params, model_type: modelType, activated_loras: [] }, availableLoras: [] })
    render(<LoraSelector />)
    await new Promise(resolve => setTimeout(resolve, 50))
    return urls.filter(url => url.includes('/api/v1/loras/'))
  } finally {
    cleanup()
    useStore.setState(before); globalThis.fetch = beforeFetch
  }
}

test('the LoRA selector does not ask the server for the virtual SFX models', async () => {
  assert.deepEqual(await loraRequests('mmaudio_v2'), [])
  assert.deepEqual(await loraRequests('mmaudio_nsfw'), [])
})

test('the LoRA selector still loads the list and the details of a real model', async () => {
  const urls = await loraRequests('ltx2_22B_distilled_1_1')
  assert.ok(urls.some(url => url.endsWith('/api/v1/loras/ltx2_22B_distilled_1_1')), urls.join(', '))
  assert.ok(urls.some(url => url.includes('/api/v1/loras/ltx2_22B_distilled_1_1/details')), urls.join(', '))
})
