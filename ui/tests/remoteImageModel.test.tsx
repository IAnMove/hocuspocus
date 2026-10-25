import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const MINIMAX = {
  model_type: 'minimax:image-01', name: 'MiniMax Image-01 (remote, no GPU)', family: 'minimax', architecture: 'minimax_image',
  is_i2v: false, is_t2v: false, supports_ref_images: true, is_downloaded: true,
  resource_requirements: { tier: 'remote', backend: 'minimax', note: 'Remote API, no GPU' },
}
const QWEN = {
  model_type: 'qwen_image_21_turbo', name: 'Qwen Image 2.1 Turbo', family: 'qwen', architecture: 'qwen_image_21',
  is_i2v: false, is_t2v: false, supports_ref_images: true, is_downloaded: true,
}

test('MiniMax Image-01 is on by default, and an existing install gets it once', async () => {
  const { DEFAULT_ENABLED_MODELS, DEFAULTS_ADDED_IN, DEFAULTS_VERSION } = await import('../src/stores/modelVisibility')
  assert.ok(DEFAULT_ENABLED_MODELS.has('minimax:image-01'))
  assert.deepEqual(DEFAULTS_ADDED_IN[DEFAULTS_VERSION], ['minimax:image-01', 'minimax_h3_fasth3_v2', 'minimax_h3_fasth3_trim'])
  // Every id a version adds is in the curated list, so a fresh install and an updated one end with the same set.
  for (const ids of Object.values(DEFAULTS_ADDED_IN)) for (const id of ids) assert.ok(DEFAULT_ENABLED_MODELS.has(id), id)
})

test('a remote model is told apart by its tier and needs no VRAM', async () => {
  const { catalogVramGb, isRemoteModel } = await import('../src/lib/modelCatalog')
  assert.equal(isRemoteModel(MINIMAX as never), true)
  assert.equal(isRemoteModel(QWEN as never), false)
  assert.equal(catalogVramGb(MINIMAX as never), undefined)
  assert.equal(typeof catalogVramGb(QWEN as never), 'number')
})

test('the external-API entry is not listed twice in a picker that already offers it', async () => {
  const { withoutExternalImageModel } = await import('../src/lib/externalModels')
  assert.deepEqual(withoutExternalImageModel([MINIMAX, QWEN]).map(model => model.model_type), ['qwen_image_21_turbo'])
})

test('the Studio picker marks the remote model, shows no VRAM for it and keeps Qwen as it was', async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore')
  const { ModelSelector } = await import('../src/components/Sidebar/ModelSelector')
  const initial = useStore.getState()
  useStore.setState({
    generationMode: 'image',
    models: [QWEN, MINIMAX] as never,
    families: [{ id: 'qwen', label: 'Qwen', order: 110 }, { id: 'minimax', label: 'MiniMax (remote API)', order: 1170 }],
    enabledModels: new Set([QWEN.model_type, MINIMAX.model_type]),
    params: { ...initial.params, model_type: QWEN.model_type },
  })
  try {
    const view = render(<ModelSelector />)
    fireEvent.click(view.getByRole('button', { name: QWEN.name }))
    const remote = view.getByRole('button', { name: MINIMAX.name })
    assert.match(remote.textContent ?? '', /API/)
    assert.doesNotMatch(remote.textContent ?? '', /GB VRAM|VRAM ~/)
    assert.match(view.getAllByRole('button', { name: QWEN.name }).at(-1)?.textContent ?? '', /GB VRAM|VRAM ~/)
  } finally { cleanup(); useStore.setState(initial) }
})
