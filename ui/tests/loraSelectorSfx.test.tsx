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
  Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver, localStorage: dom.window.localStorage,
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

test('Load Settings of an SFX output does not leave the previous model\'s LoRA list in the selector', async () => {
  // The 404 of /api/v1/loras/mmaudio_v2 used to empty the list as a side effect; without that request the
  // restore itself must clear it, as selectModel does for every model change.
  const { render, cleanup } = await import('@testing-library/react')
  const { LoraSelector } = await import('../src/components/SettingsDrawer/LoraSelector.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const before = useStore.getState(), beforeFetch = globalThis.fetch
  try {
    globalThis.fetch = (async () => new Response(JSON.stringify({ loras: [] }), { headers: { 'content-type': 'application/json' } })) as typeof fetch
    useStore.setState({
      generationMode: 'video', availableLoras: ['ltx_style.safetensors'],
      params: { ...before.params, model_type: 'ltx2_22B_distilled_1_1', activated_loras: [] },
      models: [{ model_type: 'ltx2_22B_distilled_1_1', name: 'LTX-2', family: 'ltx2' }, { model_type: 'mmaudio_v2', name: 'MMAudio', family: 'tts' }] as never,
      selectedOutputMeta: { params: { model_type: 'mmaudio_v2', _audio_sub_mode: 'sfx', sfx_mode: true, MMAudio_prompt: 'a chime', prompt: 'a chime', duration_seconds: 3 } } as never,
      loadModelOptions: async () => {},
    })
    assert.equal(await useStore.getState().loadSettingsFromOutput(), true)
    render(<LoraSelector />)
    await new Promise(resolve => setTimeout(resolve, 50))
    assert.equal(useStore.getState().audioSubMode, 'sfx')
    assert.deepEqual(useStore.getState().availableLoras, [], 'the LTX-2 LoRAs are still offered for MMAudio')
    assert.equal(document.body.textContent?.includes('ltx_style'), false)
  } finally {
    cleanup()
    useStore.setState(before); globalThis.fetch = beforeFetch
  }
})
